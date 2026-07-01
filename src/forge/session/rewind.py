"""Transcript prefix utilities for the rewind resume strategy."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge.core.state.io import atomic_write_text
from forge.core.transcript import parse_jsonl_transcript, truncate
from forge.session.transfer import (
    MAX_TRANSCRIPT_CHARS,
    _call_llm_for_curation_prompt,
    _emit_curation_usage,
    _extract_entry_blocks,
    _extract_turn_summary,
    _group_entries_into_turns,
    _validate_decision_citations,
)

logger = logging.getLogger(__name__)

REWIND_CODE_DELTA_SCHEMA = "rewind-code-delta"
REWIND_CODE_DELTA_COMMAND = "rewind-code-delta"
REWIND_CODE_DELTA_OPERATION = "rewind.code_delta"
_CODE_DELTA_TOOL_NAMES = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
_CODE_DELTA_FIELD_CHARS = 900

REWIND_CODE_DELTA_USER_PROMPT_TEMPLATE = """Analyze this rewound Claude Code session tail and return a JSON object.

The child conversation will resume from before these dropped turns, but the files on disk already include any code
changes made by them. Your job is to explain that disk/conversation gap.

Return a JSON object with these keys:
- "changes": array of objects {{"text": "<file path - net code change and why it matters>", "citation": "<turn N and/or file path>"}}.
  Cite only a listed turn number (for example "turn 4") or file path. Omit ungrounded claims.
- "net_effect": short paragraph summarizing the net effect of the dropped code-editing turns.
- "unfinished": array of strings for dangling or risky follow-ups the resumed agent should know.

Focus on net changes, not replaying every edit. If a file has multiple tool calls, treat the latest call as the best
signal for the final state. Do not tell the child to reapply changes blindly; the files already contain them.
Return ONLY the JSON object, with no surrounding prose or code fence.

<rewind_tail>
{source_text}
</rewind_tail>"""


@dataclass(frozen=True)
class RewindPrefixResult:
    """Result of writing a rewind transcript prefix."""

    source_path: Path
    dest_path: Path
    requested_drop_last: int
    total_turns: int
    requested_keep_turns: int
    kept_turns: int
    actual_dropped_turns: int
    lines_written: int
    entries_written: int
    snapped_to_safe_boundary: bool


@dataclass(frozen=True)
class RewindFileDelta:
    """Net code-edit signal for one file in the dropped rewind window."""

    path: str
    first_turn: int
    last_turn: int
    tool_names: tuple[str, ...]
    operation_count: int
    latest_summary: str


@dataclass(frozen=True)
class RewindCodeDeltaSource:
    """Bounded LLM input assembled from the dropped rewind window."""

    text: str
    emitted_turns: set[int]
    file_deltas: list[RewindFileDelta]
    total_turns: int
    kept_turns: int
    was_truncated: bool


@dataclass(frozen=True)
class _RawTranscriptEntry:
    """Parsed JSONL object with its original raw-line index."""

    entry: dict[str, Any]
    line_index: int


@dataclass
class _FileDeltaBuilder:
    path: str
    first_turn: int
    last_turn: int
    tool_names: list[str]
    operation_count: int
    latest_summary: str

    def add(self, *, turn_number: int, tool_name: str, summary: str) -> None:
        if tool_name not in self.tool_names:
            self.tool_names.append(tool_name)
        self.last_turn = turn_number
        self.operation_count += 1
        self.latest_summary = summary

    def build(self) -> RewindFileDelta:
        return RewindFileDelta(
            path=self.path,
            first_turn=self.first_turn,
            last_turn=self.last_turn,
            tool_names=tuple(self.tool_names),
            operation_count=self.operation_count,
            latest_summary=self.latest_summary,
        )


def write_rewind_transcript_prefix(
    *,
    source_path: Path,
    dest_path: Path,
    drop_last: int,
) -> RewindPrefixResult:
    """Write a safe raw JSONL prefix for ``--strategy rewind``.

    ``drop_last`` counts conversational turns using the same grouping helper as
    transfer curation. Positive drops write a raw-line prefix ending at the last
    complete turn at or before ``T - drop_last``. If that boundary would leave a
    known ``tool_use`` without its matching ``tool_result``, the prefix snaps
    back to the previous complete turn.

    ``drop_last=0`` intentionally copies the source text unchanged: it is the
    plain native-relocate degenerate path, so it must not trim an in-progress
    tail or normalize formatting.
    """
    if drop_last < 0:
        raise ValueError("drop_last must be non-negative")

    source_text = source_path.read_text(encoding="utf-8")
    raw_lines = source_text.splitlines(keepends=True)
    raw_entries = _parse_raw_transcript_entries(raw_lines)
    turn_groups = _group_entries_into_turns([raw.entry for raw in raw_entries])
    total_turns = len(turn_groups)
    requested_keep_turns = max(total_turns - drop_last, 0)

    if drop_last == 0:
        atomic_write_text(dest_path, source_text)
        return RewindPrefixResult(
            source_path=source_path,
            dest_path=dest_path,
            requested_drop_last=drop_last,
            total_turns=total_turns,
            requested_keep_turns=total_turns,
            kept_turns=total_turns,
            actual_dropped_turns=0,
            lines_written=len(raw_lines),
            entries_written=len(raw_entries),
            snapped_to_safe_boundary=False,
        )

    entry_line_by_id = {id(raw.entry): raw.line_index for raw in raw_entries}
    kept_turns = _snap_to_complete_prefix(
        raw_entries=raw_entries,
        turn_groups=turn_groups,
        entry_line_by_id=entry_line_by_id,
        requested_keep_turns=requested_keep_turns,
    )
    cutoff_line = _cutoff_line_for_kept_turns(
        turn_groups=turn_groups,
        entry_line_by_id=entry_line_by_id,
        kept_turns=kept_turns,
    )
    _assert_kept_turns_form_raw_prefix(
        raw_entries=raw_entries,
        turn_groups=turn_groups,
        kept_turns=kept_turns,
        cutoff_line=cutoff_line,
    )

    selected_lines = raw_lines[: cutoff_line + 1] if cutoff_line >= 0 else []
    selected_entry_count = sum(1 for raw in raw_entries if raw.line_index <= cutoff_line)
    atomic_write_text(dest_path, "".join(selected_lines))

    return RewindPrefixResult(
        source_path=source_path,
        dest_path=dest_path,
        requested_drop_last=drop_last,
        total_turns=total_turns,
        requested_keep_turns=requested_keep_turns,
        kept_turns=kept_turns,
        actual_dropped_turns=total_turns - kept_turns,
        lines_written=len(selected_lines),
        entries_written=selected_entry_count,
        snapped_to_safe_boundary=kept_turns != requested_keep_turns,
    )


def extract_rewind_file_deltas(entries: list[dict[str, Any]], *, kept_turns: int) -> list[RewindFileDelta]:
    """Extract net file-level code-edit signals from turns after ``kept_turns``."""
    if kept_turns < 0:
        raise ValueError("kept_turns must be non-negative")

    builders: dict[str, _FileDeltaBuilder] = {}
    for turn_number, group in enumerate(_group_entries_into_turns(entries), start=1):
        if turn_number <= kept_turns:
            continue
        for entry in group:
            for block in _extract_entry_blocks(entry):
                if block.get("type") != "tool_use":
                    continue
                tool_name = block.get("name")
                tool_input = block.get("input")
                if not isinstance(tool_name, str) or tool_name not in _CODE_DELTA_TOOL_NAMES:
                    continue
                if not isinstance(tool_input, dict):
                    continue
                path = _extract_code_tool_path(tool_name, tool_input)
                if not path:
                    continue
                summary = _summarize_code_tool_call(tool_name, tool_input)
                builder = builders.get(path)
                if builder is None:
                    builders[path] = _FileDeltaBuilder(
                        path=path,
                        first_turn=turn_number,
                        last_turn=turn_number,
                        tool_names=[tool_name],
                        operation_count=1,
                        latest_summary=summary,
                    )
                else:
                    builder.add(turn_number=turn_number, tool_name=tool_name, summary=summary)

    return [builder.build() for builder in builders.values()]


def build_rewind_code_delta_source(entries: list[dict[str, Any]], *, kept_turns: int) -> RewindCodeDeltaSource:
    """Build the bounded, turn-grounded source text for the rewind code-delta LLM."""
    if kept_turns < 0:
        raise ValueError("kept_turns must be non-negative")

    turn_groups = _group_entries_into_turns(entries)
    total_turns = len(turn_groups)
    bounded_kept_turns = min(kept_turns, total_turns)
    file_deltas = extract_rewind_file_deltas(entries, kept_turns=bounded_kept_turns)
    emitted_turns: set[int] = set()
    lines: list[str] = [
        "## Rewind Boundary",
        "",
        f"Kept turns: 1..{bounded_kept_turns}. Dropped turns: {bounded_kept_turns + 1}..{total_turns}.",
        "The resumed child will not have these dropped turns in conversation history.",
        "The files on disk already include code changes made by these dropped turns.",
        "",
        "## Code-edit Tool Calls (net by file)",
        "",
    ]

    if file_deltas:
        for delta in file_deltas:
            emitted_turns.update(range(delta.first_turn, delta.last_turn + 1))
            turns = _format_turn_range(delta.first_turn, delta.last_turn)
            tools = ", ".join(delta.tool_names)
            lines.append(
                f"- {delta.path}: {delta.latest_summary} "
                f"(latest turn {delta.last_turn}; {delta.operation_count} tool call(s) across {turns}; tools: {tools})"
            )
    else:
        lines.append("- No Edit/Write/MultiEdit/NotebookEdit tool calls were captured in the dropped turns.")

    lines.extend(["", "## Dropped Transcript", ""])
    for turn_number, group in enumerate(turn_groups, start=1):
        if turn_number <= bounded_kept_turns:
            continue
        for entry in group:
            summary = _extract_turn_summary(entry)
            if not summary:
                continue
            role = summary["role"].upper()
            if summary["text"]:
                lines.append(f"[turn {turn_number}] [{role}] {summary['text']}")
                emitted_turns.add(turn_number)
            if summary["tools"]:
                lines.append(f"[turn {turn_number}]   Tools: {', '.join(summary['tools'])}")
                emitted_turns.add(turn_number)

    text = "\n".join(lines)
    was_truncated = False
    if len(text) > MAX_TRANSCRIPT_CHARS:
        text = text[:MAX_TRANSCRIPT_CHARS].rstrip() + "\n\n...(rewind tail truncated for length)"
        was_truncated = True

    return RewindCodeDeltaSource(
        text=text,
        emitted_turns=emitted_turns,
        file_deltas=file_deltas,
        total_turns=total_turns,
        kept_turns=bounded_kept_turns,
        was_truncated=was_truncated,
    )


def generate_rewind_code_delta_context(
    *,
    parent_name: str,
    lineage: list[str],
    transcript_path: Path | None,
    kept_turns: int,
) -> tuple[str, list[str], str]:
    """Generate the rewind code-delta context body for the dropped transcript window."""
    warnings: list[str] = []
    if not transcript_path or not transcript_path.is_file():
        content = _build_rewind_deterministic_output(
            parent_name=parent_name,
            lineage=lineage,
            source=None,
            reason="No transcript available; code-delta unavailable.",
        )
        return content, ["No transcript available; using rewind code-delta fallback"], "compatibility-fallback"

    entries = parse_jsonl_transcript(transcript_path)
    if not entries:
        content = _build_rewind_deterministic_output(
            parent_name=parent_name,
            lineage=lineage,
            source=None,
            reason="Empty transcript; code-delta unavailable.",
        )
        return content, ["Empty transcript; using rewind code-delta fallback"], "compatibility-fallback"

    source = build_rewind_code_delta_source(entries, kept_turns=kept_turns)
    if source.was_truncated:
        warnings.append("Dropped rewind window truncated to fit context limit")

    if not source.file_deltas:
        # A valid empty code-delta is still the rewind schema, not a fallback:
        # the dropped window may simply contain no code-editing tool calls, and
        # no LLM spend is needed to state that.
        content = _build_rewind_deterministic_output(
            parent_name=parent_name,
            lineage=lineage,
            source=source,
            reason="No code-edit tool calls captured in the dropped turns.",
        )
        return content, warnings, REWIND_CODE_DELTA_SCHEMA

    prompt = REWIND_CODE_DELTA_USER_PROMPT_TEMPLATE.format(source_text=source.text)
    try:
        call = _call_llm_for_curation_prompt(prompt, provider_user_role=REWIND_CODE_DELTA_COMMAND)
    except Exception as e:
        logger.warning("Rewind code-delta curation failed: %s", e)
        content = _build_rewind_deterministic_output(
            parent_name=parent_name,
            lineage=lineage,
            source=source,
            reason=f"AI code-delta failed ({e}); using deterministic tool-call summary.",
        )
        return (
            content,
            warnings + [f"AI code-delta failed ({e}); using deterministic summary"],
            "compatibility-fallback",
        )

    _emit_curation_usage(call, command=REWIND_CODE_DELTA_COMMAND, operation=REWIND_CODE_DELTA_OPERATION)
    if call.curated is None:
        content = _build_rewind_deterministic_output(
            parent_name=parent_name,
            lineage=lineage,
            source=source,
            reason="AI code-delta did not return a parseable JSON object; using deterministic tool-call summary.",
        )
        return (
            content,
            warnings + ["AI code-delta did not return a parseable JSON object; using deterministic summary"],
            "compatibility-fallback",
        )

    curated, model_used = call.curated, call.model_used
    warnings.append(f"Rewind code-delta: dropped-window code/transcript sent to {model_used} for processing")
    curated["changes"], cite_warnings = _validate_decision_citations(curated.get("changes"), source.emitted_turns)
    warnings.extend(cite_warnings)

    content = _build_rewind_code_delta_output(
        parent_name=parent_name,
        lineage=lineage,
        source=source,
        curated=curated,
        model_used=model_used,
    )
    return content, warnings, REWIND_CODE_DELTA_SCHEMA


def _extract_code_tool_path(tool_name: str, tool_input: dict[str, Any]) -> str:
    if tool_name == "NotebookEdit":
        raw_path = tool_input.get("notebook_path") or tool_input.get("file_path") or tool_input.get("path")
    else:
        raw_path = tool_input.get("file_path") or tool_input.get("path")
    return str(raw_path).strip() if isinstance(raw_path, str) and raw_path.strip() else ""


def _summarize_code_tool_call(tool_name: str, tool_input: dict[str, Any]) -> str:
    if tool_name == "Edit":
        old = _input_text(tool_input, "old_string")
        new = _input_text(tool_input, "new_string")
        return (
            f"Edit replaces `{truncate(old, _CODE_DELTA_FIELD_CHARS)}` with `{truncate(new, _CODE_DELTA_FIELD_CHARS)}`"
        )

    if tool_name == "Write":
        content = _input_text(tool_input, "content")
        return f"Write sets file content to `{truncate(content, _CODE_DELTA_FIELD_CHARS)}`"

    if tool_name == "MultiEdit":
        edits = tool_input.get("edits")
        if isinstance(edits, list):
            edit_summaries: list[str] = []
            for index, edit in enumerate(edits, start=1):
                if not isinstance(edit, dict):
                    continue
                old = _input_text(edit, "old_string")
                new = _input_text(edit, "new_string")
                edit_summaries.append(f"{index}. `{truncate(old, 180)}` -> `{truncate(new, 180)}`")
            if edit_summaries:
                return f"MultiEdit applies {len(edit_summaries)} edit(s): {'; '.join(edit_summaries)}"
        return "MultiEdit updates the file"

    if tool_name == "NotebookEdit":
        cell_id = _input_text(tool_input, "cell_id")
        source = _input_text(tool_input, "new_source") or _input_text(tool_input, "source")
        cell_suffix = f" cell {cell_id}" if cell_id else ""
        if source:
            return f"NotebookEdit updates{cell_suffix} to `{truncate(source, _CODE_DELTA_FIELD_CHARS)}`"
        return f"NotebookEdit updates{cell_suffix or ' a notebook cell'}"

    return f"{tool_name} updates the file"


def _input_text(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    return value if isinstance(value, str) else ""


def _format_turn_range(first_turn: int, last_turn: int) -> str:
    return f"turn {first_turn}" if first_turn == last_turn else f"turns {first_turn}-{last_turn}"


def _build_rewind_code_delta_output(
    *,
    parent_name: str,
    lineage: list[str],
    source: RewindCodeDeltaSource,
    curated: dict[str, Any],
    model_used: str,
) -> str:
    lines = [
        f"# Rewind Code Delta: {parent_name}",
        "",
        f"_Curated by {model_used}._",
        "",
        "## Lineage",
        "",
        " <- ".join(lineage) if lineage else parent_name,
        "",
        "## Conversation Gap",
        "",
        (
            f"The child conversation is rewound after turn {source.kept_turns}; dropped turns "
            f"{source.kept_turns + 1}..{source.total_turns} are not live history. "
            "Files on disk already include the code changes below."
        ),
        "",
        "## Files Changed",
        "",
        *_render_change_items(curated.get("changes")),
        "",
        "## Net Effect",
        "",
        _coerce_text(curated.get("net_effect")) or "_Not captured._",
        "",
        "## Unfinished / Watchpoints",
        "",
        *_render_str_list(curated.get("unfinished")),
        "",
    ]
    return "\n".join(lines)


def _build_rewind_deterministic_output(
    *,
    parent_name: str,
    lineage: list[str],
    source: RewindCodeDeltaSource | None,
    reason: str,
) -> str:
    if source is None:
        source = RewindCodeDeltaSource(
            text="",
            emitted_turns=set(),
            file_deltas=[],
            total_turns=0,
            kept_turns=0,
            was_truncated=False,
        )
    changes = [
        {
            "text": (
                f"{delta.path} - {delta.latest_summary} "
                f"({delta.operation_count} code-edit tool call(s), latest turn {delta.last_turn})"
            ),
            "citation": f"turn {delta.last_turn}",
        }
        for delta in source.file_deltas
    ]
    curated = {
        "changes": changes,
        "net_effect": reason,
        "unfinished": [],
    }
    return _build_rewind_code_delta_output(
        parent_name=parent_name,
        lineage=lineage,
        source=source,
        curated=curated,
        model_used="deterministic tool-call summary",
    )


def _render_change_items(changes: Any) -> list[str]:
    lines: list[str] = []
    if isinstance(changes, list):
        for item in changes:
            if isinstance(item, dict):
                text = _coerce_text(item.get("text"))
                citation = _coerce_text(item.get("citation"))
            else:
                text, citation = _coerce_text(item), ""
            if not text:
                continue
            lines.append(f"- {text} _(cite: {citation})_" if citation else f"- {text}")
    return lines or ["_No code changes captured._"]


def _render_str_list(items: Any) -> list[str]:
    lines = [f"- {_coerce_text(item)}" for item in items if _coerce_text(item)] if isinstance(items, list) else []
    return lines or ["_None captured._"]


def _coerce_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _parse_raw_transcript_entries(raw_lines: list[str]) -> list[_RawTranscriptEntry]:
    entries: list[_RawTranscriptEntry] = []
    for line_index, raw_line in enumerate(raw_lines):
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            entries.append(_RawTranscriptEntry(entry=parsed, line_index=line_index))
    return entries


def _snap_to_complete_prefix(
    *,
    raw_entries: list[_RawTranscriptEntry],
    turn_groups: list[list[dict[str, Any]]],
    entry_line_by_id: dict[int, int],
    requested_keep_turns: int,
) -> int:
    kept_turns = min(max(requested_keep_turns, 0), len(turn_groups))
    while kept_turns > 0:
        cutoff_line = _cutoff_line_for_kept_turns(
            turn_groups=turn_groups,
            entry_line_by_id=entry_line_by_id,
            kept_turns=kept_turns,
        )
        prefix_entries = [raw.entry for raw in raw_entries if raw.line_index <= cutoff_line]
        if not _has_dangling_tool_use(prefix_entries):
            return kept_turns
        kept_turns -= 1
    return 0


def _cutoff_line_for_kept_turns(
    *,
    turn_groups: list[list[dict[str, Any]]],
    entry_line_by_id: dict[int, int],
    kept_turns: int,
) -> int:
    if kept_turns <= 0:
        return -1

    line_indexes: list[int] = []
    for group in turn_groups[:kept_turns]:
        for entry in group:
            line_index = entry_line_by_id.get(id(entry))
            if line_index is not None:
                line_indexes.append(line_index)
    return max(line_indexes, default=-1)


def _assert_kept_turns_form_raw_prefix(
    *,
    raw_entries: list[_RawTranscriptEntry],
    turn_groups: list[list[dict[str, Any]]],
    kept_turns: int,
    cutoff_line: int,
) -> None:
    # Raw prefixing is only honest when grouped turns are append-contiguous.
    # If requestIds interleave, a max-line cutoff would leak dropped-turn
    # entries into the output while the result claims they were removed.
    grouped_entry_ids = {id(entry) for group in turn_groups for entry in group}
    expected_entry_ids = {id(entry) for group in turn_groups[:kept_turns] for entry in group}
    selected_grouped_entry_ids = {
        id(raw.entry) for raw in raw_entries if raw.line_index <= cutoff_line and id(raw.entry) in grouped_entry_ids
    }

    if selected_grouped_entry_ids != expected_entry_ids:
        raise ValueError(
            "rewind transcript turns are not a contiguous raw prefix; refusing to include dropped-window entries"
        )


def _has_dangling_tool_use(entries: list[dict[str, Any]]) -> bool:
    tool_uses: set[str] = set()
    tool_results: set[str] = set()

    for entry in entries:
        for block in _extract_entry_blocks(entry):
            block_type = block.get("type")
            if block_type == "tool_use":
                tool_id = block.get("id")
                if isinstance(tool_id, str) and tool_id:
                    tool_uses.add(tool_id)
            elif block_type == "tool_result":
                tool_use_id = block.get("tool_use_id")
                if isinstance(tool_use_id, str) and tool_use_id:
                    tool_results.add(tool_use_id)

    return bool(tool_uses - tool_results)

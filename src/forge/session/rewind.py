"""Transcript prefix utilities for the rewind resume strategy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge.core.state.io import atomic_write_text
from forge.session.transfer import _extract_entry_blocks, _group_entries_into_turns


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
class _RawTranscriptEntry:
    """Parsed JSONL object with its original raw-line index."""

    entry: dict[str, Any]
    line_index: int


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
        id(raw.entry)
        for raw in raw_entries
        if raw.line_index <= cutoff_line and id(raw.entry) in grouped_entry_ids
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

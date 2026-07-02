"""Tests for rewind resume strategy primitives."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from forge.session.rewind import (
    REWIND_CODE_DELTA_COMMAND,
    REWIND_CODE_DELTA_SCHEMA,
    build_rewind_code_delta_source,
    extract_rewind_file_deltas,
    generate_rewind_code_delta_context,
    write_rewind_transcript_prefix,
)


def _fake_completion(text: str, *, usage: dict[str, int] | None = None) -> Any:
    return SimpleNamespace(
        text=text,
        usage=usage if usage is not None else {"prompt_tokens": 120, "completion_tokens": 60},
    )


def _entry(
    *,
    role: str,
    text: str | None = None,
    request_id: str | None = None,
    blocks: list[dict[str, Any]] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    content: list[dict[str, Any]]
    if blocks is not None:
        content = blocks
    else:
        content = [{"type": "text", "text": text or role}]

    entry: dict[str, Any] = {"message": {"role": role, "content": content}}
    if request_id is not None:
        entry["requestId"] = request_id
    if timestamp is not None:
        entry["timestamp"] = timestamp
    return entry


def _write_jsonl(path: Path, entries: list[dict[str, Any]]) -> list[str]:
    lines = [json.dumps(entry, sort_keys=True) for entry in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


def _tool_use(name: str, tool_input: dict[str, Any], *, tool_id: str | None = None) -> dict[str, Any]:
    return {
        "type": "tool_use",
        "id": tool_id or f"toolu_{name}",
        "name": name,
        "input": tool_input,
    }


def test_turn_prefix_selects_entries_before_dropped_window(tmp_path: Path) -> None:
    source = tmp_path / "parent.jsonl"
    dest = tmp_path / "rewind.jsonl"
    lines = _write_jsonl(
        source,
        [
            _entry(role="user", text="u1", request_id="r1"),
            _entry(role="assistant", text="a1", request_id="r1"),
            _entry(role="user", text="u2", request_id="r2"),
            _entry(role="assistant", text="a2", request_id="r2"),
            _entry(role="user", text="u3", request_id="r3"),
            _entry(role="assistant", text="a3", request_id="r3"),
            _entry(role="user", text="u4", request_id="r4"),
            _entry(role="assistant", text="a4", request_id="r4"),
        ],
    )

    result = write_rewind_transcript_prefix(source_path=source, dest_path=dest, drop_last=2)

    assert dest.read_text(encoding="utf-8") == "\n".join(lines[:4]) + "\n"
    assert result.total_turns == 4
    assert result.requested_keep_turns == 2
    assert result.kept_turns == 2
    assert result.actual_dropped_turns == 2
    assert result.entries_written == 4
    assert result.snapped_to_safe_boundary is False


def test_truncation_snaps_back_from_dangling_tool_use(tmp_path: Path) -> None:
    source = tmp_path / "parent.jsonl"
    dest = tmp_path / "rewind.jsonl"
    lines = _write_jsonl(
        source,
        [
            _entry(role="user", text="u1"),
            _entry(role="assistant", text="a1"),
            _entry(role="user", text="please read"),
            _entry(
                role="assistant",
                blocks=[
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Read",
                        "input": {"file_path": "README.md"},
                    }
                ],
            ),
            _entry(role="user", blocks=[{"type": "tool_result", "tool_use_id": "toolu_1", "content": "done"}]),
            _entry(role="assistant", text="read done"),
        ],
    )

    result = write_rewind_transcript_prefix(source_path=source, dest_path=dest, drop_last=1)

    assert dest.read_text(encoding="utf-8") == "\n".join(lines[:2]) + "\n"
    assert result.total_turns == 3
    assert result.requested_keep_turns == 2
    assert result.kept_turns == 1
    assert result.actual_dropped_turns == 2
    assert result.entries_written == 2
    assert result.snapped_to_safe_boundary is True


def test_drop_last_zero_copies_full_file_without_snapping(tmp_path: Path) -> None:
    source = tmp_path / "parent.jsonl"
    dest = tmp_path / "rewind.jsonl"
    _write_jsonl(
        source,
        [
            _entry(role="user", text="u1"),
            _entry(role="assistant", blocks=[{"type": "tool_use", "id": "toolu_1", "name": "Read", "input": {}}]),
        ],
    )
    original = source.read_text(encoding="utf-8")

    result = write_rewind_transcript_prefix(source_path=source, dest_path=dest, drop_last=0)

    assert dest.read_text(encoding="utf-8") == original
    assert result.kept_turns == result.total_turns
    assert result.actual_dropped_turns == 0
    assert result.snapped_to_safe_boundary is False


def test_drop_last_at_or_beyond_turn_count_writes_empty_prefix(tmp_path: Path) -> None:
    source = tmp_path / "parent.jsonl"
    dest = tmp_path / "rewind.jsonl"
    _write_jsonl(
        source,
        [
            _entry(role="user", text="u1", request_id="r1"),
            _entry(role="assistant", text="a1", request_id="r1"),
            _entry(role="user", text="u2", request_id="r2"),
            _entry(role="assistant", text="a2", request_id="r2"),
        ],
    )

    result = write_rewind_transcript_prefix(source_path=source, dest_path=dest, drop_last=9)

    assert dest.read_text(encoding="utf-8") == ""
    assert result.total_turns == 2
    assert result.requested_keep_turns == 0
    assert result.kept_turns == 0
    assert result.actual_dropped_turns == 2
    assert result.entries_written == 0


def test_interleaved_request_ids_are_rejected_to_preserve_prefix_contract(tmp_path: Path) -> None:
    source = tmp_path / "parent.jsonl"
    dest = tmp_path / "rewind.jsonl"
    _write_jsonl(
        source,
        [
            _entry(role="user", text="u1", request_id="r1"),
            _entry(role="user", text="u2", request_id="r2"),
            _entry(role="assistant", text="a1", request_id="r1"),
            _entry(role="assistant", text="a2", request_id="r2"),
        ],
    )

    with pytest.raises(ValueError, match="not a contiguous raw prefix"):
        write_rewind_transcript_prefix(source_path=source, dest_path=dest, drop_last=1)

    assert not dest.exists()


def test_negative_drop_last_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "parent.jsonl"
    dest = tmp_path / "rewind.jsonl"
    _write_jsonl(source, [_entry(role="user", text="u1")])

    with pytest.raises(ValueError, match="drop_last must be non-negative"):
        write_rewind_transcript_prefix(source_path=source, dest_path=dest, drop_last=-1)


def test_code_delta_extracts_only_dropped_turn_tools() -> None:
    entries = [
        _entry(
            role="assistant",
            request_id="r1",
            blocks=[_tool_use("Edit", {"file_path": "src/head.py", "old_string": "old", "new_string": "head"})],
        ),
        _entry(role="assistant", text="kept", request_id="r2"),
        _entry(
            role="assistant",
            request_id="r3",
            blocks=[
                _tool_use(
                    "Write",
                    {"file_path": "src/dropped.py", "content": "def dropped():\n    return True\n"},
                )
            ],
        ),
        _entry(
            role="assistant",
            request_id="r4",
            blocks=[
                _tool_use(
                    "NotebookEdit",
                    {"notebook_path": "notebooks/demo.ipynb", "cell_id": "cell-1", "new_source": "print('done')"},
                )
            ],
        ),
    ]

    deltas = extract_rewind_file_deltas(entries, kept_turns=2)

    assert [delta.path for delta in deltas] == ["src/dropped.py", "notebooks/demo.ipynb"]
    assert {delta.last_turn for delta in deltas} == {3, 4}


def test_code_delta_reconciles_multiple_edits_to_one_file() -> None:
    entries = [
        _entry(role="assistant", text="kept", request_id="r1"),
        _entry(
            role="assistant",
            request_id="r2",
            blocks=[
                _tool_use(
                    "Edit",
                    {"file_path": "src/app.py", "old_string": "first_old()", "new_string": "first_new()"},
                )
            ],
        ),
        _entry(
            role="assistant",
            request_id="r3",
            blocks=[
                _tool_use(
                    "MultiEdit",
                    {
                        "file_path": "src/app.py",
                        "edits": [{"old_string": "second_old()", "new_string": "second_new()"}],
                    },
                )
            ],
        ),
    ]

    deltas = extract_rewind_file_deltas(entries, kept_turns=1)

    assert len(deltas) == 1
    delta = deltas[0]
    assert delta.path == "src/app.py"
    assert delta.first_turn == 2
    assert delta.last_turn == 3
    assert delta.operation_count == 2
    assert delta.tool_names == ("Edit", "MultiEdit")
    assert "second_new()" in delta.latest_summary


def test_code_delta_source_contains_dropped_turns_not_head() -> None:
    entries = [
        _entry(
            role="assistant",
            request_id="r1",
            blocks=[_tool_use("Write", {"file_path": "src/head.py", "content": "head"})],
        ),
        _entry(
            role="assistant",
            request_id="r2",
            blocks=[_tool_use("Write", {"file_path": "src/tail.py", "content": "tail"})],
        ),
    ]

    source = build_rewind_code_delta_source(entries, kept_turns=1)

    assert "src/tail.py" in source.text
    assert "src/head.py" not in source.text
    assert source.emitted_turns == {2}
    assert source.file_deltas[0].path == "src/tail.py"


def test_code_delta_generator_uses_raw_order_shared_with_prefix_writer(tmp_path: Path) -> None:
    from unittest.mock import MagicMock, patch

    transcript = tmp_path / "parent.jsonl"
    _write_jsonl(
        transcript,
        [
            _entry(
                role="assistant",
                text="kept head",
                request_id="r1",
                timestamp="2026-01-01T00:00:03Z",
            ),
            {
                "requestId": "r2",
                "timestamp": "2026-01-01T00:00:01Z",
                "metadataOnly": True,
            },
            _entry(
                role="assistant",
                request_id="r3",
                timestamp="2026-01-01T00:00:02Z",
                blocks=[_tool_use("Write", {"file_path": "src/raw_tail.py", "content": "tail"})],
            ),
        ],
    )
    mock_adapter = MagicMock()
    mock_adapter.complete.return_value = _fake_completion(
        json.dumps(
            {
                "changes": [{"text": "src/raw_tail.py - wrote raw tail", "citation": "turn 3"}],
                "net_effect": "Raw tail exists on disk.",
                "unfinished": [],
            }
        )
    )

    with (
        patch("forge.core.llm.SyncAdapter", return_value=mock_adapter),
        patch("forge.core.llm.get_client"),
    ):
        content, _warnings, schema = generate_rewind_code_delta_context(
            parent_name="parent",
            lineage=["parent"],
            transcript_path=transcript,
            kept_turns=2,
        )

    prompt = mock_adapter.complete.call_args.args[0][1].content

    assert schema == REWIND_CODE_DELTA_SCHEMA
    assert "src/raw_tail.py" in prompt
    assert "Dropped turns: 3..3" in prompt
    assert "src/raw_tail.py - wrote raw tail" in content


def test_rewind_code_delta_prompt_and_rendering_are_grounded(tmp_path: Path) -> None:
    from unittest.mock import MagicMock, patch

    transcript = tmp_path / "parent.jsonl"
    _write_jsonl(
        transcript,
        [
            _entry(
                role="assistant",
                request_id="r1",
                blocks=[_tool_use("Write", {"file_path": "src/head.py", "content": "head"})],
            ),
            _entry(
                role="assistant",
                request_id="r2",
                blocks=[_tool_use("Write", {"file_path": "src/tail.py", "content": "tail"})],
            ),
        ],
    )
    curated = {
        "changes": [
            {"text": "src/tail.py - wrote the tail state", "citation": "turn 2"},
            {"text": "fabricated", "citation": "turn 99"},
        ],
        "net_effect": "Tail state exists on disk.",
        "unfinished": ["Check whether tail state is desired."],
    }
    mock_adapter = MagicMock()
    mock_adapter.complete.return_value = _fake_completion(json.dumps(curated))

    with (
        patch("forge.core.llm.SyncAdapter", return_value=mock_adapter),
        patch("forge.core.llm.get_client"),
    ):
        content, warnings, schema = generate_rewind_code_delta_context(
            parent_name="parent",
            lineage=["parent"],
            transcript_path=transcript,
            kept_turns=1,
        )

    prompt = mock_adapter.complete.call_args.args[0][1].content
    assert "src/tail.py" in prompt
    assert "src/head.py" not in prompt
    assert "files on disk already include" in prompt
    assert schema == REWIND_CODE_DELTA_SCHEMA
    assert "src/tail.py - wrote the tail state" in content
    assert "turn 2" in content
    assert "turn 99" not in content
    assert any("ungrounded citation" in warning for warning in warnings)


def test_rewind_code_delta_parse_failure_emits_error_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock, patch

    from forge.core.usage.ledger import read_usage_events

    transcript = tmp_path / "parent.jsonl"
    _write_jsonl(
        transcript,
        [
            _entry(role="assistant", text="kept", request_id="r1"),
            _entry(
                role="assistant",
                request_id="r2",
                blocks=[_tool_use("Edit", {"file_path": "src/tail.py", "old_string": "old", "new_string": "new"})],
            ),
        ],
    )
    monkeypatch.setenv("FORGE_RUN_ID", "run_root")
    monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_root")
    monkeypatch.delenv("FORGE_PARENT_RUN_ID", raising=False)
    mock_adapter = MagicMock()
    mock_adapter.complete.return_value = _fake_completion(
        "not json", usage={"prompt_tokens": 222, "completion_tokens": 9}
    )

    with (
        patch("forge.core.llm.SyncAdapter", return_value=mock_adapter),
        patch("forge.core.llm.get_client"),
    ):
        content, warnings, schema = generate_rewind_code_delta_context(
            parent_name="parent",
            lineage=["parent"],
            transcript_path=transcript,
            kept_turns=1,
        )

    assert schema == "compatibility-fallback"
    assert "deterministic tool-call summary" in content
    assert any("parseable JSON" in warning for warning in warnings)
    events = [event for event in read_usage_events() if event.command == REWIND_CODE_DELTA_COMMAND]
    assert len(events) == 1
    assert events[0].status == "error"
    assert events[0].failure_type == "unparseable_output"
    assert events[0].input_tokens == 222

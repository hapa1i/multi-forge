"""Tests for rewind resume strategy primitives."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from forge.session.rewind import write_rewind_transcript_prefix


def _entry(
    *,
    role: str,
    text: str | None = None,
    request_id: str | None = None,
    blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    content: list[dict[str, Any]]
    if blocks is not None:
        content = blocks
    else:
        content = [{"type": "text", "text": text or role}]

    entry: dict[str, Any] = {"message": {"role": role, "content": content}}
    if request_id is not None:
        entry["requestId"] = request_id
    return entry


def _write_jsonl(path: Path, entries: list[dict[str, Any]]) -> list[str]:
    lines = [json.dumps(entry, sort_keys=True) for entry in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


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

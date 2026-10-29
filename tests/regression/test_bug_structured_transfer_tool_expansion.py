"""Structured transfers must not turn tool traffic into a raw-output transcript."""

import json
from pathlib import Path

import pytest

from forge.session.models import create_session_state
from forge.session.transfer import (
    ResumeStrategy,
    _generate_structured_context,
    assemble_transfer_context,
)
from tests.fixtures.transcript_delegation import tool_heavy_transcript

pytestmark = pytest.mark.regression


def test_tool_only_groups_do_not_expand_structured_transfer(tmp_path: Path) -> None:
    entries = tool_heavy_transcript()
    path = tmp_path / "busy.jsonl"
    path.write_text("\n".join(json.dumps(entry) for entry in entries))
    content, warnings = _generate_structured_context("parent", ["parent"], path, None, None, None)
    assert content.count("### Turn ") == 3
    assert "Inspect the project" in content
    assert "Review complete" in content
    assert "raw output" not in content
    assert len(content.encode("utf-8")) < 2000
    assert warnings == []


@pytest.mark.parametrize("strategy", [ResumeStrategy.STRUCTURED, ResumeStrategy.FULL])
@pytest.mark.parametrize("block_kind", ["result", "agent", "message"])
def test_new_tool_text_is_writable_when_json_contains_a_lone_surrogate(tmp_path: Path, strategy, block_kind) -> None:
    damaged = "before \ud800 after \U0001f30d"
    blocks = {
        "result": {"type": "tool_result", "content": [{"type": "text", "text": damaged}]},
        "agent": {"type": "tool_use", "name": "Agent", "input": {"prompt": damaged}},
        "message": {"type": "tool_use", "name": "SendMessage", "input": {"content": damaged}},
    }
    note = {"type": "text", "text": "Review note"}
    # Native transcripts put tool results before neighboring text and tool calls after it.
    ordered = [blocks[block_kind], note] if block_kind == "result" else [note, blocks[block_kind]]
    transcript = tmp_path / "damaged.jsonl"
    transcript.write_text(
        json.dumps({"message": {"role": "user" if block_kind == "result" else "assistant", "content": ordered}}) + "\n"
    )
    parent = create_session_state("parent", worktree_path=str(tmp_path))
    parent.confirmed.transcript_path = str(transcript)
    result = assemble_transfer_context(
        parent_name="parent",
        parent_state=parent,
        forge_root=tmp_path,
        strategy=strategy,
        depth=1,
        get_session=lambda _: None,
        child_name="child",
    )
    assert result.context_file is not None
    content = result.context_file.read_text(encoding="utf-8")
    assert "before \\ud800 after \U0001f30d" in content
    assert result.warnings == []

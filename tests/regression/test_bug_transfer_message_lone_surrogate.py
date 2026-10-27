"""Lone surrogates in transcript message text must not break transfer writes or their inputs."""

import json
from pathlib import Path

import pytest

from forge.core.transcript import parse_jsonl_transcript
from forge.session.models import create_session_state
from forge.session.rewind import build_rewind_code_delta_source
from forge.session.transfer import (
    MAX_TRANSCRIPT_CHARS,
    ResumeStrategy,
    _format_transcript_for_llm,
    assemble_transfer_context,
)

pytestmark = pytest.mark.regression

DAMAGED = "before \ud800 after \U0001f30d"
ESCAPED = "before \\ud800 after \U0001f30d"


def _write_transcript(path: Path, damaged_role: str) -> Path:
    # json.dumps spells the lone surrogate as \ud800, as Claude Code's JSON.stringify does.
    texts = {"user": "Plan the change", "assistant": "Planned"} | {damaged_role: DAMAGED}
    entries = [
        {
            "requestId": "r1",
            "message": {"role": role, "content": [{"type": "text", "text": text}]},
        }
        for role, text in texts.items()
    ]
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("strategy", [ResumeStrategy.STRUCTURED, ResumeStrategy.FULL])
@pytest.mark.parametrize("damaged_role", ["user", "assistant"])
def test_message_text_with_a_lone_surrogate_writes_the_child(tmp_path: Path, strategy, damaged_role) -> None:
    parent = create_session_state("parent", worktree_path=str(tmp_path))
    parent.confirmed.transcript_path = str(_write_transcript(tmp_path / "damaged.jsonl", damaged_role))

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
    assert ESCAPED in result.context_file.read_text(encoding="utf-8")
    assert result.warnings == []


@pytest.mark.parametrize("damaged_role", ["user", "assistant"])
def test_curation_and_rewind_inputs_remain_utf8_encodable(tmp_path: Path, damaged_role) -> None:
    entries = parse_jsonl_transcript(_write_transcript(tmp_path / "damaged.jsonl", damaged_role))

    curation_input, _, _ = _format_transcript_for_llm(entries)
    rewind_tail = build_rewind_code_delta_source(entries, kept_turns=0).text

    for text in (curation_input, rewind_tail):
        assert ESCAPED in text.encode("utf-8").decode("utf-8")


@pytest.mark.parametrize("escape_chars_before_cap", range(1, 7))
def test_rewind_tail_cap_keeps_surrogate_escapes_whole(
    escape_chars_before_cap: int,
) -> None:
    def entry(text: str) -> dict:
        return {
            "requestId": "r1",
            "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        }

    prefix = build_rewind_code_delta_source([entry("MARKER")], kept_turns=0).text.index("MARKER")
    padding = "x" * (MAX_TRANSCRIPT_CHARS - prefix - escape_chars_before_cap)
    source = build_rewind_code_delta_source([entry(padding + "\ud800tail")], kept_turns=0)

    kept, marker = source.text.split("\n\n...(rewind tail truncated for length)")
    assert source.was_truncated
    assert marker == ""
    assert len(kept) <= MAX_TRANSCRIPT_CHARS
    expected = padding + ("\\ud800" if escape_chars_before_cap == 6 else "")
    assert kept[prefix:] == expected
    assert source.text.encode("utf-8").decode("utf-8") == source.text

"""Input admission counts state and criteria without a runtime tokenizer."""

import pytest

from forge.core.judgments import JudgmentError, NoulQuestion
from forge.core.judgments.openrouter import MAX_INPUT_BYTES, build_payload


def question():
    return NoulQuestion(instructions="Match?", criteria={"true": "Match", "false": "No match"})


@pytest.mark.parametrize("state", ["x" * MAX_INPUT_BYTES, "\u4e2d" * (MAX_INPUT_BYTES // 3)])
def test_serialized_bytes_include_envelope(state):
    with pytest.raises(JudgmentError) as caught:
        build_payload("typesafe/jev-1.13", state, {"q": question()})
    assert caught.value.kind == "payload_too_large"


def test_questions_count_toward_budget():
    with pytest.raises(JudgmentError):
        build_payload("typesafe/jev-1.13", "tiny", {str(i): question() for i in range(500)})


def test_payload_snapshot_does_not_share_state():
    state = {"items": ["original"]}
    payload = build_payload("typesafe/jev-1.13", state, {"q": question()})
    state["items"].append("changed")
    assert payload["state"] == {"items": ["original"]}


def test_mutated_question_is_revalidated():
    q = question()
    q.criteria.pop("false")
    with pytest.raises(JudgmentError, match="criteria are invalid"):
        build_payload("typesafe/jev-1.13", "x", {"q": q})


@pytest.mark.parametrize("state", [{"x": float("nan")}, {"x": object()}, 123])
def test_non_json_or_invalid_state(state):
    with pytest.raises(JudgmentError):
        build_payload("typesafe/jev-1.13", state, {"q": question()})

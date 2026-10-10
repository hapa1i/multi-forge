"""Trusted real-Codex delivery; run only through an owned, quota-bounded B3 fixture."""

import json
import os

import pytest

pytest_plugins = ["tests.fixtures.b3_feedback"]

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.mark.parametrize("kind", ["tdd", "stub"])
def test_trusted_product_warning_reaches_native_model_context(enrolled_b3_round, kind):
    prefix = os.environ.get("B3_TEST_PREFIX", "integration")
    directory = enrolled_b3_round.case(f"{prefix}-{kind}", kind)
    control = json.loads((directory / "control.json").read_text())
    hooks = [json.loads(line) for line in (directory / "hooks.jsonl").read_text().splitlines()]
    policy = [h for h in hooks if h["hook"] == ["codex-policy-check"]]
    assert len(policy) == 1
    assert policy[0]["exit_code"] == 0
    wire = json.loads(policy[0]["stdout"])
    context = wire["hookSpecificOutput"]["additionalContext"]
    assert "permissionDecision" not in wire["hookSpecificOutput"]
    assert wire["systemMessage"]
    native = [json.loads(line) for line in (directory / "private-rollout.jsonl").read_text().splitlines()]
    injected = [
        r["payload"]
        for r in native
        if r.get("type") == "response_item"
        and r["payload"].get("role") == "developer"
        and "hooks.additional_context" in json.dumps(r)
    ]
    assert any(
        context in json.dumps(r, ensure_ascii=False).replace("\\n", "\n").replace('\\"', '"')
        or context in "".join(c.get("text", "") for c in r.get("content", []))
        for r in injected
    )
    action = json.loads((directory / "action-result.json").read_text())
    assert action["exists"] and action["content"].strip() == "VALUE = 1"
    streams = [
        json.loads(line)
        for p in directory.glob("*-native-stream.jsonl")
        for line in p.read_text().splitlines()
        if line.strip()
    ]
    assert any(r.get("type") == "turn.completed" for r in streams)
    assert json.loads((directory / "usage.json").read_text())
    if kind == "stub":
        nonce = control["reviewer_nonce"]
        assert nonce in context
        replies = [r for r in native if r.get("type") == "response_item" and r["payload"].get("role") == "assistant"]
        assert any(nonce in json.dumps(r) for r in replies)

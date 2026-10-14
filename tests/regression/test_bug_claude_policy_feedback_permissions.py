"""Injected policy outcomes must not approve a native Claude permission request."""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from forge.cli.hooks import hooks
from forge.policy.types import CompositeDecision, PolicyDecision, Violation
from forge.runtime_config import write_runtime_config
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.models import PolicyIntent
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("outcome", ["clean", "warning", "unavailable", "deny", "needs_review"])
@pytest.mark.parametrize("feedback", ["on", "off"])
@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_policy_outcomes_preserve_native_permissions(tmp_path, monkeypatch, outcome, feedback, tool):
    """Cover shared response/audit behavior, not policy evaluation or supervisor registration."""
    policy_id = "coding_standards.no-backward-compat"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_SESSION", "feedback-test")
    state = create_session_state("feedback-test", worktree_path=str(tmp_path))
    state.forge_root = str(tmp_path)
    state.intent.policy = PolicyIntent(enabled=True, bundles=["coding_standards"], fail_mode="closed")
    publish_session(IndexStore(), state, tmp_path, forge_root=tmp_path, checkout_root=tmp_path, relative_path=".")
    store = SessionStore(str(tmp_path), state.name)
    write_runtime_config({"policy_summary_feedback": feedback})

    verdict = "warn" if outcome == "warning" else outcome if outcome in {"deny", "needs_review"} else "allow"
    warnings = ["Synthetic policy warning"] if outcome in {"warning", "unavailable"} else []
    violations = (
        [Violation(policy_id, "Synthetic blocking reason", "high")] if verdict in {"deny", "needs_review"} else []
    )
    decision = PolicyDecision(
        verdict,
        policy_id,
        violations=violations,
        warnings=warnings,
        fail_open=outcome == "unavailable",
        failure_type="timeout" if outcome == "unavailable" else None,
    )
    composite = CompositeDecision(verdict, [decision], violations if verdict == "deny" else [], warnings)
    engine = MagicMock()
    engine.registered_policy_ids = [policy_id]
    engine.evaluate.return_value = composite
    engine.get_collected_state.return_value = {}
    tool_input = {"file_path": "src/example.py"}
    if tool == "Write":
        tool_input["content"] = "value = 1"
    else:
        tool_input.update(old_string="value = 0", new_string="value = 1", replace_all=False)
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
    with patch("forge.cli.hooks.commands.build_hook_engine", return_value=engine):
        result = CliRunner().invoke(hooks, ["policy-check"], input=json.dumps(payload))

    blocked = verdict in {"deny", "needs_review"}
    assert result.exit_code == (2 if blocked else 0), result.output
    if blocked or feedback == "off":
        assert result.stdout == ""
    else:
        wire = json.loads(result.stdout)
        hook = wire["hookSpecificOutput"]
        assert hook["hookEventName"] == "PreToolUse"
        assert hook["additionalContext"].startswith("Forge policy:")
        assert "permissionDecision" not in hook
        assert "decision" not in wire
    if warnings:
        assert warnings[0] in result.stderr
    if verdict == "deny":
        assert "Synthetic blocking reason" in result.stderr
    elif verdict == "needs_review":
        assert "Policy review required" in result.stderr
        assert policy_id in result.stderr
    entries = store.read().confirmed.policy.decisions
    assert len(entries) == 1
    assert entries[0]["decisions"][0]["policy_id"] == policy_id
    assert entries[0]["decisions"][0]["warnings"] == warnings

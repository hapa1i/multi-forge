"""Feedback projection cannot erase denial, audit, or per-file failure information."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from forge.cli.hooks.commands import hooks
from forge.core.runtime.codex_feedback import CODEX_EXECUTOR_IDENTITY_VAR
from forge.policy.types import (
    CompositeDecision,
    PolicyDecision,
    VerifiedCitation,
    Violation,
)
from forge.runtime_config import reset_runtime_config, write_runtime_config
from forge.session import SessionStore, create_session_state
from forge.session.index import IndexStore
from forge.session.models import PolicyIntent
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("forge.core.runtime.codex_feedback._hook_from_launch_child", lambda parent: True)
    monkeypatch.setenv("FORGE_SESSION", "b3")
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))
    monkeypatch.setenv(
        CODEX_EXECUTOR_IDENTITY_VAR,
        json.dumps(
            {
                "schema": 2,
                "launch_parent_pid": os.getpid(),
                "version": "0.162.1",
                "executable": "/fixture/codex",
                "sha256": "a" * 64,
                "device": 0,
                "inode": 1,
                "size": 1,
                "mtime_ns": 1,
            }
        ),
    )
    state = create_session_state("b3", worktree_path=str(tmp_path))
    state.forge_root = str(tmp_path)
    state.intent.policy = PolicyIntent(enabled=True, bundles=["tdd"], bundle_config={"tdd": {"strict": False}})
    publish_session(IndexStore(), state, tmp_path)
    reset_runtime_config()
    yield SessionStore(str(tmp_path), "b3")
    reset_runtime_config()


def invoke(*sections):
    return CliRunner().invoke(
        hooks,
        ["codex-policy-check"],
        input=json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Begin Patch\n" + "\n".join(sections) + "\n*** End Patch"},
            }
        ),
    )


def test_off_keeps_operator_and_full_structured_evidence(session) -> None:
    write_runtime_config({"policy_summary_feedback": "off", "codex_policy_feedback_format": "source-only"})
    result = invoke("*** Add File: src/a.py", "+a = 1")
    assert result.exit_code == 0
    wire = json.loads(result.stdout)
    assert set(wire) == {"systemMessage"}
    assert "Implementation changes require test changes first" in wire["systemMessage"]
    record = session.read().confirmed.policy.decisions[0]["decisions"][0]
    assert record["violations"] == []
    assert record["warning_findings"][0]["suggested_fix"]
    assert record["warning_findings"][0]["provenance"] == "policy"


def test_product_warning_wire_has_context_without_explicit_allow(session) -> None:
    result = invoke("*** Add File: src/a.py", "+a = 1")
    assert result.exit_code == 0
    wire = json.loads(result.stdout)
    assert set(wire["hookSpecificOutput"]) == {"hookEventName", "additionalContext"}
    assert "Implementation changes require test changes first" in wire["hookSpecificOutput"]["additionalContext"]
    assert wire["systemMessage"]


@pytest.mark.parametrize("review_failure", [None, "timeout"])
def test_resolved_tier_one_failure_is_not_reported_as_unreviewed(session, review_failure) -> None:
    tier_one = PolicyDecision(
        "needs_review", "semantic.plan_check", fail_open=True, failure_type="exception", warnings=["tier-one detail"]
    )
    supervisor = PolicyDecision(
        "allow", "semantic.supervisor", fail_open=bool(review_failure), failure_type=review_failure
    )
    engine = MagicMock()
    engine.registered_policy_ids = [tier_one.policy_id, supervisor.policy_id]
    engine.evaluate.return_value = CompositeDecision("allow", [tier_one, supervisor], all_warnings=tier_one.warnings)
    engine.get_collected_state.return_value = {}
    with patch("forge.cli.hooks.commands.build_hook_engine", return_value=engine):
        result = invoke("*** Add File: src/a.py", "+a = 1")
    assert result.exit_code == 0
    assert ("unreviewed" in result.stderr) is bool(review_failure)
    if review_failure:
        assert "unreviewed" in json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    else:
        assert result.stdout == ""
    record = session.read().confirmed.policy.decisions[0]["decisions"][0]
    assert record["failure_type"] == "exception"


@pytest.mark.parametrize("decision", ["deny", "needs_review"])
@pytest.mark.parametrize("supported", [True, False])
def test_blocking_guidance_survives_renderer_on_every_executor(session, decision, supported) -> None:
    from forge.cli.hooks.policy import DENY_NOTE, NEEDS_REVIEW_GUIDANCE

    finding = Violation("rule", "Comply with the rule", "high", provenance="policy")
    blocked = PolicyDecision(decision, "rules", violations=[finding], intent="Preserve the interface")
    engine = MagicMock()
    engine.registered_policy_ids = ["rules"]
    engine.evaluate.return_value = CompositeDecision(decision, [blocked], [finding])
    engine.get_collected_state.return_value = {}
    with (
        patch("forge.cli.hooks.commands.build_hook_engine", return_value=engine),
        patch("forge.core.runtime.codex_feedback.policy_feedback_supported", return_value=supported),
    ):
        result = invoke("*** Add File: src/a.py", "+a = 1")
    wire = json.loads(result.stdout)
    assert wire["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert (DENY_NOTE if decision == "deny" else NEEDS_REVIEW_GUIDANCE) in wire["hookSpecificOutput"][
        "permissionDecisionReason"
    ]


@pytest.mark.parametrize(
    "provenance, verified, must_stop", [("policy", False, False), ("reviewer", True, False), ("reviewer", False, True)]
)
def test_source_only_stop_guidance_belongs_only_to_unquoted_reviewer_findings(
    session, provenance, verified, must_stop
) -> None:
    write_runtime_config({"codex_policy_feedback_format": "source-only"})
    finding = Violation("rule", "Finding", "high", provenance=provenance)
    if verified:
        finding.verified_citations = [VerifiedCitation("/plan", "a" * 64, 0, 12, "Keep the API")]
    blocked = PolicyDecision("deny", "rules", violations=[finding], intent="Preserve the API")
    engine = MagicMock()
    engine.registered_policy_ids = ["rules"]
    engine.evaluate.return_value = CompositeDecision("deny", [blocked], [finding])
    engine.get_collected_state.return_value = {}
    with patch("forge.cli.hooks.commands.build_hook_engine", return_value=engine):
        result = invoke("*** Add File: src/a.py", "+a = 1")
    reason = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert ("Stop and ask the operator" in reason) is must_stop
    if must_stop:
        assert '"path":"src/a.py"' in reason


@pytest.mark.parametrize("failure", ["format", "persist"])
def test_feedback_failures_preserve_deny_without_source_only_prose_fallback(session, failure) -> None:
    write_runtime_config({"codex_policy_feedback_format": "source-only"})
    denied = PolicyDecision("deny", "reviewer", violations=[Violation("reviewer", "private prose", "high")])
    engine = MagicMock()
    engine.registered_policy_ids = ["reviewer"]
    engine.evaluate.return_value = CompositeDecision("deny", [denied], denied.violations)
    engine.get_collected_state.return_value = {"optimistic": {"bad": True}}
    target = (
        "forge.cli.hooks.codex_policy_feedback.render_policy_feedback"
        if failure == "format"
        else "forge.cli.hooks.commands._persist_policy_decisions"
    )
    with (
        patch("forge.cli.hooks.commands.build_hook_engine", return_value=engine),
        patch(target, side_effect=RuntimeError("private exception")),
    ):
        result = invoke("*** Add File: src/a.py", "+a = 1")
    assert result.exit_code == 0
    hook = json.loads(result.stdout)["hookSpecificOutput"]
    assert hook["permissionDecision"] == "deny"
    assert "private prose" not in hook["permissionDecisionReason"]
    assert "private exception" not in hook["permissionDecisionReason"]
    if failure == "format":
        assert not session.read().confirmed.policy.policy_states


@pytest.mark.parametrize("all_failed", [True, False])
def test_partial_or_all_evaluation_failures_remain_unreviewed_and_audited(session, all_failed) -> None:
    engine = MagicMock()
    engine.registered_policy_ids = ["rules"]
    engine.evaluate.side_effect = [
        RuntimeError("provider detail"),
        RuntimeError("provider detail") if all_failed else CompositeDecision("allow"),
    ]
    engine.get_collected_state.return_value = {}
    with patch("forge.cli.hooks.commands.build_hook_engine", return_value=engine):
        result = invoke("*** Add File: src/a.py", "+a = 1", "*** Add File: src/b.py", "+b = 1")
    assert result.exit_code == 0
    wire = json.loads(result.stdout)
    assert "unreviewed" in wire["hookSpecificOutput"]["additionalContext"]
    assert "provider detail" not in result.stdout
    assert "aligned" not in result.stderr
    assert len(session.read().confirmed.policy.decisions) == 2


def test_claude_ignores_codex_format_preference(session) -> None:
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": "src/a.py", "content": "a = 1"},
        }
    )
    baseline = CliRunner().invoke(hooks, ["policy-check"], input=payload)
    write_runtime_config({"codex_policy_feedback_format": "source-only"})
    reset_runtime_config()
    selected = CliRunner().invoke(hooks, ["policy-check"], input=payload)
    assert selected.exit_code == baseline.exit_code
    assert selected.stdout == baseline.stdout

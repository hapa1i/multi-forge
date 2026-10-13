"""Stop evidence must retain gaps without inventing work or paid reviews."""

from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from forge.cli.hooks import hooks
from forge.cli.hooks.codex_stop import _action
from forge.policy.semantic import stop_review as review
from forge.policy.semantic import turn_evidence as evidence
from forge.policy.semantic.supervisor import SupervisorRun
from forge.policy.types import PolicyDecision
from forge.session import SessionStore
from forge.session.events import read_review_checkpoint
from tests.fixtures.stop_review import changed, context, deadline, git

pytestmark = pytest.mark.regression


def _allow():
    return SupervisorRun(PolicyDecision("allow", "semantic.supervisor"), run_ok=True, parsed=True)


def _stop(ctx):
    return review.review_stop(ctx, deadline=deadline(), current_config=lambda: ctx.config_digest)


@pytest.mark.parametrize("observed_work", [False, True])
def test_interrupted_turn_carries_only_an_actual_review_obligation(tmp_path, monkeypatch, observed_work):
    ctx = context(tmp_path)
    review.begin_turn(ctx, deadline=deadline())
    if observed_work:
        # An edit/revert has no net delta, but its observed action still needs review.
        changed(ctx, "original\n", start=False)
    later = replace(ctx, turn_id="01900001-0000-7000-8000-000000000002")
    review.begin_turn(later, deadline=deadline())
    reviewer = Mock(return_value=_allow())
    monkeypatch.setattr(review, "run_supervisor_check", reviewer)

    result = _stop(later)

    assert result.status == ("reviewed" if observed_work else "no_changes")
    assert reviewer.call_count == int(observed_work)
    status = review.status(ctx.forge_root, ctx.session)
    assert status["spent"] is observed_work


def test_submodule_nested_edit_cannot_be_reported_as_complete(tmp_path):
    ctx = context(tmp_path)
    sub = ctx.checkout / "sub"
    sub.mkdir()
    git(sub, "init", "-q")
    git(sub, "config", "user.name", "Fixture")
    git(sub, "config", "user.email", "fixture@example.invalid")
    nested = sub / "nested.txt"
    nested.write_text("original\n")
    git(sub, "add", ".")
    git(sub, "commit", "-qm", "nested")
    git(ctx.checkout, "add", "sub")
    git(ctx.checkout, "commit", "-qm", "gitlink")
    before = evidence.capture(ctx.checkout, ctx.storage, deadline=deadline())
    nested.write_text("changed\n")
    after = evidence.capture(ctx.checkout, ctx.storage, deadline=deadline())
    actions = [{"id": "shell", "phase": phase, "tool": "exec_command"} for phase in ("request", "outcome")]

    result = evidence.compare(ctx.storage, before, after, actions)

    assert b" M sub" in git(ctx.checkout, "status", "--porcelain")
    assert not result["complete"]
    assert "unverified_submodule:sub" in result["omissions"]


def test_reviewed_actions_do_not_create_another_turn_obligation(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    changed(ctx)
    reviewer = Mock(return_value=_allow())
    monkeypatch.setattr(review, "run_supervisor_check", reviewer)
    assert _stop(ctx).status == "reviewed"
    later = replace(ctx, turn_id="01900001-0000-7000-8000-000000000002")
    review.begin_turn(later, deadline=deadline())

    assert _stop(later).status == "no_changes"
    assert reviewer.call_count == 1


def test_large_patch_paths_leave_bounded_evidence_instead_of_disappearing(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    review.begin_turn(ctx, deadline=deadline())
    patch = (
        "*** Begin Patch\n"
        + "".join(f"*** Add File: path_{i:04d}_with_a_long_name.txt\n+x\n" for i in range(300))
        + "*** End Patch\n"
    )
    payload = {
        "tool_use_id": "patch",
        "tool_name": "apply_patch",
        "tool_input": {"command": patch},
    }
    for phase in ("request", "outcome"):
        action = _action(payload, phase, ctx)
        assert len(json.dumps(action).encode()) <= 8_000
        review.record_action(ctx, action)
    checkpoint = read_review_checkpoint(ctx.forge_root, ctx.session, payload_validator=review.validate_payload)
    assert checkpoint is not None
    assert len(checkpoint.payload["actions"]) == 2
    reviewer = Mock(return_value=_allow())
    monkeypatch.setattr(review, "run_supervisor_check", reviewer)

    result = _stop(ctx)

    assert result.status == "partial"
    assert result.reason == "incomplete_evidence"
    assert not result.complete
    assert "tool_evidence_byte_limit" in review.status(ctx.forge_root, ctx.session)["coverage"]["omissions"]
    assert reviewer.call_count == 1


def test_fail_closed_policy_error_removes_the_denied_stop_request(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    changed(ctx)
    store = SessionStore(str(ctx.forge_root), ctx.session)
    state = store.read()
    state.intent.policy.bundles = ["tdd"]
    state.intent.policy.fail_mode = "closed"
    store.write(state)
    monkeypatch.setenv("FORGE_SESSION", ctx.session)
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(ctx.forge_root))
    monkeypatch.setattr("forge.cli.hooks.codex_stop.resolve_context", lambda data: (ctx, store))
    engine = Mock()
    engine.registered_policy_ids = ["tdd"]
    engine.evaluate.side_effect = RuntimeError("synthetic evaluation failure")
    monkeypatch.setattr("forge.cli.hooks.commands.build_hook_engine", lambda effective: engine)
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_use_id": "denied-on-error",
        "tool_name": "apply_patch",
        "tool_input": {"command": "*** Begin Patch\n*** Add File: new.txt\n+test\n*** End Patch"},
        "session_id": ctx.thread_id,
        "turn_id": ctx.turn_id,
        "cwd": str(ctx.checkout),
    }

    result = CliRunner().invoke(hooks, ["codex-policy-check"], input=json.dumps(payload))

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    checkpoint = read_review_checkpoint(ctx.forge_root, ctx.session, payload_validator=review.validate_payload)
    assert checkpoint is not None
    assert not any(action["id"] == "denied-on-error" for action in checkpoint.payload["actions"])
    reviewer = Mock(return_value=_allow())
    monkeypatch.setattr(review, "run_supervisor_check", reviewer)
    assert _stop(ctx).complete
    assert reviewer.call_count == 1

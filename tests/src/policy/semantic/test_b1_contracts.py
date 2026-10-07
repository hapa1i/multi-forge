"""Admission, source identity, and durable evidence for plan-file supervision."""

import json
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from forge.policy.semantic import deadline
from forge.policy.semantic.attempts import ReviewAttempt, read_attempts
from forge.policy.semantic.identity import (
    SUPERVISOR_CONSUMER,
    select_supervisor_lane,
    validate_reviewer,
)
from forge.policy.semantic.plan_source import PlanSnapshot, ReviewSource
from forge.policy.semantic.supervisor import (
    SemanticSupervisorPolicy,
    run_supervisor_check,
)
from forge.policy.types import ActionContext, PolicyDecision
from forge.session.models import LaneRecord, SupervisorConfig


def context(tmp_path):
    return ActionContext(
        origin="codex",
        event="PreToolUse.Write",
        tool_name="Write",
        tool_args={},
        repo_root=str(tmp_path),
        session_name="worker",
        target_path="greet.py",
        new_content="hello",
    )


def test_pending_completed_and_interrupted_are_read_without_mutation(tmp_path):
    config = SupervisorConfig(plan_override_path=str(tmp_path / "plan.md"), forge_root=str(tmp_path))
    snapshot = PlanSnapshot(config.plan_override_path, "hello", "digest")
    first = ReviewAttempt(config, context(tmp_path), snapshot, None, budget=40)
    second = ReviewAttempt(config, context(tmp_path), snapshot, None, budget=40)
    assert all(row["state"] == "pending" for row in read_attempts("worker"))
    first.finish(PolicyDecision(decision="deny", policy_id="semantic.supervisor"))
    second.close()
    before = second.path.read_bytes()
    records = read_attempts("worker")
    assert {row["state"] for row in records} == {"completed", "incomplete"}
    assert next(row for row in records if row["state"] == "incomplete")["verdict"] is None
    assert second.path.read_bytes() == before
    assert read_attempts("worker") == records


def test_killed_hook_leaves_incomplete_attempt_without_usage(tmp_path):
    marker = tmp_path / "ready"
    script = f"""import time
from pathlib import Path
from forge.policy.semantic.attempts import ReviewAttempt
from forge.policy.semantic.plan_source import PlanSnapshot
from forge.policy.types import ActionContext
from forge.session.models import SupervisorConfig
attempt=ReviewAttempt(SupervisorConfig(plan_override_path="/approved.md"), ActionContext(origin="codex",event="PreToolUse.Write",tool_name="Write",tool_args={{}},repo_root={str(tmp_path)!r},session_name="killed"), PlanSnapshot("/approved.md","plan","digest"), None, budget=40)
Path({str(marker)!r}).write_text("ready")
time.sleep(100)
"""
    process = subprocess.Popen([sys.executable, "-c", script])
    try:
        end = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < end:
            time.sleep(0.02)
        assert marker.exists()
        assert read_attempts("killed")[0]["state"] == "pending"
        process.kill()
        process.wait(timeout=3)
        rows = read_attempts("killed")
        assert rows[0]["state"] == "incomplete" and rows[0]["model_run_id"] is None
        from forge.core.usage.ledger import read_usage_events

        assert not list(read_usage_events(command="supervisor"))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_start_evidence_failure_prevents_dispatch(tmp_path):
    with (
        patch("forge.policy.semantic.attempts.atomic_write_json", side_effect=OSError("disk full")),
        patch("forge.policy.semantic.supervisor._dispatch_supervisor") as call,
    ):
        result = run_supervisor_check(SupervisorConfig(plan_override_path="/missing"), context(tmp_path))
    assert result.decision.fail_open
    call.assert_not_called()


def test_checker_and_frontier_share_snapshot_only_for_same_action(tmp_path):
    plan = tmp_path / "plan"
    plan.write_text("old")
    config = SupervisorConfig(plan_override_path=str(plan))
    source, action = ReviewSource(), context(tmp_path)
    snapshot = source.begin(config, action)
    plan.write_text("new")
    assert source.take(config, action) is snapshot
    assert source.take(config, action).text == "new"


def test_reviewer_identity_invalidates_a_persisted_allow(tmp_path):
    plan = tmp_path / "plan"
    plan.write_text("plan")
    config = SupervisorConfig(plan_override_path=str(plan), supervisor_model="opus")
    first = SemanticSupervisorPolicy(config)
    with patch(
        "forge.policy.semantic.supervisor.invoke_supervisor",
        return_value=PolicyDecision(decision="allow", policy_id="semantic.supervisor"),
    ) as call:
        first.evaluate(context(tmp_path))
        config.supervisor_effort = "low"
        second = SemanticSupervisorPolicy(config)
        second.set_state(first.get_state())
        second.evaluate(context(tmp_path))
        assert call.call_count == 2


def test_multi_file_and_cascade_do_not_reset_hook_deadline(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(deadline, "monotonic", lambda: clock[0])

    @deadline.hook_review_budget
    def hook():
        assert deadline.remaining_review_seconds(15) == 15
        clock[0] += 14
        assert deadline.remaining_review_seconds(45) == 41
        clock[0] += 40
        assert deadline.remaining_review_seconds(45) == 1
        clock[0] += 1
        with pytest.raises(TimeoutError):
            deadline.remaining_review_seconds(45)

    hook()
    assert deadline.remaining_review_seconds(45) == 45


def test_changed_registration_is_not_silently_budgeted(monkeypatch):
    from forge.install.codex_hooks import CodexHookEntry

    monkeypatch.setattr(
        "forge.install.codex_hooks.get_builtin_codex_entries",
        lambda: (CodexHookEntry("PreToolUse", "forge-hook codex-policy-check", timeout=30),),
    )
    with pytest.raises(ValueError, match="registration"):
        deadline.validate_timeout(45)


@pytest.mark.parametrize(
    "config,lane",
    [
        (SupervisorConfig(auth_mode="subscription-only", direct=True), select_supervisor_lane(runtime="codex")),
        (
            SupervisorConfig(auth_mode="subscription-only", direct=True, cascade=True),
            select_supervisor_lane(backend="claude-max"),
        ),
        (
            SupervisorConfig(proxy="paid", supervisor_model="claude-opus-5"),
            select_supervisor_lane(model="claude-opus-5"),
        ),
        (
            SupervisorConfig(supervisor_model="gpt-6.1-sol", supervisor_effort="minimal"),
            select_supervisor_lane(runtime="codex", model="gpt-6.1-sol"),
        ),
    ],
)
def test_incompatible_reviewer_identity_refuses(config, lane):
    with pytest.raises(ValueError):
        validate_reviewer(config, lane)


def test_legacy_frozen_subscription_lane_keeps_api_auth(tmp_path, monkeypatch):
    from forge.core.usage.billing import resolve_billing_mode
    from forge.session import SessionStore, create_session_state
    from forge.session.consumer_lanes import (
        ensure_consumer_lane_binding,
        read_bound_lane,
        set_intent_lane,
    )
    from forge.session.models import PolicyIntent
    from tests.fixtures.session_state import publish_session

    root = str(tmp_path)
    store = SessionStore(root, "old")
    state = create_session_state("old", worktree_path=root)
    state.forge_root = root
    state.intent.policy = PolicyIntent(
        enabled=True, supervisor=SupervisorConfig(resume_id="legacy-target", direct=True)
    )
    lane = LaneRecord("claude_code", "claude-max", "opus")
    set_intent_lane(state, SUPERVISOR_CONSUMER, lane)
    ensure_consumer_lane_binding(state, SUPERVISOR_CONSUMER, lane)
    from forge.session.index import IndexStore

    publish_session(IndexStore(), state, root)
    raw = json.loads(store.manifest_path.read_text())
    raw["schema_version"] = 2
    for name in ("auth_mode", "supervisor_model"):
        del raw["intent"]["policy"]["supervisor"][name]
    store.manifest_path.write_text(json.dumps(raw))
    before = store.manifest_path.read_bytes()
    decoded = store.read()
    sup = decoded.intent.policy.supervisor
    assert sup.auth_mode == "inherit" and sup.supervisor_model is None
    assert read_bound_lane(decoded, SUPERVISOR_CONSUMER) == lane
    assert store.manifest_path.read_bytes() == before
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-old-key")
    with (
        patch("forge.policy.semantic.supervisor.run_claude_session") as runner,
        patch("forge.core.usage.emit_usage_for_session_result"),
    ):
        from forge.core.reactive.session_runner import SessionResult

        runner.return_value = SessionResult(
            stdout='{"verdict":"aligned","confidence":1,"violations":[]}', stderr="", returncode=0
        )
        from forge.policy.semantic.supervisor import _ResolvedTarget

        result = run_supervisor_check(
            sup,
            context(tmp_path),
            lane_record=lane,
            resolved_target=_ResolvedTarget(resume_id="legacy-target", source_cwd=root),
        )
    assert result.run_ok
    assert runner.call_args.kwargs["subscription_only"] is False
    assert resolve_billing_mode(direct=True, has_api_key=True, backend_id=lane.backend_id) == "api"
    from forge.core.ops.policy import SupervisorLaneFrozenError, supervisor_set

    plan = tmp_path / "plan"
    plan.write_text("plan")
    with pytest.raises(SupervisorLaneFrozenError):
        supervisor_set(
            store=store,
            manifest=decoded,
            policy_forge_root=root,
            target=None,
            plan=str(plan),
            auth_mode="subscription-only",
        )
    assert store.manifest_path.read_bytes() == before


@pytest.mark.parametrize("source", ["plan", "target+plan", "subscription"])
@pytest.mark.parametrize("legacy_sidecar", [False, True])
def test_sidecar_setup_refuses_before_proxy_or_mutation(tmp_path, source, legacy_sidecar):
    from forge.core.ops.policy import SupervisorInputError, supervisor_set
    from forge.session import SessionStore, create_session_state

    state = create_session_state("sidecar", worktree_path=str(tmp_path), launch_mode="sidecar")
    if legacy_sidecar:
        state.intent.launch = None
        state.confirmed.is_sandboxed = True
    store = SessionStore(str(tmp_path), "sidecar")
    store.write(state)
    before = store.manifest_path.read_bytes()
    plan = tmp_path / "plan.md"
    plan.write_text("approved")
    with patch("forge.policy.semantic.supervisor.ensure_supervisor_proxy") as proxy:
        with pytest.raises(SupervisorInputError, match="host executor"):
            supervisor_set(
                store=store,
                manifest=state,
                policy_forge_root=str(tmp_path),
                target="planner" if source != "plan" else None,
                plan=str(plan) if source != "subscription" else None,
                auth_mode="subscription-only" if source == "subscription" else "inherit",
            )
    proxy.assert_not_called()
    assert store.manifest_path.read_bytes() == before


def test_stale_plan_sidecar_dispatch_is_unavailable_without_model(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_SIDECAR", "1")
    with patch("forge.policy.semantic.supervisor._dispatch_supervisor") as dispatch:
        run = run_supervisor_check(SupervisorConfig(plan_override_path="/host/plan.md"), context(tmp_path))
    assert run.decision.failure_type == "unsupported_executor"
    dispatch.assert_not_called()
    assert read_attempts("worker")[0]["state"] == "unavailable"


def test_legacy_conversation_sidecar_keeps_explicit_route_and_read_only_guard(tmp_path, monkeypatch):
    from forge.core.reactive.session_runner import SessionResult
    from forge.policy.semantic.supervisor import _ResolvedTarget

    monkeypatch.setenv("FORGE_SIDECAR", "1")
    with patch("forge.policy.semantic.supervisor.run_claude_session") as runner:
        runner.return_value = SessionResult(
            stdout='{"verdict":"aligned","confidence":1,"violations":[]}', stderr="", returncode=0
        )
        run = run_supervisor_check(
            SupervisorConfig(resume_id="planner", direct=True),
            context(tmp_path),
            resolved_target=_ResolvedTarget(resume_id="planner", source_cwd=str(tmp_path)),
        )
    assert run.run_ok and runner.call_args.kwargs["read_only"] is True
    assert runner.call_args.kwargs["direct"] is True and runner.call_args.kwargs["subscription_only"] is False


def test_late_terminal_record_replaces_derived_incomplete_state(tmp_path):
    attempt = ReviewAttempt(SupervisorConfig(), context(tmp_path), PlanSnapshot(None, None, None), None, budget=1)
    attempt.record.deadline_at = "2000-01-01T00:00:00+00:00"
    from dataclasses import asdict

    from forge.core.state import atomic_write_json

    atomic_write_json(attempt.path, asdict(attempt.record))
    assert read_attempts("worker")[0]["state"] == "incomplete"
    attempt.finish(PolicyDecision(decision="allow", policy_id="semantic.supervisor"))
    assert read_attempts("worker")[0]["state"] == "completed"


def test_plan_replaced_with_fifo_is_unavailable_without_blocking(tmp_path):
    import os

    from forge.policy.semantic.plan_source import read_plan

    path = tmp_path / "approved.md"
    os.mkfifo(path)
    snapshot = read_plan(SupervisorConfig(plan_override_path=str(path)))
    assert snapshot.text is None and snapshot.digest is None


def test_incomplete_attempt_is_visible_without_usage_and_reset_removes_it(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from forge.cli.main import main
    from forge.session import IndexStore, create_session_state
    from forge.session.models import PolicyIntent
    from tests.fixtures.session_state import publish_session

    monkeypatch.chdir(tmp_path)
    config = SupervisorConfig(resume_id="planner", forge_root=str(tmp_path))
    state = create_session_state("worker", worktree_path=str(tmp_path))
    state.intent.policy = PolicyIntent(supervisor=config)
    publish_session(IndexStore(), state, tmp_path)
    attempt = ReviewAttempt(config, context(tmp_path), PlanSnapshot(None, None, None), None, budget=30)
    attempt.close()
    before = attempt.path.read_bytes()
    runner = CliRunner()
    status = runner.invoke(main, ["policy", "supervisor", "status", "-s", "worker", "--json"])
    assert status.exit_code == 0, status.output
    assert json.loads(status.stdout)["supervisor"]["latest_review"]["state"] == "incomplete"
    activity = runner.invoke(main, ["telemetry", "activity", "worker", "--json"])
    assert activity.exit_code == 0, activity.output
    data = json.loads(activity.stdout)
    assert data["supervisor_reviews"][0]["state"] == "incomplete"
    assert data["downstream"]["rows"] == [] and data["downstream"]["total_cost_micro_usd"] is None
    from forge.core.usage.ledger import read_usage_events

    assert not list(read_usage_events(command="supervisor"))
    assert attempt.path.read_bytes() == before
    preview = runner.invoke(main, ["telemetry", "costs", "reset", "--dry-run"])
    assert preview.exit_code == 0 and "supervisor attempts" in preview.stdout, preview.output
    assert attempt.path.exists()
    applied = runner.invoke(main, ["telemetry", "costs", "reset", "--yes"])
    assert applied.exit_code == 0, applied.output
    assert not read_attempts("worker") and not attempt.lock_path.exists()


@pytest.mark.parametrize("value", ["null", '{"supervisor":null}', '{"supervisor":{"auth_mode":"subscription-only"}}'])
def test_generic_policy_override_cannot_clear_or_change_frozen_identity(tmp_path, monkeypatch, value):
    from click.testing import CliRunner

    from forge.cli.main import main
    from forge.session import IndexStore, SessionStore, create_session_state
    from forge.session.consumer_lanes import (
        ensure_consumer_lane_binding,
        set_intent_lane,
    )
    from forge.session.models import PolicyIntent
    from tests.fixtures.session_state import publish_session

    monkeypatch.chdir(tmp_path)
    state = create_session_state("worker", worktree_path=str(tmp_path))
    state.intent.policy = PolicyIntent(supervisor=SupervisorConfig(resume_id="planner", direct=True))
    lane = LaneRecord("claude_code", "claude-max", "opus")
    set_intent_lane(state, SUPERVISOR_CONSUMER, lane)
    ensure_consumer_lane_binding(state, SUPERVISOR_CONSUMER, lane)
    publish_session(IndexStore(), state, tmp_path)
    store = SessionStore(str(tmp_path), "worker")
    before = store.manifest_path.read_bytes()
    result = CliRunner().invoke(main, ["session", "set", "--session", "worker", "policy", value])
    assert result.exit_code != 0, result.output
    assert store.manifest_path.read_bytes() == before

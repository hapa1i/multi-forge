"""Exercise real Click handlers, including the Stop wire and policy coexistence."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from forge.cli.hooks import codex_stop as hook_module
from forge.cli.hooks import hooks
from forge.policy.semantic import stop_review
from forge.policy.semantic.supervisor import SupervisorRun
from forge.policy.types import PolicyDecision, VerifiedCitation, Violation
from forge.session import SessionStore
from tests.fixtures.stop_review import context


@pytest.fixture
def managed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge-home"))
    ctx = context(tmp_path)
    monkeypatch.setenv("FORGE_SESSION", ctx.session)
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(ctx.forge_root))
    monkeypatch.setenv("FORGE_CODEX_EXECUTOR_IDENTITY", "{}")
    monkeypatch.setattr(hook_module, "stop_review_supported", lambda env: True)
    monkeypatch.setattr(hook_module.codex_turn_enrollment, "verified", lambda identity=None: True)
    monkeypatch.setattr(hook_module.codex_turn_enrollment, "observe", lambda data: False)
    return ctx


def payload(ctx, event, **kwargs):
    return json.dumps(
        {
            "hook_event_name": event,
            "session_id": ctx.thread_id,
            "turn_id": ctx.turn_id,
            "cwd": str(ctx.checkout),
            **kwargs,
        }
    )


def invoke(ctx, command, event, **kwargs):
    result = CliRunner().invoke(hooks, [command], input=payload(ctx, event, **kwargs))
    assert result.exit_code == 0, (result.output, result.exception)
    return json.loads(result.stdout) if result.stdout.strip() else {}


def apply(ctx):
    command = "*** Begin Patch\n*** Update File: work.txt\n@@\n-original\n+changed\n*** End Patch"
    fields = {"tool_name": "apply_patch", "tool_use_id": "tool-one", "tool_input": {"command": command}}
    invoke(ctx, "codex-policy-check", "PreToolUse", **fields)
    (ctx.checkout / "work.txt").write_text("changed\n")
    invoke(ctx, "codex-turn-tool", "PostToolUse", tool_response="Exit code 0", **fields)


def test_real_handlers_emit_one_source_only_correction(managed, monkeypatch) -> None:
    ctx = managed
    quote = VerifiedCitation(str(ctx.config.plan_override_path), "a" * 64, 0, 10, "Keep small")
    violation = Violation(
        "semantic.supervisor",
        "REVIEWER-INJECTION",
        "high",
        evidence="UNVERIFIED",
        suggested_fix="UNVERIFIED",
        provenance="reviewer",
        verified_citations=[quote],
    )
    call = Mock(
        return_value=SupervisorRun(
            PolicyDecision("deny", "semantic.supervisor", violations=[violation]), run_ok=True, parsed=True
        )
    )
    monkeypatch.setattr(stop_review, "run_supervisor_check", call)
    from types import SimpleNamespace

    monkeypatch.setattr(
        "forge.runtime_config.get_runtime_config",
        lambda: SimpleNamespace(codex_policy_feedback_format="source-only", policy_summary_feedback="off"),
    )
    invoke(ctx, "codex-turn-start", "UserPromptSubmit")
    apply(ctx)
    wire = invoke(ctx, "codex-stop", "Stop", stop_hook_active=False)
    assert wire["decision"] == "block"
    assert "Keep small" in wire["reason"]
    assert "UNVERIFIED" not in wire["reason"] and "REVIEWER-INJECTION" not in wire["reason"]
    assert "permissionDecision" not in json.dumps(wire)
    assert call.call_count == 1
    # Crash after returned verdict/before stdout is indistinguishable from delivery:
    # the durable correction is already consumed, so the real adapter never replays it.
    repeated = invoke(ctx, "codex-stop", "Stop", stop_hook_active=True)
    assert set(repeated) == {"systemMessage"}
    assert call.call_count == 1


def test_unmanaged_and_nested_runtime_cannot_mutate_parent(managed, monkeypatch) -> None:
    ctx = managed
    monkeypatch.setattr(hook_module, "stop_review_supported", lambda env: False)
    assert invoke(ctx, "codex-turn-start", "UserPromptSubmit") == {}
    assert invoke(ctx, "codex-stop", "Stop", stop_hook_active=False) == {}
    assert not ctx.storage.parent.exists()


def test_wrong_thread_or_checkout_never_establishes_baseline(managed) -> None:
    ctx = replace(managed, thread_id="01900000-0000-7000-8000-000000000002")
    invoke(ctx, "codex-turn-start", "UserPromptSubmit")
    assert not ctx.storage.parent.exists()
    wire = invoke(ctx, "codex-stop", "Stop", stop_hook_active=False)
    assert set(wire) == {"systemMessage"}
    assert "unavailable" in wire["systemMessage"]


def test_stop_keeps_deterministic_engine_but_excludes_semantic_registration(managed, monkeypatch) -> None:
    from forge.cli.hooks.policy import register_supervisor_and_restore
    from forge.session.effective import compute_effective_intent

    ctx = managed
    state = SessionStore(str(ctx.forge_root), ctx.session).read()
    engine = Mock()
    assert register_supervisor_and_restore(engine, compute_effective_intent(state), state) is None
    engine.register.assert_not_called()
    engine.register_resolver.assert_not_called()
    engine.restore_state.assert_called_once()


def test_telemetry_reset_cannot_reopen_operational_allowance(managed, monkeypatch) -> None:
    from forge.cli.main import main

    ctx = managed
    call = Mock(return_value=SupervisorRun(PolicyDecision("allow", "semantic.supervisor"), run_ok=True, parsed=True))
    monkeypatch.setattr(stop_review, "run_supervisor_check", call)
    invoke(ctx, "codex-turn-start", "UserPromptSubmit")
    apply(ctx)
    invoke(ctx, "codex-stop", "Stop", stop_hook_active=False)
    journal = ctx.storage.parent / "events.jsonl"
    before = journal.read_bytes()
    reset = CliRunner().invoke(main, ["telemetry", "costs", "reset", "--yes"])
    assert reset.exit_code == 0, reset.output
    assert journal.read_bytes() == before
    invoke(ctx, "codex-stop", "Stop", stop_hook_active=True)
    assert call.call_count == 1
    assert stop_review.status(ctx.forge_root, ctx.session)["spent"]


@pytest.mark.parametrize("method", ["resume_session", "fork_session", "relaunch_session"])
def test_policy_inheriting_claude_derivation_refuses_before_publication(managed, method: str) -> None:
    from forge.session.manager import SessionManager

    ctx = managed
    manager = SessionManager()
    parent = SessionStore(str(ctx.forge_root), ctx.session)
    before = parent.read()
    kwargs = {"forge_root": str(ctx.forge_root)}
    if method != "fork_session":
        kwargs["child_name"] = "refused-child"
    with pytest.raises(ValueError, match="Stop"):
        getattr(manager, method)(ctx.session, **kwargs)
    assert parent.read() == before
    assert not SessionStore(str(ctx.forge_root), "refused-child").exists()


def test_trigger_omission_switch_and_atomic_cascade_rejection(managed, monkeypatch) -> None:
    from forge.cli.main import main

    ctx = managed
    monkeypatch.chdir(ctx.checkout)
    monkeypatch.setattr("forge.core.reactive.reviewer_runtime.preflight_supervisor_runtime", lambda *a, **k: None)
    monkeypatch.setattr(hook_module.codex_turn_enrollment, "require_for_launch", lambda **kwargs: None)
    args = [
        "policy",
        "supervisor",
        "set",
        "--session",
        ctx.session,
        "--plan",
        ctx.config.plan_override_path,
        "--model",
        "sonnet",
    ]
    runner = CliRunner()
    retained = runner.invoke(main, args)
    assert retained.exit_code == 0, retained.output
    store = SessionStore(str(ctx.forge_root), ctx.session)
    policy = store.read().intent.policy
    assert policy is not None and policy.supervisor is not None
    assert policy.supervisor.review_trigger == "stop"
    before = store.read()
    rejected = runner.invoke(main, args + ["--cascade"])
    assert rejected.exit_code != 0
    assert store.read() == before
    default = runner.invoke(main, args + ["--trigger", "pre-tool-use"])
    assert default.exit_code == 0, default.output
    policy = store.read().intent.policy
    assert policy is not None and policy.supervisor is not None
    assert policy.supervisor.review_trigger == "pre-tool-use"

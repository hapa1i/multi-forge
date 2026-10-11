"""B4: stop_review lost unfinished turns and let incomplete carry poison all later turns."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.policy.semantic import stop_review as review
from forge.policy.semantic.supervisor import SupervisorRun
from forge.policy.types import PolicyDecision
from tests.fixtures.stop_review import changed, context, deadline

pytestmark = pytest.mark.regression


def run(ctx):
    return review.review_stop(ctx, deadline=deadline(), current_config=lambda: ctx.config_digest)


@pytest.mark.parametrize("new_thread", [False, True])
def test_turn_without_stop_is_reviewed_on_next_prompt(tmp_path: Path, monkeypatch, new_thread: bool) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    later = replace(ctx, turn_id="01900001-0000-7000-8000-000000000002")
    if new_thread:
        later = replace(later, thread_id="01900000-0000-7000-8000-000000000099")
    call = Mock(return_value=SupervisorRun(PolicyDecision("allow", "semantic.supervisor"), run_ok=True, parsed=True))
    monkeypatch.setattr(review, "run_supervisor_check", call)
    review.begin_turn(later, deadline=deadline())
    assert run(later).status == "reviewed"
    evidence = json.loads(call.call_args.args[1].raw_diff)
    assert "-original" in evidence["changes"][0]["diff"]
    assert evidence["provenance_turns"] == [ctx.turn_id, later.turn_id]


def test_changes_after_approval_without_followup_stop_are_carried(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    call = Mock(return_value=SupervisorRun(PolicyDecision("allow", "semantic.supervisor"), run_ok=True, parsed=True))
    monkeypatch.setattr(review, "run_supervisor_check", call)
    assert run(ctx).status == "reviewed"
    review.record_action(ctx, {"id": "later", "phase": "request", "turn_id": ctx.turn_id})
    review.record_action(ctx, {"id": "later", "phase": "outcome", "turn_id": ctx.turn_id})
    (ctx.checkout / "work.txt").write_text("later change\n")
    later = replace(ctx, turn_id="01900001-0000-7000-8000-000000000002")
    review.begin_turn(later, deadline=deadline())
    assert run(later).status == "reviewed"
    assert "later change" in call.call_args.args[1].raw_diff
    assert call.call_count == 2


def test_carry_limit_remains_readable_and_reset_preserves_spending(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    review.record_action(ctx, {"id": "missing", "phase": "request", "turn_id": ctx.turn_id})
    assert run(ctx).reason == "incomplete_evidence"
    for number in range(2, 36):
        later = replace(ctx, turn_id=f"01900001-0000-7000-8000-{number:012x}")
        review.begin_turn(later, deadline=deadline())
    status = review.status(ctx.forge_root, ctx.session)
    assert status["reason"] == "carry_limit"
    assert status["reset_required"] is True
    assert len(status["provenance_turns"]) <= review.MAX_PROVENANCE_TURNS
    preview = review.reset_review(ctx.forge_root, ctx.session)
    assert preview["applied"] is False
    assert review.status(ctx.forge_root, ctx.session)["reason"] == "carry_limit"
    assert review.reset_review(ctx.forge_root, ctx.session, apply=True)["applied"]
    review.begin_turn(later, deadline=deadline())  # A repeated capped prompt is not a fresh turn after reset.
    assert run(later).status == "unavailable"
    assert review.status(ctx.forge_root, ctx.session)["reset_requested"]
    fresh = replace(ctx, turn_id="01900001-0000-7000-8000-000000000100")
    changed(fresh, "new epoch\n")
    call = Mock(return_value=SupervisorRun(PolicyDecision("deny", "semantic.supervisor"), run_ok=True, parsed=True))
    monkeypatch.setattr(review, "run_supervisor_check", call)
    assert run(fresh).correction
    assert review.status(ctx.forge_root, ctx.session)["excluded_work"]["turns"] >= 32
    review.reset_review(ctx.forge_root, ctx.session, apply=True)
    review.begin_turn(fresh, deadline=deadline())
    assert run(fresh).status == "unavailable"
    assert review.status(ctx.forge_root, ctx.session)["spent"] is True
    assert call.call_count == 1


def test_no_dispatch_is_false_until_reservation(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    assert review.status(ctx.forge_root, ctx.session)["dispatched"] is False
    review.begin_turn(ctx, deadline=deadline())
    assert run(ctx).status == "no_changes"
    assert review.status(ctx.forge_root, ctx.session)["dispatched"] is False


def test_dropped_action_limit_remains_incomplete_until_explicit_reset(
    tmp_path: Path,
) -> None:
    ctx = context(tmp_path)
    review.begin_turn(ctx, deadline=deadline())
    for number in range(review.MAX_ACTIONS + 2):
        review.record_action(
            ctx,
            {
                "id": str(number // 2),
                "phase": "request" if number % 2 == 0 else "outcome",
                "turn_id": ctx.turn_id,
            },
        )
    changed_config = replace(ctx, config=replace(ctx.config, timeout_seconds=12))
    review.record_action(changed_config, {"id": "config-change", "phase": "request", "turn_id": ctx.turn_id})
    later = replace(changed_config, turn_id="01900001-0000-7000-8000-000000000002")
    review.begin_turn(later, deadline=deadline())
    assert run(later).reason == "incomplete_evidence"
    assert "action_limit" in review.status(ctx.forge_root, ctx.session)["coverage"]["omissions"]


def test_reviewer_depth_refusal_is_known_no_dispatch(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    monkeypatch.setenv("FORGE_DEPTH", "2")
    outcome = run(ctx)  # Exercise the real supervisor's refusal before any runtime dispatch.
    assert outcome.status == "unavailable"
    status = review.status(ctx.forge_root, ctx.session)
    assert status["spent"] is True
    assert status["dispatched"] is False


def test_codex_readiness_refusal_is_known_no_dispatch(tmp_path: Path, monkeypatch) -> None:
    from forge.policy.semantic import supervisor
    from forge.policy.types import ActionContext

    ctx = context(tmp_path)
    monkeypatch.setattr("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight", lambda: None)
    with pytest.raises(supervisor._SupervisorRoutingError) as failure:
        supervisor._dispatch_codex_supervisor(
            prompt="unused",
            config=ctx.config,
            context=ActionContext(
                origin="codex",
                event="Stop",
                tool_name="TurnReview",
                tool_args={},
                repo_root=str(ctx.checkout),
                session_name=ctx.session,
            ),
            usage_command="supervisor",
        )
    assert failure.value.dispatched is False


def test_carry_barrier_during_review_cannot_deliver_an_old_correction(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    for number in range(2, review.MAX_PROVENANCE_TURNS + 1):
        ctx = replace(ctx, turn_id=f"01900001-0000-7000-8000-{number:012x}")
        review.begin_turn(ctx, deadline=deadline())

    def dispatch(*args, **kwargs):
        later = replace(ctx, turn_id="01900001-0000-7000-8000-000000000099")
        review.begin_turn(later, deadline=deadline())
        return SupervisorRun(PolicyDecision("deny", "semantic.supervisor"), run_ok=True, parsed=True)

    monkeypatch.setattr(review, "run_supervisor_check", dispatch)
    result = run(ctx)
    assert not result.correction
    status = review.status(ctx.forge_root, ctx.session)
    assert status["reason"] == "carry_limit"
    assert status["spent"]

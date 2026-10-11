"""Stop reviews spend once, preserve incomplete work, and assess frozen evidence."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.policy.semantic import stop_review as review
from forge.policy.semantic.supervisor import SupervisorRun
from forge.policy.types import PolicyDecision
from tests.fixtures.stop_review import changed, context, deadline


def complete(decision="allow"):
    return SupervisorRun(PolicyDecision(decision, "semantic.supervisor"), run_ok=True, parsed=True)


def run(ctx):
    return review.review_stop(ctx, deadline=deadline(), current_config=lambda: ctx.config_digest)


def test_no_change_skips_but_edit_revert_dispatches(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    call = Mock(return_value=complete())
    monkeypatch.setattr(review, "run_supervisor_check", call)
    review.begin_turn(ctx, deadline=deadline())
    assert run(ctx).status == "no_changes"
    call.assert_not_called()
    # Tool outcomes remain reviewable even when final bytes equal the baseline.
    changed(ctx, "original\n", start=False)
    assert run(ctx).status == "reviewed"
    assert call.call_count == 1
    action = call.call_args.args[1]
    assert action.event == "Stop" and action.tool_name == "TurnReview"
    assert json.loads(action.raw_diff)["actions"]


def test_correction_once_then_next_turn_carries_original_baseline(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    call = Mock(return_value=complete("deny"))
    monkeypatch.setattr(review, "run_supervisor_check", call)
    changed(ctx)
    assert run(ctx).correction
    assert review.status(ctx.forge_root, ctx.session)["correction_consumed"]
    assert not run(ctx).correction
    (ctx.checkout / "work.txt").write_text("corrected without another review\n")
    assert run(ctx).status == "unreviewed"
    assert call.call_count == 1
    next_ctx = replace(ctx, turn_id="01900001-0000-7000-8000-000000000002")
    review.begin_turn(next_ctx, deadline=deadline())
    call.return_value = complete()
    assert run(next_ctx).status == "reviewed"
    evidence = json.loads(call.call_args.args[1].raw_diff)
    assert evidence["provenance_turns"] == [ctx.turn_id, next_ctx.turn_id]
    assert "-original" in evidence["changes"][0]["diff"]
    assert "+corrected" in evidence["changes"][0]["diff"]
    assert not review.status(ctx.forge_root, ctx.session)["outstanding"]


@pytest.mark.parametrize("failure", ["timeout", "subscription_exhausted", "parse_failure", "auth_unavailable"])
def test_operational_failures_consume_reservation(tmp_path: Path, monkeypatch, failure: str) -> None:
    ctx = context(tmp_path)
    call = Mock(
        return_value=SupervisorRun(PolicyDecision("allow", "semantic.supervisor", fail_open=True, failure_type=failure))
    )
    monkeypatch.setattr(review, "run_supervisor_check", call)
    changed(ctx)
    first = run(ctx)
    assert first.status == "unavailable" and not first.correction
    assert not run(ctx).correction and call.call_count == 1
    assert review.status(ctx.forge_root, ctx.session)["spent"]


def test_mode_change_requires_new_explicit_turn(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    different = replace(ctx, config=replace(ctx.config, timeout_seconds=12))
    call = Mock()
    monkeypatch.setattr(review, "run_supervisor_check", call)
    assert run(different).reason == "configuration_changed"
    call.assert_not_called()
    review.begin_turn(different, deadline=deadline())  # same turn cannot reset it
    assert run(different).status == "unavailable"


def test_missing_baseline_or_partial_tools_spend_no_call(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    call = Mock()
    monkeypatch.setattr(review, "run_supervisor_check", call)
    assert run(ctx).status == "unavailable"
    review.begin_turn(ctx, deadline=deadline())
    review.record_action(ctx, {"id": "missing-post", "phase": "request", "turn_id": ctx.turn_id})
    assert run(ctx).reason == "incomplete_evidence"
    call.assert_not_called()


def test_stop_ignores_historical_per_edit_lane_fallback() -> None:
    from forge.policy.supervisor_lane_degrade import (
        read_supervisor_degrade,
        set_supervisor_degrade,
    )
    from forge.session.models import (
        LaneRecord,
        PolicyIntent,
        SupervisorConfig,
        create_session_state,
    )

    state = create_session_state("executor")
    state.intent.policy = PolicyIntent(supervisor=SupervisorConfig(resume_id="planner", review_trigger="stop"))
    set_supervisor_degrade(
        state,
        from_lane=LaneRecord("codex", "codex", "gpt-6.1-sol"),
        to_lane=None,
        reason="subscription_exhausted",
        at="2026-10-11T00:00:00Z",
    )
    assert read_supervisor_degrade(state) is None
    assert state.intent.policy.supervisor is not None
    state.intent.policy.supervisor.review_trigger = "pre-tool-use"
    assert read_supervisor_degrade(state) is not None

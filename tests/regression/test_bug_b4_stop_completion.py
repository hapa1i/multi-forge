"""B4: stop_review completion could lose verdicts to capture timeouts or invalid reason tokens."""

import json
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.cli.hooks.codex_policy_feedback import render_stop_feedback
from forge.policy.semantic import stop_review as review
from forge.policy.semantic.deadline import review_deadline
from forge.policy.semantic.supervisor import SupervisorRun
from forge.policy.types import PolicyDecision
from forge.session.events import read_review_checkpoint
from tests.fixtures.stop_review import changed, context, deadline

pytestmark = pytest.mark.regression


def run(ctx):
    return review.review_stop(ctx, deadline=deadline(), current_config=lambda: ctx.config_digest)


def test_signal_killed_reviewer_finishes_and_cannot_repeat(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    call = Mock(
        return_value=SupervisorRun(
            PolicyDecision("allow", "semantic.supervisor", fail_open=True, failure_type="exit_-9"),
            dispatched=True,
        )
    )
    monkeypatch.setattr(review, "run_supervisor_check", call)
    assert run(ctx).status == "unavailable"
    status = review.status(ctx.forge_root, ctx.session)
    assert status["dispatched"] is True
    event = read_review_checkpoint(ctx.forge_root, ctx.session, payload_validator=review.validate_payload)
    assert event is not None
    assert event.payload["decision"]["failure_type"] == "exit_-9"
    assert not run(ctx).correction
    assert call.call_count == 1


def test_completion_capture_failure_retains_deny_and_budget(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    expires = time.monotonic() + 20

    def dispatch(*args, **kwargs):
        assert review_deadline(45, trigger="stop") <= expires - review.COMPLETION_SECONDS + 0.01
        monkeypatch.setattr(
            review.turn_evidence,
            "capture",
            Mock(side_effect=TimeoutError("capture expired")),
        )
        return SupervisorRun(
            PolicyDecision("deny", "semantic.supervisor"),
            run_ok=True,
            parsed=True,
            dispatched=True,
        )

    monkeypatch.setattr(review, "run_supervisor_check", dispatch)
    result = review.review_stop(ctx, deadline=expires, current_config=lambda: ctx.config_digest)
    assert not result.correction
    event = read_review_checkpoint(ctx.forge_root, ctx.session, payload_validator=review.validate_payload)
    assert event is not None
    assert event.payload["decision"]["decision"] == "deny"
    assert event.payload["status"] == "unavailable"
    assert event.payload["reason"] == "completion_unavailable"


def test_correction_followup_notice_does_not_claim_approval(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    monkeypatch.setattr(
        review,
        "run_supervisor_check",
        Mock(return_value=SupervisorRun(PolicyDecision("deny", "semantic.supervisor"), run_ok=True, parsed=True)),
    )
    assert run(ctx).correction
    again = run(ctx)
    assert again.status == "unreviewed"
    serialized = render_stop_feedback(again, source_only=True, model_feedback=False)
    assert serialized is not None
    wire = json.loads(serialized)
    assert "unreviewed" in wire["systemMessage"]
    assert "decision" not in wire

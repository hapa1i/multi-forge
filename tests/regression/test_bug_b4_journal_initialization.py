"""B4: marker-first session/events initialization made an interrupted first write unrecoverable."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.policy.semantic import stop_review as review
from forge.policy.semantic.supervisor import SupervisorRun
from forge.policy.types import PolicyDecision
from forge.session import events
from tests.fixtures.stop_review import changed, context, deadline

pytestmark = pytest.mark.regression


def test_crash_while_initializing_marker_keeps_complete_checkpoint(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    write = events.atomic_write_text

    def interrupted(path, *args, **kwargs):
        if path.name == "checkpoint-established":
            raise OSError("simulated crash before marker publication")
        return write(path, *args, **kwargs)

    monkeypatch.setattr(events, "atomic_write_text", interrupted)
    with pytest.raises(OSError):
        review.begin_turn(ctx, deadline=deadline())
    assert review.status(ctx.forge_root, ctx.session)["state"] == "collecting"
    monkeypatch.setattr(events, "atomic_write_text", write)
    changed(ctx, start=False)
    call = Mock(return_value=SupervisorRun(PolicyDecision("allow", "semantic.supervisor"), run_ok=True, parsed=True))
    monkeypatch.setattr(review, "run_supervisor_check", call)
    for _ in range(2):
        review.review_stop(ctx, deadline=deadline(), current_config=lambda: ctx.config_digest)
    assert call.call_count == 1
    assert (
        events.get_session_event_journal_path(ctx.forge_root, ctx.session, "review")
        .with_name("checkpoint-established")
        .exists()
    )


def test_missing_marker_never_refunds_valid_spent_journal(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    call = Mock(return_value=SupervisorRun(PolicyDecision("allow", "semantic.supervisor"), run_ok=True, parsed=True))
    monkeypatch.setattr(review, "run_supervisor_check", call)
    review.review_stop(ctx, deadline=deadline(), current_config=lambda: ctx.config_digest)
    journal = events.get_session_event_journal_path(ctx.forge_root, ctx.session, "review")
    journal.with_name("checkpoint-established").unlink()
    review.begin_turn(ctx, deadline=deadline())
    review.review_stop(ctx, deadline=deadline(), current_config=lambda: ctx.config_digest)
    assert call.call_count == 1
    assert review.status(ctx.forge_root, ctx.session)["spent"]

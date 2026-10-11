"""A completed result cannot approve a changed checkout, plan, configuration, or turn."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.policy.semantic import stop_review as review
from forge.policy.semantic.supervisor import SupervisorRun
from forge.policy.types import PolicyDecision
from tests.fixtures.stop_review import changed, context, deadline

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("change", ["checkout", "plan", "configuration", "next-turn"])
def test_stale_deny_is_audit_only_and_never_replayed(tmp_path: Path, monkeypatch, change: str) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    latest_config = ctx.config_digest

    def dispatch(*args, **kwargs):
        nonlocal latest_config
        if change == "checkout":
            (ctx.checkout / "work.txt").write_text("concurrently changed\n")
        elif change == "plan":
            Path(ctx.config.plan_override_path).write_text("New plan\n")
        elif change == "configuration":
            latest_config = "changed"
        else:
            next_ctx = replace(ctx, turn_id="01900001-0000-7000-8000-000000000002")
            review.begin_turn(next_ctx, deadline=deadline())
        return SupervisorRun(PolicyDecision("deny", "semantic.supervisor"), run_ok=True, parsed=True)

    call = Mock(side_effect=dispatch)
    monkeypatch.setattr(review, "run_supervisor_check", call)
    outcome = review.review_stop(ctx, deadline=deadline(), current_config=lambda: latest_config)
    assert outcome.status in {"unreviewed", "unavailable"}
    assert not outcome.correction
    repeated = review.review_stop(ctx, deadline=deadline(), current_config=lambda: latest_config)
    assert not repeated.correction
    assert call.call_count == 1
    assert review.status(ctx.forge_root, ctx.session)["outstanding"]

"""B4 R1/R2: between-turn edits were attributed to Codex and poisoned later reviews."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.policy.semantic import stop_review as review
from forge.policy.semantic.supervisor import SupervisorRun
from forge.policy.types import PolicyDecision
from tests.fixtures.stop_review import changed, context, deadline, git

pytestmark = pytest.mark.regression


def run(ctx):
    return review.review_stop(ctx, deadline=deadline(), current_config=lambda: ctx.config_digest)


@pytest.fixture
def reviewer(monkeypatch):
    call = Mock(return_value=SupervisorRun(PolicyDecision("allow", "semantic.supervisor"), run_ok=True, parsed=True))
    monkeypatch.setattr(review, "run_supervisor_check", call)
    return call


@pytest.mark.parametrize("intervening", ["manual", "commit", "finder", "suspended"])
def test_completed_turn_does_not_own_intervening_work(tmp_path: Path, reviewer, intervening: str) -> None:
    ctx = context(tmp_path)
    changed(ctx, "approved\n")
    assert run(ctx).status == "reviewed"
    if intervening == "commit":
        git(ctx.checkout, "add", "work.txt")
        git(ctx.checkout, "commit", "-qm", "save approved work")
    elif intervening == "finder":
        (ctx.checkout / ".DS_Store").write_bytes(b"\0\0\0\1Bud1")
    else:
        # Disabled/suspended hooks do not report actions, just like a human editor.
        (ctx.checkout / "notes.txt").write_text("outside the supervised turn\n")
    later = replace(ctx, turn_id="01900001-0000-7000-8000-000000000002")
    changed(later, "next supervised edit\n")
    assert run(later).status == "reviewed"
    evidence = json.loads(reviewer.call_args.args[1].raw_diff)
    assert [change["path"] for change in evidence["changes"]] == ["work.txt"]
    assert evidence["complete"]


def test_manual_edit_then_question_does_not_disable_later_turns(tmp_path: Path, reviewer) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    assert run(ctx).status == "reviewed"
    (ctx.checkout / "notes.txt").write_text("human notes\n")
    question = replace(ctx, turn_id="01900001-0000-7000-8000-000000000002")
    review.begin_turn(question, deadline=deadline())
    assert run(question).status == "no_changes"
    for number in range(3, 6):
        later = replace(ctx, turn_id=f"01900001-0000-7000-8000-{number:012x}")
        changed(later, f"edit {number}\n")
        assert run(later).status == "reviewed"
    assert reviewer.call_count == 4


def test_pending_work_excludes_later_manual_edits(tmp_path: Path, reviewer) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    reviewer.return_value = SupervisorRun(PolicyDecision("deny", "semantic.supervisor"), run_ok=True, parsed=True)
    assert run(ctx).correction
    (ctx.checkout / "notes.txt").write_text("human notes\n")
    later = replace(ctx, turn_id="01900001-0000-7000-8000-000000000002")
    review.begin_turn(later, deadline=deadline())
    reviewer.return_value = SupervisorRun(PolicyDecision("allow", "semantic.supervisor"), run_ok=True, parsed=True)
    assert run(later).status == "reviewed"
    evidence = json.loads(reviewer.call_args.args[1].raw_diff)
    assert [change["path"] for change in evidence["changes"]] == ["work.txt"]
    assert "-original" in evidence["changes"][0]["diff"]


def test_unknown_newer_stop_records_missing_tracking_without_a_call(tmp_path: Path, reviewer) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    assert run(ctx).status == "reviewed"
    missed = replace(ctx, turn_id="01900001-0000-7000-8000-000000000002")
    (ctx.checkout / "missed.txt").write_text("unknown execution\n")
    assert run(missed).reason == "missing_turn_start"
    status = review.status(ctx.forge_root, ctx.session)
    assert status["turn_id"] == missed.turn_id
    assert status["excluded_work"]["reviewed"] is False
    assert reviewer.call_count == 1
    later = replace(ctx, turn_id="01900001-0000-7000-8000-000000000003")
    changed(later, "observed\n")
    assert run(later).status == "reviewed"
    evidence = json.loads(reviewer.call_args.args[1].raw_diff)
    assert [change["path"] for change in evidence["changes"]] == ["work.txt"]


def test_unfinished_turn_keeps_observed_commit_gap(tmp_path: Path, reviewer) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    review.record_action(ctx, {"id": "commit", "phase": "request", "turn_id": ctx.turn_id})
    git(ctx.checkout, "add", "work.txt")
    git(ctx.checkout, "commit", "-qm", "executor commit before interruption")
    review.record_action(ctx, {"id": "commit", "phase": "outcome", "turn_id": ctx.turn_id})
    later = replace(ctx, turn_id="01900001-0000-7000-8000-000000000002")
    review.begin_turn(later, deadline=deadline())
    outcome = run(later)
    assert outcome.status == "partial" and not outcome.complete
    evidence = json.loads(reviewer.call_args.args[1].raw_diff)
    assert "repository_identity_or_index_changed" in evidence["omissions"]


def test_unknown_stop_retains_the_unfinished_turn_in_excluded_history(tmp_path: Path, reviewer) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    missed = replace(ctx, turn_id="01900001-0000-7000-8000-000000000002")
    assert run(missed).reason == "missing_turn_start"
    assert review.status(ctx.forge_root, ctx.session)["excluded_work"]["turns"] == 2
    reviewer.assert_not_called()


def test_failed_baseline_is_excluded_before_a_later_review(tmp_path: Path, reviewer, monkeypatch) -> None:
    ctx = context(tmp_path)
    with monkeypatch.context() as failure:
        failure.setattr(review.turn_evidence, "capture", Mock(side_effect=TimeoutError))
        review.begin_turn(ctx, deadline=deadline())
    (ctx.checkout / "work.txt").write_text("work without a baseline\n")
    assert run(ctx).reason == "baseline_unavailable"
    later = replace(ctx, turn_id="01900001-0000-7000-8000-000000000002")
    changed(later, "new observed edit\n")
    assert run(later).complete
    excluded = review.status(ctx.forge_root, ctx.session)["excluded_work"]
    assert excluded["reason"] == "missing_observation" and excluded["reviewed"] is False

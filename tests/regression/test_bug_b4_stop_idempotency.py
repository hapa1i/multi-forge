"""B4: stop_review must not grant another model call to a replay or interrupted owner."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.policy.semantic import stop_review as review
from forge.policy.semantic.supervisor import SupervisorRun
from forge.policy.types import PolicyDecision
from forge.session.events import SessionEventError, get_session_event_journal_path
from tests.fixtures.stop_review import changed, context, deadline

pytestmark = pytest.mark.regression


def run(ctx):
    return review.review_stop(ctx, deadline=deadline(), current_config=lambda: ctx.config_digest)


def test_overlapping_stops_have_one_dispatch_owner(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    started, release = threading.Event(), threading.Event()

    def dispatch(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return SupervisorRun(PolicyDecision("deny", "semantic.supervisor"), run_ok=True, parsed=True)

    call = Mock(side_effect=dispatch)
    monkeypatch.setattr(review, "run_supervisor_check", call)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, ctx)
        assert started.wait(5)
        second = pool.submit(run, ctx).result(timeout=5)
        assert second.status == "incomplete" and not second.correction
        release.set()
        assert first.result(timeout=5).correction
    assert call.call_count == 1
    assert not run(ctx).correction


def test_crash_after_reservation_before_attempt_does_not_retry(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    call = Mock(side_effect=SystemExit("simulated owner death before attempt creation"))
    monkeypatch.setattr(review, "run_supervisor_check", call)
    with pytest.raises(SystemExit):
        run(ctx)
    assert review.status(ctx.forge_root, ctx.session)["state"] == "incomplete"
    assert run(ctx).status == "incomplete"
    assert call.call_count == 1


@pytest.mark.parametrize("damage", ["remove-journal", "empty-journal", "corrupt-journal", "corrupt-marker"])
def test_damaged_history_cannot_grant_fresh_allowance(tmp_path: Path, monkeypatch, damage: str) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    call = Mock(return_value=SupervisorRun(PolicyDecision("allow", "semantic.supervisor"), run_ok=True, parsed=True))
    monkeypatch.setattr(review, "run_supervisor_check", call)
    run(ctx)
    journal = get_session_event_journal_path(ctx.forge_root, ctx.session, "review")
    marker = journal.with_name("checkpoint-established")
    if damage == "remove-journal":
        journal.unlink()
    elif damage == "empty-journal":
        journal.write_text("")
    elif damage == "corrupt-journal":
        journal.write_text('{"interrupted":')
    else:
        marker.write_text("bad marker")
    assert review.status(ctx.forge_root, ctx.session)["state"] == "unavailable"
    with pytest.raises(SessionEventError):
        review.begin_turn(
            replace(ctx, turn_id="01900001-0000-7000-8000-000000000002"),
            deadline=deadline(),
        )
    assert call.call_count == 1


def test_compaction_keeps_watermark_and_leaves_other_domains(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    call = Mock(return_value=SupervisorRun(PolicyDecision("allow", "semantic.supervisor"), run_ok=True, parsed=True))
    monkeypatch.setattr(review, "run_supervisor_check", call)
    run(ctx)
    other = ctx.storage.parent.parent / "authority" / "events.jsonl"
    other.parent.mkdir()
    other.write_text("another domain's bytes\n")
    for _ in range(22):
        run(ctx)
    journal = get_session_event_journal_path(ctx.forge_root, ctx.session, "review")
    assert len(journal.read_text().splitlines()) <= 16
    assert journal.stat().st_size < 2_000_000
    # Replayed UserPromptSubmit cannot manufacture a second allowance.
    review.begin_turn(ctx, deadline=deadline())
    assert review.status(ctx.forge_root, ctx.session)["spent"]
    assert call.call_count == 1
    assert other.read_text() == "another domain's bytes\n"


@pytest.mark.parametrize("damage", ["spent-flag", "frozen-evidence"])
def test_inconsistent_checkpoint_cannot_reopen_spending(tmp_path: Path, monkeypatch, damage: str) -> None:
    ctx = context(tmp_path)
    changed(ctx)
    call = Mock(return_value=SupervisorRun(PolicyDecision("allow", "semantic.supervisor"), run_ok=True, parsed=True))
    monkeypatch.setattr(review, "run_supervisor_check", call)
    run(ctx)
    journal = get_session_event_journal_path(ctx.forge_root, ctx.session, "review")
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    if damage == "spent-flag":
        rows[-1]["payload"]["spent"] = False
    else:
        rows[-1]["payload"]["evidence"]["changes"] = []
    journal.write_text("".join(json.dumps(row) + "\n" for row in rows))
    assert review.status(ctx.forge_root, ctx.session)["reason"] == "review_history_unavailable"
    with pytest.raises(SessionEventError):
        run(ctx)
    assert call.call_count == 1


def test_new_turn_and_other_checkout_have_independent_allowances(tmp_path: Path, monkeypatch) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    a, b = context(first), context(second)
    call = Mock(return_value=SupervisorRun(PolicyDecision("allow", "semantic.supervisor"), run_ok=True, parsed=True))
    monkeypatch.setattr(review, "run_supervisor_check", call)
    for ctx in (a, b):
        changed(ctx)
        assert run(ctx).status == "reviewed"
    next_ctx = replace(a, turn_id="01900001-0000-7000-8000-000000000002")
    changed(next_ctx, "second turn\n")
    assert run(next_ctx).status == "reviewed"
    review.begin_turn(a, deadline=deadline())
    assert run(a).status == "unavailable"
    assert call.call_count == 3


def test_stop_transport_does_not_retry_rejected_output_format(monkeypatch) -> None:
    from unittest.mock import MagicMock

    from forge.core.reactive import headless_json
    from forge.core.reactive.session_runner import run_claude_session

    headless_json.reset_json_capability_cache()
    call = Mock(return_value=MagicMock(stdout="", stderr="error: unknown option '--output-format'", returncode=2))
    monkeypatch.setattr("forge.core.reactive.session_runner.subprocess.run", call)
    try:
        result = run_claude_session("bounded review", retry_output_format=False)
        assert result.returncode == 2
        assert call.call_count == 1
    finally:
        headless_json.reset_json_capability_cache()

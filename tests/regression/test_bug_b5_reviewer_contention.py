"""B5 readiness must not mistake an active reviewer for a missing login."""

import subprocess
import sys
import time
from contextlib import ExitStack

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.reactive import codex_reviewer_home as reviewer
from tests.src.core.reactive.test_codex_reviewer_home import owned as owned
from tests.src.core.reactive.test_codex_reviewer_home import selection as selection

pytestmark = pytest.mark.regression


def test_busy_login_remains_ready_without_acquiring_a_lease(owned, selection, monkeypatch):
    with reviewer.reviewer_lease(owned):
        status = reviewer.auth_status()
        assert status["ready"] and status["busy"] and not status["lease_available"]
        assert status["unavailable_reason"] is None
        shown = CliRunner().invoke(main, ["policy", "supervisor", "auth", "status", "--runtime", "codex"])
        assert shown.exit_code == 0 and "ready" in shown.stdout and "busy" in shown.stdout
        assert not shown.stderr
        monkeypatch.setattr(
            reviewer, "reviewer_lease", lambda *a, **kw: pytest.fail("Readiness must not take the lease")
        )
        reviewer.require_reviewer_auth("subscription-only")
        reviewer.require_source_account(selection)


def test_queued_review_acquires_after_other_process_releases(owned):
    code = (
        "from pathlib import Path\n"
        "from time import monotonic\n"
        "from forge.core.reactive.codex_reviewer_home import reviewer_lease\n"
        "print('waiting', flush=True)\n"
        f"with reviewer_lease(Path({str(owned)!r}), deadline=monotonic()+5):\n"
        " print('acquired', flush=True)\n"
    )
    with reviewer.reviewer_lease(owned):
        child = subprocess.Popen(
            [sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        assert child.stdout.readline().strip() == "waiting"
        time.sleep(0.1)
        assert child.poll() is None
    try:
        out, err = child.communicate(timeout=6)
        assert child.returncode == 0 and out.strip() == "acquired", err
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_queue_expiry_preserves_active_inputs_and_never_asks_for_login(owned, selection, monkeypatch):
    monkeypatch.setattr(reviewer, "QUEUED_REVIEW_FLOOR_SECONDS", 0.0)  # Exercise a timed wait.
    with reviewer.prepare_reviewer_home(selection, auth_mode="subscription-only") as active:
        index = active.sqlite_home / "active.sqlite"
        index.write_text("active reviewer")
        started = time.monotonic()
        with pytest.raises(reviewer.ReviewerBusyError, match="deadline exhausted") as failure:
            with reviewer.prepare_reviewer_home(selection, auth_mode="subscription-only", deadline=started + 0.1):
                pytest.fail("Expired waiter cannot replace active inputs")
        assert 0.09 <= time.monotonic() - started < 2
        assert "auth login" not in str(failure.value)
        assert index.read_text() == "active reviewer"
        assert reviewer.verify_selected_inputs(active.home, selection)


def test_login_reports_busy_without_starting_a_second_native_process(owned, monkeypatch):
    monkeypatch.setattr(reviewer.subprocess, "run", lambda *a, **kw: pytest.fail("Cannot interrupt active reviewer"))
    with reviewer.reviewer_lease(owned):
        with pytest.raises(reviewer.ReviewerBusyError, match="retry after"):
            reviewer.auth_login(extra_usage_off=True)


def test_queued_review_stops_waiting_before_too_little_budget_remains(owned, selection, monkeypatch):
    """A waiter that acquired the login with seconds left would spend quota on a timeout."""
    monkeypatch.setattr(reviewer, "QUEUED_REVIEW_FLOOR_SECONDS", 1.0)
    with reviewer.prepare_reviewer_home(selection, auth_mode="subscription-only"):
        started = time.monotonic()
        with pytest.raises(reviewer.ReviewerBusyError, match="deadline exhausted"):
            with reviewer.prepare_reviewer_home(selection, auth_mode="subscription-only", deadline=started + 1.2):
                pytest.fail("A queued review must keep the floor for its own inference")
        assert 0.15 <= time.monotonic() - started < 0.9


def test_uncontended_review_starts_even_below_the_queue_floor(owned, selection):
    deadline = time.monotonic() + 0.5
    assert deadline - time.monotonic() < reviewer.QUEUED_REVIEW_FLOOR_SECONDS
    with reviewer.prepare_reviewer_home(selection, auth_mode="subscription-only", deadline=deadline) as prepared:
        assert reviewer.verify_selected_inputs(prepared.home, selection)


@pytest.mark.parametrize("wake_time", [100.125, 101.0])
def test_release_during_final_wait_does_not_bypass_cutoff(owned, selection, monkeypatch, wake_time):
    now = [100.0]
    monkeypatch.setattr(reviewer, "QUEUED_REVIEW_FLOOR_SECONDS", 1.0)
    monkeypatch.setattr(reviewer.time, "monotonic", lambda: now[0])
    with ExitStack() as holder:
        active = holder.enter_context(reviewer.prepare_reviewer_home(selection, auth_mode="subscription-only"))
        index = active.sqlite_home / "active.sqlite"
        index.write_text("previous reviewer")

        def release_during_sleep(seconds):
            holder.close()
            now[0] = wake_time

        monkeypatch.setattr(reviewer.time, "sleep", release_during_sleep)
        deadline = 100.125 + reviewer.QUEUED_REVIEW_FLOOR_SECONDS
        with pytest.raises(reviewer.ReviewerBusyError, match="deadline exhausted"):
            with reviewer.prepare_reviewer_home(selection, auth_mode="subscription-only", deadline=deadline):
                pytest.fail("A late successful retry must not stage another review")
        assert index.read_text() == "previous reviewer"
        assert reviewer.verify_selected_inputs(active.home, selection)

    # Refusing a late acquisition must also release the newly acquired descriptor.
    with reviewer.reviewer_lease(owned):
        pass

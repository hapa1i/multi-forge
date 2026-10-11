"""B5 readiness must not mistake an active reviewer for a missing login."""

import subprocess
import sys
import time

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


def test_queue_expiry_preserves_active_inputs_and_never_asks_for_login(owned, selection):
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

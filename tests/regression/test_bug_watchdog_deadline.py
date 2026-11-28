"""A watchdog deadline must survive late pipe readiness and process-group cleanup."""

import errno
import os
import select
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest

from forge.core.reactive import watchdog

pytestmark = pytest.mark.regression


def _wait_for_zombie(pid: int) -> None:
    # Observing the process state keeps the leader unreaped on every supported macOS Python.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = subprocess.check_output(["ps", "-p", str(pid), "-o", "stat="], text=True)
        if state.lstrip().startswith("Z"):
            return
        time.sleep(0.01)
    pytest.fail(f"process {pid} did not exit")


def test_status_pipe_becomes_readable_after_deadline(monkeypatch):
    deadline = time.monotonic() + 30
    clock = Mock(wraps=time)
    clock.monotonic.return_value = deadline - 30
    monkeypatch.setattr(watchdog, "time", clock)
    select_fds = select.select

    def delayed_wait(readers, writers, errors, timeout):
        ready = select_fds(readers, writers, errors, timeout)
        if timeout:
            assert readers[1] in ready[0]
            clock.monotonic.return_value = deadline + 1
        return ready

    monkeypatch.setattr(select, "select", delayed_wait)
    control, parent = os.pipe()
    try:
        result = watchdog._watch(
            control, {"deadline": deadline, "argv": [sys.executable, "-c", "pass"], "prompt": "", "cwd": None}
        )
        assert clock.monotonic.return_value > deadline
        assert result == watchdog._TIMEOUT_EXIT
    finally:
        os.close(parent)


def test_cleanup_reaps_exited_group_before_concluding_it_is_gone(monkeypatch):
    with subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True) as anchor:
        _wait_for_zombie(anchor.pid)
        if sys.platform != "darwin":
            # Darwin denies signals to a group whose only member is an unreaped zombie.
            killpg = os.killpg

            def signal_group(pid, sig):
                if sig and pid == anchor.pid:
                    raise PermissionError(errno.EPERM, "zombie-only group")
                killpg(pid, sig)

            monkeypatch.setattr(os, "killpg", signal_group)
        watchdog._cleanup_anchor(anchor, completed=True, cancel_before_kill=False)
        assert anchor.returncode == 0


@pytest.mark.parametrize("probe_denied", [False, True])
def test_cleanup_preserves_permission_error_when_group_member_survives(monkeypatch, probe_denied):
    blocker = [sys.executable, "-c", "import sys; sys.stdin.read()"]
    with (
        subprocess.Popen(blocker, stdin=subprocess.PIPE, process_group=0) as anchor,
        subprocess.Popen(blocker, stdin=subprocess.PIPE, process_group=anchor.pid) as survivor,
    ):
        assert anchor.stdin is not None
        anchor.stdin.close()
        _wait_for_zombie(anchor.pid)
        killpg = os.killpg

        def deny_signal(pid, sig):
            if sig and pid == anchor.pid:
                raise PermissionError(errno.EPERM, "live group denied")
            if probe_denied and pid == anchor.pid:
                raise PermissionError(errno.EPERM, "group probe denied")
            killpg(pid, sig)

        monkeypatch.setattr(os, "killpg", deny_signal)
        with pytest.raises(PermissionError, match="live group denied"):
            watchdog._cleanup_anchor(anchor, completed=True, cancel_before_kill=False)
        assert survivor.poll() is None

"""Real descriptor inheritance across experimental watchdog owner death; no LLM."""

import fcntl
import json
import os
import signal
import subprocess
import sys
import time

import pytest

from tests.fixtures.codex_probe import PROBES


def _wait(predicate, seconds=6):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    assert predicate()


def _running(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip()) and not result.stdout.strip().startswith("Z")


@pytest.mark.parametrize("kill_watcher", [False, True])
def test_lease_survives_hook_death_until_owned_reviewer_is_gone(tmp_path, kill_watcher):
    evidence = tmp_path / "processes.json"
    lease = tmp_path / "lease"
    reviewer = tmp_path / "reviewer.py"
    reviewer.write_text(
        "import json, os, signal, sys, time\n"
        "from pathlib import Path\n"
        "os.close(int(sys.argv[1]))\n"  # Only the guard, not a cooperative reviewer, retains the lease.
        "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"Path({str(evidence)!r}).write_text(json.dumps([os.getpid(), os.getppid()]))\n"
        "time.sleep(30)\n"
    )
    owner_code = (
        "import fcntl, os, runpy, sys\n"
        f"guard = runpy.run_path({str(PROBES / 'b5-watchdog.py')!r})\n"
        f"with open({str(lease)!r}, 'w') as lease:\n"
        " fcntl.flock(lease.fileno(), fcntl.LOCK_EX)\n"
        f" guard['run_guarded']([sys.executable, {str(reviewer)!r}, str(lease.fileno())], "
        "input='', env=dict(os.environ), cwd=None, timeout=3, pass_fds=(lease.fileno(),))\n"
    )
    anchor = None
    with (tmp_path / "owner.log").open("w") as log:
        owner = subprocess.Popen([sys.executable, "-c", owner_code], stdout=log, stderr=log, start_new_session=True)
        try:
            _wait(evidence.exists)
            pid, anchor = json.loads(evidence.read_text())
            watcher = int(subprocess.check_output(["ps", "-p", str(anchor), "-o", "ppid="], text=True))
            owner.kill()
            owner.wait(timeout=2)
            if kill_watcher:
                os.kill(watcher, signal.SIGKILL)
            with lease.open("r+") as contender:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                assert _running(pid)

                def released():
                    try:
                        fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        return False
                    return True

                _wait(released)
                assert not _running(pid)
                _wait(lambda: not _running(anchor) and not _running(watcher))
        finally:
            if owner.poll() is None:
                owner.kill()
                owner.wait()
            if anchor and _running(anchor):
                os.killpg(anchor, signal.SIGKILL)

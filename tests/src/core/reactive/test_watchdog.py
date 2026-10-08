"""Real process-lifetime tests; no model calls or runtime credentials."""

import json
import os
import signal
import subprocess
import sys
import time

import pytest

from forge.core.reactive.watchdog import run_guarded


def _wait_until(predicate, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.02)
    assert predicate()


def _running(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip()) and not result.stdout.strip().startswith("Z")


@pytest.mark.parametrize("termination", ["deadline", "hook", "hook_group", "watcher"])
def test_reviewers_and_grandchildren_cannot_outlive_hook_budget(tmp_path, termination):
    evidence = tmp_path / "processes.json"
    reviewer = tmp_path / "reviewer.py"
    reviewer.write_text(
        "import json, os, signal, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(100)'])\n"
        f"Path({str(evidence)!r}).write_text(json.dumps([os.getpid(), child.pid, os.getppid()]))\n"
        "time.sleep(100)\n"
    )
    parent_code = (
        "import os, sys\n"
        "from forge.core.reactive.watchdog import run_guarded\n"
        f"run_guarded([sys.executable, {str(reviewer)!r}], input='', env=dict(os.environ), cwd=None, timeout=2)\n"
    )
    with (tmp_path / "hook.log").open("w") as log:
        parent = subprocess.Popen([sys.executable, "-c", parent_code], stdout=log, stderr=log, start_new_session=True)
        try:
            _wait_until(evidence.exists)
            reviewer_pid, grandchild_pid, anchor_pid = json.loads(evidence.read_text())
            assert _running(reviewer_pid) and _running(grandchild_pid)
            if termination == "hook":
                parent.kill()
            elif termination == "hook_group":
                os.killpg(parent.pid, signal.SIGKILL)
            elif termination == "watcher":
                watcher_pid = subprocess.check_output(["ps", "-p", str(anchor_pid), "-o", "ppid="], text=True)
                os.kill(int(watcher_pid), signal.SIGKILL)
            _wait_until(lambda: not _running(reviewer_pid) and not _running(grandchild_pid), seconds=4)
            parent.wait(timeout=4)
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait()


def test_success_preserves_output_and_cleans_finished_group(tmp_path):
    result = run_guarded(
        [sys.executable, "-c", "import sys; print(sys.stdin.read()); print('diagnostic', file=sys.stderr)"],
        input="review text",
        env=dict(os.environ),
        cwd=str(tmp_path),
        timeout=3,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "review text"
    assert result.stderr.strip() == "diagnostic"


def test_deadline_reports_timeout():
    with pytest.raises(subprocess.TimeoutExpired):
        run_guarded(
            [sys.executable, "-c", "import time; time.sleep(100)"],
            input="",
            env=dict(os.environ),
            cwd=None,
            timeout=0.2,
        )

"""B4: Executor cancellation must close a detached Stop hook's reviewer control pipe."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression


def running(pid: int) -> bool:
    result = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip()) and not result.stdout.strip().startswith("Z")


def wait_for(predicate) -> None:
    end = time.monotonic() + 6
    while time.monotonic() < end and not predicate():
        time.sleep(0.03)
    assert predicate()


def test_executor_death_reaps_hook_reviewer_and_descendant(tmp_path: Path) -> None:
    evidence = tmp_path / "reviewer.json"
    hook_pid = tmp_path / "hook.pid"
    reviewer = tmp_path / "reviewer.py"
    reviewer.write_text(
        "import json, os, signal, subprocess, sys, time\nfrom pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(100)'])\n"
        f"Path({str(evidence)!r}).write_text(json.dumps([os.getpid(), child.pid]))\n"
        "time.sleep(100)\n"
    )
    hook = tmp_path / "hook.py"
    hook.write_text(
        "import os, sys\nfrom pathlib import Path\n"
        "from forge.core.reactive.watchdog import exit_on_parent_death, run_guarded\n"
        f"Path({str(hook_pid)!r}).write_text(str(os.getpid()))\n"
        "with exit_on_parent_death(os.getppid()):\n"
        f"    run_guarded([sys.executable, {str(reviewer)!r}], input='', env=dict(os.environ), cwd=None, timeout=45)\n"
    )
    executor = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess, sys, time; subprocess.Popen([sys.executable, sys.argv[1]], start_new_session=True); time.sleep(100)",
            str(hook),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    owned = []
    try:
        wait_for(evidence.exists)
        owned = [int(hook_pid.read_text()), *json.loads(evidence.read_text())]
        assert all(running(pid) for pid in owned)
        executor.terminate()
        executor.wait(timeout=2)
        wait_for(lambda: not any(running(pid) for pid in owned))
    finally:
        if executor.poll() is None:
            executor.kill()
            executor.wait()
        for pid in owned:
            if running(pid):
                os.kill(pid, 9)

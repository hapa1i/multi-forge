"""B1: output-format negotiation previously spent the full timeout twice."""

import subprocess

import pytest

from forge.core.reactive import session_runner

pytestmark = pytest.mark.regression


def test_output_format_retry_uses_remaining_budget(monkeypatch):
    elapsed = [0.0]
    timeouts = []
    monkeypatch.setattr(session_runner, "monotonic", lambda: elapsed[0], raising=False)
    monkeypatch.setattr(session_runner, "prepare_json_argv", lambda cmd, fmt: (cmd + ["--output-format", "json"], True))
    monkeypatch.setattr(session_runner, "mark_json_output_unsupported", lambda: None)

    def run(argv, **kwargs):
        timeouts.append(kwargs["timeout"])
        if len(timeouts) == 1:
            elapsed[0] = 44.0
            return subprocess.CompletedProcess(argv, 2, "", "error: unknown option '--output-format'")
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(session_runner.subprocess, "run", run)
    result = session_runner.run_claude_session("review", timeout_seconds=45)
    assert result.success
    assert len(timeouts) == 2
    assert 0 < timeouts[1] <= 1


def test_new_hook_processes_each_negotiate_with_one_deadline(tmp_path):
    """A capability latch in an earlier process cannot prevent a second full timeout."""
    import json
    import os
    import sys

    binary = tmp_path / "claude"
    binary.write_text("""#!/usr/bin/env python3
import json,sys,time
from pathlib import Path
if '--version' in sys.argv:
    print('2.1.291'); sys.exit(0)
if '--help' in sys.argv:
    print('--restricted --safe-mode --strict-mcp-config --disable-slash-commands --tools --allowedTools --setting-sources'); sys.exit(0)
with Path(sys.argv[0]).with_suffix('.calls').open('a') as calls:
    calls.write(json.dumps(sys.argv[1:]) + '\\n')
if '--output-format' in sys.argv:
    time.sleep(1.2)
    print("error: unknown option '--output-format'", file=sys.stderr)
    sys.exit(2)
time.sleep(4)
""")
    binary.chmod(0o700)
    program = """import json,time
from forge.core.reactive.env import build_claude_env
from forge.core.reactive.reviewer_runtime import require_reviewer_runtime
from forge.core.reactive.session_runner import run_claude_session
# This test owns output-format negotiation, not cold admission startup latency.
require_reviewer_runtime(env=build_claude_env(), deadline=time.monotonic()+10)
start=time.monotonic()
r=run_claude_session('review',timeout_seconds=2,read_only=True)
print(json.dumps({'timed_out':r.timed_out,'elapsed':time.monotonic()-start,'error':r.error,'dispatched':r.dispatched}))
"""
    env = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ["PATH"])
    for _ in range(2):
        result = subprocess.run([sys.executable, "-c", program], env=env, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        row = json.loads(result.stdout)
        assert row["dispatched"] and row["timed_out"] and row["elapsed"] < 3.5, row
    calls = [json.loads(line) for line in binary.with_suffix(".calls").read_text().splitlines()]
    assert ["--output-format" in argv for argv in calls] == [True, False, True, False]

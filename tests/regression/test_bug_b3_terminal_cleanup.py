"""A terminal must consume Escape before the probe driver sends EOF."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression


def test_probe_closes_modal_before_sending_eof(tmp_path):
    control = tmp_path / "control.json"
    control.write_text(json.dumps({"capture": str(tmp_path)}))
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    script = Path(__file__).resolve().parents[2] / "scripts/experiments/codex-hooks/b3-terminal.py"
    # A small real PTY peer models the input ambiguity: an Escape and EOF in one
    # burst are an Alt-modified key, not a modal dismissal followed by EOF.
    peer = """
import os, time, tty
from pathlib import Path
tty.setraw(0)
(Path(os.environ['CODEX_HOME']) / 'rollout-test.jsonl').write_text('{"type":"task_complete"}\\n')
escaped = None
while True:
    keys = os.read(0, 100)
    now = time.monotonic()
    if keys == b'\\x1b':
        escaped = now
    elif keys == b'\\x04' and escaped is not None and now - escaped > 0.2:
        break
"""
    result = subprocess.run(
        [sys.executable, str(script), "--close-after-turn", "--", sys.executable, "-c", peer],
        env={**os.environ, "PROBE_CONTROL": str(control), "CODEX_HOME": str(runtime)},
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert json.loads((tmp_path / "terminal-result.json").read_text())["exited"]

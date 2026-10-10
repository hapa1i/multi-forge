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


def test_prompt_waits_for_terminal_mode_after_slow_preflight(tmp_path):
    control = tmp_path / "control.json"
    control.write_text(json.dumps({"capture": str(tmp_path)}))
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("fixture prompt")
    script = Path(__file__).resolve().parents[2] / "scripts/experiments/codex-hooks/b3-terminal.py"
    # The former eight-second timer wrote into Forge's inherited terminal before
    # Codex owned input. Model that slow preflight with a real PTY and no model.
    peer = """
import os, select, time, tty
time.sleep(9)
assert not select.select([0], [], [], 0)[0], 'prompt arrived before terminal mode'
tty.setraw(0)
os.write(1, b'\\x1b[?2004')
time.sleep(.3)
os.write(1, b'h' + b'.' * 100)
data = b''
while b'\\r' not in data:
    data += os.read(0, 1000)
assert data == b'\\x1b[200~fixture prompt\\x1b[201~\\r', repr(data)
"""
    result = subprocess.run(
        [sys.executable, str(script), "--prompt-file", str(prompt), "--", sys.executable, "-c", peer],
        env={**os.environ, "PROBE_CONTROL": str(control), "CODEX_HOME": str(runtime)},
        capture_output=True,
        timeout=25,
    )
    assert result.returncode == 0, (tmp_path / "terminal.log").read_text(errors="replace")
    assert json.loads((tmp_path / "terminal-result.json").read_text())["exited"]

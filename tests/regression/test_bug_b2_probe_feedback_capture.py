"""B2: distinguish a response-channel observation from a crashed fixture hook."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tests.fixtures.codex_probe import PROBES

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    "mode", ["feedback-explicit", "feedback-context", "observe", "system-message", "stderr", "updated-input"]
)
def test_hook_retains_stdout_stderr_and_exit_including_a_response_exception(tmp_path, mode):
    capture = tmp_path / "capture"
    control = tmp_path / "control.json"
    control.write_text(json.dumps({"capture": str(capture), "mode": mode, "nonce": "OFFLINE-B2"}))
    # Missing tool_input deliberately crashes the updated-input arm, after recording stdin.
    payload = {"hook_event_name": "PreToolUse", "tool_name": "apply_patch"}
    result = subprocess.run(
        [sys.executable, str(PROBES / "hooks/b2-hook.py"), "PreToolUse"],
        input=json.dumps(payload),
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "PROBE_CONTROL": str(control),
            "PYTHON_DOTENV_DISABLED": "1",
        },
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert next(capture.glob("*.stdout")).read_text() == result.stdout
    assert next(capture.glob("*.stderr")).read_text() == result.stderr
    outcome = json.loads(next(capture.glob("*.result.json")).read_text())
    assert outcome["returncode"] == result.returncode == (1 if mode == "updated-input" else 0)
    if mode == "updated-input":
        assert "KeyError" in result.stderr
    elif mode == "stderr":
        assert "OFFLINE-B2" in result.stderr and not result.stdout
    elif mode == "observe":
        assert not result.stdout and not result.stderr
    elif mode == "system-message":
        assert "OFFLINE-B2" in json.loads(result.stdout)["systemMessage"]
    else:
        response = json.loads(result.stdout)["hookSpecificOutput"]
        assert "OFFLINE-B2" in response["additionalContext"]
        assert ("permissionDecision" in response) == (mode == "feedback-explicit")

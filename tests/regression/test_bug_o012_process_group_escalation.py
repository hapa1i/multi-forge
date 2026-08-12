"""Regression for O012: cancellation left a SIGTERM-ignoring descendant alive."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from unittest.mock import patch

import pytest

from forge.core.invoker import ClaudeHeadlessInvoker, HeadlessRequest
from forge.core.invoker import _lifecycle as lifecycle

pytestmark = pytest.mark.regression

_LEADER_SCRIPT = """
import signal
import subprocess
import sys
import time

child_script = '''
import signal
import time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
print("ready", flush=True)
while True:
    time.sleep(1)
'''

child = subprocess.Popen(
    [sys.executable, "-c", child_script],
    stdout=subprocess.PIPE,
    text=True,
)
print(child.pid, flush=True)
print(child.stdout.readline().strip(), flush=True)
while True:
    time.sleep(1)
"""


def _request() -> HeadlessRequest:
    return HeadlessRequest(
        argv=["claude", "-p"],
        prompt="review",
        env={},
        output_format=None,
        label="worker",
    )


def _group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    return True


def test_o012_cancellation_escalates_when_descendant_ignores_sigterm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leader = subprocess.Popen(
        [sys.executable, "-c", _LEADER_SCRIPT],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    assert leader.stdout is not None
    child_pid = int(leader.stdout.readline().strip())
    assert leader.stdout.readline().strip() == "ready"
    interrupt = KeyboardInterrupt()

    # Keep the regression fast while exercising the real TERM -> wait -> KILL path.
    monkeypatch.setattr(lifecycle, "_PROCESS_GROUP_TERM_TIMEOUT_SECONDS", 0.1, raising=False)
    monkeypatch.setattr(lifecycle, "_PROCESS_GROUP_KILL_TIMEOUT_SECONDS", 1.0, raising=False)

    try:
        with (
            patch("forge.core.invoker._lifecycle.subprocess.Popen", return_value=leader),
            patch.object(leader, "communicate", side_effect=interrupt),
            pytest.raises(KeyboardInterrupt) as exc_info,
        ):
            ClaudeHeadlessInvoker().run(_request())

        assert exc_info.value is interrupt
        assert not _group_exists(
            leader.pid
        ), f"process group {leader.pid} survived cancellation; SIGTERM-ignoring child pid={child_pid}"
    finally:
        try:
            os.killpg(leader.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            leader.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        for stream in (leader.stdout, leader.stderr):
            if stream is not None:
                stream.close()

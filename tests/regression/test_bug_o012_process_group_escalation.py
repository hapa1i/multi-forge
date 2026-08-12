"""Regression for O012: cancellation left a SIGTERM-ignoring descendant alive."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
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
from pathlib import Path

child_pid_path = Path(sys.argv[1])
ready_path = Path(sys.argv[2])

child_script = '''
import signal
import sys
import time
from pathlib import Path

signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(sys.argv[1]).write_text("ready", encoding="utf-8")
while True:
    time.sleep(1)
'''

child = subprocess.Popen(
    [sys.executable, "-c", child_script, str(ready_path)],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
child_pid_path.write_text(str(child.pid), encoding="utf-8")
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


def _wait_for_path(path: Path, leader: subprocess.Popen[str], timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while not path.exists():
        if leader.poll() is not None:
            stdout, stderr = leader.communicate(timeout=1)
            pytest.fail(f"process-group leader exited before {path.name}: stdout={stdout!r}, stderr={stderr!r}")
        if time.monotonic() >= deadline:
            pytest.fail(f"timed out waiting for process-group readiness marker {path.name}")
        time.sleep(0.01)


@pytest.fixture
def stubborn_process_group(tmp_path: Path) -> Iterator[tuple[subprocess.Popen[str], int]]:
    """Start a real group whose child ignores SIGTERM, with bounded readiness."""
    child_pid_path = tmp_path / "child-pid"
    ready_path = tmp_path / "child-ready"
    leader = subprocess.Popen(
        [sys.executable, "-c", _LEADER_SCRIPT, str(child_pid_path), str(ready_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    try:
        _wait_for_path(child_pid_path, leader)
        _wait_for_path(ready_path, leader)
        yield leader, int(child_pid_path.read_text(encoding="utf-8"))
    finally:
        try:
            os.killpg(leader.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            leader.wait(timeout=2)
        except subprocess.TimeoutExpired:
            leader.kill()
            leader.wait(timeout=2)
        for stream in (leader.stdout, leader.stderr):
            if stream is not None:
                stream.close()


def test_o012_cancellation_escalates_when_descendant_ignores_sigterm(
    stubborn_process_group: tuple[subprocess.Popen[str], int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leader, child_pid = stubborn_process_group
    interrupt = KeyboardInterrupt()

    # Keep the regression fast while exercising the real TERM -> wait -> KILL path.
    monkeypatch.setattr(lifecycle, "_PROCESS_GROUP_TERM_TIMEOUT_SECONDS", 0.1, raising=False)
    monkeypatch.setattr(lifecycle, "_PROCESS_GROUP_KILL_TIMEOUT_SECONDS", 1.0, raising=False)

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


def test_o012_grouped_timeout_escalates_when_descendant_ignores_sigterm(
    stubborn_process_group: tuple[subprocess.Popen[str], int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leader, child_pid = stubborn_process_group

    monkeypatch.setattr(lifecycle, "_PROCESS_GROUP_TERM_TIMEOUT_SECONDS", 0.1, raising=False)
    monkeypatch.setattr(lifecycle, "_PROCESS_GROUP_KILL_TIMEOUT_SECONDS", 1.0, raising=False)

    with (
        patch("forge.core.invoker._lifecycle.subprocess.Popen", return_value=leader),
        patch.object(
            leader,
            "communicate",
            side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=1),
        ),
    ):
        result = ClaudeHeadlessInvoker().run_parallel([_request()])

    assert result[0].timed_out
    assert not _group_exists(
        leader.pid
    ), f"process group {leader.pid} survived timeout; SIGTERM-ignoring child pid={child_pid}"

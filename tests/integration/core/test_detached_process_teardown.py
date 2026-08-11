"""Real-process integration coverage for detached process-group teardown."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.backend import BackendStartError
from forge.backend.adapters.litellm import LiteLLMAdapter
from forge.backend.registry import ManagedBackendProcess
from forge.core.invoker import ClaudeHeadlessInvoker, HeadlessRequest

pytestmark = pytest.mark.integration

_CHILD_SCRIPT = """
import signal
import sys
import time
from pathlib import Path

stopped = Path(sys.argv[1])
ready = Path(sys.argv[2])

def stop(_signum, _frame):
    stopped.write_text("stopped", encoding="utf-8")
    raise SystemExit(0)

signal.signal(signal.SIGTERM, stop)
ready.write_text("ready", encoding="utf-8")
while True:
    time.sleep(1)
"""

_PARENT_SCRIPT = """
import signal
import subprocess
import sys
import time
from pathlib import Path

parent_stopped = Path(sys.argv[1])
child_stopped = Path(sys.argv[2])
child_ready = Path(sys.argv[3])
group_ready = Path(sys.argv[4])
child_pid = Path(sys.argv[5])
child_script = sys.argv[6]

def stop(_signum, _frame):
    parent_stopped.write_text("stopped", encoding="utf-8")
    raise SystemExit(0)

signal.signal(signal.SIGTERM, stop)
child = subprocess.Popen([sys.executable, "-c", child_script, str(child_stopped), str(child_ready)])
deadline = time.monotonic() + 5
while not child_ready.exists():
    if time.monotonic() >= deadline:
        raise SystemExit("child did not become ready")
    time.sleep(0.01)
child_pid.write_text(str(child.pid), encoding="utf-8")
group_ready.write_text("ready", encoding="utf-8")
while True:
    time.sleep(1)
"""


@dataclass
class _DetachedGroup:
    process: subprocess.Popen[str]
    ready: Path
    parent_stopped: Path
    child_stopped: Path


def _wait_for(path: Path, process: subprocess.Popen[str] | None = None, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if process is not None and process.poll() is not None:
            stdout, stderr = process.communicate()
            pytest.fail(f"detached process exited before {path.name}: stdout={stdout!r}, stderr={stderr!r}")
        if time.monotonic() >= deadline:
            pytest.fail(f"timed out waiting for {path.name}")
        time.sleep(0.01)


def _wait_for_group_exit(process_group_id: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return
        if time.monotonic() >= deadline:
            pytest.fail(f"timed out waiting for process group {process_group_id} to exit")
        time.sleep(0.01)


def _spawn_detached_group(tmp_path: Path) -> _DetachedGroup:
    parent_stopped = tmp_path / "parent-stopped"
    child_stopped = tmp_path / "child-stopped"
    child_ready = tmp_path / "child-ready"
    group_ready = tmp_path / "group-ready"
    child_pid = tmp_path / "child-pid"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _PARENT_SCRIPT,
            str(parent_stopped),
            str(child_stopped),
            str(child_ready),
            str(group_ready),
            str(child_pid),
            _CHILD_SCRIPT,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    group = _DetachedGroup(
        process=process,
        ready=group_ready,
        parent_stopped=parent_stopped,
        child_stopped=child_stopped,
    )
    try:
        _wait_for(group.ready, process)
    except BaseException:
        _force_cleanup(group)
        raise
    return group


def _force_cleanup(group: _DetachedGroup) -> None:
    try:
        os.killpg(group.process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        group.process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    for stream in (group.process.stdout, group.process.stderr):
        if stream is not None:
            stream.close()


def _request() -> HeadlessRequest:
    return HeadlessRequest(
        argv=["claude", "-p"],
        prompt="review",
        env={},
        output_format=None,
        label="worker",
    )


def test_litellm_stop_reaches_workers_in_the_detached_group(tmp_path: Path) -> None:
    group = _spawn_detached_group(tmp_path)
    try:
        LiteLLMAdapter().stop(
            ManagedBackendProcess(
                process_id="litellm-test",
                adapter_type="litellm",
                port=4000,
                pid=group.process.pid,
            )
        )

        group.process.wait(timeout=5)
        _wait_for(group.parent_stopped)
        _wait_for(group.child_stopped)
    finally:
        _force_cleanup(group)


def test_failed_litellm_start_kills_the_detached_group(tmp_path: Path) -> None:
    group = _spawn_detached_group(tmp_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("model_list: []\n", encoding="utf-8")
    adapter = LiteLLMAdapter()
    try:
        with (
            patch("forge.backend.adapters.litellm.subprocess.Popen", return_value=group.process),
            patch("forge.backend.adapters.litellm.get_forge_home", return_value=tmp_path),
            patch.object(adapter, "_wait_for_health", return_value=False),
            pytest.raises(BackendStartError, match="failed to start"),
        ):
            adapter.start("litellm-test", config_path, 4000)

        group.process.wait(timeout=5)
        _wait_for_group_exit(group.process.pid)
    finally:
        _force_cleanup(group)


def test_single_shot_cancellation_reaps_a_real_detached_group(tmp_path: Path) -> None:
    group = _spawn_detached_group(tmp_path)
    interrupt = KeyboardInterrupt()
    try:
        with (
            patch("forge.core.invoker._lifecycle.subprocess.Popen", return_value=group.process),
            patch.object(group.process, "communicate", side_effect=interrupt),
            pytest.raises(KeyboardInterrupt) as exc_info,
        ):
            ClaudeHeadlessInvoker().run(_request())

        assert exc_info.value is interrupt
        assert group.process.returncode == 0
        _wait_for(group.parent_stopped)
        _wait_for(group.child_stopped)
    finally:
        _force_cleanup(group)

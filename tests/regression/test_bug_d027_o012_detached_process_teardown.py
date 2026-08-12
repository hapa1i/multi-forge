"""Regression guards for detached backend and headless child teardown."""

from __future__ import annotations

import signal
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from click.testing import CliRunner

from forge.backend import BackendManager, BackendStartError
from forge.backend.adapters.litellm import LiteLLMAdapter
from forge.backend.registry import (
    BackendRegistry,
    BackendRegistryStore,
    ManagedBackendProcess,
)
from forge.cli.main import main
from forge.core.invoker import ClaudeHeadlessInvoker, HeadlessRequest

pytestmark = pytest.mark.regression


def _managed_process() -> ManagedBackendProcess:
    return ManagedBackendProcess(
        process_id="litellm-4000",
        adapter_type="litellm",
        port=4000,
        pid=12345,
        status="healthy",
    )


def _backend_manager(tmp_path: Path) -> tuple[BackendManager, BackendRegistryStore]:
    store = BackendRegistryStore(tmp_path / "backends" / "index.json")
    store.write(BackendRegistry(processes={"litellm-4000": _managed_process()}))
    manager = BackendManager(store)
    manager.register_adapter("litellm", LiteLLMAdapter())
    return manager, store


def _headless_request() -> HeadlessRequest:
    return HeadlessRequest(
        argv=["claude", "-p"],
        prompt="review",
        env={},
        output_format=None,
        label="worker",
    )


def _headless_process(*, interrupt: BaseException | None = None) -> MagicMock:
    proc = MagicMock()
    if interrupt is None:
        proc.communicate.return_value = ("ok", "")
    else:
        proc.communicate.side_effect = interrupt
    proc.returncode = 0
    proc.poll.return_value = None
    proc.pid = 54321
    proc.wait.return_value = 0
    return proc


def test_d027_stop_signals_the_owned_process_group() -> None:
    process = _managed_process()

    with (
        patch("forge.backend.adapters.litellm.os.kill") as kill_pid,
        patch("forge.backend.adapters.litellm.os.killpg") as kill_group,
    ):
        LiteLLMAdapter().stop(process)

    kill_group.assert_called_once_with(12345, signal.SIGTERM)
    kill_pid.assert_not_called()


def test_d027_stop_failure_preserves_registry_ownership(tmp_path: Path) -> None:
    manager, store = _backend_manager(tmp_path)

    with (
        patch("forge.backend.adapters.litellm.os.kill", side_effect=PermissionError("not authorized")),
        patch("forge.backend.adapters.litellm.os.killpg", side_effect=PermissionError("not authorized")),
        pytest.raises(PermissionError, match="not authorized"),
    ):
        manager.stop_backend("litellm-4000")

    assert "litellm-4000" in store.read().processes


def test_d027_missing_process_group_is_unregistered(tmp_path: Path) -> None:
    manager, store = _backend_manager(tmp_path)

    with (
        patch("forge.backend.adapters.litellm.os.kill", side_effect=ProcessLookupError),
        patch("forge.backend.adapters.litellm.os.killpg", side_effect=ProcessLookupError),
    ):
        manager.stop_backend("litellm-4000")

    assert "litellm-4000" not in store.read().processes


def test_d027_delete_stop_failure_retains_config_and_reports_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    config_path = tmp_path / "backends" / "litellm" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("model_list: []\n", encoding="utf-8")
    store = BackendRegistryStore(tmp_path / "backends" / "index.json")
    store.write(BackendRegistry(processes={"litellm-4000": _managed_process()}))

    with patch("forge.backend.adapters.litellm.os.killpg", side_effect=PermissionError("not authorized")):
        result = CliRunner().invoke(main, ["model", "backend", "delete", "litellm", "--yes"])

    assert result.exit_code == 1
    assert "litellm-4000: not authorized" in result.output
    assert "Deleted" not in result.output
    assert config_path.exists()
    assert "litellm-4000" in store.read().processes


def test_d027_failed_health_cleanup_kills_the_owned_process_group(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("model_list: []\n", encoding="utf-8")
    proc = MagicMock(pid=12345)
    adapter = LiteLLMAdapter()

    with (
        patch("forge.backend.adapters.litellm.subprocess.Popen", return_value=proc),
        patch.object(adapter, "_wait_for_health", return_value=False),
        patch("forge.backend.adapters.litellm.os.killpg") as kill_group,
        pytest.raises(BackendStartError, match="failed to start"),
    ):
        adapter.start("litellm-4000", config_path, 4000)

    kill_group.assert_called_once_with(12345, signal.SIGKILL)
    proc.kill.assert_not_called()


def test_o012_single_shot_cancellation_terminates_and_reaps_child_group() -> None:
    interrupt = KeyboardInterrupt()
    proc = _headless_process(interrupt=interrupt)

    with (
        patch("forge.core.invoker._lifecycle.subprocess.Popen", return_value=proc),
        patch("forge.core.invoker._lifecycle.os.getpgid", return_value=54321),
        patch("forge.core.invoker._lifecycle.os.killpg") as kill_group,
        patch("forge.core.invoker._lifecycle._process_group_exists", return_value=False),
        pytest.raises(KeyboardInterrupt) as exc_info,
    ):
        ClaudeHeadlessInvoker().run(_headless_request())

    assert exc_info.value is interrupt
    kill_group.assert_called_once_with(54321, signal.SIGTERM)
    assert proc.poll.call_count >= 2  # initial liveness check plus group-wait reaping


def test_o012_normal_single_shot_exit_does_not_signal_child() -> None:
    proc = _headless_process()
    proc.poll.return_value = 0

    with (
        patch("forge.core.invoker._lifecycle.subprocess.Popen", return_value=proc),
        patch("forge.core.invoker._lifecycle.os.killpg") as kill_group,
    ):
        result = ClaudeHeadlessInvoker().run(_headless_request())

    assert result.success
    assert result.stdout == "ok"
    kill_group.assert_not_called()
    proc.wait.assert_not_called()


def test_o012_completed_single_shot_drops_group_ownership_before_result_building() -> None:
    interrupt = KeyboardInterrupt()
    proc = _headless_process()
    invoker = ClaudeHeadlessInvoker()

    with (
        patch("forge.core.invoker._lifecycle.subprocess.Popen", return_value=proc),
        patch.object(invoker, "_build_result", side_effect=interrupt),
        patch("forge.core.invoker._lifecycle.os.getpgid", return_value=54321),
        patch("forge.core.invoker._lifecycle.os.killpg") as kill_group,
        patch("forge.core.invoker._lifecycle._process_group_exists", return_value=False) as group_exists,
        pytest.raises(KeyboardInterrupt) as exc_info,
    ):
        invoker.run(_headless_request())

    assert exc_info.value is interrupt
    group_exists.assert_not_called()
    kill_group.assert_not_called()


def test_o012_grouped_timeout_attempts_group_teardown_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = _headless_process()
    proc.communicate.side_effect = subprocess.TimeoutExpired(cmd=["claude"], timeout=1)
    proc.returncode = None
    proc.poll.return_value = None

    monkeypatch.setattr("forge.core.invoker._lifecycle._PROCESS_GROUP_TERM_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr("forge.core.invoker._lifecycle._PROCESS_GROUP_KILL_TIMEOUT_SECONDS", 0.0)

    with (
        patch("forge.core.invoker._lifecycle.subprocess.Popen", return_value=proc),
        patch("forge.core.invoker._lifecycle.os.getpgid", return_value=54321),
        patch("forge.core.invoker._lifecycle.os.killpg") as kill_group,
        patch("forge.core.invoker._lifecycle._process_group_exists", return_value=True),
    ):
        result = ClaudeHeadlessInvoker().run_parallel([_headless_request()])[0]

    assert result.timed_out
    assert kill_group.call_args_list == [
        call(54321, signal.SIGTERM),
        call(54321, signal.SIGKILL),
    ]

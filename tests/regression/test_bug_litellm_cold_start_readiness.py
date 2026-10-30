"""A healthy cold LiteLLM start must survive the former ten-second deadline."""

from __future__ import annotations

import signal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from forge.backend import BackendStartError
from forge.backend.adapters import litellm

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("healthy_at", [12.0, None])
def test_start_waits_for_cold_readiness_but_kills_a_never_ready_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, healthy_at: float | None
) -> None:
    elapsed = 0.0
    probes: list[tuple[float, float | None]] = []
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        nonlocal elapsed
        sleeps.append(seconds)
        elapsed += seconds

    def get(url: str, *, timeout: float | None = None) -> httpx.Response:
        assert url == "http://localhost:4000/health/liveliness"
        probes.append((elapsed, timeout))
        if healthy_at is not None and elapsed >= healthy_at:
            return httpx.Response(200)
        raise httpx.ConnectError("cold import is not listening yet")

    clock = SimpleNamespace(monotonic=lambda: elapsed, time=lambda: elapsed, sleep=sleep)
    monkeypatch.setattr(litellm, "time", clock)
    client = MagicMock()
    client.__enter__.return_value = client
    client.get.side_effect = get
    client_factory = MagicMock(return_value=client)
    monkeypatch.setattr(litellm.httpx, "Client", client_factory)
    launch = MagicMock(return_value=SimpleNamespace(pid=12345))
    monkeypatch.setattr(litellm.subprocess, "Popen", launch)
    kill_group = MagicMock()
    monkeypatch.setattr(litellm.os, "killpg", kill_group)
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge-home"))
    config = tmp_path / "config.yaml"
    config.write_text("model_list: []\n")

    adapter = litellm.LiteLLMAdapter()
    if healthy_at is not None:
        result = adapter.start("litellm-4000", config, 4000)
        assert result.status == "healthy"
        assert result.pid == 12345
        assert elapsed == healthy_at
        kill_group.assert_not_called()
    else:
        with pytest.raises(BackendStartError, match="failed to start on port 4000"):
            adapter.start("litellm-4000", config, 4000)
        assert elapsed == 30.0
        kill_group.assert_called_once_with(12345, signal.SIGKILL)

    launch.assert_called_once()
    assert launch.call_args.kwargs["start_new_session"] is True
    client_factory.assert_called_once()
    assert probes
    assert all(timeout is not None and 0 < timeout <= min(2.0, 30.0 - started) for started, timeout in probes)
    assert all(0 < delay <= 0.5 for delay in sleeps)

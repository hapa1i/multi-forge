"""Tests for LiteLLM backend adapter.

Note: The adapter is now provider-agnostic. It doesn't load or validate
API keys itself - that's done by _ensure_dependency_backend() which checks
BackendDependency.required_env_vars before calling the adapter.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from forge.backend import BackendStartError
from forge.backend.adapters.litellm import LiteLLMAdapter
from forge.backend.registry import ManagedBackendProcess


class TestLiteLLMAdapterHealthCheck:
    """Tests for health_check method."""

    def test_returns_true_when_healthy(self) -> None:
        """Verify health_check returns True when backend responds 200."""
        adapter = LiteLLMAdapter()
        process = ManagedBackendProcess(
            process_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
        )

        with patch("forge.backend.adapters.litellm.httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response

            result = adapter.health_check(process)

        assert result is True

    def test_returns_false_when_unhealthy(self) -> None:
        """Verify health_check returns False when backend responds non-200."""
        adapter = LiteLLMAdapter()
        process = ManagedBackendProcess(
            process_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
        )

        with patch("forge.backend.adapters.litellm.httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response

            result = adapter.health_check(process)

        assert result is False

    def test_returns_false_on_connection_error(self) -> None:
        """Verify health_check returns False on connection error."""
        import httpx

        adapter = LiteLLMAdapter()
        process = ManagedBackendProcess(
            process_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
        )

        with patch("forge.backend.adapters.litellm.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = httpx.RequestError("Connection refused")

            result = adapter.health_check(process)

        assert result is False


class TestLiteLLMAdapterStop:
    """Tests for stop method."""

    def test_sends_sigterm_to_pid(self) -> None:
        """Verify stop sends SIGTERM to process."""
        adapter = LiteLLMAdapter()
        process = ManagedBackendProcess(
            process_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
            pid=12345,
        )

        with patch("os.kill") as mock_kill:
            adapter.stop(process)
            mock_kill.assert_called_once_with(12345, 15)  # 15 = SIGTERM

    def test_does_nothing_for_none_pid(self) -> None:
        """Verify stop does nothing when pid is None."""
        adapter = LiteLLMAdapter()
        process = ManagedBackendProcess(
            process_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
            pid=None,
        )

        with patch("os.kill") as mock_kill:
            adapter.stop(process)
            mock_kill.assert_not_called()

    def test_ignores_process_not_found(self) -> None:
        """Verify stop ignores ProcessLookupError."""
        adapter = LiteLLMAdapter()
        process = ManagedBackendProcess(
            process_id="litellm-4000",
            adapter_type="litellm",
            port=4000,
            pid=12345,
        )

        with patch("os.kill", side_effect=ProcessLookupError):
            # Should not raise
            adapter.stop(process)


class TestLiteLLMAdapterStart:
    """Tests for start method."""

    def test_start_spawns_litellm_process(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify start spawns litellm subprocess."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        config_path = tmp_path / "config.yaml"
        config_path.write_text("model_list: []")

        adapter = LiteLLMAdapter()

        with (
            patch("subprocess.Popen") as mock_popen,
            patch.object(adapter, "_wait_for_health", return_value=True),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc

            result = adapter.start("litellm-4000", config_path, 4000)

        assert result.process_id == "litellm-4000"
        assert result.port == 4000
        assert result.pid == 12345
        assert result.status == "healthy"

        # Verify command (litellm binary resolved from venv, not bare "litellm")
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert cmd[0].endswith("/litellm")
        assert "--config" in cmd
        assert str(config_path) in cmd
        assert "--port" in cmd
        assert "4000" in cmd

    def test_start_raises_when_health_check_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify start raises when backend fails health check."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        config_path = tmp_path / "config.yaml"
        config_path.write_text("model_list: []")

        adapter = LiteLLMAdapter()

        with (
            patch("subprocess.Popen") as mock_popen,
            patch.object(adapter, "_wait_for_health", return_value=False),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc

            with pytest.raises(BackendStartError) as exc_info:
                adapter.start("litellm-4000", config_path, 4000)

            assert "failed to start" in str(exc_info.value).lower()
            mock_proc.kill.assert_called_once()

    def test_start_creates_log_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify start creates log directory if needed."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path))  # Intentional: test asserts tmp_path/logs exists
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        config_path = tmp_path / "config.yaml"
        config_path.write_text("model_list: []")

        adapter = LiteLLMAdapter()

        with (
            patch("subprocess.Popen") as mock_popen,
            patch.object(adapter, "_wait_for_health", return_value=True),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc

            adapter.start("litellm-4000", config_path, 4000)

        # Log directory should be created
        logs_dir = tmp_path / "logs" / "backend"
        assert logs_dir.exists()

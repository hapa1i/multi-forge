"""LiteLLM backend adapter.

Manages LiteLLM proxy processes for multi-provider model access.
LiteLLM supports many providers (Gemini, OpenAI, Anthropic, etc.) -
the specific provider is determined by the config file and env vars.

Env var validation happens BEFORE this adapter is called (in _ensure_dependency_backend),
so this adapter just passes through whatever is in os.environ.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from forge.backend import BackendAdapter, BackendStartError
from forge.backend.registry import ManagedBackendProcess
from forge.core.paths import get_forge_home
from forge.core.state import now_iso


class LiteLLMAdapter(BackendAdapter):
    """Adapter for managing LiteLLM backend processes.

    This adapter is provider-agnostic - it starts LiteLLM with whatever
    config and environment variables are provided. The specific provider
    (Gemini, OpenAI, etc.) is determined by:
    1. The LiteLLM config file (model_list with provider prefixes)
    2. Environment variables (GEMINI_API_KEY, OPENAI_API_KEY, etc.)

    Env var validation is handled by the caller (_ensure_dependency_backend)
    which checks BackendDependency.required_env_vars before starting.
    """

    def _wait_for_health(self, port: int, timeout: float = 15.0) -> bool:
        """Wait for backend to become healthy.

        Uses /health/liveliness (not /health) because the full health endpoint
        runs model-level checks against remote providers, which can take 5-10s.
        The liveliness endpoint just verifies the server process is accepting
        requests (~5ms).

        Args:
            port: Port to check
            timeout: Timeout in seconds

        Returns:
            True if healthy within timeout, False otherwise
        """
        start_time = time.time()
        url = f"http://localhost:{port}/health/liveliness"

        while time.time() - start_time < timeout:
            try:
                with httpx.Client(timeout=httpx.Timeout(2.0)) as client:
                    response = client.get(url)
                    if response.status_code == 200:
                        return True
            except (httpx.RequestError, httpx.TimeoutException):
                pass
            time.sleep(0.5)

        return False

    def start(self, process_id: str, config_path: Path, port: int) -> ManagedBackendProcess:
        """Start LiteLLM backend.

        Args:
            process_id: Managed process ID (e.g., "litellm-4000")
            config_path: Path to LiteLLM config file
            port: Port number to bind

        Returns:
            ManagedBackendProcess with PID and status

        Raises:
            BackendStartError: If backend fails to start

        Note:
            Required env vars (GEMINI_API_KEY, OPENAI_API_KEY, etc.) should
            already be in os.environ - validation happens before this method
            is called. We pass through the full environment to the subprocess.
        """
        # Build command — resolve the litellm binary from the same venv as
        # sys.executable, rather than relying on a bare 'litellm' on PATH.
        # Console scripts (pip, litellm, etc.) are always siblings of python
        # in the venv's bin/ directory.
        litellm_bin = str(Path(sys.executable).parent / "litellm")
        cmd = [litellm_bin, "--config", str(config_path), "--port", str(port)]

        # Pass through current environment (includes API keys loaded by load_config)
        log_file = get_forge_home() / "logs" / "backend" / f"litellm-{port}.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        with log_file.open("a") as log:
            proc = subprocess.Popen(
                cmd,
                env=os.environ.copy(),
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # Detach from parent
            )

        # Wait for health (timeout 10s)
        if not self._wait_for_health(port, timeout=10):
            try:
                proc.kill()
            except OSError:
                pass  # Process already exited
            raise BackendStartError(f"LiteLLM failed to start on port {port}\nCheck logs: {log_file}")

        return ManagedBackendProcess(
            process_id=process_id,
            adapter_type="litellm",
            port=port,
            pid=proc.pid,
            status="healthy",
            created_at=now_iso(),
        )

    def stop(self, instance: ManagedBackendProcess) -> None:
        """Stop LiteLLM backend (best effort).

        Args:
            instance: Managed backend process to stop
        """
        if instance.pid is None:
            return

        try:
            os.kill(instance.pid, 15)  # SIGTERM
        except (ProcessLookupError, PermissionError):
            pass

    def health_check(self, instance: ManagedBackendProcess) -> bool:
        """Check if LiteLLM backend is healthy.

        Uses /health/liveliness for fast checks (~5ms) rather than the full
        /health endpoint which contacts all model providers (~5-10s).

        Args:
            instance: Managed backend process to check

        Returns:
            True if healthy, False otherwise
        """
        try:
            url = f"http://localhost:{instance.port}/health/liveliness"
            with httpx.Client(timeout=httpx.Timeout(2.0)) as client:
                response = client.get(url)
                return response.status_code == 200
        except (httpx.RequestError, httpx.TimeoutException):
            return False

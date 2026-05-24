"""Proxy lifecycle management for tests.

Provides context managers and utilities for programmatic proxy control:
- Ephemeral port allocation (OS-assigned random ports)
- Proxy lifecycle context manager with auto-cleanup
- Health checking and readiness detection

Usage:
    from tests.fixtures.proxy import proxy_context, allocate_ephemeral_port

    with proxy_context(template="litellm-gemini-test", forge_home=tmp_path) as proxy:
        response = httpx.get(f"{proxy.base_url}/")
        assert response.status_code == 200
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Generator


@dataclass
class ProxyInstance:
    """Running proxy instance information."""

    process: subprocess.Popen
    port: int
    base_url: str
    template: str
    forge_home: Path


def allocate_ephemeral_port() -> int:
    """Allocate a random ephemeral port from the OS.

    Uses the bind(0) technique: bind to port 0, let the OS assign
    an available port, then close the socket. The port remains
    available briefly for the proxy to claim.

    Returns:
        Available port number in the ephemeral range (typically 49152-65535).
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        return port


def wait_for_port(port: int, timeout: float = 10.0) -> bool:
    """Wait for a port to accept connections.

    Args:
        port: Port number to check.
        timeout: Maximum time to wait in seconds.

    Returns:
        True if port is accepting connections, False if timeout.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("localhost", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def kill_process(pid: int) -> None:
    """Kill a process gracefully, then forcefully if needed.

    Sends SIGTERM first, waits briefly, then SIGKILL if still running.

    Args:
        pid: Process ID to kill.
    """
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.5)
        # Check if still running
        try:
            os.kill(pid, 0)  # Signal 0 just checks if process exists
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # Already dead
    except ProcessLookupError:
        pass  # Process doesn't exist


@contextmanager
def proxy_context(
    *,
    template: str,
    forge_home: Path,
    cwd: Path | None = None,
    port: int | None = None,
    env: dict[str, str] | None = None,
    wait_timeout: float = 10.0,
) -> Generator[ProxyInstance, None, None]:
    """Context manager for proxy lifecycle with auto-cleanup.

    Starts a proxy subprocess, waits for it to be ready, yields control,
    then ensures cleanup on exit (even if tests fail).

    Args:
        template: Configuration template (e.g., "litellm-gemini-test").
        forge_home: Path to FORGE_HOME directory.
        cwd: Working directory for proxy process (defaults to forge_home).
        port: Port to use (None = allocate ephemeral port).
        env: Environment variables (defaults to os.environ with FORGE_HOME added).
        wait_timeout: Timeout in seconds for proxy readiness.

    Yields:
        ProxyInstance with process info and base URL.

    Raises:
        RuntimeError: If proxy fails to start or become ready.
    """
    actual_port = port if port is not None else allocate_ephemeral_port()
    actual_cwd = cwd if cwd is not None else forge_home

    # Build environment
    actual_env = env if env is not None else os.environ.copy()
    actual_env["FORGE_HOME"] = str(forge_home)

    # Start proxy subprocess
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "python",
            "-m",
            "forge.proxy.server",
            "--template",
            template,
            "--port",
            str(actual_port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=actual_env,
        cwd=str(actual_cwd),
    )

    try:
        # Wait for proxy to be ready
        if not wait_for_port(actual_port, timeout=wait_timeout):
            proc.kill()
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            raise RuntimeError(f"Proxy failed to start on port {actual_port}. Stderr: {stderr[:2000]}")

        yield ProxyInstance(
            process=proc,
            port=actual_port,
            base_url=f"http://localhost:{actual_port}",
            template=template,
            forge_home=forge_home,
        )

    finally:
        # Always cleanup
        kill_process(proc.pid)

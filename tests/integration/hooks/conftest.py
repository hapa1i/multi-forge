"""Fixtures for hook integration tests.

These fixtures provide:
- Session manifests with various configurations
- Local HTTP server for runtime truth testing
- Claude CLI hook configuration
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Generator

import pytest
from click.testing import CliRunner

from forge.session import SessionStore, create_session_state
from forge.session.models import PolicyIntent
from tests.fixtures.proxy import allocate_ephemeral_port, wait_for_port


@pytest.fixture
def cli_runner() -> CliRunner:
    """Create Click CLI runner for hook command invocation.

    Click 8.x provides separate result.stdout and result.stderr by default.
    Use result.stderr for block messages, result.output (stdout) for JSON responses.
    """
    return CliRunner()


@pytest.fixture
def project_with_session(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[Path, SessionStore], None, None]:
    """Create a git repo with Forge session manifest.

    Sets cwd to the repo, creates:
    - .forge/sessions/<name>/forge.session.json (via SessionStore)

    Yields:
        Tuple of (repo_path, SessionStore) for test manipulation.
    """
    monkeypatch.chdir(git_repo)

    # Create session state
    session_name = "test-session"
    manifest = create_session_state(
        session_name,
        proxy_template="test-family",
        proxy_base_url="http://localhost:8080",
    )

    # Write manifest
    store = SessionStore(str(git_repo), "test-session")
    store.write(manifest)

    monkeypatch.setenv("FORGE_SESSION", session_name)

    yield (git_repo, store)


@pytest.fixture
def project_with_policy(
    project_with_session: tuple[Path, SessionStore],
) -> tuple[Path, SessionStore]:
    """Project with TDD policy enabled.

    Extends project_with_session by setting:
    - intent.policy.enabled = True
    - intent.policy.bundles = ["tdd"]
    - intent.policy.fail_mode = "open"

    Returns:
        Same tuple as project_with_session.
    """
    repo_path, store = project_with_session

    # Read, modify, write manifest
    manifest = store.read()
    manifest.intent.policy = PolicyIntent(
        enabled=True,
        bundles=["tdd"],
        fail_mode="open",
    )
    store.write(manifest)

    return (repo_path, store)


class RuntimeTruthHandler(BaseHTTPRequestHandler):
    """HTTP handler that serves proxy runtime truth JSON."""

    context_window: int = 500_000  # Class variable, configurable

    def do_GET(self) -> None:
        """Serve GET / with runtime truth JSON."""
        if self.path == "/":
            response = {
                "is_proxy": True,
                "runtime": {
                    "active_context_window": self.context_window,
                    "active_tier": "opus",
                },
                "tiers": {
                    "haiku": {"context_window": 128000},
                    "sonnet": {"context_window": 200000},
                    "opus": {"context_window": self.context_window},
                },
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        """Suppress logging to keep test output clean."""
        pass


@pytest.fixture
def local_runtime_truth_server() -> Generator[str, None, None]:
    """HTTP server serving proxy GET / runtime truth.

    Starts a ThreadingHTTPServer on an ephemeral port serving:
    GET / -> {"runtime": {"active_context_window": 500000}}

    The large context window (500K) is designed to trigger pre-compact
    blocking (threshold is 300K).

    Yields:
        Base URL like "http://127.0.0.1:<port>"
    """
    port = allocate_ephemeral_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), RuntimeTruthHandler)

    # Start server in daemon thread
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Wait for server to be ready
    if not wait_for_port(port, timeout=5.0):
        server.shutdown()
        pytest.fail(f"Runtime truth server failed to start on port {port}")

    yield f"http://127.0.0.1:{port}"

    # Cleanup
    server.shutdown()


@pytest.fixture
def project_with_proxy_session(
    git_repo: Path,
    local_runtime_truth_server: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[Path, SessionStore], None, None]:
    """Project with session configured to use local runtime truth server.

    Creates manifest with:
    - intent.proxy.base_url pointing to local_runtime_truth_server

    Yields:
        Tuple of (repo_path, SessionStore).
    """
    monkeypatch.chdir(git_repo)

    # Create session state with proxy pointing to local server
    session_name = "test-proxy-session"
    manifest = create_session_state(
        session_name,
        proxy_template="test-family",
        proxy_base_url=local_runtime_truth_server,
    )

    # Write manifest
    store = SessionStore(str(git_repo), "test-proxy-session")
    store.write(manifest)

    monkeypatch.setenv("FORGE_SESSION", session_name)

    yield (git_repo, store)

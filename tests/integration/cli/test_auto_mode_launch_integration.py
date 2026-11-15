"""Docker integration tests for auto-mode classifier routing on Claude launches.

A real translated Forge proxy runs in the container with an unreachable upstream, so
no model request is made. The mock ``claude`` records its environment.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]

_PROXY_ID = "auto-mode-translated"
_PORT = 18231


@pytest.fixture
def translated_proxy(mock_claude_workspace: ContainerLike):
    result = mock_claude_workspace.exec(
        f"forge proxy create litellm-openai --name {_PROXY_ID} --port {_PORT} --base-url http://127.0.0.1:9/v1",
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    identity = mock_claude_workspace.exec(f"curl -s http://localhost:{_PORT}/")
    assert identity.returncode == 0, identity.stderr
    payload = json.loads(identity.stdout)
    assert payload["wire_shape"] == "openai_translated"
    try:
        yield payload["runtime"]["tier_mappings"]["sonnet"]
    finally:
        mock_claude_workspace.exec(f"forge proxy delete {_PROXY_ID} --yes >/dev/null 2>&1 || true")


def test_bare_translated_launch_uses_local_classifier_and_names_backend(
    mock_claude_workspace: ContainerLike, claude_capture_file: Callable[[str], str], translated_proxy: str
) -> None:
    result = mock_claude_workspace.exec(f"cd /workspace && forge claude start --proxy {_PROXY_ID}", timeout=60)

    assert result.returncode == 0, result.stdout + result.stderr
    env_capture = claude_capture_file("/tmp/claude_env_*.log")
    assert "CLAUDE_CODE_AUTO_MODE_SERVER=0" in env_capture.splitlines()
    assert (
        f"Auto mode: actions are judged by {translated_proxy} (requested as claude-sonnet-5, sonnet tier)"
        in result.stderr
    )
    assert "Auto mode" not in result.stdout


def test_managed_session_translated_launch_uses_local_classifier(
    mock_claude_workspace: ContainerLike, claude_capture_file: Callable[[str], str], translated_proxy: str
) -> None:
    result = mock_claude_workspace.exec(
        f"cd /workspace && forge session start auto-mode-session --proxy {_PROXY_ID}", timeout=60
    )

    assert result.returncode == 0, result.stdout + result.stderr
    env_capture = claude_capture_file("/tmp/claude_env_*.log")
    assert "CLAUDE_CODE_AUTO_MODE_SERVER=0" in env_capture.splitlines()
    assert f"Auto mode: actions are judged by {translated_proxy}" in result.stderr


@pytest.mark.usefixtures("translated_proxy")
def test_user_auto_mode_server_value_survives_translated_launch(
    mock_claude_workspace: ContainerLike, claude_capture_file: Callable[[str], str]
) -> None:
    result = mock_claude_workspace.exec(
        f"cd /workspace && CLAUDE_CODE_AUTO_MODE_SERVER=1 forge claude start --proxy {_PROXY_ID}", timeout=60
    )

    assert result.returncode == 0, result.stdout + result.stderr
    env_capture = claude_capture_file("/tmp/claude_env_*.log")
    assert "CLAUDE_CODE_AUTO_MODE_SERVER=1" in env_capture.splitlines()
    assert "Auto mode" not in result.stderr


def test_direct_launch_inside_translated_session_drops_forge_default(
    mock_claude_workspace: ContainerLike, claude_capture_file: Callable[[str], str]
) -> None:
    # Values a translated Forge session hands to commands run from its Bash tool.
    inherited = (
        "ANTHROPIC_BASE_URL=http://127.0.0.1:18299 FORGE_PROXY_WIRE_SHAPE=openai_translated "
        "CLAUDE_CODE_AUTO_MODE_SERVER=0 FORGE_AUTO_MODE_SERVER_MANAGED=1"
    )
    result = mock_claude_workspace.exec(f"cd /workspace && {inherited} forge claude start --no-proxy", timeout=60)

    assert result.returncode == 0, result.stdout + result.stderr
    env_capture = claude_capture_file("/tmp/claude_env_*.log")
    assert "CLAUDE_CODE_AUTO_MODE_SERVER=" not in env_capture
    assert "FORGE_AUTO_MODE_SERVER_MANAGED=" not in env_capture
    assert "ANTHROPIC_BASE_URL=" not in env_capture

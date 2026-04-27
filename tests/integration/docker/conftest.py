"""Fixtures for Docker-based integration tests.

Re-exports shared Docker fixtures for pytest discovery in this subtree,
plus additional fixtures for session lifecycle tests and hook tests.
"""

from __future__ import annotations

import json
import os
from typing import Generator

import pytest

from tests.fixtures.docker import (
    ContainerLike,
    clean_workspace,
    docker_available,
    forge_test_image,
    local_claude_available,
    synced_container,
)

__all__ = [
    "ContainerLike",
    "clean_workspace",
    "docker_available",
    "forge_test_image",
    "forge_workspace",
    "local_claude_available",
    "policy_workspace",
    "precompact_workspace",
    "run_claude_print",
    "setup_real_claude",
    "synced_container",
]


# ---------------------------------------------------------------------------
# Shared helpers for tests that use real Claude Code (not the mock binary).
# ---------------------------------------------------------------------------


def setup_real_claude(workspace: ContainerLike, *, session_name: str = "real-claude-test") -> None:
    """Restore real Claude binary and set up a session for testing.

    1. Restores real claude binary (forge_workspace replaces it with mock)
    2. Enables forge hooks (required for hooks to fire)
    3. Creates a named session with --no-launch

    SECURITY: API key is passed via environment, NOT in command strings.
    """
    result = workspace.exec("""
        if [ -f /usr/local/bin/claude-real ]; then
            mv /usr/local/bin/claude-real /usr/local/bin/claude
        fi
        """)
    if result.returncode != 0:
        pytest.fail(f"Failed to restore claude: {result.stderr}")

    result = workspace.exec("mkdir -p /workspace/.claude /workspace/.forge")
    if result.returncode != 0:
        pytest.fail(f"Failed to create .claude/.forge directories: {result.stderr}")

    result = workspace.exec("cd /workspace && forge hook enable")
    if result.returncode != 0:
        pytest.fail(f"Failed to enable hooks: {result.stderr}")

    result = workspace.exec(f"cd /workspace && forge session start --no-launch {session_name}")
    if result.returncode != 0:
        pytest.fail(f"Failed to create session: {result.stderr}")


def run_claude_print(
    workspace: ContainerLike,
    prompt: str,
    *,
    session_name: str = "real-claude-test",
    resume_id: str | None = None,
    fork_session: bool = False,
    timeout: int = 60,
) -> tuple[int, str, str]:
    """Run ``claude --print`` with the given prompt.

    Args:
        workspace: Container to execute in.
        prompt: Prompt to send to Claude.
        session_name: FORGE_SESSION env var value for hook dispatch.
        resume_id: If set, pass ``--resume <id>`` to Claude.
        fork_session: If True, pass ``--fork-session`` (use with resume_id).
        timeout: Timeout in seconds.

    Returns:
        Tuple of (exit_code, stdout, stderr).
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")

    workspace.exec(
        "printf '%s' > /tmp/.anthropic_key && chmod 600 /tmp/.anthropic_key",
        timeout=5,
    )
    write_result = workspace.exec(f"cat > /tmp/.anthropic_key << 'KEY_EOF'\n{api_key}\nKEY_EOF")
    if write_result.returncode != 0:
        pytest.fail("Failed to write API key")

    # Build claude command
    cmd_parts = ["claude", "--print"]
    if resume_id:
        cmd_parts += ["--resume", resume_id]
    if fork_session:
        cmd_parts.append("--fork-session")
    cmd_parts.append(f'"{prompt}"')
    claude_cmd = " ".join(cmd_parts)

    try:
        result = workspace.exec(
            f"""
            export ANTHROPIC_API_KEY=$(cat /tmp/.anthropic_key)
            export FORGE_SESSION={session_name}
            cd /workspace && timeout {timeout} {claude_cmd}
            """,
            timeout=timeout + 10,
        )
        return result.returncode, result.stdout, result.stderr
    finally:
        workspace.exec("rm -f /tmp/.anthropic_key")


@pytest.fixture
def forge_workspace(
    clean_workspace: ContainerLike,
) -> Generator[ContainerLike, None, None]:
    """Per-test workspace with forge in PATH, mock claude, and clean state.

    Creates:
    - Symlink /usr/local/bin/forge -> /forge/.venv/bin/forge
    - Mock claude binary that logs and exits 0
    - Clean ~/.forge/ and ~/.claude/ for test isolation

    This allows testing forge CLI commands that invoke Claude without
    actually launching Claude Code.
    """
    result = clean_workspace.exec("""
        # Clean global forge state (session index, active pointer)
        rm -rf ~/.forge ~/.claude

        # Symlink forge to PATH so it's available from any directory
        ln -sf /forge/.venv/bin/forge /usr/local/bin/forge 2>/dev/null || true

        # Create mock claude binary
        cat > /usr/local/bin/claude-mock << 'SCRIPT'
#!/bin/bash
# Mock claude binary for testing
# Returns a parseable version for installer/version checks,
# then logs normal invocations and exits 0.
if [ "${1:-}" = "--version" ]; then
    echo "99.99.99 (Claude Code)"
    exit 0
fi

echo "$(date -Iseconds) claude $*" >> /tmp/claude_invocations.log
exit 0
SCRIPT
        chmod +x /usr/local/bin/claude-mock

        # Backup real claude and replace with mock
        if [ -f /usr/local/bin/claude ]; then
            mv /usr/local/bin/claude /usr/local/bin/claude-real
        fi
        ln -sf /usr/local/bin/claude-mock /usr/local/bin/claude

        # Clear log file
        > /tmp/claude_invocations.log

        # Rule 1: create .forge/ and .claude/ anchors so session start works
        mkdir -p /workspace/.forge /workspace/.claude
        """)
    if result.returncode != 0:
        pytest.fail(f"Failed to set up forge_workspace: {result.stderr}")

    yield clean_workspace

    # Restore real claude after test
    clean_workspace.exec("""
        if [ -f /usr/local/bin/claude-real ]; then
            mv /usr/local/bin/claude-real /usr/local/bin/claude
        fi
        """)


@pytest.fixture
def policy_workspace(
    forge_workspace: ContainerLike,
) -> Generator[ContainerLike, None, None]:
    """Per-test workspace with TDD policy enabled.

    Builds on forge_workspace by:
    1. Creating a session with `forge session start`
    2. Updating manifest with TDD policy config

    The hook tests can then invoke `forge hook policy-check` and verify
    TDD enforcement behavior.
    """
    # Create session (forge_workspace already creates .forge/ + .claude/)
    result = forge_workspace.exec("cd /workspace && forge session start policy-test")
    if result.returncode != 0:
        pytest.fail(f"Session start failed: {result.stderr}")

    # Read manifest and add policy config (per-session directory layout)
    manifest_path = "/workspace/.forge/sessions/policy-test/forge.session.json"
    manifest_result = forge_workspace.exec(f"cat {manifest_path}")
    if manifest_result.returncode != 0:
        pytest.fail(f"Failed to read manifest: {manifest_result.stderr}")

    manifest = json.loads(manifest_result.stdout)
    manifest["intent"]["policy"] = {
        "enabled": True,
        "bundles": ["tdd"],
        "fail_mode": "open",
    }

    # Write updated manifest
    manifest_json = json.dumps(manifest, indent=2)
    write_result = forge_workspace.exec(f"cat > {manifest_path} << 'MANIFEST_EOF'\n{manifest_json}\nMANIFEST_EOF")
    if write_result.returncode != 0:
        pytest.fail(f"Failed to write manifest: {write_result.stderr}")

    yield forge_workspace


@pytest.fixture
def precompact_workspace(
    forge_workspace: ContainerLike,
) -> Generator[ContainerLike, None, None]:
    """Per-test workspace with a session for pre-compact transcript capture testing.

    Builds on forge_workspace by creating a session. No mock server needed —
    pre-compact captures transcripts, it doesn't query the proxy.
    """
    # Create session (forge_workspace already creates .forge/ + .claude/)
    result = forge_workspace.exec("cd /workspace && forge session start precompact-test")
    if result.returncode != 0:
        pytest.fail(f"Session start failed: {result.stderr}")

    yield forge_workspace

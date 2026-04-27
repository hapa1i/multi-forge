"""Sandbox runtime integration tests.

Tests mount semantics, environment variable propagation, and shell access
for sidecar sessions. These tests run on HOST and spawn REAL Docker
containers (no DinD).

Marker: @pytest.mark.docker_host

Note: These tests do NOT test CLI workflow (Click parsing, manifest creation).
That belongs in behavioral tests. These test container runtime behavior.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.sidecar.docker import is_docker_available

pytestmark = [pytest.mark.integration, pytest.mark.docker_host]


@pytest.fixture(scope="module", autouse=True)
def _require_docker() -> None:
    """Fail loudly if Docker is unavailable (never skip tests policy)."""
    if not is_docker_available():
        pytest.fail("Docker not available. Start Docker (or install it) and re-run integration tests.")


class TestMountSemantics:
    """Tests for workspace mount behavior."""

    def test_project_dir_mounted_at_workspace(
        self,
        temp_project: Path,
        container_name: str,
        container_cleanup: str,
    ) -> None:
        """Verify host project directory is readable at /workspace in container."""
        # Create a test file on host
        test_file = temp_project / "mount_test.txt"
        test_content = "mounted successfully from host"
        test_file.write_text(test_content)

        # Start container with mount
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container_name,
                "-v",
                f"{temp_project}:/workspace",
                "-w",
                "/workspace",
                "alpine",
                "sleep",
                "30",
            ],
            check=True,
            capture_output=True,
        )

        # Read file from inside container
        result = subprocess.run(
            ["docker", "exec", container_name, "cat", "/workspace/mount_test.txt"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert test_content in result.stdout

    def test_changes_in_container_visible_on_host(
        self,
        temp_project: Path,
        container_name: str,
        container_cleanup: str,
    ) -> None:
        """Verify changes made in container appear on host (bi-directional mount)."""
        # Start container with mount
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container_name,
                "-v",
                f"{temp_project}:/workspace",
                "-w",
                "/workspace",
                "alpine",
                "sleep",
                "30",
            ],
            check=True,
            capture_output=True,
        )

        # Create file from inside container
        container_content = "created inside container"
        subprocess.run(
            [
                "docker",
                "exec",
                container_name,
                "sh",
                "-c",
                f'echo "{container_content}" > /workspace/from_container.txt',
            ],
            check=True,
            capture_output=True,
        )

        # Verify file exists on host
        host_file = temp_project / "from_container.txt"
        assert host_file.exists(), "File created in container should appear on host"
        assert container_content in host_file.read_text()


class TestEnvVarPropagation:
    """Tests for environment variable propagation to container."""

    def test_forge_env_vars_set(
        self,
        container_name: str,
        container_cleanup: str,
    ) -> None:
        """Verify explicitly passed FORGE_* env vars are visible in container.

        Note: We test only env vars we explicitly pass (-e flags).
        ANTHROPIC_BASE_URL is set by the real entrypoint, not tested here
        since we bypass entrypoint with --entrypoint.
        """
        template = "litellm-openai"
        context_limit = "200000"
        session_name = "test-session"

        # Run container with env vars, override entrypoint to get shell
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "/bin/sh",
                "--name",
                container_name,
                "-e",
                f"FORGE_TEMPLATE={template}",
                "-e",
                f"CLAUDE_CODE_AUTO_COMPACT_WINDOW={context_limit}",
                "-e",
                f"FORGE_SESSION={session_name}",
                "alpine",
                "-c",
                "env",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert f"FORGE_TEMPLATE={template}" in result.stdout
        assert f"CLAUDE_CODE_AUTO_COMPACT_WINDOW={context_limit}" in result.stdout
        assert f"FORGE_SESSION={session_name}" in result.stdout


class TestShellAccess:
    """Tests for exec/shell access into running containers."""

    def test_exec_into_running_container(
        self,
        container_name: str,
        container_cleanup: str,
    ) -> None:
        """Verify can exec command into running container."""
        # Start a container
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container_name,
                "alpine",
                "sleep",
                "30",
            ],
            check=True,
            capture_output=True,
        )

        # Exec a command
        result = subprocess.run(
            ["docker", "exec", container_name, "echo", "shell-access-works"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "shell-access-works" in result.stdout

    def test_exec_fails_for_stopped_container(
        self,
        container_name: str,
        container_cleanup: str,
    ) -> None:
        """Verify exec fails gracefully when container is not running."""
        # Create container that exits immediately (no --rm so it stays as stopped)
        subprocess.run(
            [
                "docker",
                "run",
                "--name",
                container_name,
                "alpine",
                "true",  # Exits immediately
            ],
            check=True,
            capture_output=True,
        )

        # Wait for container to exit
        subprocess.run(["docker", "wait", container_name], capture_output=True)

        # Exec should fail
        result = subprocess.run(
            ["docker", "exec", container_name, "echo", "test"],
            capture_output=True,
        )

        assert result.returncode != 0

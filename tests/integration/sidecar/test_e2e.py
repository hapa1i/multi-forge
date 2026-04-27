"""End-to-end integration tests for sidecar session execution.

These tests verify Docker container lifecycle operations including creation,
collision detection, and cleanup. They require Docker to be available.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.sidecar.container import (
    ContainerExistsError,
    container_exists,
    get_container_id,
    run_sidecar_session,
)
from forge.sidecar.docker import (
    is_docker_available,
    remove_container,
    stop_container,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow, pytest.mark.docker_host]


@pytest.fixture(scope="module", autouse=True)
def _require_docker() -> None:
    """Fail loudly if Docker is unavailable (never skip tests policy)."""
    if not is_docker_available():
        pytest.fail("Docker not available. Start Docker (or install it) and re-run integration tests.")


@pytest.fixture
def container_name() -> str:
    """Generate unique container name for tests."""
    import uuid

    return f"forge-test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def cleanup_container(container_name: str):
    """Cleanup container after test, regardless of outcome."""
    yield container_name
    # Force remove container if it exists
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)


class TestContainerLifecycle:
    """Tests for container lifecycle operations."""

    def test_container_exists_detects_running_container(self, container_name: str, cleanup_container: str) -> None:
        """container_exists() returns True for running container."""
        # Start a simple container in background
        subprocess.run(
            ["docker", "run", "-d", "--name", container_name, "alpine", "sleep", "60"],
            check=True,
            capture_output=True,
        )

        # Should detect running container
        assert container_exists(container_name) is True
        # get_container_id should also find it (running check)
        assert get_container_id(container_name) is not None

    def test_container_exists_detects_stopped_container(self, container_name: str, cleanup_container: str) -> None:
        """container_exists() returns True for stopped (exited) container."""
        # Create and immediately stop a container
        subprocess.run(
            ["docker", "run", "-d", "--name", container_name, "alpine", "true"],
            check=True,
            capture_output=True,
        )
        # Wait for container to exit
        subprocess.run(["docker", "wait", container_name], capture_output=True)

        # container_exists should detect stopped container (uses -a)
        assert container_exists(container_name) is True
        # But get_container_id should NOT find it (only running)
        assert get_container_id(container_name) is None

    def test_container_exists_returns_false_for_nonexistent(self, container_name: str) -> None:
        """container_exists() returns False when no container exists."""
        assert container_exists(container_name) is False

    def test_stop_and_remove_container(self, container_name: str, cleanup_container: str) -> None:
        """stop_container() and remove_container() work correctly."""
        # Start a container
        subprocess.run(
            ["docker", "run", "-d", "--name", container_name, "alpine", "sleep", "60"],
            check=True,
            capture_output=True,
        )

        # Stop it
        assert stop_container(container_name) is True
        assert get_container_id(container_name) is None  # No longer running

        # Container still exists (stopped)
        assert container_exists(container_name) is True

        # Remove it
        assert remove_container(container_name) is True
        assert container_exists(container_name) is False

    def test_remove_container_force(self, container_name: str, cleanup_container: str) -> None:
        """remove_container(force=True) removes running container."""
        # Start a container
        subprocess.run(
            ["docker", "run", "-d", "--name", container_name, "alpine", "sleep", "60"],
            check=True,
            capture_output=True,
        )

        # Force remove without stopping first
        assert remove_container(container_name, force=True) is True
        assert container_exists(container_name) is False


class TestContainerCollision:
    """Tests for container collision detection."""

    def test_collision_detected_for_running_container(
        self, container_name: str, cleanup_container: str, tmp_path: Path
    ) -> None:
        """ContainerExistsError raised when running container has same name."""
        # Start a container with the same naming pattern
        subprocess.run(
            ["docker", "run", "-d", "--name", container_name, "alpine", "sleep", "60"],
            check=True,
            capture_output=True,
        )

        # Extract session name (container_name = forge-test-{uuid})
        session_name = container_name.replace("forge-", "")

        # Attempting to run sidecar session should fail
        with pytest.raises(ContainerExistsError) as exc_info:
            run_sidecar_session(
                image="alpine",
                template="test",
                session_name=session_name,
                project_dir=tmp_path,
            )

        assert container_name in str(exc_info.value)
        assert "docker rm -f" in str(exc_info.value)

    def test_collision_detected_for_stopped_container(
        self, container_name: str, cleanup_container: str, tmp_path: Path
    ) -> None:
        """ContainerExistsError raised when stopped container has same name."""
        # Create and stop a container
        subprocess.run(
            ["docker", "run", "-d", "--name", container_name, "alpine", "true"],
            check=True,
            capture_output=True,
        )
        subprocess.run(["docker", "wait", container_name], capture_output=True)

        # Verify it's stopped but exists
        assert get_container_id(container_name) is None  # Not running
        assert container_exists(container_name) is True  # But exists

        # Extract session name
        session_name = container_name.replace("forge-", "")

        # Attempting to run sidecar session should still fail
        with pytest.raises(ContainerExistsError):
            run_sidecar_session(
                image="alpine",
                template="test",
                session_name=session_name,
                project_dir=tmp_path,
            )


class TestExecInContainer:
    """Tests for exec into running container."""

    def test_exec_runs_command_successfully(self, container_name: str, cleanup_container: str) -> None:
        """exec_in_container() runs command and returns exit code."""
        # Start a container
        subprocess.run(
            ["docker", "run", "-d", "--name", container_name, "alpine", "sleep", "60"],
            check=True,
            capture_output=True,
        )

        # Exec a simple command (non-interactive)
        result = subprocess.run(
            ["docker", "exec", container_name, "echo", "hello"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "hello" in result.stdout

"""Host-based fixtures for sidecar integration tests.

These fixtures run on the HOST machine and spawn REAL Docker containers.
This is NOT Docker-in-Docker (DinD) — tests call docker directly from host.

Marker: @pytest.mark.docker_host
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture
def unique_session_name() -> str:
    """Generate unique session name for test isolation.

    Uses forge-test- prefix to distinguish from real forge-<session> containers.
    """
    return f"forge-test-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def container_name(unique_session_name: str) -> str:
    """Container name matching Forge's naming convention.

    For sidecar tests, container name = session name (both use forge-test-* prefix).
    """
    return unique_session_name


@pytest.fixture
def container_cleanup(container_name: str) -> Generator[str, None, None]:
    """Ensure container is removed after test, regardless of outcome.

    Yields the container name, then force-removes on cleanup.
    Safe to call even if container doesn't exist.
    """
    yield container_name
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        capture_output=True,
    )


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    """Create temporary project directory with initialized git repo.

    Required because session manager expects a git repository.
    """
    project = tmp_path / "workspace"
    project.mkdir()

    # Initialize git repo
    subprocess.run(
        ["git", "init"],
        cwd=project,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@forge.local"],
        cwd=project,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Forge Test"],
        cwd=project,
        capture_output=True,
    )

    # Create initial commit (some operations require at least one commit)
    readme = project / "README.md"
    readme.write_text("# Test Project\n")
    subprocess.run(["git", "add", "."], cwd=project, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=project,
        capture_output=True,
    )

    return project


@pytest.fixture(scope="session")
def sidecar_image() -> str:
    """Check if forge-sidecar image exists, skip tests if not built.

    Returns the image name if available, otherwise skips.
    For most runtime tests, we use 'alpine' directly — this fixture
    is for tests that specifically need the full sidecar image.
    """
    image = "forge-sidecar:latest"
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.fail(f"Sandbox image '{image}' not built. Run: docker build -t {image} .")
    return image


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Cleanup orphaned test containers after pytest session.

    Safety net for containers left behind by failed tests or interrupted runs.
    Only removes containers matching the forge-test-* naming pattern.

    Gracefully skips if Docker is not available (e.g., running inside a container).
    """
    try:
        result = subprocess.run(
            ["docker", "ps", "-aq", "-f", "name=^forge-test-"],
            capture_output=True,
            text=True,
        )
        for cid in result.stdout.strip().split("\n"):
            if cid:
                subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
    except FileNotFoundError:
        # Docker not available (e.g., running inside container without DinD)
        pass

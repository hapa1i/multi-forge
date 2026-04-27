"""Docker utility functions for sidecar execution.

Low-level Docker operations used by the container lifecycle module.
"""

from __future__ import annotations

import re
import subprocess


def _docker_name_filter(container_name: str) -> str:
    """Build an exact-match docker ps name filter, escaping regex metacharacters."""
    return f"name=^{re.escape(container_name)}$"


def is_container_running(container_name: str) -> bool:
    """Check if a Docker container is running by name.

    Uses docker ps filtering with exact name match to avoid partial matches.

    Args:
        container_name: The container name to check.

    Returns:
        True if container exists and is running, False otherwise.
    """
    result = subprocess.run(
        ["docker", "ps", "-q", "-f", _docker_name_filter(container_name)],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def is_docker_available() -> bool:
    """Check if Docker is available and running.

    Returns:
        True if docker daemon is accessible, False otherwise.
    """
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def stop_container(container_name: str) -> bool:
    """Stop a running container by name.

    Args:
        container_name: The container name to stop.

    Returns:
        True if container was stopped, False if container was not running.
    """
    result = subprocess.run(
        ["docker", "stop", container_name],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def remove_container(container_name: str, force: bool = False) -> bool:
    """Remove a container by name.

    Args:
        container_name: The container name to remove.
        force: If True, force remove even if running.

    Returns:
        True if container was removed, False otherwise.
    """
    cmd = ["docker", "rm"]
    if force:
        cmd.append("-f")
    cmd.append(container_name)

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0

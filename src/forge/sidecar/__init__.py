"""Sidecar execution module for Claude Forge.

Bundles proxy + Claude Code in a Docker container with lifecycle coupling,
port isolation, and version consistency. Not a security sandbox — Claude
Code's native sandbox (Seatbelt/bubblewrap) handles that.
"""

from forge.sidecar.container import (
    ContainerExistsError,
    container_exists,
    exec_in_container,
    get_container_id,
    parse_mounts,
    run_sidecar_session,
)
from forge.sidecar.docker import is_container_running, is_docker_available
from forge.sidecar.secrets import get_secrets_for_template

__all__ = [
    "ContainerExistsError",
    "container_exists",
    "exec_in_container",
    "get_container_id",
    "get_secrets_for_template",
    "is_container_running",
    "is_docker_available",
    "parse_mounts",
    "run_sidecar_session",
]

"""Shared test fixtures for Multi-Forge.

This module provides reusable fixtures for:
- Repository setup (git repos, worktrees)
- Home directory isolation (forge home, claude home)
- Proxy lifecycle management (context managers, ephemeral ports)
- Docker container lifecycle (for in-container testing)

Import fixtures explicitly in conftest.py files or test modules.
"""

from tests.fixtures.docker import (
    ContainerLike,
    DockerContainer,
    LocalExecution,
    base_git_repo,
    clean_workspace,
    docker_available,
    forge_test_image,
    local_claude_available,
    pytest_runtest_makereport,
    synced_container,
)
from tests.fixtures.proxy import (
    ProxyInstance,
    allocate_ephemeral_port,
    proxy_context,
)
from tests.fixtures.repos import (
    claude_home,
    forge_home,
    git_repo,
    git_repo_with_claude,
)
from tests.fixtures.session_state import (
    delete_published_session,
    publish_session,
    publish_session_from_fields,
    remove_index_row_only,
    seed_row_only_session,
)

__all__ = [
    # Repos
    "git_repo",
    "git_repo_with_claude",
    "forge_home",
    "claude_home",
    # Proxy
    "ProxyInstance",
    "allocate_ephemeral_port",
    "proxy_context",
    # Docker
    "ContainerLike",
    "DockerContainer",
    "LocalExecution",
    "docker_available",
    "local_claude_available",
    "forge_test_image",
    "synced_container",
    "base_git_repo",
    "clean_workspace",
    "pytest_runtest_makereport",
    # Durable session state
    "publish_session",
    "publish_session_from_fields",
    "delete_published_session",
    "seed_row_only_session",
    "remove_index_row_only",
]

"""Root pytest configuration.

Loads environment variables from .env file for all tests.
Provides shared fixtures for all test modules.
"""

# IMPORTANT: Load .env FIRST, before any other imports
# Some modules (e.g., tests.fixtures.docker) read env vars at import time
from pathlib import Path

from dotenv import load_dotenv

# Repo root for loading .env file (explicit path, not cwd-relative)
_repo_root = Path(__file__).parent.parent

# Load environment variables from .env (secrets only: API keys, workspace ID)
# Shell environment takes precedence (override=False)
load_dotenv(_repo_root / ".env", override=False)

# ruff: noqa: E402 — Imports below MUST come after load_dotenv() because
# test fixtures may read env vars set by .env

import pytest

# Pytest hook for Docker log capture on failure (must be in conftest.py scope)
# Docker fixtures for in-container testing
from tests.fixtures.docker import pytest_runtest_makereport  # noqa: F401
from tests.fixtures.docker import (
    base_git_repo,
    clean_workspace,
    docker_available,
    forge_test_image,
    local_claude_available,
    synced_container,
)

# Import shared fixtures to make them globally available
# These are re-exported so pytest can discover them by name
from tests.fixtures.repos import (
    claude_home,
    forge_home,
    git_repo,
    git_repo_with_claude,
)

# Fixtures listed here for pytest discovery (hooks are discovered via module scope)
__all__ = [
    # Repos
    "git_repo",
    "git_repo_with_claude",
    "forge_home",
    "claude_home",
    # Docker
    "docker_available",
    "local_claude_available",
    "forge_test_image",
    "synced_container",
    "base_git_repo",
    "clean_workspace",
]


@pytest.fixture(autouse=True)
def isolate_forge_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Force tests to use an isolated FORGE_HOME and clear session/root env vars.

    This prevents user-local state under ~/.forge (including any accidental use of a
    literal "~" directory) from affecting tests. Also clears all Forge env vars that
    influence session/path resolution, so tests pass when run from inside a
    Forge-managed Claude Code session (where FORGE_SESSION, FORGE_FORGE_ROOT, etc.
    are injected).

    Note: individual tests may override FORGE_HOME explicitly when needed.
    """
    isolated_home = tmp_path / "forge_home"
    isolated_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FORGE_HOME", str(isolated_home))
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    monkeypatch.delenv("FORGE_FORK_NAME", raising=False)
    monkeypatch.delenv("FORGE_PARENT_SESSION", raising=False)
    monkeypatch.delenv("FORGE_DEPTH", raising=False)
    monkeypatch.delenv("FORGE_FORGE_ROOT", raising=False)


@pytest.fixture(autouse=True)
def isolate_claude_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Force tests to use an isolated CLAUDE_HOME.

    This prevents user-local state under ~/.claude from being touched by tests.
    Critical for isolation: "No way this is touching anything on my laptop."

    Without this fixture, tests that call installer functions or CLI commands
    that use `get_settings_path(USER)` would write to the real ~/.claude/.

    Note: individual tests may override CLAUDE_HOME explicitly when needed.
    """
    isolated_home = tmp_path / "claude_home"
    isolated_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLAUDE_HOME", str(isolated_home))

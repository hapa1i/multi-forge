"""Shared repository and home directory fixtures.

These fixtures provide isolated environments for tests:
- Git repositories with proper configuration
- Forge home directories (~/.forge)
- Claude home directories (~/.claude)

Usage:
    from tests.fixtures.repos import git_repo, forge_home

    def test_something(git_repo: Path, forge_home: Path):
        # git_repo is a fully initialized git repo
        # forge_home is an isolated ~/.forge directory
"""

from __future__ import annotations

import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture
def git_repo(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary git repository with initial commit.

    The repo is created with:
    - Explicit 'main' branch (consistent across git versions)
    - User config for commits
    - Initial commit with README.md

    Cleanup automatically removes any worktrees created during tests.

    Yields:
        Path to the repository root.
    """
    repo = tmp_path / "test-repo"
    repo.mkdir()

    # Initialize with explicit branch name
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )

    # Configure user for commits
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )

    # Create initial commit
    readme = repo / "README.md"
    readme.write_text("# Test Repository\n")
    subprocess.run(
        ["git", "add", "."],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )

    yield repo

    # Cleanup: remove any worktrees created during test
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        worktrees = []
        for line in result.stdout.strip().split("\n"):
            if line.startswith("worktree "):
                worktrees.append(line.split(" ", 1)[1])
        # Remove all worktrees except the main one
        for wt_path in worktrees:
            if wt_path != str(repo):
                subprocess.run(
                    ["git", "worktree", "remove", "--force", wt_path],
                    cwd=str(repo),
                    capture_output=True,
                )


@pytest.fixture
def git_repo_with_claude(git_repo: Path) -> Path:
    """Git repository with .claude/ directory configured.

    Builds on git_repo fixture, adding:
    - .claude/ directory
    - Empty settings.local.json

    Args:
        git_repo: Base git repository fixture.

    Returns:
        Path to the repository root (same as git_repo).
    """
    claude_dir = git_repo / ".claude"
    claude_dir.mkdir()

    # Create empty settings file
    settings = claude_dir / "settings.local.json"
    settings.write_text("{}\n")

    return git_repo


@pytest.fixture
def forge_home(tmp_path: Path) -> Path:
    """Create an isolated ~/.forge directory.

    Creates the directory structure expected by Forge:
    - proxies/ - for proxy configurations
    - active-session (optional, not created)

    Returns:
        Path to the forge home directory.
    """
    home = tmp_path / "forge_home"
    home.mkdir()
    (home / "proxies").mkdir()
    return home


@pytest.fixture
def claude_home(tmp_path: Path) -> Path:
    """Create an isolated ~/.claude directory.

    Creates the directory structure expected by Claude Code:
    - projects/ - for project state
    - settings.local.json (optional, not created)

    Returns:
        Path to the claude home directory.
    """
    home = tmp_path / "claude_home"
    home.mkdir()
    (home / "projects").mkdir()
    return home

"""Fixtures for session tests.

Provides:
- worktree_workspace: Container with git repo for worktree tests
- session_workspace: Container with HOME/.forge/.claude configured

Note: Docker fixtures (clean_workspace, synced_container) are available from
tests/fixtures/docker.py via root conftest.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.fixtures.docker import ContainerLike


@dataclass
class WorktreeExecResult:
    """Structured result from worktree operation in container."""

    returncode: int
    stdout: str
    stderr: str
    data: dict | None = None  # Parsed JSON if available

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class WorktreeWorkspace:
    """Wrapper around container for worktree testing.

    Provides helper methods for running worktree operations and parsing
    structured output.
    """

    def __init__(self, container: "ContainerLike") -> None:
        self.container = container
        self.workspace = "/workspace"

    def exec(self, command: str, timeout: int = 60) -> WorktreeExecResult:
        """Execute command in container, return structured result."""
        result = self.container.exec(command, timeout=timeout)
        data = None
        # Try to parse JSON from stdout
        if result.returncode == 0 and result.stdout.strip():
            try:
                data = json.loads(result.stdout.strip().split("\n")[-1])
            except json.JSONDecodeError:
                pass
        return WorktreeExecResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            data=data,
        )

    def run_python(self, code: str, timeout: int = 60, home: str | None = None) -> WorktreeExecResult:
        """Run Python code inside container.

        Args:
            code: Python code to execute. Will be run with `uv run python -c`.
            timeout: Execution timeout in seconds.
            home: Optional HOME directory override (e.g., "/home/test").

        Returns:
            WorktreeExecResult with stdout/stderr and parsed JSON if present.

        Note:
            Runs from /forge (where pyproject.toml exists) so that uv can find
            the forge package. The code can reference /workspace paths explicitly.
        """
        # Escape quotes for shell
        escaped_code = code.replace('"', '\\"')
        home_prefix = f"HOME={home} " if home else ""
        # Run from /forge where uv sync was done, so forge package is available
        command = f'cd /forge && {home_prefix}uv run python -c "{escaped_code}"'
        return self.exec(command, timeout=timeout)

    def file_exists(self, path: str) -> bool:
        """Check if file/directory exists in container."""
        result = self.container.exec(f"test -e {path} && echo yes || echo no")
        return "yes" in result.stdout

    def read_file(self, path: str) -> str:
        """Read file contents from container."""
        result = self.container.exec(f"cat {path}")
        return result.stdout

    def git(self, *args: str, cwd: str | None = None) -> WorktreeExecResult:
        """Run git command in container.

        Args:
            *args: Git command arguments (e.g., "branch", "-a")
            cwd: Working directory (defaults to /workspace)

        Returns:
            WorktreeExecResult with command output.
        """
        cwd = cwd or self.workspace
        cmd = f"cd {cwd} && git " + " ".join(args)
        return self.exec(cmd)


@pytest.fixture
def worktree_workspace(clean_workspace: "ContainerLike") -> WorktreeWorkspace:
    """Container workspace configured for worktree tests.

    Uses the base_git_repo (git repo at /workspace) and provides
    helper methods for worktree operations.

    The workspace is reset between tests via git clean.
    """
    return WorktreeWorkspace(clean_workspace)


@pytest.fixture
def session_workspace(clean_workspace: "ContainerLike") -> "ContainerLike":
    """Workspace configured for session manager tests.

    Sets up:
    - /home/test as HOME (isolated from container's real home)
    - /workspace as project root (already git-initialized)
    - .forge/ and .claude/ directories

    Also cleans any session state from previous tests:
    - Removes /home/test/.forge/* (session index, active pointer)
    - Removes /home/test/.claude/*
    """
    # Clean up any session state from previous tests
    clean_workspace.exec("""
        rm -rf /home/test/.forge/* /home/test/.claude/* 2>/dev/null || true
        mkdir -p /home/test/.forge /home/test/.claude
        mkdir -p /workspace/.forge/sessions
    """)
    return clean_workspace


@pytest.fixture
def manager_workspace(session_workspace: "ContainerLike") -> WorktreeWorkspace:
    """WorktreeWorkspace configured for session manager tests.

    Combines session_workspace setup (HOME directories) with
    WorktreeWorkspace helper methods.

    Use with `run_python(..., home="/home/test")` to ensure
    IndexStore uses isolated paths.
    """
    return WorktreeWorkspace(session_workspace)

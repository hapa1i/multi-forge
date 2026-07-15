"""Integration coverage for the WorktreeCreate hook."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.hooks._group import hooks

pytestmark = pytest.mark.integration


def test_branch_conflict_fallback_creates_detached_worktree(git_repo: Path) -> None:
    """A failed named-branch attempt must not let Git create a path-named branch."""
    subprocess.run(
        ["git", "branch", "forge/target-refused"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    result = CliRunner().invoke(
        hooks,
        ["worktree-create"],
        input=json.dumps({"cwd": str(git_repo), "name": "target-refused"}),
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.stderr
    worktree_path = Path(result.stdout.strip())
    symbolic_ref = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )
    assert symbolic_ref.returncode == 1

    branches = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert worktree_path.name not in branches

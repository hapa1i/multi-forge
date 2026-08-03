"""Tests for shared Git repository-path discovery."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.session.exceptions import GitNotFoundError
from forge.session.git import find_git_binary, get_main_repo_root, get_repo_root


def test_find_git_binary_finds_git_on_path() -> None:
    git = find_git_binary()

    assert git.endswith("git")
    assert Path(git).exists()


def test_find_git_binary_fails_when_git_is_missing() -> None:
    with patch("forge.session.git.shutil.which", return_value=None):
        with pytest.raises(GitNotFoundError, match="git binary not found"):
            find_git_binary()


def test_logical_root_is_stable_across_linked_worktrees(git_repo: Path, tmp_path: Path) -> None:
    linked = tmp_path / "linked"
    _git(git_repo, "worktree", "add", "-q", "-b", "feature", str(linked))

    assert get_repo_root(linked) == linked.resolve()
    assert get_main_repo_root(git_repo) == git_repo.resolve()
    assert get_main_repo_root(linked) == git_repo.resolve()


def test_bare_family_logical_root_remains_the_linked_checkout(git_repo: Path, tmp_path: Path) -> None:
    bare = tmp_path / "family.git"
    linked = tmp_path / "bare-linked"
    subprocess.run(["git", "clone", "-q", "--bare", str(git_repo), str(bare)], check=True)
    _git(bare, "worktree", "add", "-q", str(linked), "main")

    assert get_main_repo_root(linked) == linked.resolve()


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

"""Tests for Git-derived workspace discovery."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.session.exceptions import GitNotFoundError, GitWorktreeError
from forge.session.workspace import (
    Workspace,
    WorkspaceWorktree,
    list_git_worktrees,
    parse_worktree_porcelain,
    resolve_workspace,
)
from forge.session.worktree.create import get_main_repo_root


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a non-bare repository with one commit."""

    repo = tmp_path / "main"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("workspace\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "initial")
    return repo


def test_resolves_identity_from_primary_and_linked_worktree(git_repo: Path, tmp_path: Path) -> None:
    linked = tmp_path / "linked"
    _git(git_repo, "worktree", "add", "-q", "-b", "feature", str(linked))

    from_primary = resolve_workspace(git_repo)
    from_linked = resolve_workspace(linked)

    assert from_primary.common_dir == from_linked.common_dir == (git_repo / ".git").resolve()
    assert from_primary.primary_root == from_linked.primary_root == git_repo.resolve()
    assert from_primary.primary_root == get_main_repo_root(git_repo)
    assert from_linked.primary_root == get_main_repo_root(linked)
    assert [row.branch for row in from_primary.worktrees] == ["main", "feature"]
    assert [row.is_primary for row in from_primary.worktrees] == [True, False]
    assert all(row.head for row in from_primary.worktrees)


def test_newline_in_worktree_path_round_trips(git_repo: Path, tmp_path: Path) -> None:
    linked = tmp_path / "line\nbreak"
    _git(git_repo, "worktree", "add", "-q", "-b", "newline-path", str(linked))

    workspace = resolve_workspace(git_repo)

    row = next(row for row in workspace.worktrees if row.branch == "newline-path")
    assert row.checkout_root == linked.resolve()
    assert row.path_exists is True


def test_locked_and_prunable_paths_remain_distinct(git_repo: Path, tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked_moved = tmp_path / "locked-on-unmounted-volume"
    deleted = tmp_path / "deleted"
    detached = tmp_path / "detached"
    _git(git_repo, "worktree", "add", "-q", "-b", "locked", str(locked))
    _git(git_repo, "worktree", "lock", "--reason", "portable media", str(locked))
    locked.rename(locked_moved)
    _git(git_repo, "worktree", "add", "-q", "-b", "deleted", str(deleted))
    shutil.rmtree(deleted)
    _git(git_repo, "worktree", "add", "-q", "--detach", str(detached), "HEAD")

    before_prune = resolve_workspace(git_repo)
    locked_row = next(row for row in before_prune.worktrees if row.branch == "locked")
    deleted_row = next(row for row in before_prune.worktrees if row.branch == "deleted")
    detached_row = next(row for row in before_prune.worktrees if row.checkout_root == detached.resolve())

    assert (locked_row.is_locked, locked_row.is_prunable, locked_row.path_exists) == (True, False, False)
    assert (deleted_row.is_locked, deleted_row.is_prunable, deleted_row.path_exists) == (False, True, False)
    assert detached_row.is_detached is True
    assert detached_row.branch is None

    _git(git_repo, "worktree", "prune", "--expire=now")
    after_prune = resolve_workspace(git_repo)

    assert any(row.branch == "locked" for row in after_prune.worktrees)
    assert not any(row.branch == "deleted" for row in after_prune.worktrees)


def test_bare_family_keeps_bare_repository_as_primary(git_repo: Path, tmp_path: Path) -> None:
    bare = tmp_path / "family.git"
    linked = tmp_path / "bare-linked"
    subprocess.run(["git", "clone", "-q", "--bare", str(git_repo), str(bare)], check=True)
    _git(bare, "worktree", "add", "-q", str(linked), "main")

    workspace = resolve_workspace(linked)

    assert workspace.primary_root == bare.resolve()
    assert workspace.common_dir == bare.resolve()
    assert workspace.worktrees[0] == WorkspaceWorktree(
        checkout_root=bare.resolve(),
        branch=None,
        head=None,
        is_primary=True,
        is_bare=True,
        is_prunable=False,
        is_locked=False,
        is_detached=False,
        path_exists=True,
    )
    assert workspace.worktrees[1].branch == "main"


def test_non_git_directory_degrades_to_exact_single_member_shape(tmp_path: Path) -> None:
    expected_member = WorkspaceWorktree(
        checkout_root=tmp_path.resolve(),
        branch=None,
        head=None,
        is_primary=True,
        is_bare=False,
        is_prunable=False,
        is_locked=False,
        is_detached=False,
        path_exists=True,
    )

    assert resolve_workspace(tmp_path) == Workspace(
        primary_root=tmp_path.resolve(),
        common_dir=None,
        worktrees=(expected_member,),
    )


def test_parser_resolves_existing_symlink_but_preserves_missing_path(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    symlink = tmp_path / "checkout-link"
    symlink.symlink_to(target, target_is_directory=True)
    missing = tmp_path / "missing"
    output = (
        f"worktree {symlink}\0HEAD {'a' * 40}\0branch refs/heads/main\0\0"
        f"worktree {missing}\0HEAD {'b' * 40}\0branch refs/heads/missing\0prunable reason\0\0"
    ).encode()

    rows = parse_worktree_porcelain(output)

    assert rows[0].checkout_root == target.resolve()
    assert rows[0].path_exists is True
    assert rows[1].checkout_root == missing
    assert rows[1].path_exists is False


@pytest.mark.parametrize(
    "output, reason",
    [
        (b"", "missing record terminator"),
        (b"worktree /tmp/no-terminator", "missing record terminator"),
        (b"HEAD deadbeef\0branch refs/heads/main\0\0", "missing worktree path"),
        (b"worktree relative\0HEAD deadbeef\0branch refs/heads/main\0\0", "not absolute"),
        (b"worktree /tmp/repo\0branch refs/heads/main\0\0", "has no HEAD"),
    ],
)
def test_malformed_porcelain_fails_loudly(output: bytes, reason: str) -> None:
    with pytest.raises(GitWorktreeError, match=reason):
        parse_worktree_porcelain(output)


def test_unknown_attributes_and_attribute_reasons_are_forward_compatible(tmp_path: Path) -> None:
    path = tmp_path / "missing"
    output = (
        f"worktree {path}\0HEAD {'a' * 40}\0branch refs/heads/feature\0"
        "locked portable media\0prunable stale metadata\0future-attribute value\0\0"
    ).encode()

    row = parse_worktree_porcelain(output)[0]

    assert row.is_locked is True
    assert row.is_prunable is True
    assert row.branch == "feature"


def test_missing_git_fails_loudly(tmp_path: Path) -> None:
    with patch("forge.session.workspace.find_git_binary", side_effect=GitNotFoundError()):
        with pytest.raises(GitNotFoundError, match="git binary not found"):
            resolve_workspace(tmp_path)


def test_rev_parse_failure_other_than_not_a_repo_fails_loudly(tmp_path: Path) -> None:
    failed = subprocess.CompletedProcess(
        args=["git", "rev-parse"],
        returncode=128,
        stdout=b"",
        stderr=b"fatal: unsafe repository ownership",
    )
    with patch("forge.session.workspace._run_git", return_value=failed):
        with pytest.raises(GitWorktreeError, match="unsafe repository ownership"):
            resolve_workspace(tmp_path)


def test_worktree_list_failure_fails_loudly(tmp_path: Path) -> None:
    failed = subprocess.CompletedProcess(
        args=["git", "worktree", "list"],
        returncode=1,
        stdout=b"",
        stderr=b"worktree metadata unreadable",
    )
    with patch("forge.session.workspace._run_git", return_value=failed):
        with pytest.raises(GitWorktreeError, match="metadata unreadable"):
            list_git_worktrees(tmp_path)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

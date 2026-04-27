"""Git worktree cleanup utilities.

This module provides functions for safely removing git worktrees.
Cleanup order:
1. Try git worktree remove
2. If dirty: remove untracked config files, retry
3. git branch delete (with -D if force, else -d)
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..exceptions import (
    BranchInUseError,
    BranchNotMergedError,
    DirtyWorktreeError,
    GitWorktreeError,
)
from .config_copy import get_copied_config_files
from .create import find_git_binary, get_main_repo_root, get_repo_root


@dataclass
class CleanupResult:
    """Result of worktree cleanup."""

    worktree_removed: bool = False
    branch_deleted: bool = False
    config_files_removed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def is_worktree_dirty(worktree_path: Path) -> bool:
    """Check if worktree has uncommitted changes.

    Args:
        worktree_path: Path to worktree.

    Returns:
        True if worktree has uncommitted changes.
    """
    git = find_git_binary()

    result = subprocess.run(
        [git, "status", "--porcelain"],
        cwd=str(worktree_path),
        capture_output=True,
        text=True,
    )

    return bool(result.stdout.strip())


def remove_config_files(worktree_path: Path) -> list[str]:
    """Remove untracked config files from worktree.

    Only removes files that are:
    - In the allowlist AND
    - NOT tracked by git

    Called by cleanup_worktree() after a failed removal attempt to clear
    untracked config files that make the worktree dirty.

    Args:
        worktree_path: Path to worktree.

    Returns:
        List of removed file paths (relative to worktree root).
    """
    removed: list[str] = []
    config_files = get_copied_config_files(worktree_path)

    for file_path in config_files:
        try:
            if file_path.is_dir():
                shutil.rmtree(file_path)
            else:
                file_path.unlink()
            try:
                removed.append(str(file_path.relative_to(worktree_path)))
            except ValueError:
                removed.append(file_path.name)
        except OSError:
            pass  # Best effort

    return removed


def remove_worktree(
    worktree_path: Path,
    force: bool = False,
    repo_root: Path | None = None,
) -> bool:
    """Remove a git worktree.

    Args:
        worktree_path: Path to worktree.
        force: Force removal even if dirty.
        repo_root: Main repository root (must be provided, not derived from worktree).

    Returns:
        True if worktree was removed.

    Raises:
        DirtyWorktreeError: If worktree is dirty and force=False.
        GitWorktreeError: If removal fails for other reasons.
    """
    if not worktree_path.exists():
        return False

    if not force and is_worktree_dirty(worktree_path):
        raise DirtyWorktreeError(str(worktree_path))

    git = find_git_binary()

    # Get the main repo root to run git worktree remove from there
    # (git worktree remove needs to be run from the main repo, not from the worktree itself)
    if repo_root is None:
        repo_root = get_main_repo_root(worktree_path)

    cmd = [git, "worktree", "remove", str(worktree_path)]
    if force:
        cmd.append("--force")

    result = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "contains modified or untracked files" in stderr.lower():
            raise DirtyWorktreeError(str(worktree_path))
        raise GitWorktreeError("remove", stderr, result.returncode)

    return True


def delete_branch(
    branch: str,
    cwd: Path | None = None,
    force: bool = False,
) -> bool:
    """Delete a git branch.

    Args:
        branch: Branch name to delete.
        cwd: Working directory (should be main repo, not the worktree).
        force: Use -D (force delete) instead of -d.

    Returns:
        True if branch was deleted.

    Raises:
        BranchInUseError: If branch is checked out elsewhere.
        BranchNotMergedError: If branch is not fully merged and force=False.
        GitWorktreeError: If deletion fails for other reasons.
    """
    git = find_git_binary()
    repo_root = get_repo_root(cwd)

    flag = "-D" if force else "-d"
    result = subprocess.run(
        [git, "branch", flag, branch],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        stderr = result.stderr.strip().lower()
        stderr_orig = result.stderr.strip()

        if "not found" in stderr:
            return False

        # Check for "checked out" or "used by worktree" - branch is in use
        if "checked out" in stderr or "used by worktree" in stderr:
            # Try to extract worktree path from error message
            # Format: "error: Cannot delete branch 'X' checked out at '/path/to/worktree'"
            # or: "error: cannot delete branch 'X' used by worktree at '/path/to/worktree'"
            worktree = "another worktree"
            if "at '" in stderr_orig:
                try:
                    worktree = stderr_orig.split("at '")[1].split("'")[0]
                except IndexError:
                    pass
            raise BranchInUseError(branch, worktree)

        if "not fully merged" in stderr:
            raise BranchNotMergedError(branch)

        raise GitWorktreeError("branch delete", stderr_orig, result.returncode)

    return True


def cleanup_worktree(
    worktree_path: Path,
    branch: str | None = None,
    delete_branch_flag: bool = False,
    force: bool = False,
    repo_root: Path | None = None,
) -> CleanupResult:
    """Full cleanup of a worktree and optionally its branch.

    Order:
    1. Try removing worktree
    2. If dirty: remove untracked config files, retry
    3. Delete branch if requested

    Args:
        worktree_path: Path to worktree.
        branch: Branch name (required if delete_branch_flag=True).
        delete_branch_flag: Whether to delete the branch.
        force: Force removal even if dirty, and use -D for branch.
        repo_root: Main repository root (derived from worktree if not provided).

    Returns:
        CleanupResult with details of what was done.
    """
    result = CleanupResult()

    # Get main repo root before removing worktree (so we can delete branch later)
    # Must use get_main_repo_root to get the main repo, not the worktree itself
    if repo_root is None and worktree_path.exists():
        try:
            repo_root = get_main_repo_root(worktree_path)
        except GitWorktreeError:
            pass  # Will fail to delete branch if repo not found

    # 1. Try removing worktree first. If it fails due to untracked config
    #    files making it dirty, remove those files and retry — this avoids
    #    deleting config files when the removal will fail for other reasons.
    try:
        result.worktree_removed = remove_worktree(worktree_path, force=force, repo_root=repo_root)
    except DirtyWorktreeError:
        if worktree_path.exists():
            result.config_files_removed = remove_config_files(worktree_path)
        try:
            result.worktree_removed = remove_worktree(worktree_path, force=force, repo_root=repo_root)
        except (DirtyWorktreeError, GitWorktreeError) as e:
            result.errors.append(str(e))
            return result
    except GitWorktreeError as e:
        result.errors.append(str(e))
        return result

    # 3. Delete branch if requested
    if delete_branch_flag and branch and repo_root:
        try:
            result.branch_deleted = delete_branch(branch, cwd=repo_root, force=force)
        except (BranchInUseError, BranchNotMergedError, GitWorktreeError) as e:
            result.errors.append(str(e))

    return result

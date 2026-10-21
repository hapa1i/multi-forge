"""Read-only Git identities for a removable worktree and its optional branch."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from forge.core.runtime.codex_review_source import directory_fd

from .git import find_git_binary, get_main_repo_root


@dataclass(frozen=True)
class CleanupGitIdentity:
    repository_device: int
    repository_inode: int
    head: str
    ref: str


def capture_cleanup_git(path: Path, repository: Path, branch: str | None) -> CleanupGitIdentity:
    """Bind deletion to the registered checkout, branch and commit seen in preview."""
    if path.resolve() == repository.resolve() or get_main_repo_root(path).resolve() != repository.resolve():
        raise ValueError("Cleanup target is not a linked worktree of the selected repository")
    records = _git(repository, "worktree", "list", "--porcelain", "-z").split("\0\0")
    if not any(f"worktree {path}" in record.split("\0") for record in records):
        raise ValueError("Cleanup target is not registered in the selected repository")
    head = _git(path, "rev-parse", "--verify", "HEAD").strip()
    ref = _git(path, "symbolic-ref", "-q", "HEAD", allow_detached=True).strip()
    if branch is not None and ref != f"refs/heads/{branch}":
        raise ValueError("Worktree branch differs from the branch selected for deletion")
    with directory_fd(repository) as descriptor:
        identity = os.fstat(descriptor)
    return CleanupGitIdentity(identity.st_dev, identity.st_ino, head, ref)


def validate_cleanup_git(path: Path, repository: Path, expected: CleanupGitIdentity, branch: str | None) -> None:
    """Also validate a surviving branch when a prior attempt removed the checkout."""
    with directory_fd(repository) as descriptor:
        identity = os.fstat(descriptor)
    if (identity.st_dev, identity.st_ino) != (
        expected.repository_device,
        expected.repository_inode,
    ):
        raise ValueError("Worktree repository was replaced after preview")
    if path.exists():
        if capture_cleanup_git(path, repository, branch) != expected:
            raise ValueError("Worktree HEAD or branch changed after preview")
    elif branch:
        ref = f"refs/heads/{branch}"
        records = _git(repository, "for-each-ref", "--format=%(refname) %(objectname)", ref).splitlines()
        current = [record.removeprefix(ref + " ") for record in records if record.startswith(ref + " ")]
        if current and current != [expected.head]:
            raise ValueError("Selected branch changed after the worktree was removed")


def _git(path: Path, *args: str, allow_detached: bool = False) -> str:
    try:
        result = subprocess.run(
            [find_git_binary(), *args],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"Cannot verify cleanup Git identity: {error}") from error
    if result.returncode and not (allow_detached and result.returncode == 1):
        raise ValueError(f"Cannot verify cleanup Git identity: {result.stderr.strip() or result.returncode}")
    return result.stdout

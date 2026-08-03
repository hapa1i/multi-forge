"""Git-derived workspace discovery.

A workspace is the family of worktrees registered against one Git common
directory.  Membership is derived on every read; Forge does not persist a
workspace record.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .exceptions import GitWorktreeError
from .git import find_git_binary


@dataclass(frozen=True)
class WorkspaceWorktree:
    """One worktree registered in a Git workspace."""

    checkout_root: Path
    branch: str | None
    head: str | None
    is_primary: bool
    is_bare: bool
    is_prunable: bool
    is_locked: bool
    is_detached: bool
    path_exists: bool


@dataclass(frozen=True)
class Workspace:
    """A Git worktree family, or a single-directory non-Git workspace."""

    primary_root: Path
    common_dir: Path | None
    worktrees: tuple[WorkspaceWorktree, ...]


def parse_worktree_porcelain(output: bytes) -> tuple[WorkspaceWorktree, ...]:
    """Parse ``git worktree list --porcelain -z`` output.

    Unknown attributes are deliberately ignored so newer Git versions can add
    fields without breaking workspace reads.
    """

    if not output or not output.endswith(b"\0\0"):
        raise GitWorktreeError("parse", "malformed porcelain: missing record terminator")

    records = output.split(b"\0\0")
    if records[-1]:
        raise GitWorktreeError("parse", "malformed porcelain: trailing data")

    worktrees: list[WorkspaceWorktree] = []
    for index, record in enumerate(records[:-1]):
        if not record:
            raise GitWorktreeError("parse", "malformed porcelain: empty record")
        worktrees.append(_parse_worktree_record(record, is_primary=index == 0))

    if not worktrees:
        raise GitWorktreeError("parse", "malformed porcelain: no worktrees")
    return tuple(worktrees)


def list_git_worktrees(cwd: Path | None = None) -> tuple[WorkspaceWorktree, ...]:
    """Return all Git worktrees registered for the repository at *cwd*."""

    git = find_git_binary()
    start = (cwd or Path.cwd()).resolve()
    result = _run_git(git, ("worktree", "list", "--porcelain", "-z"), cwd=start)
    if result.returncode != 0:
        raise GitWorktreeError("list", _failure_reason(result.stderr), result.returncode)
    return parse_worktree_porcelain(result.stdout)


def resolve_workspace(cwd: Path | None = None) -> Workspace:
    """Resolve the Git workspace containing *cwd*.

    A path outside Git degrades to a one-member directory workspace.  Missing
    Git, other subprocess failures, and malformed porcelain remain errors.
    """

    start = (cwd or Path.cwd()).resolve()
    git = find_git_binary()
    result = _run_git(
        git,
        ("rev-parse", "--path-format=absolute", "--git-common-dir"),
        cwd=start,
    )
    if result.returncode != 0:
        if _is_not_a_repository(result.stderr):
            member = WorkspaceWorktree(
                checkout_root=start,
                branch=None,
                head=None,
                is_primary=True,
                is_bare=False,
                is_prunable=False,
                is_locked=False,
                is_detached=False,
                path_exists=True,
            )
            return Workspace(primary_root=start, common_dir=None, worktrees=(member,))
        raise GitWorktreeError("rev-parse", _failure_reason(result.stderr), result.returncode)

    common_dir_output = result.stdout[:-1] if result.stdout.endswith(b"\n") else result.stdout
    if not common_dir_output:
        raise GitWorktreeError("rev-parse", "git returned an empty common directory")

    common_dir = Path(os.fsdecode(common_dir_output))
    if not common_dir.is_absolute():
        raise GitWorktreeError("rev-parse", "git returned a non-absolute common directory")
    common_dir = common_dir.resolve()

    worktrees = list_git_worktrees(start)
    # This is Git's family-primary record, not the logical project root. Bare
    # families intentionally anchor here while get_main_repo_root() falls back
    # to the linked checkout from which it was called.
    return Workspace(primary_root=worktrees[0].checkout_root, common_dir=common_dir, worktrees=worktrees)


def find_worktree_for_branch(branch: str, cwd: Path | None = None) -> Path | None:
    """Return the first worktree carrying the local branch named *branch*."""

    for worktree in list_git_worktrees(cwd):
        if worktree.branch == branch:
            return worktree.checkout_root
    return None


def _parse_worktree_record(record: bytes, *, is_primary: bool) -> WorkspaceWorktree:
    fields = record.split(b"\0")
    path_value: bytes | None = None
    branch: str | None = None
    head: str | None = None
    is_bare = False
    is_prunable = False
    is_locked = False
    is_detached = False

    for field in fields:
        if field.startswith(b"worktree "):
            if path_value is not None or not field[len(b"worktree ") :]:
                raise GitWorktreeError("parse", "malformed porcelain: invalid worktree path")
            path_value = field[len(b"worktree ") :]
        elif field.startswith(b"HEAD "):
            head = os.fsdecode(field[len(b"HEAD ") :])
        elif field.startswith(b"branch refs/heads/"):
            branch = os.fsdecode(field[len(b"branch refs/heads/") :])
        elif field == b"bare":
            is_bare = True
        elif field == b"detached":
            is_detached = True
        elif field == b"locked" or field.startswith(b"locked "):
            is_locked = True
        elif field == b"prunable" or field.startswith(b"prunable "):
            is_prunable = True

    if path_value is None:
        raise GitWorktreeError("parse", "malformed porcelain: missing worktree path")
    if not is_bare and not head:
        raise GitWorktreeError("parse", "malformed porcelain: non-bare worktree has no HEAD")
    if not is_bare and branch is None and not is_detached:
        raise GitWorktreeError("parse", "malformed porcelain: worktree has no branch or detached marker")

    recorded_path = Path(os.fsdecode(path_value))
    if not recorded_path.is_absolute():
        raise GitWorktreeError("parse", "malformed porcelain: worktree path is not absolute")
    path_exists = recorded_path.exists()
    checkout_root = recorded_path.resolve() if path_exists else recorded_path

    return WorkspaceWorktree(
        checkout_root=checkout_root,
        branch=branch,
        head=head,
        is_primary=is_primary,
        is_bare=is_bare,
        is_prunable=is_prunable,
        is_locked=is_locked,
        is_detached=is_detached,
        path_exists=path_exists,
    )


def _run_git(git: str, args: tuple[str, ...], *, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            [git, *args],
            cwd=str(cwd),
            capture_output=True,
            env={**os.environ, "LC_ALL": "C"},
        )
    except OSError as exc:
        raise GitWorktreeError(args[0], str(exc)) from exc


def _is_not_a_repository(stderr: bytes) -> bool:
    return b"not a git repository" in stderr.lower()


def _failure_reason(stderr: bytes) -> str:
    return stderr.decode(errors="replace").strip() or "git returned no diagnostic"

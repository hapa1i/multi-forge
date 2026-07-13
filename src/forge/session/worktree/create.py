"""Git worktree creation utilities.

This module provides functions for creating git worktrees for session isolation.
Each session can have its own worktree, enabling parallel work without conflicts.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..exceptions import (
    BranchExistsError,
    BranchNotMergedError,
    GitNotFoundError,
    GitWorktreeError,
    InvalidBranchNameError,
    WorktreePathExistsError,
)


@dataclass
class WorktreeResult:
    """Result of worktree creation."""

    worktree_path: str
    branch: str
    created_branch: bool  # True if a new branch was created


def find_git_binary() -> str:
    """Find git binary in PATH.

    Returns:
        Path to git binary.

    Raises:
        GitNotFoundError: If git is not found.
    """
    git_path = shutil.which("git")
    if git_path is None:
        raise GitNotFoundError()
    return git_path


def get_repo_root(cwd: Path | None = None) -> Path:
    """Get the root of the git repository or worktree.

    For worktrees, this returns the worktree root, not the main repository.
    Use get_main_repo_root() if you need the main repository.

    Args:
        cwd: Starting directory (defaults to current).

    Returns:
        Path to repository/worktree root.

    Raises:
        GitWorktreeError: If not in a git repository.
    """
    git = find_git_binary()
    start = cwd or Path.cwd()

    result = subprocess.run(
        [git, "rev-parse", "--show-toplevel"],
        cwd=str(start),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise GitWorktreeError("rev-parse", "not in a git repository", result.returncode)

    return Path(result.stdout.strip())


def get_main_repo_root(cwd: Path | None = None) -> Path:
    """Get the root of the main git repository.

    For worktrees, this returns the main repository root, not the worktree.
    Uses git-common-dir to find the shared .git directory.

    Args:
        cwd: Starting directory (defaults to current).

    Returns:
        Path to main repository root.

    Raises:
        GitWorktreeError: If not in a git repository.
    """
    git = find_git_binary()
    start = cwd or Path.cwd()

    # Get the common git directory (shared by all worktrees)
    result = subprocess.run(
        [git, "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=str(start),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise GitWorktreeError("rev-parse", "not in a git repository", result.returncode)

    common_dir = Path(result.stdout.strip())
    if common_dir.name == ".git":
        return common_dir.parent

    # Handle edge case where common_dir might be .git/worktrees/name
    while common_dir.name != ".git" and common_dir.parent != common_dir:
        common_dir = common_dir.parent

    if common_dir.name == ".git":
        return common_dir.parent

    return get_repo_root(cwd)


def branch_exists(branch: str, cwd: Path | None = None) -> bool:
    """Check if a git branch exists.

    Uses refs/heads/ to specifically check for local branches,
    avoiding false positives from tags or other refs.

    Args:
        branch: Branch name to check.
        cwd: Working directory.

    Returns:
        True if branch exists as a local branch.
    """
    git = find_git_binary()

    result = subprocess.run(
        [git, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=str(cwd or Path.cwd()),
        capture_output=True,
        text=True,
    )

    return result.returncode == 0


def _branch_is_merged_into_head(branch: str, cwd: Path) -> bool:
    """Return whether deleting *branch* with ``git branch -d`` is safe."""

    git = find_git_binary()
    result = subprocess.run(
        [git, "merge-base", "--is-ancestor", f"refs/heads/{branch}", "HEAD"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise GitWorktreeError("merge-base", result.stderr.strip(), result.returncode)


def resolve_commit(cwd: Path, revision: str = "HEAD") -> str:
    """Resolve *revision* to an immutable commit id."""

    git = find_git_binary()
    result = subprocess.run(
        [git, "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GitWorktreeError("rev-parse", result.stderr.strip(), result.returncode)
    return result.stdout.strip()


def read_file_at_revision(
    relative_path: Path,
    *,
    revision: str,
    cwd: Path,
) -> bytes | None:
    """Read a tracked file from *revision*, or return ``None`` when absent."""

    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("revision file path must be repository-relative")

    git = find_git_binary()
    path_str = relative_path.as_posix()
    listing = subprocess.run(
        [git, "ls-tree", "-z", "--name-only", revision, "--", path_str],
        cwd=str(cwd),
        capture_output=True,
    )
    if listing.returncode != 0:
        raise GitWorktreeError(
            "ls-tree",
            listing.stderr.decode(errors="replace").strip(),
            listing.returncode,
        )
    if not listing.stdout:
        return None

    result = subprocess.run(
        [git, "show", f"{revision}:{path_str}"],
        cwd=str(cwd),
        capture_output=True,
    )
    if result.returncode != 0:
        raise GitWorktreeError(
            "show",
            result.stderr.decode(errors="replace").strip(),
            result.returncode,
        )
    return result.stdout


def get_worktree_for_branch(branch: str, cwd: Path | None = None) -> str | None:
    """Find the worktree path that has a branch checked out.

    Args:
        branch: Branch name to look up.
        cwd: Working directory.

    Returns:
        Worktree path if the branch is checked out, None otherwise.
    """
    git = find_git_binary()

    result = subprocess.run(
        [git, "worktree", "list", "--porcelain"],
        cwd=str(cwd or Path.cwd()),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return None

    # Porcelain format: blocks separated by blank lines, each has
    # "worktree <path>" and "branch refs/heads/<name>"
    current_path: str | None = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = line[len("worktree ") :]
        elif line == f"branch refs/heads/{branch}":
            return current_path

    return None


def validate_branch_name(branch: str) -> None:
    """Validate a git branch name.

    Uses git check-ref-format to validate the branch name.
    This is called for explicit --branch values.

    Args:
        branch: Branch name to validate.

    Raises:
        InvalidBranchNameError: If branch name is invalid.
    """
    git = find_git_binary()

    result = subprocess.run(
        [git, "check-ref-format", "--branch", branch],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        reason = result.stderr.strip() if result.stderr else "invalid format"
        raise InvalidBranchNameError(branch, reason)


def sanitize_branch_name(session_name: str) -> str:
    """Convert session name to valid git branch name.

    Session names are already strict (lowercase alphanumeric + hyphens),
    which are valid git branch names. This is mainly a pass-through.

    Args:
        session_name: The session name.

    Returns:
        Valid git branch name.
    """
    # Session names are validated as lowercase alphanumeric + hyphens
    # which are valid git branch names - just pass through
    return session_name


def resolve_worktree_path(repo_root: Path, session_name: str) -> Path:
    """Compute the worktree path for a session.

    Worktree path: ../<project-name>-<session-name>
    Places worktrees as siblings to the main repo.

    Args:
        repo_root: Path to the main repository.
        session_name: The session name.

    Returns:
        Absolute path for the worktree.
    """
    project_name = repo_root.name
    worktree_dir = f"{project_name}-{session_name}"
    return (repo_root.parent / worktree_dir).resolve()


def create_worktree(
    session_name: str,
    branch: str | None = None,
    cwd: Path | None = None,
    *,
    force: bool = False,
    replace_owned_stale_state: bool = False,
    start_point: str | None = None,
) -> WorktreeResult:
    """Create a git worktree for a session.

    Args:
        session_name: Session name (used for path and default branch).
        branch: Override branch name (defaults to session_name).
        cwd: Starting directory (defaults to current).
        force: Replace conflicting branch/worktree state. Deletes a merged
            branch and removes a clean registered worktree before recreating.
            Hard constraints still apply: BranchInUseError (checked out
            elsewhere), BranchNotMergedError (unmerged work), and non-worktree
            paths (no .git file).
        replace_owned_stale_state: Allow force recovery only when the caller
            has already verified the target worktree/branch belong to the same
            stale Forge session being replaced.
        start_point: Optional immutable commit used for the new branch.

    Returns:
        WorktreeResult with path and branch info.

    Raises:
        GitNotFoundError: If git is not found.
        GitWorktreeError: If worktree creation fails.
        InvalidBranchNameError: If explicit branch name is invalid.
        BranchExistsError: If branch already exists (or force with explicit --branch).
        WorktreePathExistsError: If worktree path already exists (or not a git worktree).
        BranchInUseError: If branch is checked out in another worktree (force only).
        BranchNotMergedError: If branch has unmerged work (force only).
    """
    git = find_git_binary()
    repo_root = get_repo_root(cwd)

    if branch is not None:
        validate_branch_name(branch)
        target_branch = branch
    else:
        # Derive from session name (already valid)
        target_branch = sanitize_branch_name(session_name)

    worktree_path = resolve_worktree_path(repo_root, session_name)

    # Validate every known branch refusal before force-removing an owned stale
    # checkout. The later delete keeps the same checks as a race-safe defense.
    existing_branch = branch_exists(target_branch, repo_root)
    if force and replace_owned_stale_state and existing_branch:
        if branch is not None:
            wt = get_worktree_for_branch(target_branch, repo_root)
            raise BranchExistsError(target_branch, worktree=wt)
        if not _branch_is_merged_into_head(target_branch, repo_root):
            raise BranchNotMergedError(target_branch)

    # --force only replaces worktree state when the caller has proved the
    # derived target belongs to the same stale Forge child being recovered.
    # Worktree first (un-checks-out the branch), then branch.
    if force and replace_owned_stale_state and worktree_path.exists():
        git_file = worktree_path / ".git"
        if not git_file.is_file():
            # Not a registered git worktree — refuse to delete arbitrary dirs
            raise WorktreePathExistsError(str(worktree_path))
        from .cleanup import remove_worktree

        main_root = get_main_repo_root(worktree_path)
        remove_worktree(worktree_path, force=True, repo_root=main_root)
        if worktree_path.exists():
            raise WorktreePathExistsError(str(worktree_path))
    elif worktree_path.exists():
        raise WorktreePathExistsError(str(worktree_path))

    if branch_exists(target_branch, repo_root):
        if not force or not replace_owned_stale_state:
            wt = get_worktree_for_branch(target_branch, repo_root)
            raise BranchExistsError(target_branch, worktree=wt)
        if branch is not None:
            # Race-safe defense; the precheck above handles the normal stale
            # replacement path before its checkout is removed.
            wt = get_worktree_for_branch(target_branch, repo_root)
            raise BranchExistsError(target_branch, worktree=wt)
        # --force with auto-derived branch: delete (respects git merge safety).
        # BranchInUseError/BranchNotMergedError propagate as hard constraints.
        from .cleanup import delete_branch as _delete_branch

        _delete_branch(target_branch, cwd=repo_root, force=False)

    command = [git, "worktree", "add", str(worktree_path), "-b", target_branch]
    if start_point is not None:
        command.append(start_point)
    result = subprocess.run(
        command,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise GitWorktreeError("add", result.stderr.strip(), result.returncode)

    return WorktreeResult(
        worktree_path=str(worktree_path),
        branch=target_branch,
        created_branch=True,
    )

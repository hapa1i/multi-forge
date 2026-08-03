"""Command-core execution context.

This context is intentionally lightweight: it carries paths only.
Stores (SessionStore/IndexStore/etc.) are cheap file wrappers and should be
constructed inside ops as needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from forge.core.paths import find_git_root
from forge.session.exceptions import GitNotFoundError, GitWorktreeError
from forge.session.git import get_main_repo_root


@dataclass(frozen=True)
class ExecutionContext:
    """Execution context for command-core ops.

    Attributes:
        cwd: Current working directory.
        worktree_root: Git checkout root (= checkout_root in the identity model).
        project_root: Git repository root (= logical repo, main checkout).
        forge_root: Forge project root (directory containing .forge/), or None
            if not inside a Forge project.
    """

    cwd: Path
    worktree_root: Path
    project_root: Path
    forge_root: Path | None = None

    @classmethod
    def from_cwd(cls, cwd: Path | None = None) -> "ExecutionContext":
        """Create context by deriving paths from the current working directory.

        Uses git to find the worktree/project root. Falls back to cwd if not
        in a git repository.

        Args:
            cwd: Working directory. Defaults to Path.cwd().

        Returns:
            ExecutionContext with derived paths.
        """
        if cwd is None:
            cwd = Path.cwd().resolve()
        else:
            cwd = cwd.resolve()

        # Try to find git root (works for both regular repos and worktrees)
        worktree_root = find_git_root(cwd)
        if worktree_root is None:
            # Not in a git repo: use cwd for all paths
            forge_root = find_forge_root(cwd)
            return cls(cwd=cwd, worktree_root=cwd, project_root=cwd, forge_root=forge_root)

        # Git is authoritative for logical-repository identity. Context
        # construction remains failure-soft for corrupt repositories or hosts
        # where Git disappeared after the filesystem boundary check.
        try:
            project_root = get_main_repo_root(worktree_root)
        except (GitNotFoundError, GitWorktreeError):
            project_root = worktree_root

        # Find Forge project root (.forge/ directory)
        forge_root = find_forge_root(cwd)

        return cls(cwd=cwd, worktree_root=worktree_root, project_root=project_root, forge_root=forge_root)


def find_forge_root(start: Path) -> Path | None:
    """Find the Forge project root by walking up from start.

    A Forge project root is a directory containing a ``.forge/`` subdirectory,
    established by ``forge extension enable``.

    Stops at git repository boundaries (``.git`` directory or file) to avoid
    escaping into a parent repository's ``.forge/``.

    Returns None if not inside a Forge project.
    """
    current = start
    while current != current.parent:
        if (current / ".forge").is_dir():
            return current
        if (current / ".git").exists():
            return None  # Hit git boundary without finding .forge/
        current = current.parent

    return None


def _cwd_forge_root() -> str | None:
    """Resolve forge_root from CWD for project-scoped session lookups."""
    try:
        fr = find_forge_root(Path.cwd().resolve())
        return str(fr) if fr else None
    except Exception:
        return None

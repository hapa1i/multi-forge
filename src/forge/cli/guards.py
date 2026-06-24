"""CWD validation guards for session commands.

Enforces two invariants:
1. CWD must be a git repo root OR a Forge project root (where .forge/ lives)
2. CWD must be the main repo root (not a child worktree) — for --worktree commands
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console

from forge.cli.output import print_error, print_tip
from forge.core.paths import display_path

console = Console()


def require_repo_root() -> Path:
    """Verify CWD is a git repository root or a Forge project root.

    Accepts CWD at a nested Forge project root (where .forge/ lives) for
    monorepo support. Falls back to git root check for non-Forge directories.

    Returns:
        The validated CWD on success.
    """
    from forge.core.ops.context import find_forge_root
    from forge.session.claude.paths import find_project_root

    cwd = Path.cwd().resolve()

    # Accept CWD at a Forge project root (nested or top-level)
    forge_root = find_forge_root(cwd)
    if forge_root is not None and forge_root == cwd:
        return cwd

    try:
        repo_root = find_project_root().resolve()
    except FileNotFoundError:
        print_error("Not in a git repository", console=console)
        sys.exit(1)

    if cwd != repo_root:
        hint = str(forge_root) if forge_root else str(repo_root)
        print_error(
            f"Must run from the repository root ({display_path(repo_root)}), " f"not a subdirectory",
            console=console,
        )
        print_tip("Run from:", commands=[f"cd {display_path(hint)}"], console=console)
        sys.exit(1)

    return cwd


def require_main_repo_root() -> Path:
    """Verify CWD is the main git repo root (or Forge project root), not a child worktree.

    Accepts CWD at a nested Forge project root for monorepo support.
    For --worktree commands, also checks that we're not inside a child worktree.

    Returns:
        The validated CWD on success.
    """
    from forge.core.ops.context import find_forge_root
    from forge.session.claude.paths import find_project_root
    from forge.session.exceptions import GitNotFoundError, GitWorktreeError
    from forge.session.worktree import get_main_repo_root

    cwd = Path.cwd().resolve()

    try:
        repo_root = find_project_root().resolve()
    except FileNotFoundError:
        print_error("Not in a git repository", console=console)
        sys.exit(1)

    # Resolve main repo root before any error so the tip is always correct
    try:
        main_root = get_main_repo_root(repo_root).resolve()
    except (GitWorktreeError, GitNotFoundError):
        main_root = repo_root

    if repo_root != main_root:
        # Any location inside a child worktree (root or subfolder)
        print_error(
            "Cannot create worktrees from inside a child worktree. "
            f"Run from the main repository root ({display_path(main_root)})",
            console=console,
        )
        print_tip("Run from:", commands=[f"cd {display_path(main_root)}"], console=console)
        sys.exit(1)

    # Accept CWD at a Forge project root (nested or top-level)
    forge_root = find_forge_root(cwd)
    if forge_root is not None and forge_root == cwd:
        return cwd

    if cwd != repo_root:
        # Subfolder of the main repo without .forge/
        print_error(
            f"Must run from the repository root ({display_path(repo_root)}), " f"not a subdirectory",
            console=console,
        )
        print_tip("Run from:", commands=[f"cd {display_path(repo_root)}"], console=console)
        sys.exit(1)

    return cwd

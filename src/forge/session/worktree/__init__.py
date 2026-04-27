"""Git worktree utilities for session isolation.

This module provides functions for creating, configuring, and cleaning up
git worktrees for Forge sessions. Each session can have its own worktree,
enabling parallel work without manifest conflicts.

Key safety features:
- Never overwrites tracked files during config copy
- Never deletes tracked files during cleanup
- Uses refs/heads/ for branch checks (avoids tag false positives)
- Validates explicit --branch names
"""

from .cleanup import (
    CleanupResult,
    cleanup_worktree,
    delete_branch,
    is_worktree_dirty,
    remove_config_files,
    remove_worktree,
)
from .config_copy import (
    ConfigCopyResult,
    DEFAULT_CONFIG_ALLOWLIST,
    copy_runtime_config,
    get_copied_config_files,
    is_file_tracked,
)
from .create import (
    WorktreeResult,
    branch_exists,
    create_worktree,
    find_git_binary,
    get_main_repo_root,
    get_repo_root,
    resolve_worktree_path,
    sanitize_branch_name,
    validate_branch_name,
)

__all__ = [
    # create.py
    "WorktreeResult",
    "find_git_binary",
    "get_repo_root",
    "get_main_repo_root",
    "branch_exists",
    "validate_branch_name",
    "sanitize_branch_name",
    "resolve_worktree_path",
    "create_worktree",
    # config_copy.py
    "ConfigCopyResult",
    "DEFAULT_CONFIG_ALLOWLIST",
    "is_file_tracked",
    "copy_runtime_config",
    "get_copied_config_files",
    # cleanup.py
    "CleanupResult",
    "is_worktree_dirty",
    "remove_config_files",
    "remove_worktree",
    "delete_branch",
    "cleanup_worktree",
]

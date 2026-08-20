"""Copy runtime configuration to worktree.

This module handles safe copying of runtime config files (.env, .mcp.json, etc.)
from the main repository to a new worktree. Safety rules:
1. Only copy if file exists in source
2. Only copy if file does NOT already exist in target
3. Skip files that are tracked by git
4. Never follow symlinked directory components

Entries support glob patterns (``**/`` prefix) for nested project structures.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..git import find_git_binary

logger = logging.getLogger(__name__)

# Allowlist of runtime config files/directories to copy (relative to repo root).
# Entries with glob metacharacters are resolved via Path.glob(); exact paths are
# matched directly. ``**/X`` matches X at any depth including root.
DEFAULT_CONFIG_ALLOWLIST: tuple[str, ...] = (
    ".env",
    ".env.local",
    ".envrc",
    "docker/certs",
    "**/.claude/settings.json",
    "**/.claude/settings.local.json",
    "**/.mcp.json",
    "**/.mcp.local.json",
)

_EXCLUDED_CONFIG_DIRS: frozenset[str] = frozenset({".git", "node_modules"})


@dataclass
class ConfigCopyResult:
    """Result of config copy operation."""

    copied: list[str] = field(default_factory=list)
    skipped_exists: list[str] = field(default_factory=list)  # Already exists in target
    skipped_tracked: list[str] = field(default_factory=list)  # Tracked by git
    skipped_not_found: list[str] = field(default_factory=list)  # Not in source
    failed: list[tuple[str, str]] = field(default_factory=list)  # (file, error)


def is_file_tracked(file_path: Path, cwd: Path) -> bool:
    """Check if a file is tracked by git.

    Uses `git ls-files --error-unmatch` to check if the file is tracked.

    Args:
        file_path: Path to the file (can be relative or absolute).
        cwd: Working directory for git command.

    Returns:
        True if file is tracked by git.
    """
    git = find_git_binary()

    if file_path.is_absolute():
        try:
            file_path = file_path.relative_to(cwd)
        except ValueError:
            # File is not under cwd, can't be tracked
            return False

    result = subprocess.run(
        [git, "ls-files", "--error-unmatch", str(file_path)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )

    return result.returncode == 0


def is_symlink_free_config_path(
    root: Path,
    relative_path: Path,
    *,
    include_leaf: bool = True,
) -> bool:
    """Return whether a relative config path crosses no symlink below root.

    Absolute paths and parent traversal are unsafe. Callers may exclude the leaf
    when unlinking a symlink itself is safe but following a symlinked parent is not.
    """
    if relative_path.is_absolute() or ".." in relative_path.parts:
        return False

    parts = relative_path.parts if include_leaf else relative_path.parts[:-1]
    current = root
    for part in parts:
        current /= part
        if current.is_symlink():
            return False
    return True


def _is_glob_pattern(pattern: str) -> bool:
    """Check if a pattern contains glob metacharacters."""
    return any(c in pattern for c in ("*", "?", "["))


def _is_excluded_path(relative_path: Path) -> bool:
    """Return whether a relative config path crosses an excluded directory."""
    return any(part in _EXCLUDED_CONFIG_DIRS for part in relative_path.parts)


def _resolve_glob(root: Path, pattern: str) -> list[Path]:
    """Resolve a glob while filtering Git metadata and dependency-tree matches."""
    matches: list[Path] = []
    for match in root.glob(pattern):
        relative_path = match.relative_to(root)
        if not _is_excluded_path(relative_path):
            matches.append(relative_path)
    return sorted(matches)


def _directory_files(root: Path, relative_dir: Path) -> list[Path]:
    """Return file candidates below a directory without entering excluded trees."""
    directory = root / relative_dir
    files: list[Path] = []

    if not is_symlink_free_config_path(root, relative_dir):
        return files

    def _raise_walk_error(error: OSError) -> None:
        raise error

    for current, dirnames, filenames in os.walk(
        directory,
        topdown=True,
        onerror=_raise_walk_error,
        followlinks=False,
    ):
        current_path = Path(current)
        dirnames[:] = sorted(
            name for name in dirnames if name not in _EXCLUDED_CONFIG_DIRS and not (current_path / name).is_symlink()
        )
        for name in sorted(filenames):
            relative_path = (current_path / name).relative_to(root)
            if not _is_excluded_path(relative_path):
                files.append(relative_path)

    return files


def _copy_file(
    source_root: Path,
    worktree_path: Path,
    relative_path: Path,
    result: ConfigCopyResult,
) -> None:
    """Copy one file after applying destination and tracked-file guards."""
    filename = str(relative_path)
    source_path = source_root / relative_path
    dest_path = worktree_path / relative_path

    if not is_symlink_free_config_path(source_root, relative_path, include_leaf=False):
        result.skipped_not_found.append(filename)
        return

    if not source_path.is_file():
        result.skipped_not_found.append(filename)
        return

    if not is_symlink_free_config_path(worktree_path, relative_path):
        result.skipped_exists.append(filename)
        return

    if dest_path.exists():
        result.skipped_exists.append(filename)
        return

    if is_file_tracked(relative_path, worktree_path):
        result.skipped_tracked.append(filename)
        return

    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, dest_path)
        result.copied.append(filename)
    except OSError as e:
        result.failed.append((filename, str(e)))


def _copy_single(
    source_root: Path,
    worktree_path: Path,
    filename: str,
    result: ConfigCopyResult,
) -> None:
    """Copy a single file or directory from source to worktree with safety checks."""
    relative_path = Path(filename)
    source_path = source_root / relative_path

    if _is_excluded_path(relative_path):
        result.skipped_not_found.append(filename)
        return

    if source_path.is_dir():
        dest_path = worktree_path / relative_path
        if not is_symlink_free_config_path(source_root, relative_path):
            result.skipped_not_found.append(filename)
            return
        if not is_symlink_free_config_path(worktree_path, relative_path) or (
            dest_path.exists() and not dest_path.is_dir()
        ):
            result.skipped_exists.append(filename)
            return
        try:
            directory_files = _directory_files(source_root, relative_path)
        except OSError as e:
            result.failed.append((filename, str(e)))
            return
        for child_path in directory_files:
            _copy_file(source_root, worktree_path, child_path, result)
        return

    _copy_file(source_root, worktree_path, relative_path, result)


def copy_runtime_config(
    source_root: Path,
    worktree_path: Path,
    allowlist: tuple[str, ...] | None = None,
) -> ConfigCopyResult:
    """Copy runtime configuration files to worktree.

    Safely copies files from the allowlist, respecting:
    - Only copy if file exists in source
    - Only copy if file does NOT already exist in target
    - Skip files that are tracked by git (they'll be in the worktree already)

    Allowlist entries may be exact relative paths or glob patterns (containing
    ``*``, ``?``, or ``[``). Glob patterns are resolved via ``Path.glob()``
    with excluded directories filtered out (node_modules, .git, etc.).

    Args:
        source_root: Path to source repository.
        worktree_path: Path to worktree.
        allowlist: Files to copy (defaults to DEFAULT_CONFIG_ALLOWLIST).

    Returns:
        ConfigCopyResult with detailed status of each file.
    """
    result = ConfigCopyResult()
    files_to_copy = allowlist if allowlist is not None else DEFAULT_CONFIG_ALLOWLIST

    for entry in files_to_copy:
        if _is_glob_pattern(entry):
            resolved = _resolve_glob(source_root, entry)
            if not resolved:
                result.skipped_not_found.append(entry)
                continue
            for rel_path in resolved:
                _copy_single(source_root, worktree_path, str(rel_path), result)
        else:
            _copy_single(source_root, worktree_path, entry, result)

    return result


def get_copied_config_files(worktree_path: Path) -> list[Path]:
    """Get list of untracked config files in worktree that match allowlist.

    Used for cleanup to identify which files can be safely removed.
    Only returns files that are NOT tracked by git. Handles both exact
    paths and glob patterns in the allowlist.

    Args:
        worktree_path: Path to worktree.

    Returns:
        List of existing untracked config file paths.
    """
    config_files: list[Path] = []
    seen: set[Path] = set()

    for entry in DEFAULT_CONFIG_ALLOWLIST:
        if _is_glob_pattern(entry):
            resolved = _resolve_glob(worktree_path, entry)
        else:
            relative_path = Path(entry)
            resolved = [] if _is_excluded_path(relative_path) else [relative_path]

        for relative_path in resolved:
            file_path = worktree_path / relative_path
            if file_path.is_dir():
                if not is_symlink_free_config_path(worktree_path, relative_path):
                    logger.debug("Skipping symlinked config directory during cleanup discovery: %s", file_path)
                    continue
                try:
                    candidates = _directory_files(worktree_path, relative_path)
                except OSError:
                    # Cleanup discovery is best effort; the worktree-removal retry still reports failure.
                    logger.debug(
                        "Skipping unreadable config directory during cleanup discovery: %s",
                        file_path,
                        exc_info=True,
                    )
                    continue
            else:
                candidates = [relative_path]

            for candidate in candidates:
                candidate_path = worktree_path / candidate
                if candidate in seen or not candidate_path.is_file():
                    continue
                if not is_file_tracked(candidate, worktree_path):
                    seen.add(candidate)
                    config_files.append(candidate_path)

    return config_files

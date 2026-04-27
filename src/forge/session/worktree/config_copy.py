"""Copy runtime configuration to worktree.

This module handles safe copying of runtime config files (.env, .mcp.json, etc.)
from the main repository to a new worktree. Safety rules:
1. Only copy if file exists in source
2. Only copy if file does NOT already exist in target
3. Skip files that are tracked by git

Entries support glob patterns (``**/`` prefix) for nested project structures.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .create import find_git_binary

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


def _is_glob_pattern(pattern: str) -> bool:
    """Check if a pattern contains glob metacharacters."""
    return any(c in pattern for c in ("*", "?", "["))


def _resolve_glob(root: Path, pattern: str) -> list[Path]:
    """Resolve a glob pattern relative to root.

    Returns sorted relative paths matching the pattern.
    """
    return sorted(match.relative_to(root) for match in root.glob(pattern))


def _copy_single(
    source_root: Path,
    worktree_path: Path,
    filename: str,
    result: ConfigCopyResult,
) -> None:
    """Copy a single file or directory from source to worktree with safety checks."""
    source_path = source_root / filename
    dest_path = worktree_path / filename

    if source_path.is_dir():
        if dest_path.exists():
            result.skipped_exists.append(filename)
            return
        try:
            shutil.copytree(source_path, dest_path)
            result.copied.append(filename)
        except OSError as e:
            result.failed.append((filename, str(e)))
        return

    if not source_path.is_file():
        result.skipped_not_found.append(filename)
        return

    if dest_path.exists():
        result.skipped_exists.append(filename)
        return

    if is_file_tracked(Path(filename), worktree_path):
        result.skipped_tracked.append(filename)
        return

    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, dest_path)
        result.copied.append(filename)
    except OSError as e:
        result.failed.append((filename, str(e)))


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

    for entry in DEFAULT_CONFIG_ALLOWLIST:
        if _is_glob_pattern(entry):
            for rel_path in _resolve_glob(worktree_path, entry):
                file_path = worktree_path / rel_path
                if file_path.is_dir():
                    config_files.append(file_path)
                elif file_path.is_file() and not is_file_tracked(rel_path, worktree_path):
                    config_files.append(file_path)
        else:
            file_path = worktree_path / entry
            if file_path.is_dir():
                config_files.append(file_path)
            elif file_path.is_file() and not is_file_tracked(Path(entry), worktree_path):
                config_files.append(file_path)

    return config_files

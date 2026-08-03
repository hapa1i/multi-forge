"""Shared Git executable and repository-path discovery."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .exceptions import GitNotFoundError, GitWorktreeError


def find_git_binary() -> str:
    """Return the Git executable from ``PATH``."""

    git_path = shutil.which("git")
    if git_path is None:
        raise GitNotFoundError()
    return git_path


def get_repo_root(cwd: Path | None = None) -> Path:
    """Return the checkout root containing *cwd*."""

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
    """Return the logical repository root shared by non-bare worktrees."""

    git = find_git_binary()
    start = cwd or Path.cwd()
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

    # Retain support for callers whose Git configuration reports a path below
    # the common .git directory rather than the directory itself.
    while common_dir.name != ".git" and common_dir.parent != common_dir:
        common_dir = common_dir.parent
    if common_dir.name == ".git":
        return common_dir.parent

    # Preserve the established bare-family behavior: there is no non-bare main
    # checkout, so the logical project root remains the current checkout.
    return get_repo_root(cwd)

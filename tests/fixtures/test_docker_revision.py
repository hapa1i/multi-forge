"""Unit tests for docker revision helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.fixtures.docker import _get_forge_revision


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in a temporary repo."""
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    """Create a small git repo suitable for revision-helper tests."""
    repo = tmp_path / "repo"
    repo.mkdir()

    _run_git(repo, "init")
    _run_git(repo, "config", "user.name", "Forge Tests")
    _run_git(repo, "config", "user.email", "forge-tests@example.com")

    (repo / "tracked.txt").write_text("one\n")
    _run_git(repo, "add", "tracked.txt")
    _run_git(repo, "commit", "-m", "init")
    return repo


def test_get_forge_revision_returns_head_for_clean_repo(tmp_path: Path) -> None:
    """Clean repos should use the exact HEAD SHA."""
    repo = _init_repo(tmp_path)

    expected = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
    assert _get_forge_revision(repo) == expected


def test_get_forge_revision_changes_when_tracked_dirty_contents_change(tmp_path: Path) -> None:
    """Dirty tracked edits should produce a content-sensitive revision token."""
    repo = _init_repo(tmp_path)
    head = _run_git(repo, "rev-parse", "HEAD").stdout.strip()

    (repo / "tracked.txt").write_text("two\n")
    rev_one = _get_forge_revision(repo)

    (repo / "tracked.txt").write_text("three\n")
    rev_two = _get_forge_revision(repo)

    assert rev_one.startswith(f"{head}-dirty-")
    assert rev_two.startswith(f"{head}-dirty-")
    assert rev_one != rev_two


def test_get_forge_revision_changes_when_untracked_contents_change(tmp_path: Path) -> None:
    """Untracked files should also invalidate cached Docker images."""
    repo = _init_repo(tmp_path)
    head = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
    extra = repo / "extra.txt"

    extra.write_text("alpha\n")
    rev_one = _get_forge_revision(repo)

    extra.write_text("beta\n")
    rev_two = _get_forge_revision(repo)

    assert rev_one.startswith(f"{head}-dirty-")
    assert rev_two.startswith(f"{head}-dirty-")
    assert rev_one != rev_two

"""Tests for Rule 1: session start requires .forge/."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.session.exceptions import ForgeNotEnabledError
from forge.session.manager import SessionManager


def _init_git_repo(path: Path) -> None:
    """Create a minimal git repo at *path*."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        capture_output=True,
        check=True,
        cwd=str(path),
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        capture_output=True,
        check=True,
        cwd=str(path),
    )
    (path / "README.md").write_text("# Test\n")
    subprocess.run(
        ["git", "add", "."],
        capture_output=True,
        check=True,
        cwd=str(path),
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        capture_output=True,
        check=True,
        cwd=str(path),
    )


def _enable_forge(path: Path) -> None:
    """Create .claude/ and .forge/ at *path*."""
    (path / ".claude").mkdir(exist_ok=True)
    (path / ".forge").mkdir(exist_ok=True)


class TestRule1RequireForgeDir:
    """Rule 1: session start fails without .forge/."""

    def test_start_raises_without_forge_dir(self, tmp_path: Path) -> None:
        """start_session raises ForgeNotEnabledError when .forge/ doesn't exist."""
        _init_git_repo(tmp_path)
        manager = SessionManager()

        with pytest.raises(ForgeNotEnabledError, match="forge extension enable"):
            manager.start_session(name="test-session", worktree_path=str(tmp_path))

    def test_start_succeeds_with_forge_dir(self, tmp_path: Path) -> None:
        """start_session succeeds when .forge/ exists."""
        _init_git_repo(tmp_path)
        (tmp_path / ".forge").mkdir()
        manager = SessionManager()

        state = manager.start_session(name="test-session", worktree_path=str(tmp_path))

        assert state.name == "test-session"
        assert state.forge_root == str(tmp_path)

    def test_error_includes_path(self, tmp_path: Path) -> None:
        """Error message includes the path where .forge/ was expected."""
        _init_git_repo(tmp_path)
        manager = SessionManager()

        with pytest.raises(ForgeNotEnabledError) as exc_info:
            manager.start_session(name="test-session", worktree_path=str(tmp_path))

        assert str(tmp_path) in str(exc_info.value)

    def test_finds_forge_in_parent(self, tmp_path: Path) -> None:
        """start_session succeeds when .forge/ exists in a parent directory."""
        _init_git_repo(tmp_path)
        (tmp_path / ".forge").mkdir()
        subdir = tmp_path / "src" / "deep"
        subdir.mkdir(parents=True)

        manager = SessionManager()
        state = manager.start_session(name="nested-session", worktree_path=str(subdir))

        assert state.name == "nested-session"
        assert state.forge_root == str(tmp_path)

    def test_worktree_start_nested_forge_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Worktree session finds .forge/ in a nested project via launch CWD."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        # Monorepo with .forge/ only in packages/app/
        repo = tmp_path / "monorepo"
        _init_git_repo(repo)
        nested = repo / "packages" / "app"
        nested.mkdir(parents=True)
        _enable_forge(nested)

        # User is in the nested project dir when they start
        monkeypatch.chdir(nested)

        manager = SessionManager()
        state = manager.start_session(name="wt-nested", create_worktree=True)

        # forge_root should be in the NEW worktree at the equivalent position
        assert state.forge_root is not None
        assert state.forge_root.endswith("packages/app")
        assert "wt-nested" in state.forge_root  # in the new worktree, not original
        entry = manager.index_store.get_session("wt-nested")
        assert entry.relative_path == "packages/app"

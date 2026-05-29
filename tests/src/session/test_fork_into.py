"""Tests for fork --into relative_path preservation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.session.exceptions import ForgeSessionError, SessionExistsError
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
    subprocess.run(["git", "add", "."], capture_output=True, check=True, cwd=str(path))
    subprocess.run(["git", "commit", "-m", "init"], capture_output=True, check=True, cwd=str(path))


def _enable_forge(path: Path) -> None:
    """Create .claude/ and .forge/ at *path*."""
    (path / ".claude").mkdir(exist_ok=True)
    (path / ".forge").mkdir(exist_ok=True)


class TestForkIntoRelativePath:
    """tests --into targets worktree; child at equivalent forge_root."""

    def test_into_root_forge_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fork --into with forge_root at checkout root (relative_path='.')."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        # Parent repo
        parent_repo = tmp_path / "repo-a"
        _init_git_repo(parent_repo)
        _enable_forge(parent_repo)

        # Target repo (same logical repo root in reality, simulated as separate checkout)
        target_repo = tmp_path / "repo-a-feat"
        _init_git_repo(target_repo)
        _enable_forge(target_repo)

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(parent_repo))

        _, fork = manager.fork_session("parent", "child", into_path=str(target_repo))

        assert fork.forge_root == str(target_repo)
        assert fork.worktree is not None
        assert fork.worktree.path == str(target_repo)
        assert fork.worktree.owns_worktree is False
        assert fork.confirmed.derivation is not None
        assert fork.confirmed.derivation.parent_session == "parent"
        assert fork.confirmed.derivation.resume_mode == "transfer"
        assert fork.confirmed.derivation.strategy is None
        assert fork.confirmed.derivation.depth == 1
        assert fork.confirmed.derivation.lineage == ["parent"]
        assert fork.confirmed.derivation.parent_forge_root == str(parent_repo)
        assert fork.confirmed.derivation.parent_project_root == str(parent_repo)

        # Verify index entry has correct identity
        entry = manager.index_store.get_session("child")
        assert entry.forge_root == str(target_repo)
        assert entry.relative_path == "."

    def test_into_nested_forge_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fork --into with forge_root in a subdirectory (relative_path != '.')."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        # Parent: monorepo with forge project in packages/app
        parent_repo = tmp_path / "monorepo"
        _init_git_repo(parent_repo)
        nested = parent_repo / "packages" / "app"
        nested.mkdir(parents=True)
        _enable_forge(nested)

        # Target: different checkout of same monorepo
        target_repo = tmp_path / "monorepo-feat"
        _init_git_repo(target_repo)
        target_nested = target_repo / "packages" / "app"
        target_nested.mkdir(parents=True)
        _enable_forge(target_nested)

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(nested))

        _, fork = manager.fork_session("parent", "child", into_path=str(target_repo))

        # Child should land at target_repo/packages/app (equivalent position)
        assert fork.forge_root == str(target_nested)

        entry = manager.index_store.get_session("child")
        assert entry.forge_root == str(target_nested)
        assert entry.relative_path == "packages/app"

    def test_into_force_replaces_stale_target_session_without_touching_checkout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Force retry for --into should replace target session state, not the checkout."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        parent_repo = tmp_path / "repo-a"
        _init_git_repo(parent_repo)
        _enable_forge(parent_repo)

        target_repo = tmp_path / "repo-a-feat"
        _init_git_repo(target_repo)
        _enable_forge(target_repo)

        marker = target_repo / "keep-me.txt"
        marker.write_text("safe\n")

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(parent_repo))
        _, stale = manager.fork_session("parent", "child", into_path=str(target_repo))

        assert stale.is_fork is True
        assert stale.parent_session == "parent"

        _, fork = manager.fork_session("parent", "child", into_path=str(target_repo), force=True)

        replaced = manager.get_session("child", forge_root=str(target_repo))
        entry = manager.index_store.get_session("child", forge_root=str(target_repo))

        assert marker.read_text() == "safe\n"
        assert (target_repo / ".git").exists()
        assert fork.worktree is not None
        assert fork.worktree.path == str(target_repo)
        assert fork.worktree.is_worktree is True
        assert fork.worktree.owns_worktree is False
        assert replaced.is_fork is True
        assert replaced.parent_session == "parent"
        assert entry.forge_root == str(target_repo)
        assert entry.parent_session == "parent"

    def test_into_force_rejects_unrelated_target_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Force retry for --into must not delete an unrelated same-name session."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        parent_repo = tmp_path / "repo-a"
        _init_git_repo(parent_repo)
        _enable_forge(parent_repo)

        target_repo = tmp_path / "repo-a-feat"
        _init_git_repo(target_repo)
        _enable_forge(target_repo)

        marker = target_repo / "keep-me.txt"
        marker.write_text("safe\n")

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(parent_repo))
        manager.start_session(name="child", worktree_path=str(target_repo))

        with pytest.raises(SessionExistsError):
            manager.fork_session("parent", "child", into_path=str(target_repo), force=True)

        existing = manager.get_session("child", forge_root=str(target_repo))
        entry = manager.index_store.get_session("child", forge_root=str(target_repo))

        assert marker.read_text() == "safe\n"
        assert existing.is_fork is False
        assert existing.parent_session is None
        assert entry.parent_session is None

    def test_into_missing_forge_at_target_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fork --into fails when target doesn't have .forge/ at the right position."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        parent_repo = tmp_path / "repo-a"
        _init_git_repo(parent_repo)
        _enable_forge(parent_repo)

        target_repo = tmp_path / "repo-a-feat"
        _init_git_repo(target_repo)
        # NO _enable_forge(target_repo)

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(parent_repo))

        with pytest.raises(ForgeSessionError, match="No Forge project"):
            manager.fork_session("parent", "child", into_path=str(target_repo))

    def test_into_nested_missing_forge_at_target_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fork --into fails when nested target path doesn't have .forge/."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        parent_repo = tmp_path / "monorepo"
        _init_git_repo(parent_repo)
        nested = parent_repo / "packages" / "app"
        nested.mkdir(parents=True)
        _enable_forge(nested)

        target_repo = tmp_path / "monorepo-feat"
        _init_git_repo(target_repo)
        # Create the directory but NOT .forge/
        target_nested = target_repo / "packages" / "app"
        target_nested.mkdir(parents=True)

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(nested))

        with pytest.raises(ForgeSessionError, match="No Forge project"):
            manager.fork_session("parent", "child", into_path=str(target_repo))

    def test_worktree_fork_nested_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fork --worktree propagates parent's relative_path to new checkout."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        # Monorepo with nested Forge project
        repo = tmp_path / "monorepo"
        _init_git_repo(repo)
        nested = repo / "packages" / "app"
        nested.mkdir(parents=True)
        _enable_forge(nested)

        monkeypatch.chdir(nested)
        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(nested))

        _, fork = manager.fork_session("parent", "child", create_worktree=True)

        # Child should be in a new worktree at the equivalent nested position
        assert fork.forge_root is not None
        assert fork.forge_root.endswith("packages/app")
        assert "child" in fork.forge_root  # in the new worktree

        entry = manager.index_store.get_session("child")
        assert entry.relative_path == "packages/app"

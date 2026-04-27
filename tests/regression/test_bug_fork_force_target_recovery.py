"""Regression: fork --force should only recover its own stale target and should roll back git state on failure.

Bug 1:
- same-directory `fork --force` treated any same-name session in the target forge_root
  as replaceable, even when it was an unrelated non-fork session.

Bug 2:
- `fork_session(create_worktree=True)` created the git worktree first, but if the later
  manifest/index commit failed, the new worktree and branch were left behind.

Fix:
- Narrow force replacement to an inactive fork that already matches the same parent
  and target checkout/branch.
- Roll back the created worktree/branch when commit fails after git state creation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.session import SessionExistsError
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.worktree import branch_exists, resolve_worktree_path
from forge.session.worktree.create import get_repo_root

pytestmark = pytest.mark.regression


def _init_git_repo(path: Path) -> None:
    """Create a minimal git repo at *path*."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        capture_output=True,
        check=True,
    )
    (path / "README.md").write_text("# Test\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "init"], capture_output=True, check=True)


def _enable_forge(path: Path) -> None:
    """Create .claude/ and .forge/ at *path*."""
    (path / ".claude").mkdir(exist_ok=True)
    (path / ".forge").mkdir(exist_ok=True)


def test_force_same_dir_fork_rejects_unrelated_existing_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force retry should not delete an unrelated same-name session in the target forge_root."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _enable_forge(repo)
    monkeypatch.chdir(repo)

    manager = SessionManager(index_store=IndexStore())
    manager.start_session(name="parent", worktree_path=str(repo))
    manager.start_session(name="child", worktree_path=str(repo))

    with pytest.raises(SessionExistsError):
        manager.fork_session("parent", "child", force=True)

    existing = manager.get_session("child", forge_root=str(repo))
    entry = manager.index_store.get_session("child", forge_root=str(repo))

    assert existing.is_fork is False
    assert existing.parent_session is None
    assert entry.parent_session is None


def test_force_worktree_fork_rolls_back_created_git_state_on_commit_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the post-create commit fails, the new worktree/branch should be removed."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _enable_forge(repo)
    monkeypatch.chdir(repo)

    index_store = IndexStore()
    manager = SessionManager(index_store=index_store)
    manager.start_session(name="parent", worktree_path=str(repo))

    repo_root = get_repo_root(repo)
    expected_worktree = resolve_worktree_path(repo_root, "child")

    original_add = index_store.add_from_state

    def fail_add(state, *args, **kwargs):
        if state.name == "child":
            raise RuntimeError("boom")
        return original_add(state, *args, **kwargs)

    index_store.add_from_state = fail_add  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="boom"):
        manager.fork_session("parent", "child", create_worktree=True)

    assert not expected_worktree.exists()
    assert not branch_exists("child", repo)
    assert not manager.session_exists("child", forge_root=str(expected_worktree))

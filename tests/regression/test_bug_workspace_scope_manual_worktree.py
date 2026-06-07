"""Regression: sessions in a manually-created linked worktree must group under --scope workspace.

Bug: `SessionManager.start_session` derived `project_root` (the workspace anchor)
via `find_project_root(worktree_path)` when Forge did not create the worktree.
`find_project_root` returns the first directory containing a `.git` entry, and a
linked worktree has a `.git` *file* at its own root -- so a session started in a
manually-created `git worktree` got `project_root = <worktree root>` instead of the
shared main-repo root. Sessions in sibling worktrees therefore had different
`project_root` values and did NOT group under `forge session list --scope workspace`
(which filters by `project_root`).

Root cause: `start_session` (and the same-directory `fork` path) bypassed the
canonical `SessionManager.resolve_project_root()` helper (get_main_repo_root with a
graceful non-git fallback), which is what design.md §3 specifies as the
`project_root` identity source.

Affected: src/forge/session/manager.py (start_session, fork same-dir branch).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import list_sessions
from forge.session import IndexStore
from forge.session.manager import SessionManager
from forge.session.worktree import get_main_repo_root

pytestmark = pytest.mark.regression


def _init_git_repo(path: Path) -> None:
    """Create a minimal committed git repo at *path* (HEAD needed for worktree add)."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(path)], capture_output=True, check=True)
    for key, value in (("user.email", "test@test.com"), ("user.name", "Test")):
        subprocess.run(["git", "config", key, value], cwd=str(path), capture_output=True, check=True)
    (path / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(path), capture_output=True, check=True)


def _add_linked_worktree(main: Path, worktree: Path, branch: str) -> None:
    """Create a linked worktree the way a user would (not via Forge)."""
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree)],
        cwd=str(main),
        capture_output=True,
        check=True,
    )


def _enable_forge(path: Path) -> None:
    (path / ".claude").mkdir(exist_ok=True)
    (path / ".forge").mkdir(exist_ok=True)


def test_manual_worktree_project_root_is_main_repo(tmp_path: Path) -> None:
    """start_session in a manual linked worktree records the main-repo root, not the worktree root."""
    main = tmp_path / "main"
    worktree = tmp_path / "feature-wt"
    _init_git_repo(main)
    _add_linked_worktree(main, worktree, branch="feature")
    _enable_forge(main)
    _enable_forge(worktree)

    expected_root = str(get_main_repo_root(main))

    manager = SessionManager()
    manager.start_session(name="main-sess", worktree_path=str(main))
    manager.start_session(name="wt-sess", worktree_path=str(worktree))

    index = IndexStore()
    main_entry = index.get_session("main-sess")
    wt_entry = index.get_session("wt-sess")

    # The fix: the worktree session anchors to the shared repo root, so it matches
    # the main-checkout session. Pre-fix it was str(worktree.resolve()).
    assert wt_entry.project_root == expected_root
    assert main_entry.project_root == expected_root
    assert wt_entry.project_root != str(worktree.resolve())


def test_manual_worktree_sessions_group_under_workspace_scope(tmp_path: Path) -> None:
    """`session list --scope workspace` from the worktree shows both sibling-worktree sessions."""
    main = tmp_path / "main"
    worktree = tmp_path / "feature-wt"
    _init_git_repo(main)
    _add_linked_worktree(main, worktree, branch="feature")
    _enable_forge(main)
    _enable_forge(worktree)

    manager = SessionManager()
    manager.start_session(name="main-sess", worktree_path=str(main))
    manager.start_session(name="wt-sess", worktree_path=str(worktree))

    # Query from the worktree; ExecutionContext derives the workspace anchor the same
    # way start_session does (get_main_repo_root), so the grouping is end-to-end.
    ctx = ExecutionContext.from_cwd(cwd=worktree)
    result = list_sessions(ctx=ctx, include_incognito=True, scope="workspace")

    assert {s.name for s in result.sessions} == {"main-sess", "wt-sess"}

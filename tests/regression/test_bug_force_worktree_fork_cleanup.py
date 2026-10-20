"""Force-fork replacement must authorize cleanup before removing the old checkout."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from forge.session import deletion
from forge.session.cleanup_state import cleanup_state_path
from forge.session.exceptions import (
    BranchExistsError,
    BranchNotMergedError,
    ForgeSessionError,
    WorktreePathExistsError,
)
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.models import Derivation, SessionState, create_session_state
from forge.session.store import SessionStore
from forge.session.worktree import create_worktree
from tests.fixtures.session_state import delete_published_session, publish_session

pytestmark = pytest.mark.regression


@dataclass
class ForkFixture:
    manager: SessionManager
    repo: Path
    root: Path
    state: SessionState
    content: Path
    token: str | None


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def stale_fork(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ForkFixture:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.test")
    (repo / "README.md").write_text("initial\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "initial")
    (repo / ".forge").mkdir()
    monkeypatch.chdir(repo)
    manager = SessionManager(index_store=IndexStore())
    manager.start_session("parent", worktree_path=str(repo), direct=True)
    _, state = manager.fork_session("parent", "child", create_worktree=True)
    assert state.worktree is not None
    root = Path(state.worktree.path)
    content = root / ".forge/artifacts/child/old.md"
    content.parent.mkdir(parents=True)
    content.write_text("original content\n")
    token = manager.index_store.get_session("child", str(root)).instance_id
    assert token is not None
    return ForkFixture(manager, repo, root, SessionStore(str(root), "child").read(), content, token)


def test_force_worktree_fork_removes_original_content_before_recreation(
    stale_fork: ForkFixture,
) -> None:
    case = stale_fork
    _, replacement = case.manager.fork_session("parent", "child", create_worktree=True, force=True)

    assert replacement.worktree is not None
    assert replacement.worktree.path == str(case.root)
    assert case.root.is_dir()
    assert not case.content.exists()
    assert case.manager.index_store.get_session("child", str(case.root)).instance_id != case.token
    persisted = SessionStore(str(case.root), "child").read()
    assert persisted.confirmed == replacement.confirmed
    assert persisted.worktree == replacement.worktree
    assert not cleanup_state_path(case.root, "child").exists()
    assert _git(case.root, "rev-parse", "HEAD") == _git(case.repo, "rev-parse", "HEAD")


@pytest.mark.parametrize("blocker", ["dependent", "co-resident", "unmerged", "explicit-branch"])
def test_force_worktree_fork_refuses_before_content_or_git_removal(
    stale_fork: ForkFixture, tmp_path: Path, blocker: str
) -> None:
    case = stale_fork
    error: type[Exception] = ForgeSessionError
    match = "depend" if blocker == "dependent" else "shared"
    branch = None
    if blocker == "dependent":
        borrower_root = tmp_path / "borrower"
        borrower_root.mkdir()
        borrower = create_session_state("borrower", worktree_path=str(borrower_root), parent_session="child")
        borrower.forge_root = str(borrower_root)
        borrower.confirmed.derivation = Derivation(parent_session="child", parent_forge_root=str(case.root))
        publish_session(case.manager.index_store, borrower, borrower_root, forge_root=borrower_root)
    elif blocker == "co-resident":
        case.manager.start_session("guest", worktree_path=str(case.root), direct=True)
    elif blocker == "unmerged":
        (case.root / "README.md").write_text("child commit\n")
        _git(case.root, "add", "README.md")
        _git(case.root, "commit", "-qm", "child work")
        error, match = BranchNotMergedError, "not fully merged"
    else:
        branch = "child"
        error, match = BranchExistsError, "already exists"
    manifest = SessionStore(str(case.root), "child").manifest_path.read_bytes()
    identity = case.root.stat().st_ino
    head = _git(case.root, "rev-parse", "HEAD")

    with pytest.raises(error, match=match):
        case.manager.fork_session("parent", "child", create_worktree=True, force=True, branch=branch)

    assert case.root.stat().st_ino == identity
    assert _git(case.root, "rev-parse", "HEAD") == head
    assert case.content.read_text() == "original content\n"
    assert SessionStore(str(case.root), "child").manifest_path.read_bytes() == manifest
    assert case.manager.index_store.get_session("child", str(case.root)).instance_id == case.token
    assert not cleanup_state_path(case.root, "child").exists()


def test_force_worktree_fork_retains_new_instance_before_cleanup_planning(
    stale_fork: ForkFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = stale_fork
    plan_deletion = deletion.plan_session_deletion
    replacement_token: list[str | None] = []

    def replace_before_plan(index: IndexStore, name: str, **kwargs: object) -> deletion.SessionDeletionPlan:
        assert delete_published_session(index, name, case.root)
        replacement = publish_session(index, case.state, case.repo, forge_root=case.root, checkout_root=case.root)
        replacement_token.append(replacement.instance_id)
        return plan_deletion(index, name, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(deletion, "plan_session_deletion", replace_before_plan)
    with pytest.raises(ForgeSessionError, match="changed before replacement"):
        case.manager.fork_session("parent", "child", create_worktree=True, force=True)

    assert replacement_token and replacement_token[0] != case.token
    assert case.manager.index_store.get_session("child", str(case.root)).instance_id == replacement_token[0]
    assert case.content.read_text() == "original content\n"
    assert SessionStore(str(case.root), "child").read() == case.state
    assert not cleanup_state_path(case.root, "child").exists()


def test_force_worktree_fork_preserves_branch_advanced_during_cleanup_planning(
    stale_fork: ForkFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = stale_fork
    plan_deletion = deletion.plan_session_deletion
    head: list[str] = []

    def advance_before_plan(index: IndexStore, name: str, **kwargs: object) -> deletion.SessionDeletionPlan:
        (case.root / "README.md").write_text("concurrent child commit\n")
        _git(case.root, "add", "README.md")
        _git(case.root, "commit", "-qm", "concurrent child work")
        head.append(_git(case.root, "rev-parse", "HEAD"))
        return plan_deletion(index, name, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(deletion, "plan_session_deletion", advance_before_plan)
    with pytest.raises(BranchNotMergedError):
        case.manager.fork_session("parent", "child", create_worktree=True, force=True)

    assert head and _git(case.root, "rev-parse", "HEAD") == head[0]
    assert case.content.read_text() == "original content\n"
    assert case.manager.index_store.get_session("child", str(case.root)).instance_id == case.token
    assert not cleanup_state_path(case.root, "child").exists()


def test_force_worktree_fork_preserves_checkout_published_after_cleanup(
    stale_fork: ForkFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = stale_fork
    apply_deletion = deletion.apply_session_deletion
    replacement_token: list[str | None] = []
    winner_content = case.content.with_name("winner.md")

    def replace_after_cleanup(index: IndexStore, plan: deletion.SessionDeletionPlan) -> tuple[str, ...]:
        result = apply_deletion(index, plan)
        create_worktree("child", cwd=case.repo)
        replacement = publish_session(index, case.state, case.repo, forge_root=case.root, checkout_root=case.root)
        replacement_token.append(replacement.instance_id)
        winner_content.parent.mkdir(parents=True)
        winner_content.write_text("winner\n")
        return result

    monkeypatch.setattr(deletion, "apply_session_deletion", replace_after_cleanup)
    with pytest.raises(WorktreePathExistsError):
        case.manager.fork_session("parent", "child", create_worktree=True, force=True)

    assert replacement_token and replacement_token[0] != case.token
    assert case.manager.index_store.get_session("child", str(case.root)).instance_id == replacement_token[0]
    assert winner_content.read_text() == "winner\n"
    assert SessionStore(str(case.root), "child").read() == case.state
    assert _git(case.root, "branch", "--show-current") == "child"

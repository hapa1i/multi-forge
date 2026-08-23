"""Artifact-authority journal lifetime follows its containing Forge root."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import forge.session.worktree as worktree_pkg
from forge.core.models.direct_model import resolve_direct_model_pin
from forge.core.ops.session_routing import build_claude_routing_payload
from forge.core.reactive.env import new_root_run_identity
from forge.session import IndexStore, SessionManager, SessionStore
from forge.session.authority import read_authority_events
from forge.session.cleanup import clean_old_sessions
from forge.session.models import AuthorityIntent
from forge.session.routing import append_routing_event, new_routing_event


def _init_project(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    (path / ".forge").mkdir()
    (path / ".claude").mkdir()


def _start_marked(
    manager: SessionManager,
    root: Path,
    name: str,
    *,
    incognito: bool = False,
) -> tuple[Path, Path]:
    manager.start_session(
        name,
        worktree_path=str(root),
        is_incognito=incognito,
        authority=AuthorityIntent("producer"),
        authority_explicit=True,
    )
    events = read_authority_events(str(root), name)
    assert [event.event_type for event in events] == ["authority_configured"]
    store = SessionStore(str(root), name)
    state = store.read()
    routing = new_routing_event(
        state,
        event_type="launch_routing_committed",
        run_id=new_root_run_identity().run_id,
        operation="start",
        payload=build_claude_routing_payload(
            state,
            effective_template=None,
            runtime_base_url=None,
            proxy_id=None,
            applied_direct_model=resolve_direct_model_pin("claude-opus-5"),
        ),
    )
    routing_journal = append_routing_event(root, routing)
    authority_journal = root / ".forge" / "artifacts" / name / "authority" / "events.jsonl"
    return authority_journal, routing_journal


@pytest.mark.parametrize("delete_transcripts", [False, True])
def test_delete_preserves_authority_journal_when_forge_root_remains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    delete_transcripts: bool,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    _init_project(project)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    monkeypatch.chdir(project)

    manager = SessionManager(index_store=IndexStore())
    authority_journal, routing_journal = _start_marked(manager, project, "retained")

    manager.delete_session(
        "retained",
        delete_transcripts=delete_transcripts,
        delete_worktree=False,
        force=True,
    )

    assert authority_journal.is_file()
    assert routing_journal.is_file()
    assert not SessionStore(str(project), "retained").exists()


@pytest.mark.parametrize("delete_transcripts", [False, True])
def test_age_cleanup_preserves_authority_journal_with_transcript_setting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    delete_transcripts: bool,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    _init_project(project)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    monkeypatch.chdir(project)

    manager = SessionManager(index_store=IndexStore())
    authority_journal, routing_journal = _start_marked(manager, project, "old-marked")
    manager.index_store.update_session(
        "old-marked",
        last_accessed_at="2000-01-01T00:00:00Z",
        forge_root=str(project),
    )

    result = clean_old_sessions(
        1,
        delete_transcripts=delete_transcripts,
        delete_worktree=False,
        force=True,
    )

    assert result.deleted == ["old-marked"]
    assert authority_journal.is_file()
    assert routing_journal.is_file()


def test_incognito_cleanup_preserves_journal_when_forge_root_remains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    _init_project(project)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    monkeypatch.chdir(project)

    manager = SessionManager(index_store=IndexStore())
    authority_journal, routing_journal = _start_marked(manager, project, "private", incognito=True)
    manager.delete_session("private", delete_transcripts=True, delete_worktree=False, force=True)

    assert authority_journal.is_file()
    assert routing_journal.is_file()


def test_root_level_worktree_delete_preserves_parent_root_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    checkout = tmp_path / "worktrees" / "producer"
    home.mkdir()
    _init_project(project)
    checkout.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    monkeypatch.chdir(project)

    manager = SessionManager(index_store=IndexStore())
    authority_journal, routing_journal = _start_marked(manager, project, "producer")
    store = SessionStore(str(project), "producer")

    def mark_owned_worktree(state) -> None:
        assert state.worktree is not None
        state.worktree.path = str(checkout)
        state.worktree.is_worktree = True
        state.worktree.owns_worktree = True
        state.worktree.branch = "producer"

    store.update(timeout_s=5.0, mutate=mark_owned_worktree)
    monkeypatch.setattr(
        SessionManager,
        "_find_co_resident_sessions",
        lambda self, worktree_path, exclude: [],
    )

    def remove_checkout(**kwargs):
        shutil.rmtree(kwargs["worktree_path"])
        return worktree_pkg.CleanupResult()

    monkeypatch.setattr(worktree_pkg, "cleanup_worktree", remove_checkout)
    manager.delete_session("producer", delete_worktree=True, force=True)

    assert not checkout.exists()
    assert authority_journal.is_file()
    assert routing_journal.is_file()


def test_owning_worktree_delete_removes_journal_with_nested_forge_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    checkout = tmp_path / "worktrees" / "producer"
    nested_root = checkout / "packages" / "app"
    home.mkdir()
    checkout.mkdir(parents=True)
    _init_project(nested_root)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    monkeypatch.chdir(nested_root)

    manager = SessionManager(index_store=IndexStore())
    authority_journal, routing_journal = _start_marked(manager, nested_root, "nested-producer")
    store = SessionStore(str(nested_root), "nested-producer")

    def mark_owned_worktree(state) -> None:
        assert state.worktree is not None
        state.worktree.path = str(checkout)
        state.worktree.is_worktree = True
        state.worktree.owns_worktree = True
        state.worktree.branch = "producer"

    store.update(timeout_s=5.0, mutate=mark_owned_worktree)
    monkeypatch.setattr(
        SessionManager,
        "_find_co_resident_sessions",
        lambda self, worktree_path, exclude: [],
    )

    def remove_checkout(**kwargs):
        shutil.rmtree(kwargs["worktree_path"])
        return worktree_pkg.CleanupResult()

    monkeypatch.setattr(worktree_pkg, "cleanup_worktree", remove_checkout)
    manager.delete_session("nested-producer", delete_worktree=True, force=True)

    assert not checkout.exists()
    assert not authority_journal.exists()
    assert not routing_journal.exists()

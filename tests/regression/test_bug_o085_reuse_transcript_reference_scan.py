"""Regression coverage for transcript ownership scans during native-relocate deletion."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Callable

import pytest

from forge.session import (
    IndexStore,
    SessionIndexEntry,
    SessionManager,
    SessionStore,
    create_session_state,
)
from forge.session.claude import cleanup as cleanup_module
from forge.session.claude.paths import get_transcript_path
from forge.session.models import Derivation
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression

CHILD_ID = "11111111-1111-1111-1111-111111111111"
ARTIFACT_ID = "22222222-2222-2222-2222-222222222222"
RELOCATED_PARENT_ID = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_HOME", str(home / ".claude"))

    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".git").mkdir()
    (project_root / ".forge").mkdir()
    monkeypatch.chdir(project_root)
    return project_root


def _publish(
    manager: SessionManager,
    project: Path,
    name: str,
    *,
    session_id: str | None,
    artifact_ids: tuple[str, ...] = (),
    relocated_parent_id: str | None = None,
) -> None:
    state = create_session_state(
        name,
        parent_session="parent" if relocated_parent_id else None,
        is_fork=relocated_parent_id is not None,
        worktree_path=str(project),
        worktree_branch="main",
    )
    state.forge_root = str(project)
    state.confirmed.claude_project_root = str(project)
    state.confirmed.claude_session_id = session_id
    if artifact_ids:
        state.confirmed.artifacts["transcripts"] = [
            {"session_id": artifact_id, "copied_path": f"artifact-{artifact_id}.jsonl"} for artifact_id in artifact_ids
        ]
    if relocated_parent_id:
        state.confirmed.derivation = Derivation(
            parent_session="parent",
            resume_mode="native-relocate",
            relocated_parent_session_id=relocated_parent_id,
        )
    publish_session(
        manager.index_store,
        state,
        project,
        checkout_root=project,
        forge_root=project,
        relative_path=".",
    )


def _write_transcript(project: Path, session_id: str) -> Path:
    path = get_transcript_path(str(project), session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{session_id}\n", encoding="utf-8")
    return path


def _spy_reference_scans(
    manager: SessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, tuple[str, ...]]]:
    calls: list[tuple[str, tuple[str, ...]]] = []
    original = manager._find_shared_transcript_sessions

    def _record(
        project_root: str,
        session_ids: list[str],
        *,
        exclude_name: str,
        exclude_forge_root: str,
        sessions: Iterable[tuple[str, SessionIndexEntry]] | None = None,
    ) -> dict[str, list[str]]:
        calls.append((project_root, tuple(session_ids)))
        return original(
            project_root,
            session_ids,
            exclude_name=exclude_name,
            exclude_forge_root=exclude_forge_root,
            sessions=sessions,
        )

    monkeypatch.setattr(manager, "_find_shared_transcript_sessions", _record)
    return calls


def test_native_relocate_delete_scans_all_candidate_ids_once(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SessionManager(index_store=IndexStore())
    _publish(
        manager,
        project,
        "child",
        session_id=CHILD_ID,
        artifact_ids=(ARTIFACT_ID,),
        relocated_parent_id=RELOCATED_PARENT_ID,
    )
    _publish(manager, project, "child-owner", session_id=CHILD_ID)
    _publish(manager, project, "artifact-owner", session_id=ARTIFACT_ID)
    _publish(manager, project, "parent", session_id=RELOCATED_PARENT_ID)
    transcripts = [
        _write_transcript(project, CHILD_ID),
        _write_transcript(project, ARTIFACT_ID),
        _write_transcript(project, RELOCATED_PARENT_ID),
    ]

    scan_calls = _spy_reference_scans(manager, monkeypatch)
    manifest_reads: Counter[str] = Counter()
    original_read: Callable[[SessionStore], object] = SessionStore.read

    def _count_read(store: SessionStore) -> object:
        manifest_reads[store.session_name] += 1
        return original_read(store)

    monkeypatch.setattr(SessionStore, "read", _count_read)

    manager.delete_session("child", forge_root=str(project), delete_worktree=False, force=True)

    assert scan_calls == [(str(project), (CHILD_ID, ARTIFACT_ID, RELOCATED_PARENT_ID))]
    assert manifest_reads == Counter({"child": 1, "child-owner": 1, "artifact-owner": 1, "parent": 1})
    assert all(path.exists() for path in transcripts)


def test_native_relocate_partial_launch_still_runs_one_guarded_scan(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SessionManager(index_store=IndexStore())
    _publish(
        manager,
        project,
        "child",
        session_id=None,
        relocated_parent_id=RELOCATED_PARENT_ID,
    )
    relocated = _write_transcript(project, RELOCATED_PARENT_ID)
    scan_calls = _spy_reference_scans(manager, monkeypatch)

    manager.delete_session("child", forge_root=str(project), delete_worktree=False, force=True)

    assert scan_calls == [(str(project), (RELOCATED_PARENT_ID,))]
    assert not relocated.exists()


def test_relocated_transcript_rechecks_ownership_after_ordinary_cleanup(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sibling published during ordinary cleanup must protect the relocated transcript."""
    manager = SessionManager(index_store=IndexStore())
    _publish(
        manager,
        project,
        "child",
        session_id=CHILD_ID,
        relocated_parent_id=RELOCATED_PARENT_ID,
    )
    relocated = _write_transcript(project, RELOCATED_PARENT_ID)

    def _publish_sibling(**_kwargs: object) -> None:
        _publish(
            manager,
            project,
            "late-sibling",
            session_id=None,
            relocated_parent_id=RELOCATED_PARENT_ID,
        )

    monkeypatch.setattr(cleanup_module, "cleanup_session", _publish_sibling)

    manager.delete_session("child", forge_root=str(project), delete_worktree=False, force=True)

    assert SessionStore(str(project), "late-sibling").exists()
    assert relocated.exists(), "the sibling published during cleanup still owns the relocated transcript"

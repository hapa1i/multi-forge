"""Regression: deleting one session must not remove another session's transcript.

Bug:
- Same-directory native forks launch with ``--resume <parent> --fork-session``.
- Claude may keep reporting the parent's UUID until the fork receives a real
  turn. If the fork is stopped before divergence, both manifests can reference
  the same raw Claude transcript.
- ``forge session delete <fork>`` used to unlink that UUID unconditionally,
  destroying the parent conversation.

Fix:
- Session deletion treats raw Claude transcripts like worktrees: a UUID is
  unlinked only if no other indexed session still references that transcript.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.session import IndexStore, SessionManager, SessionStore, create_session_state
from forge.session.claude.paths import get_transcript_path
from forge.session.models import Derivation, session_state_to_dict

pytestmark = pytest.mark.regression

SHARED_ID = "11111111-1111-1111-1111-111111111111"
CHILD_ID = "22222222-2222-2222-2222-222222222222"
ROLLOVER_ID = "33333333-3333-3333-3333-333333333333"


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


def _write_session(
    manager: SessionManager,
    project: Path,
    name: str,
    *,
    session_id: str,
    artifact_ids: list[str] | None = None,
    claude_project_root: Path | None = None,
    derivation_parent_transcript: str | None = None,
    parent: str | None = None,
    worktree_path: Path | None = None,
) -> None:
    launch_root = claude_project_root or project
    checkout_root = worktree_path or project
    state = create_session_state(
        name,
        parent_session=parent,
        is_fork=parent is not None,
        worktree_path=str(checkout_root),
        worktree_branch="main",
    )
    state.forge_root = str(project)
    state.confirmed.claude_project_root = str(launch_root)
    state.confirmed.claude_session_id = session_id
    state.confirmed.transcript_path = str(get_transcript_path(str(launch_root), session_id))
    if artifact_ids:
        state.confirmed.artifacts["transcripts"] = [
            {
                "session_id": artifact_id,
                "copied_path": f".forge/artifacts/{name}/transcripts/{artifact_id}.jsonl",
            }
            for artifact_id in artifact_ids
        ]
    if derivation_parent_transcript:
        state.confirmed.derivation = Derivation(
            parent_session=parent or "",
            parent_transcript=derivation_parent_transcript,
        )

    SessionStore(str(project), name).write(state)
    manager.index_store.add_from_state(
        state,
        str(project),
        checkout_root=str(checkout_root),
        forge_root=str(project),
        relative_path=".",
    )


def _write_raw_transcript(project: Path, session_id: str) -> Path:
    transcript_path = get_transcript_path(str(project), session_id)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text("{}\n", encoding="utf-8")
    return transcript_path


def test_delete_same_dir_fork_preserves_parent_transcript(project: Path) -> None:
    """Deleting a fork aliasing the parent's UUID must not unlink the parent transcript."""
    manager = SessionManager(index_store=IndexStore())
    _write_session(manager, project, "planner", session_id=SHARED_ID)
    _write_session(manager, project, "executor", session_id=SHARED_ID, parent="planner")
    shared_transcript = _write_raw_transcript(project, SHARED_ID)

    manager.delete_session("executor", force=True, forge_root=str(project))

    assert shared_transcript.exists()
    assert SessionStore(str(project), "planner").exists() is True
    assert SessionStore(str(project), "executor").exists() is False
    assert manager.session_exists("executor", forge_root=str(project)) is False


def test_delete_filters_shared_transcript_ids_but_removes_unshared_ids(
    project: Path,
) -> None:
    """Shared artifact UUIDs survive while the deleted session's private UUIDs are removed."""
    manager = SessionManager(index_store=IndexStore())
    _write_session(
        manager,
        project,
        "planner",
        session_id=SHARED_ID,
        artifact_ids=[SHARED_ID],
    )
    _write_session(
        manager,
        project,
        "executor",
        session_id=CHILD_ID,
        artifact_ids=[SHARED_ID, CHILD_ID, ROLLOVER_ID],
        parent="planner",
    )
    shared_transcript = _write_raw_transcript(project, SHARED_ID)
    child_transcript = _write_raw_transcript(project, CHILD_ID)
    rollover_transcript = _write_raw_transcript(project, ROLLOVER_ID)

    manager.delete_session("executor", force=True, forge_root=str(project))

    assert shared_transcript.exists()
    assert not child_transcript.exists()
    assert not rollover_transcript.exists()


def test_delete_uses_confirmed_claude_project_root_for_raw_cleanup(
    project: Path,
) -> None:
    """Cleanup removes the launch-root transcript, not the manifest-root path."""
    manager = SessionManager(index_store=IndexStore())
    launch_root = project.parent / "executor-checkout"
    launch_root.mkdir()
    _write_session(
        manager,
        project,
        "executor",
        session_id=CHILD_ID,
        claude_project_root=launch_root,
        worktree_path=launch_root,
    )
    launch_transcript = _write_raw_transcript(launch_root, CHILD_ID)
    forge_root_decoy = _write_raw_transcript(project, CHILD_ID)

    manager.delete_session("executor", force=True, forge_root=str(project))

    assert not launch_transcript.exists()
    assert forge_root_decoy.exists()


def test_force_delete_corrupt_manifest_uses_raw_confirmed_claude_project_root(project: Path) -> None:
    """Raw-manifest force delete must still clean the persisted launch-root transcript."""
    manager = SessionManager(index_store=IndexStore())
    launch_root = project.parent / "executor-checkout"
    launch_root.mkdir()
    _write_session(
        manager,
        project,
        "executor",
        session_id=CHILD_ID,
        claude_project_root=launch_root,
        worktree_path=launch_root,
    )
    store = SessionStore(str(project), "executor")
    raw = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    raw["unknown_top_level"] = True
    store.manifest_path.write_text(json.dumps(raw), encoding="utf-8")

    launch_transcript = _write_raw_transcript(launch_root, CHILD_ID)
    forge_root_decoy = _write_raw_transcript(project, CHILD_ID)

    manager.delete_session("executor", force=True, forge_root=str(project))

    assert not launch_transcript.exists()
    assert forge_root_decoy.exists()


def test_same_uuid_in_different_claude_project_root_does_not_block_cleanup(
    project: Path,
) -> None:
    """The guard compares transcript paths, not UUIDs alone, across projects."""
    other_project = project.parent / "other-project"
    other_project.mkdir()
    (other_project / ".git").mkdir()
    (other_project / ".forge").mkdir()

    manager = SessionManager(index_store=IndexStore())
    _write_session(manager, project, "planner", session_id=SHARED_ID)
    _write_session(manager, other_project, "executor", session_id=SHARED_ID)
    doomed_transcript = _write_raw_transcript(project, SHARED_ID)
    other_transcript = _write_raw_transcript(other_project, SHARED_ID)

    manager.delete_session("planner", force=True, forge_root=str(project))

    assert not doomed_transcript.exists()
    assert other_transcript.exists()


def test_delete_preserves_uuid_referenced_by_sibling_derivation(project: Path) -> None:
    """Derivation transcript pointers also protect shared raw transcript UUIDs."""
    manager = SessionManager(index_store=IndexStore())
    _write_session(manager, project, "planner", session_id=SHARED_ID)
    _write_session(
        manager,
        project,
        "executor",
        session_id=CHILD_ID,
        parent="planner",
        derivation_parent_transcript=f".forge/artifacts/planner/transcripts/{SHARED_ID}.jsonl",
    )
    shared_transcript = _write_raw_transcript(project, SHARED_ID)

    manager.delete_session("planner", force=True, forge_root=str(project))

    assert shared_transcript.exists()


def test_delete_preserves_uuid_referenced_by_corrupt_sibling_raw_manifest(
    project: Path,
) -> None:
    """Raw manifest fallback protects shared transcripts even when strict read fails."""
    manager = SessionManager(index_store=IndexStore())
    _write_session(manager, project, "planner", session_id=SHARED_ID)

    sibling = create_session_state(
        "executor",
        worktree_path=str(project),
        worktree_branch="main",
    )
    sibling.forge_root = str(project)
    sibling.confirmed.claude_project_root = str(project)
    sibling.confirmed.claude_session_id = SHARED_ID
    sibling.confirmed.transcript_path = str(get_transcript_path(str(project), SHARED_ID))
    sibling_store = SessionStore(str(project), "executor")
    sibling_store.session_dir.mkdir(parents=True, exist_ok=True)
    sibling_data = session_state_to_dict(sibling)
    sibling_data["unknown_top_level"] = True
    sibling_store.manifest_path.write_text(json.dumps(sibling_data), encoding="utf-8")
    manager.index_store.add_from_state(
        sibling,
        str(project),
        checkout_root=str(project),
        forge_root=str(project),
        relative_path=".",
    )
    shared_transcript = _write_raw_transcript(project, SHARED_ID)

    manager.delete_session("planner", force=True, forge_root=str(project))

    assert shared_transcript.exists()

"""Queued and derived writes must not resurrect a deleted session generation."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.workqueue import Marker, enqueue_index_marker, process_pending_work
from forge.session.index import IndexStore
from forge.session.workers import capture_session_instance, find_active_session_workers
from tests.fixtures.session_state import (
    delete_published_session,
    publish_session_from_fields,
)

pytestmark = pytest.mark.regression


def test_queued_job_does_not_attach_to_same_name_replacement(tmp_path: Path) -> None:
    index = IndexStore()
    publish_session_from_fields(index, "worker", tmp_path, tmp_path)
    marker = enqueue_index_marker(
        session_id="original",
        session_name="worker",
        worktree_path=tmp_path,
        transcript_snapshot_rel=".forge/artifacts/worker/transcripts/original.jsonl",
    )
    assert marker is not None
    original_bytes = marker.read_bytes()
    delete_published_session(index, "worker", tmp_path)
    publish_session_from_fields(index, "worker", tmp_path, tmp_path)
    writes: list[str] = []

    result = process_pending_work(handlers={"index": lambda _marker: writes.append("indexed")})

    assert writes == []
    assert result.skipped == 1
    assert marker.read_bytes() == original_bytes


def test_queue_handler_holds_an_instance_lease_through_persistence(tmp_path: Path) -> None:
    index = IndexStore()
    publish_session_from_fields(index, "worker", tmp_path, tmp_path)
    token = capture_session_instance(tmp_path, "worker")
    marker = enqueue_index_marker(
        session_id="original",
        session_name="worker",
        worktree_path=tmp_path,
        transcript_snapshot_rel=".forge/artifacts/worker/transcripts/original.jsonl",
    )
    assert marker is not None
    leases: list[str] = []

    def persist(marker: Marker) -> None:
        leases.extend(find_active_session_workers(tmp_path, "worker", token))

    result = process_pending_work(handlers={"index": persist})

    assert result.processed == 1
    assert len(leases) == 1 and "queued index" in leases[0]
    assert not marker.exists()
    assert find_active_session_workers(tmp_path, "worker", token) == ()


def test_search_rebuild_does_not_recreate_a_removed_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    transcript = project / ".forge/artifacts/worker/transcripts/original.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"message":{"role":"user","content":"remember this"}}\n')
    monkeypatch.chdir(project)
    original = IndexStore.run_session_entries_txn

    def remove_before_publication(self, callback):
        shutil.rmtree(project)
        return original(self, callback)

    monkeypatch.setattr(IndexStore, "run_session_entries_txn", remove_before_publication)
    result = CliRunner().invoke(main, ["search", "rebuild-index"])

    assert result.exit_code == 1
    assert "not published" in result.output
    assert not project.exists()


@pytest.mark.parametrize("operation", ["regenerate", "codex"])
def test_transfer_worker_excludes_cleanup_until_cache_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    from forge.core.ops import codex_bridge, transfer
    from forge.core.ops.context import ExecutionContext
    from forge.session import ForgeSessionError, SessionManager
    from forge.session.prev_sessions import generated_path

    publish_session_from_fields(IndexStore(), "planner", tmp_path, tmp_path)
    ctx = ExecutionContext(cwd=tmp_path, project_root=tmp_path, worktree_root=tmp_path, forge_root=tmp_path)
    module = transfer if operation == "regenerate" else codex_bridge
    original = module.assemble_transfer_context
    attempts = []

    def write_after_provider(**kwargs):
        with pytest.raises(ForgeSessionError, match="[Ww]orker|lease"):
            SessionManager().delete_session("planner", forge_root=str(tmp_path), force=True)
        attempts.append("refused")
        return original(**kwargs)

    monkeypatch.setattr(module, "assemble_transfer_context", write_after_provider)
    if operation == "regenerate":
        transfer.regenerate_transfer(ctx=ctx, parent="planner", strategy="minimal")
    else:
        codex_bridge.assemble_codex_transfer(ctx=ctx, parent="planner", child="exec", strategy="minimal")

    assert attempts == ["refused"]
    assert generated_path(tmp_path, "planner").is_file()
    token = capture_session_instance(tmp_path, "planner")
    assert find_active_session_workers(tmp_path, "planner", token) == ()


def test_notes_editor_protects_both_parent_and_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    from forge.session import ForgeSessionError, SessionManager
    from forge.session.prev_sessions import child_path

    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    for name in ("planner", "exec"):
        publish_session_from_fields(IndexStore(), name, project, project)
    snapshot = child_path(project, "planner", "exec")
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("frozen context")
    attempts = []

    def editor(path, **kwargs):
        for name in ("planner", "exec"):
            with pytest.raises(ForgeSessionError, match="[Ww]orker|lease"):
                SessionManager().delete_session(name, forge_root=str(project), force=True)
            attempts.append(name)
        path.write_text("user notes")

    monkeypatch.chdir(project)
    monkeypatch.setattr(importlib.import_module("forge.cli.transfer"), "open_in_editor", editor)
    result = CliRunner().invoke(main, ["session", "transfer", "edit", "planner", "--child", "exec"])

    assert result.exit_code == 0, result.output
    assert attempts == ["planner", "exec"]
    assert snapshot.with_suffix(".notes.md").read_text() == "user notes"


def test_stale_codex_rollback_preserves_replacement_and_snapshot(tmp_path: Path) -> None:
    from forge.core.ops.codex_session import _rollback_created_session
    from forge.session import SessionManager, SessionStore
    from forge.session.prev_sessions import child_path

    index = IndexStore()
    publish_session_from_fields(index, "worker", tmp_path, tmp_path, parent_session="planner")
    old_token = capture_session_instance(tmp_path, "worker")
    delete_published_session(index, "worker", tmp_path)
    publish_session_from_fields(index, "worker", tmp_path, tmp_path, parent_session="planner")
    snapshot = child_path(tmp_path, "planner", "worker")
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("replacement context")
    store = SessionStore(str(tmp_path), "worker")
    before = store.manifest_path.read_bytes()

    _rollback_created_session(
        SessionManager(),
        "worker",
        forge_root=str(tmp_path),
        snapshot=snapshot,
        delete_branch=False,
        expected_instance_id=old_token,
    )

    assert store.manifest_path.read_bytes() == before
    assert snapshot.read_text() == "replacement context"

"""Session index contention and large delete inventories must produce usable CLI output."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.hooks import hooks
from forge.cli.main import main
from forge.core.paths import get_forge_home
from forge.core.state import file_lock_for_target
from forge.core.workqueue import PROCESSOR_LOCK_TIMEOUT_S, enqueue_stop_marker
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.active import ActiveSessionStore
from forge.session.cleanup_state import cleanup_state_path
from forge.session.workers import capture_session_instance, session_worker_lease
from tests.fixtures.session_state import (
    delete_published_session,
    publish_session_from_fields,
    seed_row_only_session,
)

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("options", [[], ["--json"], ["--json", "--older-than", "1"]])
def test_list_in_another_project_shows_snapshot_and_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, options: list[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    index = IndexStore()
    publish_session_from_fields(index, "example", tmp_path, tmp_path)
    index.update_session("example", "2020-01-01T00:00:00Z", forge_root=str(tmp_path))
    ActiveSessionStore().upsert_session("example", worktree_path=str(tmp_path), launch_mode="host")
    other = tmp_path / "other"
    publish_session_from_fields(index, "other-session", other, other)
    # Simulate a creator's provisional row. A contended listing must neither show nor prune it.
    seed_row_only_session(index, create_session_state("unpublished", worktree_path=str(tmp_path)), tmp_path)
    runner = CliRunner()
    other_entry = index.get_session("other-session", str(other))
    assert other_entry.instance_id is not None
    before = index.index_path.read_bytes()

    def list_during_other_delete() -> None:
        busy = runner.invoke(main, ["sess", "list", *options], catch_exceptions=False)
        assert busy.exit_code == 0, busy.output
        assert busy.stderr.lower().count("snapshot") == 1 and "busy" in busy.stderr.lower()
        if "--json" in options:
            rows = json.loads(busy.stdout)
            assert [(row["name"], row["launchability"]) for row in rows] == [("example", "launchable")]
            assert rows[0]["is_active"]
        else:
            assert "example" in busy.stdout and "snapshot" not in busy.stdout
        assert "unpublished" not in busy.stdout and "other-session" not in busy.stdout
        assert index.index_path.read_bytes() == before
        SessionStore(str(other), "other-session").delete_locked()

    assert index.delete_session_txn(
        "other-session",
        str(other),
        expected_instance_id=other_entry.instance_id,
        delete_manifest=list_during_other_delete,
    )
    listing = runner.invoke(main, ["sess", "list", "--json"])
    assert listing.exit_code == 0, listing.output
    assert listing.stderr == ""
    assert [item["name"] for item in json.loads(listing.stdout)] == ["example"]
    assert len(index.read().sessions) == 1


def test_snapshot_skips_unverified_rows_until_an_uncontended_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    index = IndexStore()
    publish_session_from_fields(index, "legacy", tmp_path, tmp_path)
    # Persist the older, unstamped ownership representation of a complete session.
    original = index.read()
    next(iter(original.sessions.values())).instance_id = None
    index.write(original)
    before = index.index_path.read_bytes()
    with file_lock_for_target(target_path=index.index_path, timeout_s=1):
        busy = CliRunner().invoke(main, ["sess", "list", "--json"])
    assert busy.exit_code == 0 and json.loads(busy.stdout) == []
    assert "snapshot may omit new or unverified sessions" in busy.stderr
    assert index.index_path.read_bytes() == before
    after = CliRunner().invoke(main, ["sess", "list", "--json"])
    assert after.exit_code == 0 and after.stderr == ""
    assert [row["name"] for row in json.loads(after.stdout)] == ["legacy"]


def test_snapshot_does_not_show_metadata_from_a_reused_session_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    index = IndexStore()
    for name in ("stable", "reused"):
        publish_session_from_fields(index, name, tmp_path, tmp_path)
    read_listing = IndexStore.list_sessions_for_display

    def replace_after_snapshot(store, **filters):
        with file_lock_for_target(target_path=index.index_path, timeout_s=1):
            snapshot = read_listing(store, **filters)
        assert delete_published_session(index, "reused", tmp_path)
        publish_session_from_fields(index, "reused", tmp_path, tmp_path)
        return snapshot

    monkeypatch.setattr(IndexStore, "list_sessions_for_display", replace_after_snapshot)
    result = CliRunner().invoke(main, ["sess", "list", "--json"])
    assert result.exit_code == 0, result.output
    assert [row["name"] for row in json.loads(result.stdout)] == ["stable"]
    assert "snapshot" in result.stderr


@pytest.mark.parametrize("populated", [False, True])
def test_busy_index_preserves_direct_command_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, populated: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    if populated:
        publish_session_from_fields(IndexStore(), "in-chat", tmp_path, tmp_path)
    with file_lock_for_target(target_path=IndexStore().index_path, timeout_s=1):
        result = CliRunner().invoke(
            hooks, ["user-prompt-submit"], input=json.dumps({"prompt": "%session list", "transcript_path": ""})
        )
    assert result.exit_code == 0, result.output
    decision = json.loads(result.stdout)
    assert decision["decision"] == "block"
    assert ("in-chat" if populated else "No confirmed sessions") in decision["reason"]
    assert "busy" in decision["reason"] and "snapshot" in decision["reason"]
    assert result.stderr == ""


def test_list_with_pending_work_keeps_its_startup_lock_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    index = IndexStore()
    entry = publish_session_from_fields(index, "example", tmp_path, tmp_path)
    marker = enqueue_stop_marker(
        session_id="list-fixture",
        session_name="example",
        worktree_path=tmp_path,
        transcript_snapshot_rel=".forge/artifacts/example/transcripts/copy.jsonl",
        expected_instance_id=entry.instance_id,
    )
    assert marker is not None
    original = marker.read_bytes()
    waits: list[float] = []

    def record_lock_wait(*, target_path: Path, timeout_s: float):
        if target_path == index.index_path:
            waits.append(timeout_s)
        return file_lock_for_target(target_path=target_path, timeout_s=timeout_s)

    runner = CliRunner()
    with file_lock_for_target(target_path=index.index_path, timeout_s=1):
        with monkeypatch.context() as patch:
            patch.setattr("forge.session.index.file_lock_for_target", record_lock_wait)
            busy = runner.invoke(main, ["sess", "list", "--json"])
    assert busy.exit_code == 0 and [row["name"] for row in json.loads(busy.stdout)] == ["example"]
    assert "snapshot" in busy.stderr and marker.read_bytes() == original
    assert waits and max(waits) <= PROCESSOR_LOCK_TIMEOUT_S
    after = runner.invoke(main, ["sess", "list", "--json"])
    assert after.exit_code == 0 and after.stderr == "" and not marker.exists()


def test_bulk_delete_summarizes_inventory_and_preserves_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    index = IndexStore()
    publish_session_from_fields(index, "first", project, project, claude_session_id="fixture-id")
    for name in ("second", "working"):
        publish_session_from_fields(index, name, project, project)
    artifact = project / ".forge/artifacts/first/routine-copy.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("test data")
    notes = project / ".forge/prev_sessions/second/children/old-child.notes.md"
    notes.parent.mkdir(parents=True)
    notes.write_text("user-authored notes")
    retained = get_forge_home() / "manual-testing/qa/runs/other/transcript.jsonl"
    retained.parent.mkdir(parents=True)
    retained.write_text('{"sessionId":"unrelated"}\n')
    owned = retained.parents[1] / "first" / "transcript.jsonl"
    owned.parent.mkdir()
    owned.write_text('{"sessionId":"fixture-id"}\n')
    runner = CliRunner()
    args = ["sess", "delete", "--all"]
    # A selection root may spell the same project differently from its plans.
    alias = tmp_path / "project-alias"
    alias.symlink_to(project, target_is_directory=True)
    monkeypatch.setattr("forge.cli.session_delete._cwd_forge_root", lambda: str(alias))
    token = capture_session_instance(project, "working")
    with session_worker_lease(project, "working", expected_instance_id=token, label="test worker"):
        monkeypatch.setattr("forge.session.workers.is_pid_alive", lambda pid: False)
        preview = runner.invoke(main, args, input="n\n")
        assert preview.exit_code == 1
        assert "first" in preview.stdout and "second" in preview.stdout
        assert "Refused working" in preview.stdout and "test worker" in preview.stdout
        assert "abandoned lease" in preview.stdout and "still running" not in preview.stdout
        assert artifact.name not in preview.stdout and str(retained) not in preview.stdout
        assert str(notes) in preview.stdout and str(owned) in preview.stdout
        assert preview.stdout.count("Native Claude transcripts") == 1
        assert "--verbose" in preview.stdout
        assert "Delete Forge data for 2 session(s)?" in preview.stderr
        detailed = runner.invoke(main, [*args, "--verbose"], input="n\n")
        assert detailed.exit_code == 1
        assert str(artifact) in detailed.stdout and str(retained) in detailed.stdout
        assert artifact.exists() and notes.exists()
        result = runner.invoke(main, [*args, "--yes"])
    assert result.exit_code == 1
    assert "Deleted 2 sessions" in result.stdout
    assert "--verbose" not in result.stdout
    assert "Deleted session first" not in result.stdout
    assert "1 session(s) refused or failed" in result.stderr
    assert retained.exists() and SessionStore(str(project), "working").exists()
    assert not artifact.exists() and not notes.exists() and not owned.exists()


def test_bulk_result_counts_only_completed_deletions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("changed", "unchanged"):
        publish_session_from_fields(IndexStore(), name, tmp_path, tmp_path)
    artifact = tmp_path / ".forge/artifacts/changed/copy.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("previewed")

    def change_after_preview(*args, **kwargs) -> bool:
        artifact.write_text("new content")
        return True

    monkeypatch.setattr("forge.cli.session_delete.click.confirm", change_after_preview)
    result = CliRunner().invoke(main, ["session", "delete", "--all"])
    assert result.exit_code == 1
    assert "Deleted 1 session." in result.stdout
    assert "changed:" in result.stderr
    assert "--yes" not in result.stderr
    assert "preview" in result.stderr.lower() and "again" in result.stderr.lower()
    assert not cleanup_state_path(tmp_path, "changed").exists()
    assert artifact.read_text() == "new content"
    assert not SessionStore(str(tmp_path), "unchanged").exists()


def test_bulk_delete_with_busy_index_counts_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    index = IndexStore()
    publish_session_from_fields(index, "target", tmp_path, tmp_path)
    monkeypatch.setattr("forge.session.index.CLI_LOCK_TIMEOUT_S", 0.0)
    with file_lock_for_target(target_path=index.index_path, timeout_s=1):
        result = CliRunner().invoke(main, ["sess", "delete", "--all", "--yes"])
    assert result.exit_code == 1
    assert "Deleted 0 sessions." in result.stdout
    assert "target: Forge state is busy" in result.stderr
    assert "--yes" not in result.stderr
    assert SessionStore(str(tmp_path), "target").exists()


def test_saved_cleanup_retry_is_one_copyable_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / ("long-project-" * 9) / ("nested-directory-" * 6) / "operator's [project]"
    root.mkdir(parents=True)
    monkeypatch.chdir(root)
    index = IndexStore()
    publish_session_from_fields(index, "target", root, root)
    artifact = root / ".forge/artifacts/target/owned.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("previewed")
    runner = CliRunner()
    args = ["session", "delete", "--all", "--yes", "--keep-worktree"]

    def interrupt_removal(*args, **kwargs):
        raise OSError("interrupted after saving the inventory")

    with monkeypatch.context() as failure:
        failure.setattr("forge.session.deletion.apply_forge_content", interrupt_removal)
        interrupted = runner.invoke(main, args)
    assert interrupted.exit_code == 1
    assert cleanup_state_path(root, "target").is_file()
    monkeypatch.setattr("forge.session.index.CLI_LOCK_TIMEOUT_S", 0.0)
    with file_lock_for_target(target_path=index.index_path, timeout_s=1):
        busy = runner.invoke(main, args)
    assert busy.exit_code == 1
    assert "busy" in busy.stderr and "index.json.lock" in busy.stderr
    assert ".." not in busy.stderr
    command = shlex.join(
        ["forge", "session", "delete", "target", "--yes", "--forge-root", str(root), "--keep-worktree"]
    )
    for result in (interrupted, busy):
        assert result.stderr.lower().count("retry with") == 1
        assert "Retry after the other operation finishes" not in result.stderr
        assert command in [line.strip() for line in result.stderr.splitlines()]

    resumed = runner.invoke(main, shlex.split(command)[1:])
    assert resumed.exit_code == 0, resumed.output
    assert not artifact.exists() and not cleanup_state_path(root, "target").exists()

"""Session index contention and large delete inventories must produce usable CLI output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.hooks import hooks
from forge.cli.main import main
from forge.core.paths import get_forge_home
from forge.core.state import file_lock_for_target
from forge.session import IndexStore, SessionStore
from forge.session.workers import capture_session_instance, session_worker_lease
from tests.fixtures.session_state import publish_session_from_fields

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("options", [[], ["--json", "--older-than", "1"]])
def test_list_with_busy_index_reports_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, options: list[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    index = IndexStore()
    publish_session_from_fields(index, "example", tmp_path, tmp_path)
    runner = CliRunner()
    monkeypatch.setattr("forge.session.index.CLI_LOCK_TIMEOUT_S", 0.0)
    with file_lock_for_target(target_path=index.index_path, timeout_s=1):
        busy = runner.invoke(main, ["sess", "list", *options], catch_exceptions=False)
    assert busy.exit_code == 1
    assert busy.stdout == ""
    assert "busy" in busy.stderr.lower() and "retry" in busy.stderr.lower()
    assert "index.json.lock" in busy.stderr
    listing = runner.invoke(main, ["sess", "list", "--json"])
    assert listing.exit_code == 0, listing.output
    assert [item["name"] for item in json.loads(listing.stdout)] == ["example"]


def test_busy_index_preserves_direct_command_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("forge.session.index.CLI_LOCK_TIMEOUT_S", 0.0)
    with file_lock_for_target(target_path=IndexStore().index_path, timeout_s=1):
        result = CliRunner().invoke(
            hooks, ["user-prompt-submit"], input=json.dumps({"prompt": "%session list", "transcript_path": ""})
        )
    assert result.exit_code == 0, result.output
    decision = json.loads(result.stdout)
    assert decision["decision"] == "block"
    assert "busy" in decision["reason"] and "index.json.lock" in decision["reason"]


def test_bulk_delete_summarizes_inventory_and_preserves_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    index = IndexStore()
    publish_session_from_fields(index, "first", tmp_path, tmp_path, claude_session_id="fixture-id")
    for name in ("second", "working"):
        publish_session_from_fields(index, name, tmp_path, tmp_path)
    artifact = tmp_path / ".forge/artifacts/first/routine-copy.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("test data")
    notes = tmp_path / ".forge/prev_sessions/second/children/old-child.notes.md"
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
    token = capture_session_instance(tmp_path, "working")
    with session_worker_lease(tmp_path, "working", expected_instance_id=token, label="test worker"):
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
    assert "Deleted session first" not in result.stdout
    assert "1 session(s) refused or failed" in result.stderr
    assert retained.exists() and SessionStore(str(tmp_path), "working").exists()
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

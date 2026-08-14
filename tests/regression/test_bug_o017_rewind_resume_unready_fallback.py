"""O017 regression: fresh rewind resume ignores an unready fallback transcript."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import SessionManager, SessionStore
from forge.session.identity import session_name_from_key

pytestmark = pytest.mark.regression


@pytest.fixture
def rewind_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)
    return project


def _seed_parent(runner: CliRunner, project: Path, *, name: str, session_id: str) -> None:
    from forge.session.claude.paths import get_transcript_path

    created = runner.invoke(main, ["session", "start", name, "--no-launch"])
    assert created.exit_code == 0, created.output
    store = SessionStore(str(project), name)
    store.update(
        timeout_s=5.0,
        mutate=lambda state: setattr(state.confirmed, "claude_session_id", session_id),
    )
    transcript = get_transcript_path(str(project), session_id)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        '{"requestId":"r1","message":{"role":"user","content":[{"type":"text","text":"one"}]}}\n',
        encoding="utf-8",
    )


def _resume(runner: CliRunner, parent: str, child: str | None):
    args = ["session", "resume", parent, "--fresh"]
    if child is not None:
        args.extend(["--child-name", child])
    args.extend(["--strategy", "rewind", "--drop-last", "1"])
    return runner.invoke(main, args)


def test_o017_unready_rewind_fallback_removes_child_before_launch(rewind_project: Path) -> None:
    runner = CliRunner()
    _seed_parent(runner, rewind_project, name="rewind-parent", session_id="parent-rewind-uuid")

    with (
        patch("forge.cli.session_rewind.write_rewind_transcript_prefix", side_effect=ValueError("bad turn order")),
        patch("forge.session.claude.relocate_transcript", side_effect=OSError("disk full")),
        patch("forge.core.ops.claude_session.invoke_claude", return_value=0) as invoke,
    ):
        result = _resume(runner, "rewind-parent", "rewind-child")

    assert result.exit_code == 1, result.output
    assert "could not copy the full parent transcript (disk full)" in " ".join(result.output.split())
    invoke.assert_not_called()
    assert not SessionStore(str(rewind_project), "rewind-child").exists()
    assert not SessionManager().index_store.live_session_exists("rewind-child", forge_root=str(rewind_project))


def test_o017_same_directory_fallback_remains_launchable(rewind_project: Path) -> None:
    runner = CliRunner()
    _seed_parent(runner, rewind_project, name="fallback-parent", session_id="fallback-parent-uuid")

    with (
        patch("forge.cli.session_rewind.write_rewind_transcript_prefix", side_effect=ValueError("bad turn order")),
        patch("forge.core.ops.claude_session.invoke_claude", return_value=0) as invoke,
    ):
        result = _resume(runner, "fallback-parent", "fallback-child")

    assert result.exit_code == 0, result.output
    invoke.assert_called_once()
    assert SessionStore(str(rewind_project), "fallback-child").exists()


def test_o017_failed_rollback_names_retained_child_and_deletion_recovery(rewind_project: Path) -> None:
    """A second failure cannot hide the newly persisted child or its cleanup command."""
    runner = CliRunner()
    _seed_parent(runner, rewind_project, name="rollback-parent", session_id="rollback-parent-uuid")

    with (
        patch("forge.cli.session_rewind.write_rewind_transcript_prefix", side_effect=ValueError("bad turn order")),
        patch("forge.session.claude.relocate_transcript", side_effect=OSError("disk full")),
        patch.object(SessionManager, "delete_session", side_effect=OSError("cleanup denied")),
        patch("forge.core.ops.claude_session.invoke_claude", return_value=0) as invoke,
    ):
        result = _resume(runner, "rollback-parent", None)

    assert result.exit_code == 1, result.output
    invoke.assert_not_called()
    index_store = SessionManager().index_store
    child_names = {
        session_name_from_key(key)
        for key, entry in index_store.read().sessions.items()
        if session_name_from_key(key) != "rollback-parent" and entry.forge_root == str(rewind_project.resolve())
    }
    assert len(child_names) == 1
    child_name = child_names.pop()
    output = " ".join(result.output.split())
    assert "Rewind fallback could not prepare a resumable transcript." in output
    assert f"Cleanup also failed for created session '{child_name}': cleanup denied." in output
    assert f"forge session delete {child_name} --yes --force --keep-transcripts --keep-worktree" in output
    assert SessionStore(str(rewind_project), child_name).exists()
    assert index_store.session_exists(child_name, forge_root=str(rewind_project.resolve()))

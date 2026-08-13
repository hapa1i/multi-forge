"""O017 regression: fresh rewind resume ignores an unready fallback transcript."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import SessionManager, SessionStore

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


def _resume(runner: CliRunner, parent: str, child: str):
    return runner.invoke(
        main,
        [
            "session",
            "resume",
            parent,
            "--fresh",
            "--child-name",
            child,
            "--strategy",
            "rewind",
            "--drop-last",
            "1",
        ],
    )


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

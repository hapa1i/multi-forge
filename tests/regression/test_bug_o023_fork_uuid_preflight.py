"""O023 regression: fork UUID validation runs after child creation and gates UUID-free modes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import SessionManager, SessionStore

pytestmark = pytest.mark.regression


@pytest.fixture
def fork_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[CliRunner, Path]:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)
    runner = CliRunner()
    created = runner.invoke(main, ["session", "start", "fork-parent", "--no-launch"])
    assert created.exit_code == 0, created.output
    store = SessionStore(str(project), "fork-parent")
    store.update(
        timeout_s=5.0,
        mutate=lambda state: setattr(state.confirmed, "claude_session_id", None),
    )
    assert store.read().confirmed.claude_session_id is None
    return runner, project


def test_o023_native_fork_without_parent_uuid_fails_before_child_mutation(
    fork_project: tuple[CliRunner, Path],
) -> None:
    runner, project = fork_project

    result = runner.invoke(main, ["session", "fork", "fork-parent", "--name", "native-child"])

    assert result.exit_code == 1
    assert "Parent session has no UUID" in result.output
    assert not SessionStore(str(project), "native-child").exists()
    assert not SessionManager().index_store.live_session_exists("native-child", forge_root=str(project))


def test_o023_no_launch_fork_does_not_require_parent_uuid(fork_project: tuple[CliRunner, Path]) -> None:
    runner, project = fork_project

    result = runner.invoke(
        main,
        ["session", "fork", "fork-parent", "--name", "deferred-child", "--no-launch"],
    )

    assert result.exit_code == 0, result.output
    assert SessionStore(str(project), "deferred-child").exists()


def test_o023_transfer_fork_does_not_require_parent_uuid(fork_project: tuple[CliRunner, Path]) -> None:
    runner, project = fork_project

    with patch("forge.core.ops.claude_session.invoke_claude", return_value=0) as invoke:
        result = runner.invoke(
            main,
            [
                "session",
                "fork",
                "fork-parent",
                "--name",
                "transfer-child",
                "--resume-mode",
                "transfer",
            ],
        )

    assert result.exit_code == 0, result.output
    invoke.assert_called_once()
    assert SessionStore(str(project), "transfer-child").exists()


def test_o023_native_fork_with_parent_uuid_remains_launchable(fork_project: tuple[CliRunner, Path]) -> None:
    runner, project = fork_project
    parent_store = SessionStore(str(project), "fork-parent")
    parent_store.update(
        timeout_s=5.0,
        mutate=lambda state: setattr(state.confirmed, "claude_session_id", "confirmed-parent-uuid"),
    )

    with patch("forge.core.ops.claude_session.invoke_claude", return_value=0) as invoke:
        result = runner.invoke(main, ["session", "fork", "fork-parent", "--name", "confirmed-child"])

    assert result.exit_code == 0, result.output
    invoke.assert_called_once()
    assert SessionStore(str(project), "confirmed-child").exists()

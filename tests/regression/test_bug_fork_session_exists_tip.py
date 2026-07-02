"""Regression: `forge session fork` must emit a recovery tip on a name collision.

Bug ID: fork-session-exists-tip
Root cause:
- `forge session start <existing>` caught `SessionExistsError` explicitly and
  printed a resume/delete tip, but `forge session fork ... --name <existing>`
  had no `except SessionExistsError` clause. It fell through to the generic
  `except ForgeSessionError -> _handle_error`, which printed only the error and
  exited with no tip -- an inconsistent UX between two paths that raise the same
  exception.
Fix:
- `_handle_error` was replaced by `handle_session_error` (forge.cli.output),
  which consults a context-free type->tip map. `SessionExistsError` maps to a
  delete/rename tip (deliberately no "resume" -- meaningless for a fork name
  collision), so fork's generic handler now tips automatically.
Affected files: src/forge/cli/output.py, src/forge/cli/session_fork.py
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import create_session_state
from forge.session.exceptions import SessionExistsError

pytestmark = pytest.mark.regression


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def session_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Minimal git + Forge project for CLI regression tests."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)
    return project


def test_fork_onto_existing_name_emits_recovery_tip(runner: CliRunner, session_project: Path) -> None:
    """Forking onto a taken name exits 1 with a delete/rename tip (no 'resume')."""
    parent = create_session_state(
        "fork-parent",
        proxy_template="litellm-openai",
        proxy_base_url="http://localhost:8085",
        worktree_path=str(session_project),
        worktree_branch="main",
    )
    parent.confirmed.claude_session_id = "parent-uuid"

    with (
        patch("forge.cli.session_fork.SessionManager") as mock_manager_cls,
        patch("forge.cli.session.invoke_claude", return_value=0),
    ):
        mock_manager = mock_manager_cls.return_value
        mock_manager.get_session.return_value = parent
        mock_manager.fork_session.side_effect = SessionExistsError("taken")

        result = runner.invoke(main, ["session", "fork", "fork-parent", "--name", "taken"])

    assert result.exit_code == 1
    assert "already exists" in result.output
    # The regression: a recovery tip must be present.
    assert "Tip:" in result.output
    assert "forge session delete taken" in result.output
    # Generic SessionExistsError tip must not suggest resume (wrong for a fork collision).
    assert "resume" not in result.output

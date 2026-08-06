"""Team hook diagnostic feedback is visible even when the event is allowed."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from forge.cli.hooks import commands
from forge.cli.hooks._group import hooks
from forge.core import state as state_module
from forge.core.state import StateUnreadableError


@pytest.mark.parametrize("command", ["teammate-idle", "task-completed"])
def test_exit_0_writes_feedback_to_stderr(command: str, tmp_path: Path) -> None:
    store = MagicMock()
    store.read.return_value = MagicMock()
    store.forge_root = tmp_path
    effective = MagicMock()
    effective.policy.team_supervisor.enabled = True

    with (
        patch("forge.cli.hooks.commands.resolve_session_store", return_value=store),
        patch("forge.cli.hooks.commands.compute_effective_intent", return_value=effective),
        patch("forge.cli.hooks.commands.diagnose_project_compatibility_for_hook"),
        patch(
            "forge.cli.hooks.commands._run_team_handler",
            return_value=(0, "review warning"),
        ),
    ):
        result = CliRunner().invoke(
            hooks,
            [command],
            input=json.dumps({"session_id": "team-session"}),
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert "review warning" in result.stderr
    assert "review warning" not in result.stdout


def test_unreadable_team_cache_is_a_non_destructive_safe_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = commands._team_cache_path("team-session")
    path.parent.mkdir(parents=True)
    path.write_text('{"seen": ["task-1"]}')
    original_bytes = path.read_bytes()

    def raise_unreadable(_path: Path) -> dict:
        raise StateUnreadableError(str(path), "simulated transient read failure")

    monkeypatch.setattr(state_module, "read_json", raise_unreadable)
    handler = MagicMock(return_value=(0, "safe miss"))

    assert commands._run_team_handler("team-session", handler) == (0, "safe miss")
    handler.assert_called_once_with({})
    assert path.read_bytes() == original_bytes

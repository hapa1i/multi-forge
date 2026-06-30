"""The team-supervisor hooks freeze their declared lane at dispatch (epic consumer_lanes T6a).

Both ``teammate-idle`` and ``task-completed`` read the bound backend, then freeze it write-once
before running the handler. The handler itself (and its LLM call) is mocked -- this isolates the
3-line freeze wiring at each hook from the handler path already covered in
``tests/src/policy/team/test_handlers.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from forge.cli.hooks._group import hooks
from forge.policy.team.handlers import TEAM_SUPERVISOR_CONSUMER
from forge.session.consumer_lanes import set_intent_lane
from forge.session.models import LaneRecord, create_session_state
from forge.session.store import SessionStore

_CLAUDE_MAX = LaneRecord("claude_code", "claude-max", "opus")


def _enabled_effective() -> MagicMock:
    """A minimal effective intent whose team-supervisor config is enabled (passes the guard)."""
    eff = MagicMock()
    eff.policy.team_supervisor.enabled = True
    return eff


@pytest.mark.parametrize("command", ["teammate-idle", "task-completed"])
def test_team_hook_freezes_declared_lane(command: str, tmp_path: Path) -> None:
    manifest = create_session_state("session")
    set_intent_lane(manifest, TEAM_SUPERVISOR_CONSUMER, _CLAUDE_MAX)
    store = SessionStore(str(tmp_path), "session")
    store.write(manifest)

    with (
        patch("forge.cli.hooks.commands.resolve_session_store", return_value=store),
        patch("forge.cli.hooks.commands.compute_effective_intent", return_value=_enabled_effective()),
        patch("forge.cli.hooks.commands._run_team_handler", return_value=(0, None)) as mock_handler,
    ):
        result = CliRunner().invoke(hooks, [command], input=json.dumps({"session_id": "u"}), catch_exceptions=False)

    assert result.exit_code == 0, result.output
    # The handler ran with the bound backend, and the lane is now frozen in confirmed.
    assert mock_handler.called
    confirmed = store.read().confirmed.consumer_lanes
    assert confirmed is not None and confirmed.team_supervisor is not None
    assert confirmed.team_supervisor.lane == _CLAUDE_MAX


@pytest.mark.parametrize("command", ["teammate-idle", "task-completed"])
def test_team_hook_undeclared_lane_does_not_freeze(command: str, tmp_path: Path) -> None:
    store = SessionStore(str(tmp_path), "session")
    store.write(create_session_state("session"))

    with (
        patch("forge.cli.hooks.commands.resolve_session_store", return_value=store),
        patch("forge.cli.hooks.commands.compute_effective_intent", return_value=_enabled_effective()),
        patch("forge.cli.hooks.commands._run_team_handler", return_value=(0, None)),
    ):
        result = CliRunner().invoke(hooks, [command], input=json.dumps({"session_id": "u"}), catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert store.read().confirmed.consumer_lanes is None

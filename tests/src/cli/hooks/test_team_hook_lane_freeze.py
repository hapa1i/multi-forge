"""The team-supervisor hooks freeze their lane only on a real dispatch (epic consumer_lanes T6a).

The freeze runs from ``_run_supervisor``'s ``on_dispatch`` hook, so a cache/tagger/resume/depth
skip never freezes (Finding 1), and the threaded lane keeps confirmed consistent with billing
(Finding 2). The handler is faked to simulate dispatch-vs-skip without a real LLM call; the
handler's own backend_id path is covered in ``tests/src/policy/team/test_handlers.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from forge.cli.hooks._group import hooks
from forge.policy.team.handlers import TEAM_SUPERVISOR_CONSUMER
from forge.session.consumer_lanes import set_intent_lane
from forge.session.models import LaneRecord, create_session_state
from forge.session.store import SessionStore

_CLAUDE_MAX = LaneRecord("claude_code", "claude-max", "opus")
_HANDLERS = {"teammate-idle": "handle_teammate_idle", "task-completed": "handle_task_completed"}


def _enabled_effective() -> MagicMock:
    eff = MagicMock()
    eff.policy.team_supervisor.enabled = True
    return eff


def _dispatching_handler(
    data: Any, config: Any, cache: Any, backend_id: str | None = None, on_dispatch: Callable[[], None] | None = None
) -> tuple[int, str]:
    """Simulate the team supervisor actually dispatching: fire on_dispatch (verdict aligned)."""
    if on_dispatch is not None:
        on_dispatch()
    return (0, "")


def _skipping_handler(
    data: Any, config: Any, cache: Any, backend_id: str | None = None, on_dispatch: Callable[[], None] | None = None
) -> tuple[int, str]:
    """Simulate a cache/tagger/resume skip: never dispatch (on_dispatch is not called)."""
    return (0, "")


def _seed(tmp_path: Path, *, declared: bool) -> SessionStore:
    manifest = create_session_state("session")
    if declared:
        set_intent_lane(manifest, TEAM_SUPERVISOR_CONSUMER, _CLAUDE_MAX)
    store = SessionStore(str(tmp_path), "session")
    store.write(manifest)
    return store


def _invoke(command: str, store: SessionStore, handler_fake: Callable[..., tuple[int, str]]) -> Any:
    with (
        patch("forge.cli.hooks.commands.resolve_session_store", return_value=store),
        patch("forge.cli.hooks.commands.compute_effective_intent", return_value=_enabled_effective()),
        patch("forge.cli.hooks.commands._run_team_handler", lambda key, fn: fn({})),
        patch(f"forge.policy.team.handlers.{_HANDLERS[command]}", handler_fake),
    ):
        return CliRunner().invoke(hooks, [command], input=json.dumps({"session_id": "u"}), catch_exceptions=False)


@pytest.mark.parametrize("command", ["teammate-idle", "task-completed"])
def test_freezes_on_real_dispatch(command: str, tmp_path: Path) -> None:
    store = _seed(tmp_path, declared=True)
    result = _invoke(command, store, _dispatching_handler)
    assert result.exit_code == 0, result.output
    confirmed = store.read().confirmed.consumer_lanes
    assert confirmed is not None and confirmed.team_supervisor is not None
    assert confirmed.team_supervisor.lane == _CLAUDE_MAX


@pytest.mark.parametrize("command", ["teammate-idle", "task-completed"])
def test_no_freeze_when_handler_skips(command: str, tmp_path: Path) -> None:
    """A declared lane but a skipped check (no on_dispatch) must not freeze (Finding 1)."""
    store = _seed(tmp_path, declared=True)
    result = _invoke(command, store, _skipping_handler)
    assert result.exit_code == 0, result.output
    assert store.read().confirmed.consumer_lanes is None


@pytest.mark.parametrize("command", ["teammate-idle", "task-completed"])
def test_undeclared_lane_does_not_freeze(command: str, tmp_path: Path) -> None:
    """No declaration -> dispatched lane is None -> a real dispatch still never freezes."""
    store = _seed(tmp_path, declared=False)
    _invoke(command, store, _dispatching_handler)
    assert store.read().confirmed.consumer_lanes is None

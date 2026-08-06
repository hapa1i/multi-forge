"""Focused tests for shared Claude session operation boundaries."""

from pathlib import Path

import pytest

from forge.core.ops.claude_session import launch_claude_session
from forge.core.ops.session import ForgeOpError
from forge.session import create_session_state


def test_launch_refuses_missing_recorded_worktree_before_callbacks(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "deleted-worktree"
    state = create_session_state("degraded", worktree_path=str(missing))
    callbacks: list[str] = []

    with pytest.raises(ForgeOpError) as exc_info:
        launch_claude_session(
            manifest=state,
            session_id=None,
            resume_id=None,
            effective_template=None,
            runtime_base_url=None,
            context_limit=200_000,
            use_sidecar=False,
            before_launch=lambda _path: callbacks.append("before_launch"),
            invoke=lambda **_kwargs: callbacks.append("invoke") or 0,
            run_active=lambda runner, **_kwargs: runner(),
        )

    message = str(exc_info.value)
    assert "cannot launch session 'degraded'" in message
    assert str(missing) in message
    assert "forge session delete degraded" in message
    assert callbacks == []

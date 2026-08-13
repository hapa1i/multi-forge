"""O011 regression: typed fork failures gate incognito cleanup on sidecar mode."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from forge.core.ops.claude_session import (
    ClaudeLaunchPreferences,
    ForkLaunchPlan,
    fork_claude_session,
)
from forge.core.ops.session import ForgeOpError
from forge.session import create_session_state

pytestmark = pytest.mark.regression


def _plan(tmp_path: Path, *, use_sidecar: bool, incognito: bool = True) -> ForkLaunchPlan:
    manifest = create_session_state(
        "incognito-fork",
        is_incognito=incognito,
        worktree_path=str(tmp_path),
    )
    manifest.forge_root = str(tmp_path)
    return ForkLaunchPlan(
        manifest=manifest,
        session_id=None,
        resume_id="parent-uuid",
        fork_session=True,
        register_fork=False,
        prompt_file=None,
        context_limit=200_000,
        launch_preferences=ClaudeLaunchPreferences(
            use_sidecar=use_sidecar,
            mounts=(),
            image=None,
        ),
        effective_template=None,
        runtime_base_url=None,
        proxy_id=None,
        incognito=incognito,
        render_post_exit=False,
    )


@pytest.mark.parametrize("use_sidecar", [False, True], ids=["host", "sidecar"])
def test_o011_typed_incognito_launch_failure_always_cleans_up(tmp_path: Path, use_sidecar: bool) -> None:
    manager = MagicMock()
    presenter = MagicMock()
    plan = _plan(tmp_path, use_sidecar=use_sidecar)

    with (
        patch(
            "forge.core.ops.claude_session.launch_claude_session",
            side_effect=ForgeOpError("launch preparation failed"),
        ),
        patch("forge.core.ops.claude_session._run_incognito_cleanup") as cleanup,
    ):
        result = fork_claude_session(manager=manager, plan=plan, presenter=presenter)

    assert result.exit_code == 1
    cleanup.assert_called_once_with(manager, plan.manifest, presenter)


def test_o011_non_incognito_failure_does_not_delete_session(tmp_path: Path) -> None:
    manager = MagicMock()
    presenter = MagicMock()
    plan = _plan(tmp_path, use_sidecar=False, incognito=False)

    with (
        patch(
            "forge.core.ops.claude_session.launch_claude_session",
            side_effect=ForgeOpError("launch preparation failed"),
        ),
        patch("forge.core.ops.claude_session._run_incognito_cleanup") as cleanup,
    ):
        result = fork_claude_session(manager=manager, plan=plan, presenter=presenter)

    assert result.exit_code == 1
    cleanup.assert_not_called()

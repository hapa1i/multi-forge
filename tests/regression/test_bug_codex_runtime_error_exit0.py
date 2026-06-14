"""Regression: a Codex runtime error riding an exit-0 was reported as CLI success.

Bug: ``session_codex`` used returncode-based ``HeadlessResult.success`` for the exit code
and the "Codex turn failed" render, ignoring ``runtime_is_error``. A ``turn.failed``/
``error`` event that exited 0 then read as success (and even printed the "continue this
thread" tip).

Fix: ``_codex_ok(codex) = codex.success and not codex.runtime_is_error``, used for the exit
code and rendering (src/forge/cli/session_codex.py).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from forge.cli.session_codex import _codex_ok, launch_codex_session
from forge.core.invoker.types import HeadlessResult
from forge.core.ops.codex_session import CodexSessionStartResult

pytestmark = pytest.mark.regression


def _codex(*, returncode: int, runtime_is_error: bool) -> HeadlessResult:
    return HeadlessResult(
        label="codex",
        stdout="",
        stderr="boom",
        returncode=returncode,
        duration_seconds=0.1,
        runtime_is_error=runtime_is_error,
    )


def test_codex_ok_false_on_runtime_error_exit0() -> None:
    assert _codex_ok(_codex(returncode=0, runtime_is_error=True)) is False


def test_codex_ok_true_on_clean_exit0() -> None:
    assert _codex_ok(_codex(returncode=0, runtime_is_error=False)) is True


def test_launch_returns_nonzero_on_runtime_error_exit0() -> None:
    result = CodexSessionStartResult(
        session="impl",
        parent="planner",
        transfer_path=Path("/x.md"),
        root_run_id="run-1",
        codex=_codex(returncode=0, runtime_is_error=True),
        curation_ran=False,
        thread_id="tid",
        rollout_path=None,
        worktree_path=None,
    )
    with (
        patch("forge.cli.session_codex.ExecutionContext.from_cwd", return_value=MagicMock()),
        patch("forge.cli.session_codex.start_codex_session", return_value=result),
    ):
        rc = launch_codex_session(
            name="impl",
            parent="planner",
            task="t",
            strategy="ai-curated",
            depth=1,
            sandbox="workspace-write",
            worktree=False,
            branch=None,
        )
    # exit-0 + runtime_is_error must surface as a non-zero exit, not success.
    assert rc == 1

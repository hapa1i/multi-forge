"""O003 regression: a completed headless Codex turn must not undo deletion.

Root cause: headless start and resume unconditionally updated the session manifest
after Codex exited. If an explicit delete landed during the turn, lock acquisition
recreated the session directory and the update raised ``SessionFileNotFoundError``
instead of returning the completed runtime result.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from forge.core.invoker import HeadlessResult
from forge.core.ops.codex_session import continue_codex_session
from forge.core.ops.context import ExecutionContext
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.session import IndexStore, SessionManager, SessionNotFoundError, SessionStore
from forge.session.models import CodexConfirmed, create_session_state
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


def _preflight() -> CodexPreflight:
    return CodexPreflight(
        installed=True,
        version="0.139.0",
        version_ok=True,
        auth_method="chatgpt_tokens",
        auth_source="codex_store",
        billing_mode="subscription_quota",
        ready=True,
        blocking_reason=None,
        hook_seam="enrollment_gated",
        proxy_responses="native_direct",
        doctor_status="ok",
    )


def test_resume_returns_completed_turn_when_session_is_deleted_during_codex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    (project / ".forge").mkdir(parents=True)
    state = create_session_state(name="impl", worktree_path=str(project), runtime="codex")
    state.forge_root = str(project)
    state.confirmed.codex = CodexConfirmed(thread_id="thread-before-delete")
    publish_session(
        IndexStore(),
        state,
        project_root=str(project),
        forge_root=str(project),
        checkout_root=str(project),
    )
    ctx = ExecutionContext(cwd=project, worktree_root=project, project_root=project, forge_root=project)

    def _delete_then_complete(_invoker: Any, _request: Any) -> HeadlessResult:
        SessionManager().delete_session(
            state.name,
            delete_transcripts=False,
            delete_worktree=False,
            forge_root=str(project),
        )
        return HeadlessResult(
            label="codex-resume",
            stdout="completed",
            stderr="",
            returncode=0,
            duration_seconds=0.1,
            runtime_session_id="thread-before-delete",
        )

    monkeypatch.setattr("forge.core.ops.codex_session.assert_codex_ready", _preflight)
    monkeypatch.setattr("forge.core.ops.codex_session.CodexHeadlessInvoker.run", _delete_then_complete)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex-home"))

    result = continue_codex_session(ctx=ctx, name=state.name, task="Finish the turn")

    assert result.codex.stdout == "completed"
    assert any("deleted while Codex was running" in warning for warning in result.warnings)
    store = SessionStore(str(project), state.name)
    assert not store.exists()
    assert not store.session_dir.exists()
    with pytest.raises(SessionNotFoundError):
        SessionManager().get_session_entry(state.name, forge_root=str(project))

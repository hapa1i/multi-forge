"""Regression D022: unknown resume strategies must not silently run structured.

Root cause: ``SessionManager.resume_session`` caught ``ResumeStrategy`` conversion
failures, assembled structured context, then persisted the original unknown string
as durable derivation metadata.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.session import (
    SessionManager,
    SessionNotFoundError,
    SessionStore,
    create_session_state,
)
from forge.session.prev_sessions import child_notes_path, child_path, generated_path

pytestmark = pytest.mark.regression


def test_unknown_transfer_strategy_fails_before_artifacts_or_child_state(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    parent = create_session_state("parent", worktree_path=str(project))
    parent.forge_root = str(project)

    manager = SessionManager()
    SessionStore(str(project), parent.name).write(parent)
    manager.index_store.add_from_state(
        parent,
        str(project),
        checkout_root=str(project),
        forge_root=str(project),
        relative_path=".",
    )

    with pytest.raises(ValueError) as exc_info:
        manager.resume_session(
            parent.name,
            child_name="child",
            strategy="not-a-strategy",
            forge_root=str(project),
        )

    assert str(exc_info.value) == ("Unknown strategy 'not-a-strategy' (valid: minimal, structured, full, ai-curated).")
    assert not SessionStore(str(project), "child").session_dir.exists()
    with pytest.raises(SessionNotFoundError):
        manager.get_session_entry("child", forge_root=str(project))
    assert not generated_path(project, parent.name).exists()
    assert not child_path(project, parent.name, "child").exists()
    assert not child_notes_path(project, parent.name, "child").exists()

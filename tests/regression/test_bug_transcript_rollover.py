"""Tests for transcript artifact capture on compact/clear rollover.

When Claude runs /compact or /clear, the SessionStart hook is invoked with a new
session_id. Before updating confirmed.transcript_path, Forge should capture the
previous transcript into project-local artifacts.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.session import SessionStore, create_session_state
from forge.session.hooks import HookInput, handle_session_start

pytestmark = pytest.mark.regression


@pytest.fixture
def temp_worktree(tmp_path: Path) -> Path:
    (tmp_path / ".claude").mkdir()
    return tmp_path


def test_compact_copies_previous_transcript_to_project_artifacts(
    temp_worktree: Path,
    tmp_path: Path,
) -> None:
    # Create manifest
    manifest = create_session_state(
        "test-session",
        proxy_template="test-family",
        proxy_base_url="http://localhost:8080",
    )

    # Old session id + transcript
    manifest.confirmed.claude_session_id = "old-uuid"
    old_transcript = temp_worktree / "old.jsonl"
    old_transcript.write_text("{}\n", encoding="utf-8")
    manifest.confirmed.transcript_path = str(old_transcript)

    store = SessionStore(str(temp_worktree), "test-session")
    store.write(manifest)

    # New hook input indicates compact
    hook_input = HookInput(
        session_id="new-uuid",
        transcript_path=str(temp_worktree / "new.jsonl"),
        source="compact",
    )

    # Force project_root resolution to our tmp_path (acts as main repo)
    with patch("forge.session.artifacts.resolve_forge_root", return_value=tmp_path):
        with patch.dict(os.environ, {"FORGE_SESSION": "test-session"}, clear=True):
            result = handle_session_start(hook_input, temp_worktree)

    assert result.success

    copied = tmp_path / ".forge" / "artifacts" / "test-session" / "transcripts" / "old-uuid.jsonl"
    assert copied.exists()
    assert copied.read_text(encoding="utf-8") == "{}\n"

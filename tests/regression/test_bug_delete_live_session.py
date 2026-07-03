"""Regression: deleting a live session manifest must not crash the launcher.

Bug: ``forge session delete <name>`` run from another terminal while the session
is still open in Claude Code removes the manifest. When Claude later exits, the
launcher's post-launch backfill ``_infer_launch_confirmation``
(src/forge/session/launch_confirmation.py) calls ``store.update()`` -> ``store.read()``,
which raised an unhandled ``SessionFileNotFoundError`` and dumped a traceback to
the user's terminal.

Root cause: ``_infer_launch_confirmation`` did not tolerate a manifest deleted
mid-run. The transcript file still exists (lives under CLAUDE_HOME, not the
session dir), so the ``is_file()`` guard passes and the code reaches the
``store.update()`` that crashed.

Fix: catch ``SessionFileNotFoundError`` around the backfill write and degrade
quietly (src/forge/session/launch_confirmation.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.core.state import now_iso
from forge.session.claude.paths import get_transcript_path
from forge.session.exceptions import SessionFileNotFoundError
from forge.session.launch_confirmation import _infer_launch_confirmation
from forge.session.models import SessionState
from forge.session.store import SessionStore

pytestmark = pytest.mark.regression

SESSION_ID = "11111111-1111-1111-1111-111111111111"


def test_infer_launch_confirmation_tolerates_deleted_manifest(tmp_path: Path) -> None:
    """Backfill must not raise when the manifest was deleted while Claude ran."""
    forge_root = tmp_path / "project"
    forge_root.mkdir()

    state = SessionState(
        schema_version=7,
        name="live-session",
        created_at=now_iso(),
        last_accessed_at=now_iso(),
    )
    state.confirmed.claude_project_root = str(forge_root)

    store = SessionStore(str(forge_root), "live-session")
    store.write(state)

    # Create the transcript so the is_file() guard passes and execution reaches
    # the store.update() that triggered the original crash.
    transcript_path = get_transcript_path(str(forge_root), SESSION_ID)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text("{}\n", encoding="utf-8")

    # Simulate the concurrent `forge session delete` from another terminal.
    assert store.delete() is True

    # Previously raised SessionFileNotFoundError; must now degrade quietly.
    _infer_launch_confirmation(store=store, manifest=state, session_id=SESSION_ID)

    # The backfill must not resurrect the deleted session: the lock layer
    # mkdir-parents a session dir for its lockfile, so a naive catch would
    # leave a lock-only directory behind. The preflight exists() check prevents
    # entering the lock layer at all.
    assert not store.session_dir.exists()


def test_infer_launch_confirmation_tolerates_delete_race(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The narrow race -- manifest present at the exists() preflight but gone by the
    locked read inside store.update() -- must degrade quietly, not surface a traceback."""
    forge_root = tmp_path / "project"
    forge_root.mkdir()

    state = SessionState(
        schema_version=7,
        name="race-session",
        created_at=now_iso(),
        last_accessed_at=now_iso(),
    )
    state.confirmed.claude_project_root = str(forge_root)

    store = SessionStore(str(forge_root), "race-session")
    store.write(state)  # manifest present -> exists() preflight passes

    transcript_path = get_transcript_path(str(forge_root), SESSION_ID)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text("{}\n", encoding="utf-8")

    # Simulate the delete landing between the exists() check and the locked read:
    # update() acquires the lock, reads, and finds the manifest already gone.
    def _raise_missing(*_args: object, **_kwargs: object) -> None:
        raise SessionFileNotFoundError("forge.session.json")

    monkeypatch.setattr(store, "update", _raise_missing)

    # Must not raise; the except SessionFileNotFoundError branch degrades quietly.
    _infer_launch_confirmation(store=store, manifest=state, session_id=SESSION_ID)

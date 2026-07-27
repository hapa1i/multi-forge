"""Regression: deleting an adopted session deleted the user's native transcript.

Bug: native_session_adoption Slice 2 review, HIGH.
Root cause: `delete_session(delete_transcripts=True)` unlinks
`get_transcript_path(...)` under `~/.claude/projects` for the session's bound
UUID. Every other origination path created that transcript, so deleting it was
safe; adoption binds one the *user* created and may still resume natively.
`auto_clean_old_sessions` passes `delete_transcripts=True` and runs
opportunistically on CLI startup (cleanup.py:225), so this fired with no
explicit delete at all.

Fix: `_adopted_source_uuids` feeds the same filter that already spares
transcripts shared with another session. Keyed on provenance --
`adoption.source_path` and the `reason="adopt"` artifact -- not on the bound
id: hooks can move `claude_session_id` off the adoption source, while later
Forge-created transcripts remain Forge's to clean up (the last test below).

Affected: src/forge/session/manager.py
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from forge.core.ops.context import ExecutionContext
from forge.core.ops.session_adopt import adopt_session, plan_adoption
from forge.session import SessionManager, SessionStore
from forge.session.claude.paths import get_transcript_path

pytestmark = pytest.mark.regression

_UUID = "bbbb2222-3333-4444-5555-666677778888"


def _adopted_project(tmp_path: Path) -> tuple[Path, Path]:
    """Return (project, native_transcript) for a session adopted from a native chat."""
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    (project / ".forge").mkdir()

    entries = [
        {"type": "user", "cwd": str(project), "message": {"role": "user"}},
        {"type": "assistant", "cwd": str(project), "message": {"model": "claude-opus-5"}},
    ]
    native = get_transcript_path(str(project), _UUID)
    native.parent.mkdir(parents=True, exist_ok=True)
    native.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    os.utime(native, (0, 0))

    ctx = ExecutionContext.from_cwd(project)
    adopt_session(ctx, plan_adoption(ctx, _UUID), name="adopted")
    return project, native


def test_deleting_an_adopted_session_spares_the_native_transcript(tmp_path: Path) -> None:
    project, native = _adopted_project(tmp_path)
    original = native.read_bytes()

    SessionManager().delete_session("adopted", forge_root=str(project))

    assert native.is_file(), "delete_session must not remove a conversation Forge did not create"
    assert native.read_bytes() == original
    assert not (project / ".forge" / "sessions" / "adopted").exists(), "the session itself must still be gone"


def test_protection_survives_the_bound_uuid_drifting_from_the_adopted_one(tmp_path: Path) -> None:
    """Nothing pins `claude_session_id` to the adoption source; provenance must name it.

    Hooks reconcile `claude_session_id` from their payloads. If it ever moves off
    the adopted UUID, that UUID still sits in `adoption.source_path` and the
    `reason="adopt"` artifact -- a guard keyed only on the bound id would delete
    the user's conversation.
    """
    project, native = _adopted_project(tmp_path)

    store = SessionStore(str(project), "adopted")
    state = store.read()
    state.confirmed.claude_session_id = "cccc3333-4444-5555-6666-777788889999"
    store.write(state)

    SessionManager().delete_session("adopted", forge_root=str(project))

    assert native.is_file(), "the adopted transcript must survive even after the binding drifted"


def test_a_normal_session_still_has_its_transcript_deleted(tmp_path: Path) -> None:
    """Guards against over-correcting: only adopted sessions are protected."""
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    (project / ".forge").mkdir()

    manager = SessionManager()
    manager.start_session("owned", worktree_path=str(project), direct=True, claude_session_id=_UUID)

    owned = get_transcript_path(str(project), _UUID)
    owned.parent.mkdir(parents=True, exist_ok=True)
    owned.write_text("{}\n", encoding="utf-8")

    manager.delete_session("owned", forge_root=str(project))

    assert not owned.exists()


def test_only_the_adopted_source_is_spared_not_later_forge_transcripts(tmp_path: Path) -> None:
    """Protection is keyed on provenance, so Forge's own transcripts still clean up.

    Protecting every tracked id would preserve later Forge-created transcripts
    indefinitely; `adoption.source_path` and the `reason="adopt"` artifact name
    the user's conversation exactly.
    """
    project, native = _adopted_project(tmp_path)
    forge_owned = "dddd4444-5555-6666-7777-888899990000"

    store = SessionStore(str(project), "adopted")
    state = store.read()
    state.confirmed.artifacts["transcripts"].append({"reason": "stop", "session_id": forge_owned, "copied": True})
    store.write(state)

    later = get_transcript_path(str(project), forge_owned)
    later.parent.mkdir(parents=True, exist_ok=True)
    later.write_text("{}\n", encoding="utf-8")

    SessionManager().delete_session("adopted", forge_root=str(project))

    assert native.is_file(), "the adopted source is the user's"
    assert not later.exists(), "a transcript Forge created for this session is Forge's to remove"

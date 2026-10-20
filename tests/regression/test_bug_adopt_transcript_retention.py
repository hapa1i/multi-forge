"""Regression: ordinary delete preserves adopted, new and rollover native transcripts."""

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


def test_a_normal_session_also_preserves_its_native_transcript(tmp_path: Path) -> None:
    """The ordinary deletion contract now preserves all native conversations."""
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

    assert owned.read_text() == "{}\n"


def test_adopted_source_and_later_native_transcripts_are_preserved(tmp_path: Path) -> None:
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
    assert later.read_text() == "{}\n"

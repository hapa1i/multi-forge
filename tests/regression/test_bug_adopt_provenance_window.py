"""Adoption publishes source provenance atomically and preserves it through interrupted capture.

Ordinary deletion now preserves all native conversations. Explicit purge still
needs provenance recorded before a possible crash in artifact copying.
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

_UUID = "eeee5555-6666-7777-8888-99990000aaaa"


def _kill_window_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Return (project, native) with an adopt killed right after publish.

    The kill is simulated at `safe_copy_file` -- the first statement after
    `start_session` returns -- via KeyboardInterrupt, which `except Exception`
    does not catch, so `_rollback_adoption` never runs. This is the earliest
    point in the old unprotected window and therefore the strictest test of it.
    """
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

    import forge.core.ops.session_adopt as adopt_mod

    def _die(*_args: object, **_kwargs: object) -> bool:
        raise KeyboardInterrupt("killed after start_session, before the artifact update")

    monkeypatch.setattr(adopt_mod, "safe_copy_file", _die)

    ctx = ExecutionContext.from_cwd(project)
    with pytest.raises(KeyboardInterrupt):
        adopt_session(ctx, plan_adoption(ctx, _UUID), name="half-adopted")

    # The window state this regression is about: published and bound.
    state = SessionStore(str(project), "half-adopted").read()
    assert state.confirmed.claude_session_id == _UUID, "binding must already be published"
    return project, native


def test_adoption_provenance_survives_a_kill_before_the_artifact_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Provenance must ride the same write that publishes the binding."""
    project, native = _kill_window_state(tmp_path, monkeypatch)

    adoption = SessionStore(str(project), "half-adopted").read().confirmed.adoption
    assert adoption is not None, "a bound adopted session must never exist without provenance"
    assert adoption.source_path == str(native)
    assert adoption.source_runtime == "claude_code"


def test_deleting_a_kill_window_session_spares_the_native_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, native = _kill_window_state(tmp_path, monkeypatch)
    original = native.read_bytes()

    SessionManager().delete_session("half-adopted", forge_root=str(project))

    assert native.is_file(), "the user's native conversation must survive the half-adopted delete"
    assert native.read_bytes() == original
    assert not (project / ".forge" / "sessions" / "half-adopted").exists(), "the session itself is still deleted"

"""Regression: a binding-lookup failure inside the name-collision handler leaked untyped.

Bug: PR #114 review round 4, LOW.
Root cause: `adopt_session` and `adopt_codex_session` remap a name-collision
`SessionExistsError` to `UuidAlreadyBoundError` by re-querying the bound
conversations -- but unlike every other call site, that re-query was not
wrapped. `BindingLookupError` extends `SessionContextError(RuntimeError)`,
which none of the CLI leaf's handlers catch (`AdoptError`,
`ForgeSessionError`, `UuidAlreadyBoundError`, `SessionExistsError`), so an
index or manifest turning unreadable in that window surfaced as a raw
traceback instead of the op's typed vocabulary.

Fix: both handlers wrap the re-query in `AdoptError`, matching the plan and
in-lock call sites.

Affected: src/forge/core/ops/session_adopt.py, src/forge/core/ops/codex_adopt.py
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from forge.core.ops.codex_adopt import adopt_codex_session, plan_codex_adoption
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session_adopt import AdoptError, adopt_session, plan_adoption
from forge.core.ops.session_context import BindingLookupError
from forge.session import SessionManager
from forge.session.claude.paths import get_transcript_path

pytestmark = pytest.mark.regression

_UUID = "ffff6666-7777-8888-9999-0000aaaabbbb"
_THREAD = "019f0c76-c62d-7794-aad8-cc59218f8c94"


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    (project / ".forge").mkdir()
    return project


def _take_name(project: Path, name: str) -> None:
    """Create an unrelated session so the adopt's name collides."""
    SessionManager().start_session(name, worktree_path=str(project), direct=True)


def _script_second_call(monkeypatch: pytest.MonkeyPatch, module: object, attr: str) -> None:
    """Delegate the first collector call, raise BindingLookupError on the second.

    Inside the adopt ops the collector runs twice: the in-lock adoptability check
    (which must succeed so the op reaches `start_session` and its name
    collision), then the collision handler's re-query -- the unwrapped read this
    regression is about. An iterator, not call counting against the real
    function, so an added call fails loudly (StopIteration) instead of shifting
    which read raises.
    """
    real = getattr(module, attr)
    outcomes = iter(["delegate", "raise"])

    def scripted(root: str) -> dict[str, str]:
        if next(outcomes) == "raise":
            raise BindingLookupError("the session index turned unreadable mid-adopt")
        return dict(real(root))

    monkeypatch.setattr(module, attr, scripted)


def test_claude_name_collision_with_unreadable_bindings_stays_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import forge.core.ops.session_adopt as adopt_mod

    project = _make_project(tmp_path)
    entries = [
        {"type": "user", "cwd": str(project), "message": {"role": "user"}},
        {"type": "assistant", "cwd": str(project), "message": {"model": "claude-opus-5"}},
    ]
    native = get_transcript_path(str(project), _UUID)
    native.parent.mkdir(parents=True, exist_ok=True)
    native.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    os.utime(native, (0, 0))

    ctx = ExecutionContext.from_cwd(project)
    plan = plan_adoption(ctx, _UUID)
    _take_name(project, "taken")
    _script_second_call(monkeypatch, adopt_mod, "collect_bound_uuids")

    with pytest.raises(AdoptError, match="unreadable mid-adopt"):
        adopt_session(ctx, plan, name="taken")


def test_codex_name_collision_with_unreadable_bindings_stays_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import forge.core.ops.codex_adopt as codex_mod

    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))

    class _Preflight:
        auth_method = "codex_store"
        auth_source = "chatgpt"
        billing_mode = "subscription"

    monkeypatch.setattr(codex_mod, "assert_codex_ready", lambda **_: _Preflight())

    project = _make_project(tmp_path)
    day_dir = tmp_path / "codex" / "sessions" / "2026" / "07" / "27"
    day_dir.mkdir(parents=True)
    rollout = day_dir / f"rollout-2026-07-27T10-00-00-{_THREAD}.jsonl"
    rollout.write_text(
        json.dumps({"type": "session_meta", "payload": {"id": _THREAD, "cwd": str(project)}}) + "\n",
        encoding="utf-8",
    )
    os.utime(rollout, (0, 0))

    ctx = ExecutionContext.from_cwd(project)
    plan = plan_codex_adoption(ctx, _THREAD)
    _take_name(project, "taken")
    _script_second_call(monkeypatch, codex_mod, "collect_bound_codex_threads")

    with pytest.raises(AdoptError, match="unreadable mid-adopt"):
        adopt_codex_session(ctx, plan, name="taken")

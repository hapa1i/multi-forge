"""Two concurrent adopts must not bind one Codex thread to two sessions.

Bug: native_session_adoption Slice 4. ``adopt_codex_session`` checked thread
uniqueness with ``collect_bound_codex_threads``, created the session with
``start_session``, then wrote ``confirmed.codex`` in a separate ``store.update``.
The check and the write took different locks (index vs. per-session manifest), so
two differently-named adopts of one thread both passed the check and both bound.
The same split left an indexed Codex session with ``confirmed.codex = None`` if the
process died between the two writes.

Root cause: Codex thread ids had no index column, so nothing could be checked under
the index write lock -- the only lock shared across session names.

Affected: src/forge/core/ops/codex_adopt.py, src/forge/session/manager.py,
src/forge/session/index.py, src/forge/session/models.py.
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest

from forge.core.ops import codex_adopt
from forge.core.ops.codex_adopt import adopt_codex_session, plan_codex_adoption
from forge.core.ops.context import ExecutionContext
from forge.session import SessionStore, UuidAlreadyBoundError

pytestmark = pytest.mark.regression

_THREAD = "019f0b65-b51c-7683-99c7-bb48107f7b83"


class _Preflight:
    auth_method = "codex_store"
    auth_source = "chatgpt"
    billing_mode = "subscription"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(codex_adopt, "assert_codex_ready", lambda **_: _Preflight())
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))

    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".forge").mkdir()

    day = tmp_path / "codex" / "sessions" / "2026" / "06" / "27"
    day.mkdir(parents=True)
    rollout = day / f"rollout-2026-06-27T19-24-02-{_THREAD}.jsonl"
    rollout.write_text(
        json.dumps({"type": "session_meta", "payload": {"id": _THREAD, "cwd": str(root)}}) + "\n",
        encoding="utf-8",
    )
    return root


def test_interleaved_adopts_bind_the_thread_once(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both adopts pass the pre-check; exactly one may reach a manifest."""
    ctx = ExecutionContext.from_cwd(project)
    plan = plan_codex_adoption(ctx, _THREAD)

    # Release both threads only once each has seen the thread id as free, which is
    # the interleaving the single-lock check cannot survive.
    barrier = threading.Barrier(2)
    real = codex_adopt.collect_bound_codex_threads

    def gated(*args: object, **kwargs: object) -> dict[str, str]:
        result = real(*args, **kwargs)  # type: ignore[arg-type]  # passthrough
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(codex_adopt, "collect_bound_codex_threads", gated)

    errors: dict[str, BaseException] = {}

    def run(name: str) -> None:
        try:
            adopt_codex_session(ctx, plan, name=name)
        except BaseException as e:  # noqa: BLE001  # the assertion is on which type surfaced
            errors[name] = e

    threads = [threading.Thread(target=run, args=(n,)) for n in ("alpha", "beta")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    bound = {
        name: state.confirmed.codex.thread_id
        for name in ("alpha", "beta")
        if (store := SessionStore(str(project), name)).exists() and (state := store.read()).confirmed.codex is not None
    }
    assert list(bound.values()) in ([_THREAD], []), f"thread bound {len(bound)} times: {bound}"
    assert len(errors) == 1, f"exactly one adopt must be rejected, got {errors}"
    assert isinstance(next(iter(errors.values())), UuidAlreadyBoundError)


def test_a_published_codex_session_always_carries_its_binding(project: Path) -> None:
    """The manifest and index row are written with the thread id, not after it."""
    ctx = ExecutionContext.from_cwd(project)
    result = adopt_codex_session(ctx, plan_codex_adoption(ctx, _THREAD), name="solo")

    from forge.session.index import IndexStore

    state = SessionStore(str(project), result.name).read()
    assert state.confirmed.codex is not None
    assert state.confirmed.codex.thread_id == _THREAD

    rows = [e for e in IndexStore().read().sessions.values() if e.forge_root == str(project)]
    assert [e.codex_thread_id for e in rows] == [_THREAD], "the index must carry the id it locks on"

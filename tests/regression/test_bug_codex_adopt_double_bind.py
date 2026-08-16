"""One Codex thread must never end up bound to two Forge manifests.

Bug: native_session_adoption Slice 4/4a. Two defects, found in successive reviews:

1. ``adopt_codex_session`` checked thread uniqueness, created the session, then
   wrote ``confirmed.codex`` in a separate ``store.update``. The check took the
   index lock and the write took the session's manifest lock, so two
   differently-named adopts both passed and both bound.
2. Fixing (1) by committing the thread id with the session narrowed the window but
   did not close it. Session creation writes the manifest *before* the index row,
   so an adopt killed between the two leaves an orphan manifest that owns the
   thread and never reached the index. A concurrent adopt whose scan ran before
   that manifest appeared still published a second binding, and the orphan scan
   could then only refuse the *third* attempt.

Root cause of (1): Codex thread ids had no index column, so nothing could be
checked under the index write lock. Of (2): the index write lock cannot see a
binding that never reached the index.

Affected: src/forge/core/ops/codex_adopt.py, src/forge/core/ops/session_adopt.py,
src/forge/session/manager.py, src/forge/session/index.py, src/forge/session/models.py.
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest

from forge.core.ops import codex_adopt, session_adopt
from forge.core.ops.codex_adopt import adopt_codex_session, plan_codex_adoption
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session_adopt import AdoptError, conversation_lock
from forge.session import SessionStore, UuidAlreadyBoundError, create_session_state
from forge.session.models import CodexConfirmed

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


def _bound_manifests(project: Path, *names: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for name in names:
        store = SessionStore(str(project), name)
        if not store.exists():
            continue
        codex = store.read().confirmed.codex
        if codex is not None and codex.thread_id:
            found[name] = codex.thread_id
    return found


def test_the_conversation_lock_excludes_a_concurrent_adopt(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing else may adopt this conversation while one adopt is committing.

    This is what defect (2) needs: the losing adopt must not be able to run its
    scan *and* write its manifest inside the winner's scan-to-commit window. The
    index write lock cannot enforce that, because the manifest is written first
    and a killed adopt never reaches the index at all.

    Asserted directly on the lock rather than through two racing adopts: with only
    the index guard in place, two racing adopts still resolve correctly, so such a
    test would pass without this fix and prove nothing about it.
    """
    monkeypatch.setattr(session_adopt, "CLI_LOCK_TIMEOUT_S", 0.3)
    ctx = ExecutionContext.from_cwd(project)
    plan = plan_codex_adoption(ctx, _THREAD)

    inside = threading.Event()
    release = threading.Event()
    real_collect = codex_adopt.collect_bound_codex_threads

    def gated(*args: object, **kwargs: object) -> dict[str, str]:
        result = real_collect(*args, **kwargs)  # type: ignore[arg-type]  # passthrough
        inside.set()
        release.wait(timeout=15)
        return result

    monkeypatch.setattr(codex_adopt, "collect_bound_codex_threads", gated)

    outcome: dict[str, object] = {}

    def winner() -> None:
        try:
            outcome["result"] = adopt_codex_session(ctx, plan, name="winner")
        except BaseException as e:  # noqa: BLE001  # surfaced in the assertion below
            outcome["error"] = e

    thread = threading.Thread(target=winner)
    thread.start()
    assert inside.wait(timeout=15), "the winning adopt never entered its critical section"

    try:
        with pytest.raises(AdoptError, match="in progress"):
            with conversation_lock(_THREAD):
                pass
    finally:
        release.set()
        thread.join(timeout=30)

    assert "error" not in outcome, f"the winner should have completed: {outcome.get('error')!r}"
    assert _bound_manifests(project, "winner") == {"winner": _THREAD}


def test_interleaved_adopts_bind_the_thread_once(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two adopts released together must produce exactly one binding.

    Covers defect (1): the index column and in-lock uniqueness check. The barrier
    sits just BEFORE ``conversation_lock``, so both calls are inside
    ``adopt_codex_session`` with the thread still unbound when released; gating any
    later point would deadlock against the lock that defect (2) added.
    """
    ctx = ExecutionContext.from_cwd(project)
    plan = plan_codex_adoption(ctx, _THREAD)

    barrier = threading.Barrier(2)
    real_find = codex_adopt.find_adoptable_rollout

    def gated(*args: object, **kwargs: object) -> Path:
        found = real_find(*args, **kwargs)  # type: ignore[arg-type]  # passthrough
        barrier.wait(timeout=15)
        return found

    monkeypatch.setattr(codex_adopt, "find_adoptable_rollout", gated)

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
        t.join(timeout=45)

    bound = _bound_manifests(project, "alpha", "beta")
    assert list(bound.values()) == [_THREAD], f"expected exactly one bound manifest, got {bound}"
    assert len(errors) == 1, f"exactly one adopt must be rejected, got {errors}"
    assert isinstance(next(iter(errors.values())), UuidAlreadyBoundError)


def test_an_orphan_manifest_from_a_killed_adopt_blocks_the_next_one(project: Path) -> None:
    """A binding that never reached the index still owns the thread.

    Reproduces what a SIGKILL between the legacy manifest and index writes leaves
    behind: a manifest carrying the thread id, with no index row. The index
    write lock cannot see it, so only the orphan scan can.
    """
    ctx = ExecutionContext.from_cwd(project)
    plan = plan_codex_adoption(ctx, _THREAD)

    killed = create_session_state(name="killed-adopt", worktree_path=str(project))
    killed.confirmed.codex = CodexConfirmed(
        thread_id=_THREAD, rollout_path=str(plan.rollout_path), rollout_source="adopted"
    )
    SessionStore(str(project), "killed-adopt").create_exclusive(killed)

    from forge.session.index import IndexStore

    assert not IndexStore().read().sessions, "the fixture must leave the index empty to be an orphan"

    with pytest.raises(UuidAlreadyBoundError) as caught:
        adopt_codex_session(ctx, plan, name="second")

    assert caught.value.owner == "killed-adopt"
    assert not SessionStore(str(project), "second").exists()


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

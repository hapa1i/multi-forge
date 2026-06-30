"""Tests for the best-effort first-dispatch lane freeze (epic consumer_lanes T6a).

``persist_lane_freeze`` is the CLI/hook-boundary wrapper the three aux consumers call
right before dispatch. It must (1) skip the write lock on the hot path, (2) freeze a
declared lane write-once, and (3) swallow a persist failure (billing reads intent anyway).
"""

from __future__ import annotations

from pathlib import Path

from pytest import fixture

from forge.cli.consumer_lane_freeze import persist_lane_freeze
from forge.session import SessionStore, create_session_state
from forge.session.consumer_lanes import ensure_consumer_lane_binding, set_intent_lane
from forge.session.memory_writer import MEMORY_WRITER_CONSUMER
from forge.session.models import LaneRecord

_CLAUDE_MAX = LaneRecord("claude_code", "claude-max", "opus")


@fixture
def store(tmp_path: Path) -> SessionStore:
    """A real on-disk session store for the 'worker' session (no index needed -- the helper
    takes the store directly, it does not resolve_session)."""
    (tmp_path / ".forge").mkdir()
    s = SessionStore(str(tmp_path), "worker")
    s.write(create_session_state("worker", worktree_path=str(tmp_path)))
    return s


def _declare(store: SessionStore, record: LaneRecord) -> None:
    state = store.read()
    set_intent_lane(state, MEMORY_WRITER_CONSUMER, record)
    store.write(state)


def test_freezes_declared_lane(store: SessionStore) -> None:
    _declare(store, _CLAUDE_MAX)
    persist_lane_freeze(store, store.read(), MEMORY_WRITER_CONSUMER)
    confirmed = store.read().confirmed.consumer_lanes
    assert confirmed is not None and confirmed.memory_writer is not None
    assert confirmed.memory_writer.lane == _CLAUDE_MAX


def test_skips_lock_when_undeclared(store: SessionStore, monkeypatch) -> None:
    """No declaration -> the default lane is never frozen, and no write lock is taken."""
    calls: list[int] = []
    monkeypatch.setattr(store, "update", lambda **kw: calls.append(1))
    persist_lane_freeze(store, store.read(), MEMORY_WRITER_CONSUMER)
    assert calls == []
    assert store.read().confirmed.consumer_lanes is None


def test_skips_lock_when_already_frozen(store: SessionStore, monkeypatch) -> None:
    """Steady state after the first dispatch: confirmed is set, so no lock is taken again."""
    state = store.read()
    ensure_consumer_lane_binding(state, MEMORY_WRITER_CONSUMER, _CLAUDE_MAX)
    store.write(state)
    calls: list[int] = []
    monkeypatch.setattr(store, "update", lambda **kw: calls.append(1))
    persist_lane_freeze(store, store.read(), MEMORY_WRITER_CONSUMER)
    assert calls == []


def test_swallows_persist_failure(store: SessionStore, monkeypatch) -> None:
    """A lock/IO failure must not abort the run; the freeze just doesn't land (billing reads intent)."""
    _declare(store, _CLAUDE_MAX)

    def _boom(**kw: object) -> None:
        raise RuntimeError("lock timeout")

    monkeypatch.setattr(store, "update", _boom)
    persist_lane_freeze(store, store.read(), MEMORY_WRITER_CONSUMER)  # must not raise
    confirmed = store.read().confirmed.consumer_lanes
    assert confirmed is None or confirmed.memory_writer is None

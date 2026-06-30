"""Tests for the dispatch-time lane freeze helper (epic consumer_lanes T6a).

``persist_lane_freeze`` is the CLI/hook-boundary wrapper the aux consumers call from their
``on_dispatch`` hook. It must (1) freeze the *threaded* dispatched lane (not a fresh read,
so confirmed can't diverge from the billed backend), (2) drop the write under an equality
guard if a concurrent edit changed the lane, (3) no-op on the default lane, (4) forward the
timeout, and (5) swallow a persist failure.
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
    (tmp_path / ".forge").mkdir()
    s = SessionStore(str(tmp_path), "worker")
    s.write(create_session_state("worker", worktree_path=str(tmp_path)))
    return s


def _declare(store: SessionStore, record: LaneRecord) -> None:
    state = store.read()
    set_intent_lane(state, MEMORY_WRITER_CONSUMER, record)
    store.write(state)


def test_freezes_dispatched_lane(store: SessionStore) -> None:
    """The manifest still dispatches the threaded lane -> it freezes into confirmed."""
    _declare(store, _CLAUDE_MAX)
    persist_lane_freeze(store, MEMORY_WRITER_CONSUMER, _CLAUDE_MAX)
    confirmed = store.read().confirmed.consumer_lanes
    assert confirmed is not None and confirmed.memory_writer is not None
    assert confirmed.memory_writer.lane == _CLAUDE_MAX


def test_equality_guard_drops_a_stale_lane(store: SessionStore) -> None:
    """A concurrent clear/re-pin between dispatch and freeze: the manifest no longer dispatches
    the threaded lane, so the stale freeze is dropped (mirrors the supervisor guard)."""
    # Nothing declared now (simulating a `lane clear` after dispatch), but the run dispatched claude-max.
    persist_lane_freeze(store, MEMORY_WRITER_CONSUMER, _CLAUDE_MAX)
    assert store.read().confirmed.consumer_lanes is None


def test_none_dispatched_lane_never_freezes(store: SessionStore, monkeypatch) -> None:
    """The default lane (None) is never frozen, and no write lock is taken."""
    calls: list[int] = []
    monkeypatch.setattr(store, "update", lambda **kw: calls.append(1))
    persist_lane_freeze(store, MEMORY_WRITER_CONSUMER, None)
    assert calls == []
    assert store.read().confirmed.consumer_lanes is None


def test_write_once_when_already_frozen(store: SessionStore) -> None:
    """A second dispatch with the same lane is a no-op (write-once); confirmed is unchanged."""
    state = store.read()
    ensure_consumer_lane_binding(state, MEMORY_WRITER_CONSUMER, _CLAUDE_MAX)
    set_intent_lane(state, MEMORY_WRITER_CONSUMER, _CLAUDE_MAX)
    store.write(state)
    persist_lane_freeze(store, MEMORY_WRITER_CONSUMER, _CLAUDE_MAX)
    confirmed = store.read().confirmed.consumer_lanes
    assert confirmed is not None and confirmed.memory_writer is not None
    assert confirmed.memory_writer.lane == _CLAUDE_MAX


def test_forwards_timeout(store: SessionStore, monkeypatch) -> None:
    """The per-call timeout reaches store.update (hook sites pass the short HOOK_LOCK_TIMEOUT_S)."""
    seen: dict[str, float] = {}
    monkeypatch.setattr(store, "update", lambda **kw: seen.update(timeout_s=kw["timeout_s"]))
    persist_lane_freeze(store, MEMORY_WRITER_CONSUMER, _CLAUDE_MAX, timeout_s=0.2)
    assert seen["timeout_s"] == 0.2


def test_swallows_persist_failure(store: SessionStore, monkeypatch) -> None:
    """A lock/IO failure must not abort the run; the freeze just doesn't land."""
    _declare(store, _CLAUDE_MAX)

    def _boom(**kw: object) -> None:
        raise RuntimeError("lock timeout")

    monkeypatch.setattr(store, "update", _boom)
    persist_lane_freeze(store, MEMORY_WRITER_CONSUMER, _CLAUDE_MAX)  # must not raise
    confirmed = store.read().confirmed.consumer_lanes
    assert confirmed is None or confirmed.memory_writer is None

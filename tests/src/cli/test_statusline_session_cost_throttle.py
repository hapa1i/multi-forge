"""Tests for the time-only per-session cost throttle (Phase 5d).

``read_or_compute_session_cost`` backs the ``forge_cost`` status-line segment. It
differs from ``read_or_compute`` (the cache-hit-rate throttle) in three ways the
card requires:

- **Time-only** (no transcript mtime): headless cost accrues via ledger writes
  that never touch the transcript, so an mtime "unchanged" shortcut would freeze
  ``forge +$Y`` for the whole session (card R4).
- **Caches a legitimate ``0``** (#5): a no-cost session must not re-scan the
  PID-sharded ledger on every poll.
- **Keyed on FORGE session identity** (#6), not the Claude stdin ``session_id``
  (which rolls on every ``/compact`` and would fragment the cache).

A compute failure is fail-open and uncached.
"""

from __future__ import annotations

import json

import pytest

from forge.cli.statusline.throttle import (
    _session_cost_cache_path,
    _session_health_cache_path,
    _valid_health_fields,
    read_or_compute_session_cost,
    read_or_compute_session_health,
)
from forge.core.ops.usage_summary import SupervisorHealth


def _counter(value: int):
    calls = {"n": 0}

    def compute() -> int:
        calls["n"] += 1
        return value

    return compute, calls


def test_reuses_within_ttl() -> None:
    compute, calls = _counter(50_000)
    v1 = read_or_compute_session_cost("k", ttl=100, compute_fn=compute, now=1000.0)
    v2 = read_or_compute_session_cost("k", ttl=100, compute_fn=compute, now=1050.0)
    assert v1 == v2 == 50_000
    assert calls["n"] == 1, "second poll within TTL reuses the cache"


def test_recomputes_after_ttl() -> None:
    compute, calls = _counter(50_000)
    read_or_compute_session_cost("k", ttl=10, compute_fn=compute, now=1000.0)
    read_or_compute_session_cost("k", ttl=10, compute_fn=compute, now=1011.0)
    assert calls["n"] == 2, "past the TTL window the value is recomputed"


def test_caches_legitimate_zero() -> None:
    # #5: a no-cost session caches 0 and does NOT re-scan the ledger within TTL.
    compute, calls = _counter(0)
    v1 = read_or_compute_session_cost("k0", ttl=100, compute_fn=compute, now=1000.0)
    v2 = read_or_compute_session_cost("k0", ttl=100, compute_fn=compute, now=1001.0)
    assert v1 == 0 and v2 == 0
    assert calls["n"] == 1, "0 is a real, cacheable result -- not treated as a miss"


def test_distinct_keys_do_not_share_cache() -> None:
    compute_a, calls_a = _counter(10)
    compute_b, calls_b = _counter(20)
    assert read_or_compute_session_cost("ka", ttl=100, compute_fn=compute_a, now=1000.0) == 10
    assert read_or_compute_session_cost("kb", ttl=100, compute_fn=compute_b, now=1000.0) == 20
    assert calls_a["n"] == 1 and calls_b["n"] == 1


def test_same_forge_identity_reuses_regardless_of_claude_uuid() -> None:
    # #6: the key is the FORGE session identity. Two polls that would carry
    # different Claude stdin session_ids (UUID rolls on /compact) but the SAME
    # forge identity key must reuse -- the UUID is never part of the key.
    compute, calls = _counter(7_000)
    forge_key = "forge_root\x00sess-a"
    read_or_compute_session_cost(forge_key, ttl=100, compute_fn=compute, now=1000.0)
    read_or_compute_session_cost(forge_key, ttl=100, compute_fn=compute, now=1001.0)
    assert calls["n"] == 1


def test_compute_failure_is_fail_open_and_uncached() -> None:
    state = {"n": 0}

    def flaky() -> int:
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("transient ledger read error")
        return 9_000

    # First poll: compute raises -> None, and NOTHING is cached.
    assert read_or_compute_session_cost("kf", ttl=100, compute_fn=flaky, now=1000.0) is None
    # Next poll (within TTL): recomputes (failure was not cached) and recovers.
    assert read_or_compute_session_cost("kf", ttl=100, compute_fn=flaky, now=1001.0) == 9_000
    assert state["n"] == 2


def test_corrupt_cache_falls_back_to_recompute() -> None:
    # Runtime-only state: a malformed cache file must degrade to recompute, not raise.
    path = _session_cost_cache_path("kc")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not valid json", encoding="utf-8")

    compute, calls = _counter(3_000)
    assert read_or_compute_session_cost("kc", ttl=100, compute_fn=compute, now=1000.0) == 3_000
    assert calls["n"] == 1


def test_wrong_typed_cache_value_is_ignored() -> None:
    # A structurally-valid entry with a bad value type (or a bool masquerading as
    # int) must not be trusted -- recompute instead.
    path = _session_cost_cache_path("kt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "computed_at": 1000.0, "cost_micro_usd": "oops"}), encoding="utf-8")

    compute, calls = _counter(2_000)
    assert read_or_compute_session_cost("kt", ttl=100, compute_fn=compute, now=1000.5) == 2_000
    assert calls["n"] == 1


def test_uses_fcost_namespace() -> None:
    # Distinct filename namespace from the cache-hit throttle entries.
    assert _session_cost_cache_path("k").name.startswith("fcost-")


# --- Supervisor-health throttle (sibling of the cost throttle) ----------------


def _health_counter(health: SupervisorHealth):
    calls = {"n": 0}

    def compute() -> SupervisorHealth:
        calls["n"] += 1
        return health

    return compute, calls


def test_health_reuses_within_ttl() -> None:
    compute, calls = _health_counter(SupervisorHealth(3, "timeout", "ts"))
    a = read_or_compute_session_health("kh", ttl=100, compute_fn=compute, now=1000.0)
    b = read_or_compute_session_health("kh", ttl=100, compute_fn=compute, now=1050.0)
    assert a == b == SupervisorHealth(3, "timeout", "ts")
    assert calls["n"] == 1, "second poll within TTL reuses the cache"


def test_health_caches_empty_result() -> None:
    # An empty (healthy) result is a real, cacheable value -- a healthy supervisor must
    # not re-scan the PID-sharded ledger on every poll.
    compute, calls = _health_counter(SupervisorHealth())
    a = read_or_compute_session_health("khe", ttl=100, compute_fn=compute, now=1000.0)
    b = read_or_compute_session_health("khe", ttl=100, compute_fn=compute, now=1001.0)
    assert a == b == SupervisorHealth()
    assert calls["n"] == 1


def test_health_reconstructs_valid_cached_triple() -> None:
    path = _session_health_cache_path("kok")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "computed_at": 1000.0,
                "recent_failures": 3,
                "last_kind": "timeout",
                "last_seen_at": "2026-06-16T00:00:03Z",
            }
        ),
        encoding="utf-8",
    )
    compute, calls = _health_counter(SupervisorHealth())  # must NOT be called
    out = read_or_compute_session_health("kok", ttl=100, compute_fn=compute, now=1000.5)
    assert out == SupervisorHealth(3, "timeout", "2026-06-16T00:00:03Z")
    assert calls["n"] == 0, "a valid fresh cache entry is reused, not recomputed"


def test_health_compute_failure_is_fail_open_and_uncached() -> None:
    state = {"n": 0}

    def flaky() -> SupervisorHealth:
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("transient ledger read error")
        return SupervisorHealth(1, "error", "ts")

    # First poll: compute raises -> None, and NOTHING is cached.
    assert read_or_compute_session_health("khf", ttl=100, compute_fn=flaky, now=1000.0) is None
    # Next poll (within TTL): recomputes (failure was not cached) and recovers.
    assert read_or_compute_session_health("khf", ttl=100, compute_fn=flaky, now=1001.0) == SupervisorHealth(
        1, "error", "ts"
    )
    assert state["n"] == 2


@pytest.mark.parametrize(
    "entry",
    [
        # recent_failures==0 must have BOTH last_kind and last_seen_at None.
        {"recent_failures": 0, "last_kind": "timeout", "last_seen_at": None},
        {"recent_failures": 0, "last_kind": None, "last_seen_at": "ts"},
        # recent_failures>0 must have a valid kind AND a string last_seen_at.
        {"recent_failures": 3, "last_kind": "banana", "last_seen_at": "ts"},
        {"recent_failures": 3, "last_kind": "timeout", "last_seen_at": None},
        {"recent_failures": 3, "last_kind": None, "last_seen_at": "ts"},
    ],
)
def test_health_semantic_invalid_cache_recomputes(entry: dict) -> None:
    # A hand-corrupted runtime cache that violates the reader's invariant must be treated
    # as a miss (recompute), never fed to the renderer.
    path = _session_health_cache_path("kbad")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "computed_at": 1000.0, **entry}), encoding="utf-8")
    compute, calls = _health_counter(SupervisorHealth(2, "error", "2026-06-16T00:00:00Z"))
    out = read_or_compute_session_health("kbad", ttl=100, compute_fn=compute, now=1000.5)
    assert out == SupervisorHealth(2, "error", "2026-06-16T00:00:00Z")
    assert calls["n"] == 1, "invalid cache entry treated as a miss"


def test_uses_fhealth_namespace() -> None:
    assert _session_health_cache_path("k").name.startswith("fhealth-")


@pytest.mark.parametrize(
    "recent_failures,last_kind,last_seen_at,expected",
    [
        (0, None, None, True),
        (3, "timeout", "2026-06-16T00:00:00Z", True),
        (1, "error", "2026-06-16T00:00:00Z", True),
        (0, "timeout", None, False),  # kind set with a 0 count
        (0, None, "ts", False),  # last_seen set with a 0 count
        (3, None, "ts", False),  # missing kind with a positive count
        (3, "timeout", None, False),  # missing last_seen with a positive count
        (3, "banana", "ts", False),  # kind outside {timeout, error}
        (-1, None, None, False),  # negative count
        (True, None, None, False),  # bool masquerading as int
        ("3", "timeout", "ts", False),  # non-int count
    ],
)
def test_valid_health_fields(recent_failures: object, last_kind: object, last_seen_at: object, expected: bool) -> None:
    assert _valid_health_fields(recent_failures, last_kind, last_seen_at) is expected

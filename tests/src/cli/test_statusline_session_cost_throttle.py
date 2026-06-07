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

from forge.cli.statusline.throttle import (
    _session_cost_cache_path,
    read_or_compute_session_cost,
)


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

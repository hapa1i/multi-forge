"""Regression: a structurally-valid but wrong-typed throttle cache entry crashed
the status line.

Bug: ``throttle.read_or_compute`` did ``now - cached["computed_at"]`` without
type-guarding the field. A cache file like ``{"version": 1, "computed_at":
"bad", ...}`` passes the JSON/version checks, then raises ``TypeError`` on the
arithmetic — violating the runtime-only-state fail-open contract (cache failures
must degrade to recompute, never raise).

Root cause / fix: ``src/forge/cli/statusline/throttle.py`` — guard
``computed_at`` and ``cache_hit_rate`` with ``isinstance`` before using them, so
a malformed entry falls through to recompute.
"""

from __future__ import annotations

import json

import pytest

from forge.cli.statusline.throttle import _cache_path, read_or_compute

pytestmark = pytest.mark.regression


def _transcript(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(
        json.dumps({"requestId": "r1", "message": {"usage": {"input_tokens": 100, "cache_read_input_tokens": 50}}})
    )
    return str(p)


def _seed_cache(session, path, payload):
    cp = _cache_path(session, path)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(payload))


def test_non_numeric_computed_at_recomputes(tmp_path):
    path = _transcript(tmp_path)
    _seed_cache(
        "s",
        path,
        {"version": 1, "computed_at": "bad", "cache_hit_rate": 12.0, "transcript_mtime_ns": 1, "transcript_size": 2},
    )
    # Must not raise; falls through to recompute.
    assert read_or_compute(path, "s", 12, lambda p: 50.0, now=1000.0) == 50.0


def test_non_numeric_cache_hit_rate_recomputes(tmp_path):
    path = _transcript(tmp_path)
    _seed_cache(
        "s",
        path,
        {"version": 1, "computed_at": 1000.0, "cache_hit_rate": "lots", "transcript_mtime_ns": 1, "transcript_size": 2},
    )
    assert read_or_compute(path, "s", 12, lambda p: 42.0, now=1000.5) == 42.0


def test_missing_computed_at_recomputes(tmp_path):
    path = _transcript(tmp_path)
    _seed_cache("s", path, {"version": 1, "cache_hit_rate": 12.0})
    assert read_or_compute(path, "s", 12, lambda p: 7.0, now=1000.0) == 7.0

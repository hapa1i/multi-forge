"""File-backed throttle for the direct-mode cache-hit-rate computation.

Each status-line render is a fresh process, so in-memory caches don't persist
(card finding #1). To avoid re-scanning the transcript on every poll, the
computed rate is cached on disk keyed by a hash of the session id (or transcript
path). The cached value is reused while the transcript is unchanged OR the entry
is younger than ``cache_hit_ttl`` — so a busy session recomputes at most once per
TTL window, not once per render.

This is runtime-only state: a version mismatch or any I/O error means recompute
(or skip), never raise — the status line must always exit 0.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from forge.core.paths import get_forge_home

CACHE_VERSION = 1


def _cache_path(session_id: str | None, transcript_path: str) -> Path:
    # Derive a stable, filesystem-safe filename from the identity — never put a raw
    # stdin session_id in the path (system-boundary hardening: odd characters /
    # traversal). SHA-256 with usedforsecurity=False: this is a non-cryptographic
    # filename derivation, not a security primitive (SHA-1 is avoided as broken).
    identity = session_id or transcript_path or ""
    digest = hashlib.sha256(identity.encode("utf-8"), usedforsecurity=False).hexdigest()
    return get_forge_home() / "cache" / "statusline" / f"{digest}.json"


def _read(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, str(path))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except OSError:
        # Best-effort: a failed cache write just means recompute next time.
        pass


def read_or_compute(
    transcript_path: str,
    session_id: str | None,
    ttl: int,
    compute_fn: Callable[[str], float | None],
    *,
    now: float | None = None,
) -> float | None:
    """Return a cached cache-hit-rate or recompute + persist it.

    Reuses the cached value when the transcript is unchanged (same mtime+size) OR
    the entry is within ``ttl`` seconds. Recomputes otherwise. All failures
    fail-open (recompute or return None); a ``None`` recompute is not cached.
    """
    if now is None:
        now = time.time()

    try:
        st = Path(transcript_path).stat()
        mtime_ns: int | None = st.st_mtime_ns
        size: int | None = st.st_size
    except OSError:
        mtime_ns, size = None, None

    path = _cache_path(session_id, transcript_path)
    cached = _read(path)
    if cached is not None and cached.get("version") == CACHE_VERSION:
        # A structurally-valid JSON entry can still carry wrong-typed fields
        # (e.g. computed_at: "bad"). Guard every value used in arithmetic so a
        # malformed entry degrades to recompute instead of raising (runtime-only
        # state must never crash the status line).
        rate = cached.get("cache_hit_rate")
        computed_at = cached.get("computed_at")
        unchanged = (
            mtime_ns is not None
            and cached.get("transcript_mtime_ns") == mtime_ns
            and cached.get("transcript_size") == size
        )
        fresh = isinstance(computed_at, (int, float)) and (now - computed_at) < ttl
        if (unchanged or fresh) and isinstance(rate, (int, float)):
            return float(rate)

    rate = compute_fn(transcript_path)
    if rate is None:
        return None
    _write(
        path,
        {
            "version": CACHE_VERSION,
            "computed_at": now,
            "cache_hit_rate": rate,
            "transcript_mtime_ns": mtime_ns,
            "transcript_size": size,
        },
    )
    return rate


def _session_cost_cache_path(forge_session_key: str) -> Path:
    # Distinct `fcost-` namespace from the cache-hit entries above. The key is a
    # FORGE session identity (forge_root + manifest name), NOT the Claude stdin
    # session_id -- the Claude UUID rolls on every /compact and would fragment the
    # cache, refusing to ever reuse. usedforsecurity=False: filename derivation only.
    digest = hashlib.sha256(forge_session_key.encode("utf-8"), usedforsecurity=False).hexdigest()
    return get_forge_home() / "cache" / "statusline" / f"fcost-{digest}.json"


def read_or_compute_session_cost(
    forge_session_key: str,
    ttl: int,
    compute_fn: Callable[[], int],
    *,
    now: float | None = None,
) -> int | None:
    """Return a cached per-session Forge cost (micro-USD) or recompute + persist it.

    **Time-only** throttle, deliberately unlike :func:`read_or_compute`: headless
    cost accrues via usage-ledger writes that never touch the transcript, so the
    transcript-mtime "unchanged" shortcut would freeze ``forge +$Y`` for the whole
    session. Reuse happens only within ``ttl`` seconds.

    Caches **any successful int, including ``0``** (a no-cost session must not
    re-scan the PID-sharded ledger every poll). A compute *failure* (``compute_fn``
    raises) is left uncached and returns ``None`` (fail-open: a transient ledger
    read error means "no segment this poll", never a crash, and never a frozen 0).
    """
    if now is None:
        now = time.time()

    path = _session_cost_cache_path(forge_session_key)
    cached = _read(path)
    if cached is not None and cached.get("version") == CACHE_VERSION:
        value = cached.get("cost_micro_usd")
        computed_at = cached.get("computed_at")
        fresh = isinstance(computed_at, (int, float)) and (now - computed_at) < ttl
        # bool is an int subclass; a corrupt `true` must not read as cost 1.
        if fresh and isinstance(value, int) and not isinstance(value, bool):
            return value

    try:
        value = compute_fn()
    except Exception:
        # Fail-open: do NOT cache (retry next poll). Caching a failure would freeze
        # the segment empty until the TTL elapsed even after the ledger recovered.
        return None
    _write(path, {"version": CACHE_VERSION, "computed_at": now, "cost_micro_usd": value})
    return value

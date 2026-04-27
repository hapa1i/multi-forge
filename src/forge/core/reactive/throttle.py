"""Generic TTL-based throttle cache.

Extracted from forge.guard.store supervisor cache functions.
Provides a reusable cache for deduplicating expensive calls
(LLM invocations, subprocess spawns) within a time window.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from forge.core.state import now_iso

_log = logging.getLogger(__name__)


def compute_cache_key(tool_name: str, file_path: str | None, content: str | None) -> str:
    """Compute a cache key from action attributes.

    Returns a truncated SHA256 hash of tool_name + file_path + content.

    Args:
        tool_name: The tool being invoked (e.g., "Write").
        file_path: Target file path (may be None).
        content: Content being written (may be None).

    Returns:
        16-character hex string cache key.
    """
    parts = [tool_name, file_path or "", content or ""]
    key_string = "|".join(parts)
    return hashlib.sha256(key_string.encode()).hexdigest()[:16]


class ThrottleCache:
    """TTL-based in-memory cache for deduplicating expensive calls.

    Entries expire after ``ttl_seconds``. The cache is bounded to
    ``max_entries`` (pruned in ``get_state()`` for persistence).

    The cache does NOT decide *what* to cache — callers own that logic.
    For example, the supervisor only caches clean allows (no warnings).

    State round-trip via ``get_state()``/``set_state()`` supports
    ``StatefulPolicy`` persistence across hook invocations.
    """

    def __init__(self, ttl_seconds: int = 30, max_entries: int = 50) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._cache: dict[str, dict[str, Any]] = {}

    def check(self, key: str) -> dict[str, Any] | None:
        """Check if a cached entry is still valid.

        Args:
            key: Cache key to look up.

        Returns:
            Cached entry dict if valid (within TTL), None otherwise.
        """
        entry = self._cache.get(key)
        if entry is None:
            return None

        checked_at = entry.get("checked_at")
        if checked_at is None:
            return None

        try:
            checked_time = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            age_seconds = (now - checked_time).total_seconds()

            if age_seconds < self._ttl_seconds:
                _log.debug("Cache hit for %s (age: %.1fs)", key, age_seconds)
                return entry

            _log.debug(
                "Cache expired for %s (age: %.1fs > %ds)",
                key,
                age_seconds,
                self._ttl_seconds,
            )
            return None

        except (ValueError, TypeError) as e:
            _log.warning("Invalid cache timestamp for %s: %s", key, e)
            return None

    def update(self, key: str, **values: Any) -> None:
        """Add or update a cache entry.

        Automatically sets ``checked_at`` to the current UTC timestamp.

        Args:
            key: Cache key.
            **values: Arbitrary key-value pairs to store (e.g., verdict, confidence).
        """
        self._cache[key] = {
            "checked_at": now_iso(),
            **values,
        }

    def get_state(self) -> dict[str, Any]:
        """Return cache state for persistence, pruned to max_entries most recent.

        Returns a deep copy so mutations don't affect internal state.

        Returns:
            Flat dict of ``{key: {checked_at, ...}, ...}``.
        """
        cache = {k: dict(v) for k, v in self._cache.items()}
        if len(cache) > self._max_entries:
            sorted_keys = sorted(
                cache.keys(),
                key=lambda k: cache[k].get("checked_at", ""),
                reverse=True,
            )
            cache = {k: cache[k] for k in sorted_keys[: self._max_entries]}
        return cache

    def set_state(self, state: dict[str, Any]) -> None:
        """Restore cache state from persisted data.

        Args:
            state: Flat dict previously returned by ``get_state()``.
        """
        self._cache = dict(state) if state else {}

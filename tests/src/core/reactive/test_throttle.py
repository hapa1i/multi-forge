"""Tests for forge.core.reactive.throttle."""

from __future__ import annotations

from datetime import datetime, timezone

from forge.core.reactive.throttle import ThrottleCache, compute_cache_key


class TestComputeCacheKey:
    def test_deterministic(self):
        key1 = compute_cache_key("Write", "src/foo.py", "content")
        key2 = compute_cache_key("Write", "src/foo.py", "content")
        assert key1 == key2

    def test_different_inputs_produce_different_keys(self):
        key1 = compute_cache_key("Write", "src/foo.py", "content")
        key2 = compute_cache_key("Edit", "src/foo.py", "content")
        assert key1 != key2

    def test_none_values_handled(self):
        key = compute_cache_key("Write", None, None)
        assert isinstance(key, str)
        assert len(key) == 16

    def test_key_length(self):
        key = compute_cache_key("Write", "path", "content")
        assert len(key) == 16


class TestThrottleCacheCheck:
    def test_empty_cache_returns_none(self):
        cache = ThrottleCache(ttl_seconds=30)
        assert cache.check("any-key") is None

    def test_fresh_entry_returns_value(self):
        cache = ThrottleCache(ttl_seconds=30)
        cache.update("key1", verdict="aligned", confidence=1.0)
        result = cache.check("key1")
        assert result is not None
        assert result["verdict"] == "aligned"
        assert result["confidence"] == 1.0

    def test_expired_entry_returns_none(self):
        cache = ThrottleCache(ttl_seconds=5)
        # Inject an entry with an old timestamp
        old_time = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        cache._cache["key1"] = {"checked_at": old_time, "verdict": "aligned"}

        assert cache.check("key1") is None

    def test_invalid_timestamp_returns_none(self):
        cache = ThrottleCache(ttl_seconds=30)
        cache._cache["key1"] = {"checked_at": "not-a-timestamp", "verdict": "aligned"}
        assert cache.check("key1") is None

    def test_missing_checked_at_returns_none(self):
        cache = ThrottleCache(ttl_seconds=30)
        cache._cache["key1"] = {"verdict": "aligned"}
        assert cache.check("key1") is None


class TestThrottleCacheUpdate:
    def test_update_sets_checked_at(self):
        cache = ThrottleCache(ttl_seconds=30)
        cache.update("key1", verdict="aligned")
        entry = cache._cache["key1"]
        assert "checked_at" in entry
        assert entry["verdict"] == "aligned"

    def test_update_overwrites_existing(self):
        cache = ThrottleCache(ttl_seconds=30)
        cache.update("key1", verdict="aligned", confidence=1.0)
        cache.update("key1", verdict="divergent", confidence=0.5)
        entry = cache._cache["key1"]
        assert entry["verdict"] == "divergent"
        assert entry["confidence"] == 0.5


class TestThrottleCacheState:
    def test_get_state_returns_copy(self):
        cache = ThrottleCache(ttl_seconds=30)
        cache.update("key1", verdict="aligned")
        state = cache.get_state()

        # Mutating state should not affect cache
        state["key1"]["verdict"] = "modified"
        assert cache._cache["key1"]["verdict"] == "aligned"

    def test_set_state_restores_entries(self):
        cache = ThrottleCache(ttl_seconds=300)
        original_state = {
            "key1": {
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "verdict": "aligned",
            },
        }
        cache.set_state(original_state)

        result = cache.check("key1")
        assert result is not None
        assert result["verdict"] == "aligned"

    def test_set_state_empty_dict(self):
        cache = ThrottleCache(ttl_seconds=30)
        cache.update("key1", verdict="aligned")
        cache.set_state({})
        assert cache.check("key1") is None

    def test_set_state_none(self):
        cache = ThrottleCache(ttl_seconds=30)
        cache.update("key1", verdict="aligned")
        cache.set_state(None)  # type: ignore[arg-type]
        assert cache.check("key1") is None

    def test_pruning_on_get_state(self):
        cache = ThrottleCache(ttl_seconds=30, max_entries=3)
        # Add 5 entries with increasing timestamps
        for i in range(5):
            ts = f"2025-01-01T00:00:0{i}+00:00"
            cache._cache[f"key{i}"] = {"checked_at": ts, "verdict": "aligned"}

        state = cache.get_state()
        assert len(state) == 3
        # Should keep the 3 most recent (key4, key3, key2)
        assert "key4" in state
        assert "key3" in state
        assert "key2" in state
        assert "key0" not in state
        assert "key1" not in state

    def test_round_trip(self):
        """get_state → set_state preserves cache entries."""
        cache1 = ThrottleCache(ttl_seconds=300)
        cache1.update("key1", verdict="aligned", confidence=1.0)
        state = cache1.get_state()

        cache2 = ThrottleCache(ttl_seconds=300)
        cache2.set_state(state)
        result = cache2.check("key1")
        assert result is not None
        assert result["verdict"] == "aligned"
        assert result["confidence"] == 1.0


class TestThrottleCacheEdgeCases:
    def test_ttl_exact_boundary_expires(self):
        """Entry at exactly TTL age returns None (uses strict < comparison)."""
        cache = ThrottleCache(ttl_seconds=0)
        cache.update("key1", verdict="aligned")
        # ttl_seconds=0 means any positive age > 0 expires, and exactly 0 also fails < check
        result = cache.check("key1")
        assert result is None

    def test_pruning_at_exact_max_entries(self):
        """Cache at exactly max_entries is not pruned."""
        cache = ThrottleCache(ttl_seconds=300, max_entries=3)
        for i in range(3):
            cache.update(f"key{i}", verdict="aligned")

        state = cache.get_state()
        assert len(state) == 3

    def test_set_state_malformed_entries_accepted(self):
        """set_state accepts malformed entries; check() handles gracefully."""
        cache = ThrottleCache(ttl_seconds=300)
        cache.set_state(
            {
                "good": {"checked_at": datetime.now(timezone.utc).isoformat(), "verdict": "aligned"},
                "no_timestamp": {"verdict": "aligned"},
                "bad_timestamp": {"checked_at": "garbage", "verdict": "divergent"},
            }
        )
        assert cache.check("good") is not None
        assert cache.check("no_timestamp") is None
        assert cache.check("bad_timestamp") is None

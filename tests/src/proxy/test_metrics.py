"""Unit tests for ProxyMetrics (in-memory per-proxy counters)."""

from __future__ import annotations

import concurrent.futures
import time
from typing import Any

from forge.proxy.metrics import ProxyMetrics, TierTokens


def _make_metrics() -> ProxyMetrics:
    return ProxyMetrics()


def _record_simple(m: ProxyMetrics, **overrides: Any) -> None:
    kwargs: dict[str, Any] = dict(
        tier="sonnet",
        model="openai/gpt-5.5",
        input_tokens=100,
        output_tokens=50,
        cached_tokens=20,
        latency_ms=500.0,
        streaming=False,
        failed=False,
        error_type=None,
    )
    kwargs.update(overrides)
    m.record_request(**kwargs)


class TestInitialState:
    def test_all_counters_zero(self):
        m = _make_metrics()
        assert m.total_requests == 0
        assert m.total_streaming == 0
        assert m.total_failures == 0
        assert m.total_input_tokens == 0
        assert m.total_output_tokens == 0
        assert m.total_cached_tokens == 0
        assert m.failed_input_tokens == 0
        assert m.failed_output_tokens == 0
        assert m.last_request_at is None

    def test_started_at_set(self):
        m = _make_metrics()
        assert m.started_at is not None
        assert "T" in m.started_at  # ISO format

    def test_empty_dicts(self):
        m = _make_metrics()
        assert m.requests_by_tier == {}
        assert m.tokens_by_tier == {}
        assert m.requests_by_model == {}
        assert m.tokens_by_model == {}
        assert m.failures_by_type == {}


class TestRecordRequest:
    def test_single_request(self):
        m = _make_metrics()
        _record_simple(m)
        assert m.total_requests == 1
        assert m.total_streaming == 0
        assert m.total_input_tokens == 100
        assert m.total_output_tokens == 50
        assert m.total_cached_tokens == 20
        assert m.total_failures == 0
        assert m.last_request_at is not None

    def test_streaming_request(self):
        m = _make_metrics()
        _record_simple(m, streaming=True)
        assert m.total_requests == 1
        assert m.total_streaming == 1

    def test_failed_request(self):
        m = _make_metrics()
        _record_simple(m, failed=True, error_type="tool_call_error", input_tokens=80, output_tokens=10)
        assert m.total_failures == 1
        assert m.failed_input_tokens == 80
        assert m.failed_output_tokens == 10
        # Failed tokens also count toward totals
        assert m.total_input_tokens == 80
        assert m.total_output_tokens == 10

    def test_failed_without_error_type(self):
        m = _make_metrics()
        _record_simple(m, failed=True, error_type=None)
        assert m.total_failures == 1
        assert m.failures_by_type == {}

    def test_multiple_requests_accumulate(self):
        m = _make_metrics()
        _record_simple(m, input_tokens=100, output_tokens=50, cached_tokens=20)
        _record_simple(m, input_tokens=200, output_tokens=100, cached_tokens=80)
        assert m.total_requests == 2
        assert m.total_input_tokens == 300
        assert m.total_output_tokens == 150
        assert m.total_cached_tokens == 100


class TestPerTierTracking:
    def test_single_tier(self):
        m = _make_metrics()
        _record_simple(m, tier="opus", input_tokens=500, output_tokens=100, cached_tokens=50)
        assert m.requests_by_tier == {"opus": 1}
        assert "opus" in m.tokens_by_tier
        assert m.tokens_by_tier["opus"].input_tokens == 500
        assert m.tokens_by_tier["opus"].output_tokens == 100
        assert m.tokens_by_tier["opus"].cached_tokens == 50

    def test_multiple_tiers(self):
        m = _make_metrics()
        _record_simple(m, tier="haiku", input_tokens=10)
        _record_simple(m, tier="haiku", input_tokens=20)
        _record_simple(m, tier="opus", input_tokens=500)
        assert m.requests_by_tier == {"haiku": 2, "opus": 1}
        assert m.tokens_by_tier["haiku"].input_tokens == 30
        assert m.tokens_by_tier["opus"].input_tokens == 500


class TestPerModelTracking:
    def test_single_model(self):
        m = _make_metrics()
        _record_simple(m, model="openai/gpt-5.5", input_tokens=100)
        assert m.requests_by_model == {"openai/gpt-5.5": 1}
        assert m.tokens_by_model["openai/gpt-5.5"].input_tokens == 100

    def test_multiple_models(self):
        m = _make_metrics()
        _record_simple(m, model="openai/gpt-5.5", input_tokens=100)
        _record_simple(m, model="openai/gpt-4o-mini", input_tokens=50)
        _record_simple(m, model="openai/gpt-5.5", input_tokens=200)
        assert m.requests_by_model == {"openai/gpt-5.5": 2, "openai/gpt-4o-mini": 1}
        assert m.tokens_by_model["openai/gpt-5.5"].input_tokens == 300
        assert m.tokens_by_model["openai/gpt-4o-mini"].input_tokens == 50

    def test_model_latency_tracked(self):
        m = _make_metrics()
        _record_simple(m, model="openai/gpt-5.5", latency_ms=1000.0)
        _record_simple(m, model="openai/gpt-5.5", latency_ms=3000.0)
        snap = m.snapshot()
        assert snap["by_model"]["openai/gpt-5.5"]["avg_latency_ms"] == 2000.0


class TestFailuresByType:
    def test_error_types(self):
        m = _make_metrics()
        _record_simple(m, failed=True, error_type="tool_call_error")
        _record_simple(m, failed=True, error_type="tool_call_error")
        _record_simple(m, failed=True, error_type="api_error")
        assert m.failures_by_type == {"tool_call_error": 2, "api_error": 1}


class TestSnapshot:
    def test_returns_dict(self):
        m = _make_metrics()
        snap = m.snapshot()
        assert isinstance(snap, dict)
        assert "total_requests" in snap
        assert "tokens" in snap
        assert "by_tier" in snap
        assert "by_model" in snap

    def test_derived_values_empty(self):
        m = _make_metrics()
        snap = m.snapshot()
        assert snap["cache_hit_rate"] == 0.0
        assert snap["uptime_seconds"] >= 0.0

    def test_avg_latency_per_tier(self):
        m = _make_metrics()
        _record_simple(m, tier="sonnet", latency_ms=100.0)
        _record_simple(m, tier="sonnet", latency_ms=300.0)
        _record_simple(m, tier="opus", latency_ms=1000.0)
        snap = m.snapshot()
        assert snap["by_tier"]["sonnet"]["avg_latency_ms"] == 200.0
        assert snap["by_tier"]["opus"]["avg_latency_ms"] == 1000.0

    def test_cache_hit_rate(self):
        m = _make_metrics()
        _record_simple(m, input_tokens=1000, cached_tokens=250)
        snap = m.snapshot()
        assert snap["cache_hit_rate"] == 25.0

    def test_uptime_increases(self):
        m = _make_metrics()
        snap1 = m.snapshot()
        time.sleep(0.05)
        snap2 = m.snapshot()
        assert snap2["uptime_seconds"] > snap1["uptime_seconds"]

    def test_tokens_section(self):
        m = _make_metrics()
        _record_simple(m, input_tokens=100, output_tokens=50, cached_tokens=20, failed=True, error_type="e")
        snap = m.snapshot()
        assert snap["tokens"]["input"] == 100
        assert snap["tokens"]["output"] == 50
        assert snap["tokens"]["cached"] == 20
        assert snap["tokens"]["failed_input"] == 100
        assert snap["tokens"]["failed_output"] == 50

    def test_by_tier_section(self):
        m = _make_metrics()
        _record_simple(m, tier="opus", input_tokens=500, output_tokens=100, cached_tokens=50)
        snap = m.snapshot()
        assert "opus" in snap["by_tier"]
        assert snap["by_tier"]["opus"]["requests"] == 1
        assert snap["by_tier"]["opus"]["input_tokens"] == 500

    def test_by_model_section(self):
        m = _make_metrics()
        _record_simple(m, model="openai/o3", input_tokens=500)
        snap = m.snapshot()
        assert "openai/o3" in snap["by_model"]
        assert snap["by_model"]["openai/o3"]["requests"] == 1

    def test_json_serializable(self):
        """Snapshot must be JSON-serializable for GET / endpoint."""
        import json

        m = _make_metrics()
        _record_simple(m)
        json.dumps(m.snapshot())  # Raises if not serializable


class TestReset:
    def test_zeros_counters(self):
        m = _make_metrics()
        _record_simple(m)
        assert m.total_requests == 1
        m.reset()
        assert m.total_requests == 0
        assert m.total_input_tokens == 0
        assert m.requests_by_tier == {}
        assert m.tokens_by_model == {}
        assert m.last_request_at is None

    def test_preserves_started_at(self):
        m = _make_metrics()
        started = m.started_at
        _record_simple(m)
        m.reset()
        assert m.started_at == started


class TestTierTokens:
    def test_to_dict(self):
        t = TierTokens(input_tokens=100, output_tokens=50, cached_tokens=20)
        d = t.to_dict()
        assert d["input_tokens"] == 100
        assert d["output_tokens"] == 50
        assert d["cached_tokens"] == 20
        assert d["avg_latency_ms"] == 0.0

    def test_to_dict_with_latency(self):
        t = TierTokens(input_tokens=100, output_tokens=50, cached_tokens=0, total_latency_ms=500.0, request_count=2)
        assert t.to_dict()["avg_latency_ms"] == 250.0


class TestThreadSafety:
    def test_concurrent_record(self):
        """Concurrent updates from multiple threads must not lose counts."""
        m = _make_metrics()
        n_threads = 8
        n_per_thread = 500

        def _worker():
            for _ in range(n_per_thread):
                _record_simple(m, input_tokens=1, output_tokens=1, cached_tokens=0)

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as executor:
            futures = [executor.submit(_worker) for _ in range(n_threads)]
            for f in futures:
                f.result()

        expected = n_threads * n_per_thread
        assert m.total_requests == expected
        assert m.total_input_tokens == expected
        assert m.total_output_tokens == expected

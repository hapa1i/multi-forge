"""Regression: proxy cost headers are emitted only with reported-cost evidence.

metric-evidence card, Phase 2 Step 1. Two facets of one rule — a header is
emitted only when reported-cost evidence backs it:

- ``X-Request-Cost`` is omitted when this request's cost is ``None`` (an
  unavailable cost). Before the fix the header f-string did ``None / 1_000_000``,
  raising ``TypeError`` *after* a successful upstream call.
- ``X-Cumulative-Cost`` is omitted until at least one request has reported a
  cost. A passthrough-only proxy (Anthropic never reports cost) emitting
  ``0.000000`` is the same "unknown-as-zero" bug in header form.
"""

from __future__ import annotations

from typing import Any

import pytest

from forge.proxy import server
from forge.proxy.metrics import proxy_metrics

pytestmark = pytest.mark.regression


def _record(**overrides: Any) -> None:
    kwargs: dict[str, Any] = dict(
        tier="sonnet",
        model="m",
        input_tokens=1,
        output_tokens=1,
        cached_tokens=0,
        latency_ms=1.0,
        streaming=False,
        failed=False,
    )
    kwargs.update(overrides)
    proxy_metrics.record_request(**kwargs)


class TestRequestCostHeader:
    def test_omitted_when_cost_unavailable(self) -> None:
        # No None / 1_000_000 crash — just an absent header.
        assert server._request_cost_header(None) == {}

    def test_present_when_cost_reported(self) -> None:
        assert server._request_cost_header(123_456) == {"X-Request-Cost": "0.123456"}

    def test_present_for_reported_zero(self) -> None:
        # A genuine reported $0 still emits the header (it is evidence, not absence).
        assert server._request_cost_header(0) == {"X-Request-Cost": "0.000000"}


class TestCumulativeCostHeader:
    def test_omitted_without_any_reported_cost(self) -> None:
        proxy_metrics.reset()
        assert server._cumulative_cost_header() == {}

    def test_omitted_when_only_unavailable_requests(self) -> None:
        proxy_metrics.reset()
        _record(cost_micros=None)  # tokens/requests advance, cost does not
        assert server._cumulative_cost_header() == {}
        proxy_metrics.reset()

    def test_present_after_a_reported_request(self) -> None:
        proxy_metrics.reset()
        _record(cost_micros=250_000)
        assert server._cumulative_cost_header() == {"X-Cumulative-Cost": "0.250000"}
        proxy_metrics.reset()

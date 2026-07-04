"""Tests for server.py reported-cost provenance and logging (Phase 2 Step 2).

_calc_and_log_cost derives provenance from the resolved provider: OpenRouter's
body cost is 'reported', a LiteLLM gateway's header cost is 'gateway_calculated'.
With no reported cost it still falls back to the catalog ('inferred') in Step 2;
Step 3 removes that fallback.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from forge.proxy import server


@pytest.fixture
def captured_log(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture log_request_cost kwargs instead of writing JSONL."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(server, "log_request_cost", lambda **kw: calls.append(kw))
    return calls


@pytest.fixture
def recorded_costs(monkeypatch: pytest.MonkeyPatch) -> list[int | None]:
    """Capture cost_tracker.record() calls."""
    recorded: list[int | None] = []
    monkeypatch.setattr(server, "cost_tracker", SimpleNamespace(record=recorded.append))
    return recorded


def _set_provider(monkeypatch: pytest.MonkeyPatch, provider: str, *, backend: str = "") -> None:
    monkeypatch.setattr(
        server,
        "config",
        SimpleNamespace(proxy=SimpleNamespace(preferred_provider=provider, backend=backend)),
    )


def _calc(**overrides: Any) -> int | None:
    kwargs: dict[str, Any] = dict(
        model="anthropic/claude-sonnet-4.6",
        tier="sonnet",
        input_tokens=100,
        output_tokens=50,
        cached_tokens=0,
        latency_ms=10.0,
        failed=False,
        request_id="req-cost",
    )
    kwargs.update(overrides)
    return server._calc_and_log_cost(**kwargs)


class TestReportedCostProvenance:
    def test_openrouter_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_provider(monkeypatch, "openrouter")
        assert server._reported_cost_provenance() == ("openrouter", "reported")

    def test_litellm_is_gateway_calculated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_provider(monkeypatch, "litellm")
        assert server._reported_cost_provenance() == ("litellm", "gateway_calculated")

    def test_unknown_provider_reported_without_reporter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_provider(monkeypatch, "mystery")
        assert server._reported_cost_provenance() == (None, "reported")


class TestCalcAndLogCostReported:
    def test_openrouter_reported_cost_logged_with_provenance(
        self,
        monkeypatch: pytest.MonkeyPatch,
        captured_log: list[dict[str, Any]],
        recorded_costs: list[int | None],
    ) -> None:
        _set_provider(monkeypatch, "openrouter", backend="openrouter")
        result = _calc(reported_cost_micros=2300)

        assert result == 2300
        assert len(captured_log) == 1
        rec = captured_log[0]
        assert rec["cost_micros"] == 2300
        assert rec["backend_id"] == "openrouter"
        assert rec["reporter"] == "openrouter"
        assert rec["confidence"] == "reported"
        # Reported cost feeds the spend-cap tracker.
        assert recorded_costs == [2300]

    def test_litellm_reported_cost_is_gateway_calculated(
        self,
        monkeypatch: pytest.MonkeyPatch,
        captured_log: list[dict[str, Any]],
        recorded_costs: list[int | None],
    ) -> None:
        _set_provider(monkeypatch, "litellm")
        _calc(reported_cost_micros=700)

        rec = captured_log[0]
        assert rec["cost_micros"] == 700
        assert rec["reporter"] == "litellm"
        assert rec["confidence"] == "gateway_calculated"

    def test_reported_zero_is_logged_as_reported(
        self,
        monkeypatch: pytest.MonkeyPatch,
        captured_log: list[dict[str, Any]],
        recorded_costs: list[int | None],
    ) -> None:
        """A reported $0 is provenance 'reported' with cost 0 — not catalog-inferred."""
        _set_provider(monkeypatch, "openrouter")
        result = _calc(reported_cost_micros=0)

        assert result == 0
        assert captured_log[0]["cost_micros"] == 0
        assert captured_log[0]["confidence"] == "reported"

    def test_no_reported_cost_is_unavailable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        captured_log: list[dict[str, Any]],
        recorded_costs: list[int | None],
    ) -> None:
        """No reported cost → None / 'unavailable'; tokens still logged, no catalog guess."""
        _set_provider(monkeypatch, "litellm")

        result = _calc(input_tokens=100, output_tokens=50)  # no reported_cost_micros

        assert result is None
        rec = captured_log[0]
        assert rec["cost_micros"] is None
        assert rec["reporter"] is None
        assert rec["confidence"] == "unavailable"
        # Tokens are preserved even when cost is unavailable.
        assert rec["input_tokens"] == 100
        assert rec["output_tokens"] == 50
        # An unavailable cost advances no spend-cap aggregate.
        assert recorded_costs == []

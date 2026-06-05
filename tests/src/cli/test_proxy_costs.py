"""Tests for proxy cost reporting."""

from __future__ import annotations

import json

from click.testing import CliRunner

from forge.cli.proxy_costs import _format_usd, _scope_verb_records_to_proxy, costs_cmd


class TestFormatUsd:
    def test_normal_dollar_amount(self) -> None:
        assert _format_usd(1_500_000) == "$1.50"

    def test_large_amount_with_comma(self) -> None:
        assert _format_usd(1_234_567_890) == "$1,234.57"

    def test_cents(self) -> None:
        assert _format_usd(50_000) == "$0.05"

    def test_sub_cent(self) -> None:
        assert _format_usd(500) == "$0.0005"

    def test_sub_microdollar(self) -> None:
        assert _format_usd(3) == "$0.000003"

    def test_zero(self) -> None:
        assert _format_usd(0) == "$0.00"


def test_scope_verb_records_to_proxy_slices_multi_proxy_record() -> None:
    records = [
        {
            "verb": "panel",
            "total_cost_micros": 125_000,
            "input_tokens": 12_000,
            "output_tokens": 4_500,
            "cached_tokens": 2_000,
            "request_count": 3,
            "per_proxy": [
                {
                    "base_url": "http://localhost:8084",
                    "cost_micros": 80_000,
                    "input_tokens": 8_000,
                    "output_tokens": 3_000,
                    "cached_tokens": 1_200,
                    "request_count": 2,
                },
                {
                    "base_url": "http://localhost:8085",
                    "cost_micros": 45_000,
                    "input_tokens": 4_000,
                    "output_tokens": 1_500,
                    "cached_tokens": 800,
                    "request_count": 1,
                },
            ],
        },
        {
            "verb": "supervisor",
            "total_cost_micros": 10_000,
            "request_count": 1,
            "per_proxy": [
                {
                    "base_url": "http://localhost:8085",
                    "cost_micros": 10_000,
                    "request_count": 1,
                }
            ],
        },
    ]

    scoped = _scope_verb_records_to_proxy(records, "http://localhost:8084/")

    assert len(scoped) == 1
    assert scoped[0]["verb"] == "panel"
    assert scoped[0]["total_cost_micros"] == 80_000
    assert scoped[0]["input_tokens"] == 8_000
    assert scoped[0]["output_tokens"] == 3_000
    assert scoped[0]["cached_tokens"] == 1_200
    assert scoped[0]["request_count"] == 2
    assert len(scoped[0]["per_proxy"]) == 1
    assert scoped[0]["per_proxy"][0]["base_url"] == "http://localhost:8084"


def test_costs_json_filters_verb_records_by_proxy(monkeypatch) -> None:
    request_records = [
        {
            "proxy_id": "openrouter",
            "model": "anthropic/claude-sonnet-4.6",
            "cost_micros": 100_000,
            "input_tokens": 1_000,
            "output_tokens": 500,
        },
        {
            "proxy_id": "litellm-gemini",
            "model": "gemini/gemini-3.1-pro-preview",
            "cost_micros": 40_000,
            "input_tokens": 800,
            "output_tokens": 200,
        },
    ]
    verb_records = [
        {
            "verb": "panel",
            "total_cost_micros": 120_000,
            "request_count": 3,
            "per_proxy": [
                {"base_url": "http://localhost:8084", "cost_micros": 80_000, "request_count": 2},
                {"base_url": "http://localhost:8085", "cost_micros": 40_000, "request_count": 1},
            ],
        },
        {
            "verb": "supervisor",
            "total_cost_micros": 40_000,
            "request_count": 1,
            "per_proxy": [
                {"base_url": "http://localhost:8085", "cost_micros": 40_000, "request_count": 1},
            ],
        },
    ]

    monkeypatch.setattr("forge.proxy.cost_logger.read_cost_logs", lambda *args, **kwargs: request_records)
    monkeypatch.setattr("forge.core.reactive.cost_tracking.read_verb_logs", lambda *args, **kwargs: verb_records)
    monkeypatch.setattr("forge.core.reactive.proxy.lookup_proxy_base_url", lambda proxy_id: "http://localhost:8084")

    result = CliRunner().invoke(costs_cmd, ["openrouter", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["total_cost_micros"] == 100_000
    assert data["interactive_cost_micros"] == 20_000
    assert set(data["by_verb"]) == {"panel"}
    assert data["by_verb"]["panel"]["cost_micros"] == 80_000
    assert data["by_verb"]["panel"]["request_count"] == 2
    assert set(data["by_model"]) == {"anthropic/claude-sonnet-4.6"}


def test_costs_json_mixed_reported_and_unavailable(monkeypatch) -> None:
    """Legacy catalog int + new reported + new unavailable(null) aggregate cleanly.

    The present-but-null cost_micros must NOT be summed as 0 (and `sum` must not
    crash on it): it's excluded from the total and counted as unavailable.
    """
    request_records = [
        # Legacy catalog record (pre-rename: int cost, no provenance fields).
        {"proxy_id": "p", "model": "m-legacy", "cost_micros": 30_000, "input_tokens": 100, "output_tokens": 50},
        # New reported record.
        {
            "proxy_id": "p",
            "model": "m-reported",
            "cost_micros": 70_000,
            "reporter": "openrouter",
            "confidence": "reported",
            "input_tokens": 200,
            "output_tokens": 80,
        },
        # New unavailable record — cost is null.
        {
            "proxy_id": "p",
            "model": "m-unavail",
            "cost_micros": None,
            "reporter": None,
            "confidence": "unavailable",
            "input_tokens": 300,
            "output_tokens": 120,
        },
    ]
    monkeypatch.setattr("forge.proxy.cost_logger.read_cost_logs", lambda *a, **k: request_records)
    monkeypatch.setattr("forge.core.reactive.cost_tracking.read_verb_logs", lambda *a, **k: [])

    result = CliRunner().invoke(costs_cmd, ["--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    # Total sums REPORTED costs only (30k + 70k); the null is excluded, not 0.
    assert data["total_cost_micros"] == 100_000
    assert data["reported_requests"] == 2
    assert data["unavailable_requests"] == 1
    assert "estimated" not in data  # clean break: provenance replaces the flag
    assert data["by_model"]["m-reported"]["reported"] is True
    assert data["by_model"]["m-unavail"]["reported"] is False


def test_costs_human_output_renders_unavailable(monkeypatch) -> None:
    """A cost-unavailable request renders 'unavailable', not $0.00, without crashing."""
    request_records = [
        {"proxy_id": "p", "model": "m-unavail", "cost_micros": None, "input_tokens": 10, "output_tokens": 5},
    ]
    monkeypatch.setattr("forge.proxy.cost_logger.read_cost_logs", lambda *a, **k: request_records)
    monkeypatch.setattr("forge.core.reactive.cost_tracking.read_verb_logs", lambda *a, **k: [])

    by_model = CliRunner().invoke(costs_cmd, ["--by-model"])
    assert by_model.exit_code == 0, by_model.output
    assert "unavailable" in by_model.output

    by_verb = CliRunner().invoke(costs_cmd, ["--by-verb"])
    assert by_verb.exit_code == 0, by_verb.output
    assert "cost unavailable" in by_verb.output

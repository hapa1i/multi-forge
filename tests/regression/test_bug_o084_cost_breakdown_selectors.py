"""O084 regressions for cost breakdown selectors and logical run counts."""

from __future__ import annotations

import json
from typing import Any

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.usage.ledger import UsageEvent, log_usage_event

pytestmark = pytest.mark.regression


def _costs_args(*args: str) -> list[str]:
    return ["telemetry", "costs", "show", *args]


def _usage_event(run_id: str, command: str = "panel") -> None:
    log_usage_event(
        UsageEvent(
            run_id=run_id,
            root_run_id=run_id,
            runtime="claude_code",
            command=command,
            status="success",
        )
    )


def _request(run_id: str, cost_micros: int | None) -> dict[str, Any]:
    return {
        "proxy_id": "test-proxy",
        "model": "test-model",
        "cost_micros": cost_micros,
        "input_tokens": 10,
        "output_tokens": 5,
        "forge_run_id": run_id,
    }


def _patch_cost_logs(monkeypatch: pytest.MonkeyPatch, records: list[dict[str, Any]]) -> None:
    from forge.proxy.cost_logger import CostLogReadResult

    monkeypatch.setattr(
        "forge.proxy.cost_logger.read_cost_logs_with_stats",
        lambda *args, **kwargs: CostLogReadResult(records=records, skipped_legacy_schema=0),
    )


def _json_summary(monkeypatch: pytest.MonkeyPatch, records: list[dict[str, Any]]) -> dict[str, Any]:
    _patch_cost_logs(monkeypatch, records)
    result = CliRunner().invoke(main, _costs_args("--json"))
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_conflicting_selectors_fail_before_cost_log_read(monkeypatch: pytest.MonkeyPatch) -> None:
    reads: list[bool] = []

    def read_costs(*args: object, **kwargs: object) -> None:
        reads.append(True)
        raise AssertionError("cost telemetry must not be read for invalid selectors")

    monkeypatch.setattr("forge.proxy.cost_logger.read_cost_logs_with_stats", read_costs)

    result = CliRunner().invoke(main, _costs_args("--by-model", "--by-verb"))

    assert result.exit_code == 2
    assert "--by-model" in result.stderr
    assert "--by-verb" in result.stderr
    assert "cannot be used together" in result.stderr
    assert reads == []


def test_one_run_with_many_requests_counts_one_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    _usage_event("run-one")

    summary = _json_summary(monkeypatch, [_request("run-one", 20_000), _request("run-one", 30_000)])

    panel = summary["by_verb"]["panel"]
    assert panel["invocations"] == 1
    assert panel["request_count"] == 2
    assert panel["cost_micros"] == 50_000


def test_one_run_with_many_requests_renders_distinct_human_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    _usage_event("run-one")
    _patch_cost_logs(monkeypatch, [_request("run-one", 20_000), _request("run-one", 30_000)])

    result = CliRunner().invoke(main, _costs_args("--by-verb"))

    assert result.exit_code == 0, result.output
    assert "1 run, 2 reqs" in result.stdout
    assert "2 runs" not in result.stdout


def test_multiple_runs_for_one_verb_count_distinct_run_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    _usage_event("run-one")
    _usage_event("run-two")

    summary = _json_summary(
        monkeypatch,
        [_request("run-one", 10_000), _request("run-one", 20_000), _request("run-two", 30_000)],
    )

    panel = summary["by_verb"]["panel"]
    assert panel["invocations"] == 2
    assert panel["request_count"] == 3
    assert panel["cost_micros"] == 60_000


def test_missing_usage_event_stays_in_totals_but_not_verb_attribution(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = _json_summary(monkeypatch, [_request("missing-run", 40_000)])

    assert summary["total_requests"] == 1
    assert summary["total_cost_micros"] == 40_000
    assert summary["interactive_cost_micros"] == 40_000
    assert summary["by_verb"] == {}


def test_unique_run_count_preserves_request_cost_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    _usage_event("run-mixed")

    summary = _json_summary(monkeypatch, [_request("run-mixed", None), _request("run-mixed", 15_000)])

    panel = summary["by_verb"]["panel"]
    assert panel == {
        "cost_micros": 15_000,
        "reported": True,
        "request_count": 2,
        "invocations": 1,
    }
    assert summary["reported_requests"] == 1
    assert summary["unavailable_requests"] == 1


def test_explicit_by_verb_matches_default_human_view(monkeypatch: pytest.MonkeyPatch) -> None:
    _usage_event("run-one")
    records = [_request("run-one", 25_000)]
    _patch_cost_logs(monkeypatch, records)

    default = CliRunner().invoke(main, _costs_args())
    explicit = CliRunner().invoke(main, _costs_args("--by-verb"))

    assert default.exit_code == 0, default.output
    assert explicit.exit_code == 0, explicit.output
    assert explicit.stdout == default.stdout
    assert explicit.stderr == default.stderr == ""

"""Reported accounting survives strict baseline readers without changing their schemas."""

import json
from pathlib import Path

import pytest

from forge.core.judgments.types import JudgmentAttempt, JudgmentResponse, ReportedUsage
from forge.core.judgments.usage import emit_attempt
from forge.core.reactive.env import RunIdentity
from forge.core.telemetry.downstream import (
    DownstreamRecord,
    read_downstream_records,
    write_downstream_record,
)
from forge.core.usage.ledger import read_usage_events
from forge.proxy.cost_logger import read_cost_logs


@pytest.mark.parametrize("cost,expected", [(None, None), (0.0, 0), (0.00000049, 0), (0.0000005, 1), (0.0000015, 2)])
def test_nullable_cost_and_rounding(cost, expected):
    attempt = JudgmentAttempt(
        "req_jev",
        "ds_jev",
        "typesafe/jev-1.13",
        12.0,
        model="typesafe/jev-1.13-20260917",
        provider="TypeSafe",
        provider_response_id="gen-synthetic",
        usage=ReportedUsage(30, 2, cost),
    )
    emit_attempt(
        attempt,
        identity=RunIdentity("run_jev", None, "run_jev"),
        session="test",
        grouping=None,
        command="jev",
        direct=True,
    )
    (record,) = read_downstream_records()
    (event,) = read_usage_events()
    assert record.schema_version == 2 and event.schema_version == 1
    assert record.cost_micros == record.reported_cost_micros == event.cost_micro_usd == expected
    assert record.confidence == event.confidence == ("unavailable" if cost is None else "reported")
    assert record.input_tokens == event.input_tokens == 30
    assert record.output_tokens == event.output_tokens == 2
    assert record.request_id == "req_jev" and record.provider_response_id == "gen-synthetic"
    assert event.route == "core_llm" and event.source_refs is None and event.billing_mode == "api"
    assert record.proxy_id is event.proxy_id is None


def test_standalone_attempts_preserve_old_history_and_deduplicate_cost():
    old = DownstreamRecord(
        kind="attempt",
        downstream_event_id="ds_old",
        request_id="req_old",
        cost_micros=7,
        reporter="openrouter",
        confidence="reported",
        model="old-model",
    )
    write_downstream_record(old)
    write_downstream_record(old)
    emit_attempt(
        JudgmentAttempt("req_jev", "ds_jev", "typesafe/jev-1.13", 2.0, usage=ReportedUsage(cost=0.000002)),
        identity=None,
        session=None,
        grouping=None,
        command="jev",
        direct=True,
    )
    assert {record.request_id for record in read_downstream_records()} == {"req_old", "req_jev"}
    assert sum(row["cost_micros"] for row in read_cost_logs()) == 9
    assert read_usage_events() == []


@pytest.mark.parametrize("kind", ["choice", "noul", "score"])
def test_captured_success_contract(kind):
    fixture = Path(__file__).resolve().parents[3] / "fixtures" / "jev" / f"{kind}.json"
    response = JudgmentResponse.model_validate(json.loads(fixture.read_text()))
    assert response.model == "typesafe/jev-1.13-20260917"
    assert response.provider == "TypeSafe"
    assert response.usage.input_tokens > 0 and response.usage.cost > 0


def test_telemetry_failure_does_not_break_judgment(monkeypatch):
    def broken(record):
        raise OSError("synthetic write failure")

    monkeypatch.setattr("forge.core.judgments.usage.write_downstream_record", broken)
    emit_attempt(
        JudgmentAttempt("req_jev", "ds_jev", "typesafe/jev-1.13", 1.0),
        identity=None,
        session=None,
        grouping=None,
        command="jev",
        direct=False,
    )

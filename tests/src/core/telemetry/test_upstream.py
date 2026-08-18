"""Tests for upstream outcome volume rules."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from forge.core.paths import get_forge_home
from forge.core.telemetry import upstream
from forge.core.telemetry.upstream import (
    UPSTREAM_SCHEMA_VERSION,
    UpstreamOutcome,
    read_upstream_outcomes,
    record_upstream_operation,
    should_record_upstream_outcome,
    write_upstream_outcome,
)


@dataclass
class _RuntimeConfig:
    upstream_event_volume: str = "non_success"


@pytest.fixture(autouse=True)
def _reset_newer_schema_latch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upstream, "_warned_newer_schema", False)


def _upstream_path() -> Path:
    return get_forge_home() / "telemetry" / "upstream" / "2026-01_1.jsonl"


def _append_raw(record: object) -> None:
    path = _upstream_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(record) + "\n")


def test_default_volume_skips_cached_success_and_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("forge.runtime_config.get_runtime_config", lambda: _RuntimeConfig())

    assert should_record_upstream_outcome("success", cached=True) is False
    assert should_record_upstream_outcome("warning", cached=True) is False
    assert should_record_upstream_outcome("fail_open", cached=True) is True


def test_all_volume_records_cached_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("forge.runtime_config.get_runtime_config", lambda: _RuntimeConfig("all"))

    assert should_record_upstream_outcome("success", cached=True) is True
    assert should_record_upstream_outcome("warning", cached=True) is True


def test_record_upstream_operation_fills_ambient_run_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_RUN_ID", "run_child")
    monkeypatch.setenv("FORGE_PARENT_RUN_ID", "run_parent")
    monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_root")

    record_upstream_operation(
        command="memory-writer",
        operation="memory_writer.run",
        status="error",
        session="planner",
        reason_code="transcript_not_found",
    )

    outcomes = read_upstream_outcomes(session="planner", command="memory-writer")
    assert len(outcomes) == 1
    assert outcomes[0].run_id == "run_child"
    assert outcomes[0].parent_run_id == "run_parent"
    assert outcomes[0].root_run_id == "run_root"
    assert outcomes[0].reason_code == "transcript_not_found"


def test_newer_schema_warning_precedes_value_and_period_filters(caplog: pytest.LogCaptureFixture) -> None:
    _append_raw(
        {
            "schema_version": 99,
            "command": "drop",
            "status": "error",
            "ts": "2999-01-01T00:00:00Z",
        }
    )
    _append_raw(
        {
            "schema_version": UPSTREAM_SCHEMA_VERSION,
            "command": "keep",
            "status": "error",
            "ts": "2026-01-01T00:00:00Z",
        }
    )

    with caplog.at_level(logging.WARNING):
        outcomes = read_upstream_outcomes(
            command="keep",
            period_end=datetime(2027, 1, 1, tzinfo=timezone.utc),
        )
        read_upstream_outcomes()

    assert [outcome.command for outcome in outcomes] == ["keep"]
    assert sum("newer Forge" in message for message in caplog.messages) == 1


def test_strict_reader_skips_unknown_fields_and_non_object_lines(caplog: pytest.LogCaptureFixture) -> None:
    _append_raw(
        {
            "schema_version": UPSTREAM_SCHEMA_VERSION,
            "command": "keep",
            "status": "error",
            "ts": "2026-01-01T00:00:00Z",
        }
    )
    _append_raw(
        {
            "schema_version": UPSTREAM_SCHEMA_VERSION,
            "command": "drop",
            "status": "error",
            "ts": "2026-01-01T00:00:00Z",
            "future_field": "must be rejected",
        }
    )
    _append_raw(["not", "an", "object"])

    with caplog.at_level(logging.WARNING):
        outcomes = read_upstream_outcomes()

    assert [outcome.command for outcome in outcomes] == ["keep"]
    assert sum("malformed upstream telemetry" in message for message in caplog.messages) == 1


def test_upstream_filters_retain_half_open_period_bounds() -> None:
    for event_id, ts in (
        ("before", "2025-12-31T23:59:59Z"),
        ("inside", "2026-01-01T12:00:00Z"),
        ("end", "2026-01-02T00:00:00Z"),
    ):
        write_upstream_outcome(
            UpstreamOutcome(
                command="policy",
                status="error",
                event_id=event_id,
                session="planner",
                policy_id="semantic.supervisor",
                ts=ts,
            )
        )

    outcomes = read_upstream_outcomes(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc),
        session="planner",
        command="policy",
        policy_id="semantic.supervisor",
    )

    assert [outcome.event_id for outcome in outcomes] == ["inside"]

"""Regression: cost_logger records must carry schema_version with forward-compat warn-skip.

Bug (audit P4, note-only / durable-state parity): the PID-sharded cost log
(now ~/.forge/telemetry/downstream/<month>_<pid>.jsonl) had no schema_version field, unlike its sibling
durable JSONL writers proxy/audit_logger.py (AUDIT_SCHEMA_VERSION) and core/usage/ledger.py
(USAGE_SCHEMA_VERSION). A newer Forge could append records of an unknown shape that an older Forge's
read_cost_logs() would silently aggregate as if current, corrupting cost summaries.

Fix: stamp schema_version=COST_SCHEMA_VERSION on every record; read_cost_logs() skips records whose
schema_version exceeds COST_SCHEMA_VERSION (warn-once), while still reading legacy unversioned
records -- mirroring the sibling loggers' forward-only degrade (best-effort system boundary).

Affected: src/forge/proxy/cost_logger.py.
"""

from __future__ import annotations

import json
import logging

import pytest

from forge.core.telemetry import downstream as downstream_telemetry
from forge.core.telemetry.downstream import DOWNSTREAM_SCHEMA_VERSION
from forge.proxy.cost_logger import (
    COST_SCHEMA_VERSION,
    log_request_cost,
    read_cost_logs,
)

pytestmark = pytest.mark.regression


def test_log_request_cost_stamps_schema_version() -> None:
    """Every written cost record carries schema_version=COST_SCHEMA_VERSION (FORGE_HOME isolated)."""
    log_request_cost(
        proxy_id="p1",
        model="gpt-5.5",
        tier="sonnet",
        input_tokens=10,
        output_tokens=5,
        cached_tokens=0,
        cost_micros=1234,
        latency_ms=12.3,
        failed=False,
        request_id="req-1",
    )

    records = read_cost_logs()
    assert len(records) == 1
    assert records[0]["schema_version"] == COST_SCHEMA_VERSION
    assert records[0]["request_id"] == "req-1"


def test_read_cost_logs_skips_non_current_schema_keeps_current(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Older/missing and newer downstream schemas are skipped; current schema records are read."""
    monkeypatch.setattr(downstream_telemetry, "_warned_older_schema", False)
    monkeypatch.setattr(downstream_telemetry, "_warned_newer_schema", False)

    telemetry_dir = downstream_telemetry._downstream_dir()
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    shard = telemetry_dir / "2026-06_testshard.jsonl"
    rows = [
        {
            "schema_version": DOWNSTREAM_SCHEMA_VERSION,
            "kind": "attempt",
            "downstream_event_id": "ds_current",
            "ts": "2026-06-01T00:00:00Z",
            "request_id": "current",
            "cost_micros": 100,
        },
        {
            "kind": "attempt",
            "downstream_event_id": "ds_legacy",
            "ts": "2026-06-01T00:00:01Z",
            "request_id": "legacy",
            "cost_micros": 200,
        },  # pre-versioning record
        {
            "schema_version": DOWNSTREAM_SCHEMA_VERSION + 1,
            "kind": "attempt",
            "downstream_event_id": "ds_future",
            "ts": "2026-06-01T00:00:02Z",
            "request_id": "future",
            "cost_micros": 9,
        },
    ]
    shard.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    with caplog.at_level(logging.WARNING, logger="forge.core.telemetry.downstream"):
        records = read_cost_logs()

    seen = {r["request_id"] for r in records}
    assert seen == {"current"}, "only current downstream schema records are projected into cost logs"
    assert "older Forge backend-identity schema" in caplog.text
    assert "newer Forge" in caplog.text


def test_read_cost_logs_warns_only_once_for_newer_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """The newer-schema warning is latched: a second read does not re-warn (matches sibling loggers)."""
    monkeypatch.setattr(downstream_telemetry, "_warned_newer_schema", False)

    telemetry_dir = downstream_telemetry._downstream_dir()
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    (telemetry_dir / "2026-06_future.jsonl").write_text(
        json.dumps(
            {
                "schema_version": DOWNSTREAM_SCHEMA_VERSION + 1,
                "kind": "attempt",
                "downstream_event_id": "ds_future",
                "ts": "2026-06-01T00:00:00Z",
                "request_id": "f",
            }
        )
        + "\n"
    )

    read_cost_logs()
    assert downstream_telemetry._warned_newer_schema is True, "latch must be set after first newer-schema skip"

    warned: list[str] = []
    monkeypatch.setattr(downstream_telemetry.logger, "warning", lambda *a, **_k: warned.append(str(a)))
    read_cost_logs()
    assert warned == [], "second read must not re-warn once the latch is set"

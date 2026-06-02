"""Regression: cost_logger records must carry schema_version with forward-compat warn-skip.

Bug (audit P4, note-only / durable-state parity): the PID-sharded cost log
(~/.forge/costs/requests/<month>_<pid>.jsonl) had no schema_version field, unlike its sibling
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

import forge.proxy.cost_logger as cost_logger
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


def test_read_cost_logs_skips_newer_schema_keeps_current_and_legacy(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A record from a newer Forge (schema_version > COST_SCHEMA_VERSION) is skipped with a warning;
    current and legacy-unversioned records are still read."""
    monkeypatch.setattr(cost_logger, "_warned_newer_schema", False)  # reset the one-time latch

    costs_dir = cost_logger._costs_dir()
    costs_dir.mkdir(parents=True, exist_ok=True)
    shard = costs_dir / "2026-06_testshard.jsonl"
    rows = [
        {
            "schema_version": COST_SCHEMA_VERSION,
            "ts": "2026-06-01T00:00:00Z",
            "request_id": "current",
            "cost_micros": 100,
        },
        {"ts": "2026-06-01T00:00:01Z", "request_id": "legacy", "cost_micros": 200},  # pre-versioning record
        {
            "schema_version": COST_SCHEMA_VERSION + 1,
            "ts": "2026-06-01T00:00:02Z",
            "request_id": "future",
            "cost_micros": 9,
        },
    ]
    shard.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    with caplog.at_level(logging.WARNING, logger="forge.proxy.cost_logger"):
        records = read_cost_logs()

    seen = {r["request_id"] for r in records}
    assert seen == {"current", "legacy"}, "newer-schema record must be skipped; current+legacy kept"
    assert "newer Forge" in caplog.text, "skipping a newer-schema record must warn"


def test_read_cost_logs_warns_only_once_for_newer_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """The newer-schema warning is latched: a second read does not re-warn (matches sibling loggers)."""
    monkeypatch.setattr(cost_logger, "_warned_newer_schema", False)

    costs_dir = cost_logger._costs_dir()
    costs_dir.mkdir(parents=True, exist_ok=True)
    (costs_dir / "2026-06_future.jsonl").write_text(
        json.dumps({"schema_version": COST_SCHEMA_VERSION + 1, "ts": "2026-06-01T00:00:00Z", "request_id": "f"}) + "\n"
    )

    read_cost_logs()
    assert cost_logger._warned_newer_schema is True, "latch must be set after first newer-schema skip"

    warned: list[str] = []
    monkeypatch.setattr(cost_logger.logger, "warning", lambda *a, **_k: warned.append(str(a)))
    read_cost_logs()
    assert warned == [], "second read must not re-warn once the latch is set"

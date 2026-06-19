"""Tests for the shared downstream telemetry plane."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from forge.core.telemetry import downstream
from forge.core.telemetry.downstream import (
    DownstreamRecord,
    prune_downstream_records,
    read_downstream_records,
    write_downstream_record,
)


@pytest.fixture(autouse=True)
def _isolated_downstream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    telemetry_dir = tmp_path / "telemetry" / "downstream"
    monkeypatch.setattr("forge.core.telemetry.downstream._downstream_dir", lambda: telemetry_dir)
    downstream._warned_newer_schema = False
    return telemetry_dir


def test_duplicate_attempt_ids_merge_latest_non_null_fields() -> None:
    write_downstream_record(
        DownstreamRecord(
            kind="attempt",
            downstream_event_id="ds_one",
            request_id="req-1",
            input_tokens=10,
            confidence="reported",
        )
    )
    write_downstream_record(
        DownstreamRecord(
            kind="attempt",
            downstream_event_id="ds_one",
            output_tokens=5,
            confidence="unknown",
            cost_micros=123,
        )
    )

    records = read_downstream_records(kind="attempt")

    assert len(records) == 1
    assert records[0].input_tokens == 10
    assert records[0].output_tokens == 5
    assert records[0].cost_micros == 123
    assert records[0].confidence == "reported"


def test_backend_id_survives_later_null_merge_and_can_filter() -> None:
    write_downstream_record(
        DownstreamRecord(
            kind="attempt",
            downstream_event_id="ds_backend",
            request_id="req-1",
            backend_id="openrouter",
        )
    )
    write_downstream_record(
        DownstreamRecord(
            kind="attempt",
            downstream_event_id="ds_backend",
            output_tokens=5,
            backend_id=None,
        )
    )

    records = read_downstream_records(kind="attempt", backend_id="openrouter")

    assert len(records) == 1
    assert records[0].backend_id == "openrouter"
    assert records[0].output_tokens == 5
    assert read_downstream_records(kind="attempt", backend_id="litellm-remote") == []


def test_non_attempt_substreams_do_not_merge() -> None:
    write_downstream_record(
        DownstreamRecord(
            kind="audit",
            downstream_event_id="ds_audit",
            audit_record_type="request",
            payload={"record_type": "request", "request_id": "req-1"},
        )
    )
    write_downstream_record(
        DownstreamRecord(
            kind="drift",
            downstream_event_id="ds_audit",
            audit_record_type="drift",
            payload={"record_type": "drift", "request_id": "req-1"},
        )
    )

    records = read_downstream_records()

    assert [record.kind for record in records] == ["audit", "drift"]


def test_newer_schema_is_skipped(_isolated_downstream: Path, caplog: pytest.LogCaptureFixture) -> None:
    _isolated_downstream.mkdir(parents=True)
    path = _isolated_downstream / "2026-06_1.jsonl"
    with open(path, "w") as f:
        f.write(
            json.dumps(
                {
                    "schema_version": 99,
                    "kind": "attempt",
                    "downstream_event_id": "future",
                }
            )
            + "\n"
        )
        f.write(json.dumps({"schema_version": 1, "kind": "attempt", "downstream_event_id": "ok"}) + "\n")

    with caplog.at_level("WARNING"):
        records = read_downstream_records(kind="attempt")

    assert [record.downstream_event_id for record in records] == ["ok"]
    assert sum("newer Forge" in message for message in caplog.messages) == 1


def test_strict_reader_skips_unknown_fields_and_non_object_lines(
    _isolated_downstream: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _isolated_downstream.mkdir(parents=True)
    path = _isolated_downstream / "2026-06_1.jsonl"
    with open(path, "w") as f:
        f.write(json.dumps({"schema_version": 1, "kind": "attempt", "downstream_event_id": "valid"}) + "\n")
        f.write(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "attempt",
                    "downstream_event_id": "unknown-field",
                    "future_field": "must be rejected",
                }
            )
            + "\n"
        )
        f.write(json.dumps(["not", "an", "object"]) + "\n")

    with caplog.at_level("WARNING"):
        records = read_downstream_records(kind="attempt")

    assert [record.downstream_event_id for record in records] == ["valid"]
    assert any("Skipping malformed downstream telemetry" in message for message in caplog.messages)


def test_prune_downstream_records_by_age(_isolated_downstream: Path) -> None:
    _isolated_downstream.mkdir(parents=True)
    old = _isolated_downstream / "2026-01_1.jsonl"
    recent = _isolated_downstream / "2026-06_1.jsonl"
    old.write_text("{}\n")
    recent.write_text("{}\n")
    old_time = time.time() - 30 * 86400
    os.utime(old, (old_time, old_time))

    prune_downstream_records(retention_days=14, max_total_mb=0)

    assert not old.exists()
    assert recent.exists()


def test_prune_preserves_current_month_shard_by_age(_isolated_downstream: Path) -> None:
    _isolated_downstream.mkdir(parents=True)
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    current = _isolated_downstream / f"{current_month}_1.jsonl"
    old = _isolated_downstream / "2000-01_1.jsonl"
    current.write_text("{}\n")
    old.write_text("{}\n")
    old_time = time.time() - 30 * 86400
    os.utime(current, (old_time, old_time))
    os.utime(old, (old_time, old_time))

    prune_downstream_records(retention_days=14, max_total_mb=0)

    assert current.exists()
    assert not old.exists()


def test_prune_preserves_current_month_shard_by_size(
    _isolated_downstream: Path,
) -> None:
    _isolated_downstream.mkdir(parents=True)
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    current = _isolated_downstream / f"{current_month}_1.jsonl"
    other = _isolated_downstream / "2000-01_1.jsonl"
    current.write_bytes(b"x" * (2 * 1024 * 1024))
    other.write_text("{}\n")
    old_time = time.time() - 30 * 86400
    os.utime(current, (old_time, old_time))

    prune_downstream_records(retention_days=0, max_total_mb=1)

    assert current.exists()
    assert not other.exists()

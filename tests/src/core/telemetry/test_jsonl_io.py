"""Tests for shared telemetry JSONL append mechanics."""

from __future__ import annotations

import json
import logging
import stat
import threading
from dataclasses import asdict
from pathlib import Path

import pytest

from forge.core.telemetry.downstream import DOWNSTREAM_SCHEMA_VERSION, DownstreamRecord, write_downstream_record
from forge.core.telemetry.jsonl_io import append_jsonl_record
from forge.core.telemetry.upstream import UPSTREAM_SCHEMA_VERSION, UpstreamOutcome, write_upstream_outcome
from forge.core.usage.ledger import USAGE_SCHEMA_VERSION, UsageEvent, log_usage_event


def _jsonl_lines(root: Path, relative_dir: str) -> list[str]:
    files = list((root / "forge" / relative_dir).glob("*.jsonl"))
    assert len(files) == 1
    return files[0].read_text(encoding="utf-8").splitlines()


def test_append_jsonl_record_compact_json_and_secure_modes(tmp_path: Path) -> None:
    log_path = tmp_path / "telemetry" / "downstream" / "2026-01_123.jsonl"

    append_jsonl_record(
        log_path,
        {"b": 2, "a": "x"},
        secure_dirs=(log_path.parent.parent, log_path.parent),
        lock=threading.Lock(),
        logger=logging.getLogger(__name__),
        warning_message="write failed: %s",
    )

    assert log_path.read_text(encoding="utf-8") == '{"b":2,"a":"x"}\n'
    assert stat.S_IMODE(log_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(log_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(log_path.parent.parent.stat().st_mode) == 0o700


def test_plane_writers_preserve_compact_record_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge"))
    ts = "2026-01-01T00:00:00Z"

    downstream = DownstreamRecord(kind="attempt", downstream_event_id="ds_1", ts=ts)
    write_downstream_record(downstream)
    expected_downstream = {
        "kind": "attempt",
        "downstream_event_id": "ds_1",
        "confidence": "unknown",
        "schema_version": DOWNSTREAM_SCHEMA_VERSION,
        "ts": ts,
    }
    assert _jsonl_lines(tmp_path, "telemetry/downstream") == [json.dumps(expected_downstream, separators=(",", ":"))]

    upstream = UpstreamOutcome(command="policy", status="error", event_id="up_1", ts=ts)
    write_upstream_outcome(upstream)
    expected_upstream = {
        "command": "policy",
        "status": "error",
        "event_id": "up_1",
        "cached": False,
        "schema_version": UPSTREAM_SCHEMA_VERSION,
        "ts": ts,
    }
    assert _jsonl_lines(tmp_path, "telemetry/upstream") == [json.dumps(expected_upstream, separators=(",", ":"))]

    usage = UsageEvent(
        run_id="run_1",
        root_run_id="run_1",
        runtime="codex",
        command="panel",
        status="success",
        event_id="evt_1",
        ts=ts,
    )
    log_usage_event(usage)
    expected_usage = asdict(usage)
    expected_usage["schema_version"] = USAGE_SCHEMA_VERSION
    assert _jsonl_lines(tmp_path, "usage/events") == [json.dumps(expected_usage, separators=(",", ":"), default=str)]

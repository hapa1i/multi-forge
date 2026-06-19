"""Tests for PID-sharded JSONL cost logger."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from forge.proxy.cost_logger import (
    log_request_cost,
    read_cost_logs,
)


@pytest.fixture
def cost_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point downstream telemetry to a temp directory."""
    telemetry_dir = tmp_path / "telemetry" / "downstream"
    monkeypatch.setattr("forge.core.telemetry.downstream._downstream_dir", lambda: telemetry_dir)
    return telemetry_dir


class TestLogRequestCost:
    def test_creates_dir_and_writes_record(self, cost_log_dir: Path):
        log_request_cost(
            proxy_id="openrouter",
            backend_id="openrouter",
            model="anthropic/claude-sonnet-4.6",
            tier="sonnet",
            input_tokens=1500,
            output_tokens=800,
            cached_tokens=500,
            cost_micros=16500,
            latency_ms=1200.5,
            failed=False,
            request_id="req_abc123",
            reporter="openrouter",
            confidence="reported",
        )

        assert cost_log_dir.is_dir()
        files = list(cost_log_dir.glob("*.jsonl"))
        assert len(files) == 1

        with open(files[0]) as f:
            lines = f.readlines()
        assert len(lines) == 1

        record = json.loads(lines[0])
        assert record["proxy_id"] == "openrouter"
        assert record["backend_id"] == "openrouter"
        assert record["model"] == "anthropic/claude-sonnet-4.6"
        assert record["tier"] == "sonnet"
        assert record["input_tokens"] == 1500
        assert record["output_tokens"] == 800
        assert record["cached_tokens"] == 500
        assert record["cost_micros"] == 16500
        # Provenance replaces the old always-estimated / pricing_source pair.
        assert record["reporter"] == "openrouter"
        assert record["confidence"] == "reported"
        assert "estimated" not in record
        assert "pricing_source" not in record
        assert record["failed"] is False
        assert record["request_id"] == "req_abc123"
        assert record["ts"].endswith("Z")
        assert read_cost_logs()[0]["backend_id"] == "openrouter"

    def test_unavailable_cost_is_none_not_zero(self, cost_log_dir: Path):
        """No reported cost → cost_micros is None (not 0); tokens still recorded."""
        log_request_cost(
            proxy_id="anthropic-passthrough",
            model="claude-opus-4-6",
            tier="opus",
            input_tokens=1200,
            output_tokens=300,
            cached_tokens=0,
            cost_micros=None,
            latency_ms=900.0,
            failed=False,
            request_id="req_unavail",
            reporter=None,
            confidence="unavailable",
        )

        records = read_cost_logs()
        assert len(records) == 1
        record = records[0]
        assert record["cost_micros"] is None
        assert record["confidence"] == "unavailable"
        assert record["reporter"] is None
        # Tokens are preserved even when cost is unavailable.
        assert record["input_tokens"] == 1200
        assert record["output_tokens"] == 300

    def test_default_provenance_is_unknown(self, cost_log_dir: Path):
        """A caller that doesn't stamp provenance gets confidence='unknown'."""
        log_request_cost(
            proxy_id="p",
            model="m",
            tier="sonnet",
            input_tokens=10,
            output_tokens=5,
            cached_tokens=0,
            cost_micros=100,
            latency_ms=10.0,
            failed=False,
            request_id="req_default",
        )

        record = read_cost_logs()[0]
        assert record["confidence"] == "unknown"
        assert record["reporter"] is None

    def test_appends_multiple_records(self, cost_log_dir: Path):
        for i in range(3):
            log_request_cost(
                proxy_id="test",
                model="test-model",
                tier="sonnet",
                input_tokens=100 * (i + 1),
                output_tokens=50,
                cached_tokens=0,
                cost_micros=1000 * (i + 1),
                latency_ms=100.0,
                failed=False,
                request_id=f"req_{i}",
            )

        files = list(cost_log_dir.glob("*.jsonl"))
        assert len(files) == 1
        with open(files[0]) as f:
            lines = f.readlines()
        assert len(lines) == 3

    def test_failed_request_logged(self, cost_log_dir: Path):
        log_request_cost(
            proxy_id="test",
            model="test-model",
            tier="opus",
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            cost_micros=0,
            latency_ms=50.0,
            failed=True,
            request_id="req_fail",
        )

        records = read_cost_logs()
        assert len(records) == 1
        assert records[0]["failed"] is True


class TestRoundtrip:
    """Write with log_request_cost, read back with period filtering."""

    def test_write_then_read_with_period(self, cost_log_dir: Path):
        """Records written by the logger are findable by period-filtered reads."""
        now = datetime.now(timezone.utc)

        log_request_cost(
            proxy_id="test",
            model="claude-sonnet-4-6",
            tier="sonnet",
            input_tokens=1000,
            output_tokens=500,
            cached_tokens=200,
            cost_micros=5000,
            latency_ms=100.0,
            failed=False,
            request_id="req_roundtrip",
        )

        one_minute_ago = now - timedelta(minutes=1)
        one_minute_later = now + timedelta(minutes=1)
        records = read_cost_logs(period_start=one_minute_ago, period_end=one_minute_later)
        assert len(records) == 1
        assert records[0]["request_id"] == "req_roundtrip"
        assert records[0]["cost_micros"] == 5000

    def test_timestamp_format_is_valid_utc(self, cost_log_dir: Path):
        """Written timestamps parse correctly and don't have double suffixes."""
        log_request_cost(
            proxy_id="test",
            model="m",
            tier="t",
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            cost_micros=0,
            latency_ms=0,
            failed=False,
            request_id="req_ts",
        )

        records = read_cost_logs()
        assert len(records) == 1
        ts_str = records[0]["ts"]
        assert ts_str.endswith("Z")
        assert "+00:00" not in ts_str
        parsed = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None


class TestReadCostLogs:
    def test_empty_dir_returns_empty(self, cost_log_dir: Path):
        assert read_cost_logs() == []

    def test_reads_all_shards(self, cost_log_dir: Path):
        """Simulate multiple PID shards."""
        cost_log_dir.mkdir(parents=True, exist_ok=True)

        for pid in [1234, 5678]:
            path = cost_log_dir / f"2026-05_{pid}.jsonl"
            with open(path, "w") as f:
                record = {
                    "kind": "attempt",
                    "downstream_event_id": f"ds_{pid}",
                    "ts": "2026-05-07T10:00:00Z",
                    "cost_micros": pid,
                    "model": "m",
                }
                f.write(json.dumps(record) + "\n")

        records = read_cost_logs()
        assert len(records) == 2

    def test_filters_by_period(self, cost_log_dir: Path):
        cost_log_dir.mkdir(parents=True, exist_ok=True)
        path = cost_log_dir / "2026-05_9999.jsonl"
        with open(path, "w") as f:
            for hour in [8, 12, 16]:
                record = {
                    "kind": "attempt",
                    "downstream_event_id": f"ds_{hour}",
                    "ts": f"2026-05-07T{hour:02d}:00:00Z",
                    "cost_micros": 100,
                }
                f.write(json.dumps(record) + "\n")

        start = datetime(2026, 5, 7, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 5, 7, 14, 0, 0, tzinfo=timezone.utc)
        records = read_cost_logs(period_start=start, period_end=end)
        assert len(records) == 1
        assert "T12:00:00" in records[0]["ts"]

    def test_skips_malformed_lines(self, cost_log_dir: Path):
        cost_log_dir.mkdir(parents=True, exist_ok=True)
        path = cost_log_dir / "2026-05_9999.jsonl"
        with open(path, "w") as f:
            f.write("not json\n")
            f.write(
                json.dumps(
                    {
                        "kind": "attempt",
                        "downstream_event_id": "ds_ok",
                        "ts": "2026-05-07T10:00:00Z",
                        "request_id": "req_ok",
                    }
                )
                + "\n"
            )
            f.write("\n")

        records = read_cost_logs()
        assert len(records) == 1
        assert records[0]["request_id"] == "req_ok"

    def test_provider_trace_fragment_does_not_clobber_cost_confidence(self, cost_log_dir: Path):
        """A later provider-trace fragment carries default confidence=unknown, which is not
        cost evidence and must not replace the cost fragment's provenance."""
        cost_log_dir.mkdir(parents=True, exist_ok=True)
        path = cost_log_dir / "2026-05_9999.jsonl"
        with open(path, "w") as f:
            f.write(
                json.dumps(
                    {
                        "kind": "attempt",
                        "downstream_event_id": "ds_one",
                        "ts": "2026-05-07T10:00:00Z",
                        "request_id": "req_one",
                        "proxy_id": "p1",
                        "cost_micros": 100,
                        "reporter": "openrouter",
                        "confidence": "reported",
                    }
                )
                + "\n"
            )
            f.write(
                json.dumps(
                    {
                        "kind": "attempt",
                        "downstream_event_id": "ds_one",
                        "ts": "2026-05-07T10:00:01Z",
                        "request_id": "req_one",
                        "proxy_id": "p1",
                        "provider_generation_id": "gen_123",
                        "confidence": "unknown",
                    }
                )
                + "\n"
            )

        record = read_cost_logs()[0]
        assert record["confidence"] == "reported"
        assert record["request_id"] == "req_one"


class TestForgeRunCorrelation:
    """Slice 4g: cost records carry the Forge run-tree ids; the root-join sums them."""

    def _log(self, dir_: Path, *, root: str | None, run: str | None, cost: int | None) -> None:
        log_request_cost(
            proxy_id="p1",
            model="gpt-5.5",
            tier="sonnet",
            input_tokens=10,
            output_tokens=4,
            cached_tokens=1,
            cost_micros=cost,
            latency_ms=1.0,
            failed=False,
            request_id="req_" + (run or root or "x"),
            reporter="openrouter" if cost is not None else None,
            confidence="reported" if cost is not None else "unavailable",
            forge_run_id=run,
            forge_root_run_id=root,
        )

    def test_fields_persisted_additively(self, cost_log_dir: Path):
        self._log(cost_log_dir, root="run_root00000", run="run_leaf00000", cost=12345)
        rec = read_cost_logs()[0]
        assert rec["forge_run_id"] == "run_leaf00000"
        assert rec["forge_root_run_id"] == "run_root00000"
        # Additive: schema version unchanged (old readers .get() these as None).
        assert rec["schema_version"] == 1

    def test_fields_default_none_when_absent(self, cost_log_dir: Path):
        log_request_cost(
            proxy_id="p1",
            model="m",
            tier="sonnet",
            input_tokens=1,
            output_tokens=1,
            cached_tokens=0,
            cost_micros=10,
            latency_ms=1.0,
            failed=False,
            request_id="req_x",
        )
        rec = read_cost_logs()[0]
        assert rec["forge_run_id"] is None
        assert rec["forge_root_run_id"] is None

    def test_root_join_sums_by_root(self, cost_log_dir: Path):
        from forge.proxy.cost_logger import sum_reported_cost_by_root

        self._log(cost_log_dir, root="run_A", run="run_a1", cost=100)
        self._log(cost_log_dir, root="run_A", run="run_a2", cost=50)
        self._log(cost_log_dir, root="run_B", run="run_b1", cost=999)  # different root, excluded
        join = sum_reported_cost_by_root({"run_A"})
        assert join.has_records and join.has_cost
        assert join.cost_micros == 150
        assert join.roots_with_records == {"run_A"}
        assert join.per_run == {"run_a1": 100, "run_a2": 50}
        assert join.runs_with_records == {"run_a1", "run_a2"}

    def test_root_join_present_without_cost(self, cost_log_dir: Path):
        from forge.proxy.cost_logger import sum_reported_cost_by_root

        self._log(cost_log_dir, root="run_A", run="run_a1", cost=None)  # passthrough: no dollars
        join = sum_reported_cost_by_root({"run_A"})
        assert join.has_records is True  # the run went through the proxy
        assert join.has_cost is False  # but no price -> not $0
        assert join.cost_micros is None
        assert join.input_tokens == 10  # tokens still summed
        # Presence is tracked even with no dollars (per_run holds only dollar-bearing runs),
        # so read-time suppression can supersede the snapshot of a records-but-priceless run.
        assert join.runs_with_records == {"run_a1"}
        assert join.per_run == {}

    def test_root_join_runs_with_records_mixes_dollar_and_priceless(self, cost_log_dir: Path):
        from forge.proxy.cost_logger import sum_reported_cost_by_root

        self._log(cost_log_dir, root="run_A", run="run_paid", cost=70)
        self._log(cost_log_dir, root="run_A", run="run_free", cost=None)  # passthrough
        join = sum_reported_cost_by_root({"run_A"})
        assert join.runs_with_records == {"run_paid", "run_free"}  # both present
        assert join.per_run == {"run_paid": 70}  # only the dollar-bearing run

    def test_root_join_skips_bool_cost_micros(self, cost_log_dir: Path):
        """bool is an int subclass: a corrupt ``cost_micros: true`` line must read as
        presence-without-dollars (like null), never sum as 1 micro."""
        from forge.proxy.cost_logger import sum_reported_cost_by_root

        self._log(cost_log_dir, root="run_A", run="run_a1", cost=100)
        # The typed writer cannot produce a bool; append the corrupt line directly.
        shard = next(cost_log_dir.glob("*.jsonl"))
        with shard.open("a", encoding="utf-8") as f:
            corrupt = {
                "kind": "attempt",
                "downstream_event_id": "ds_bool",
                "ts": "2099-01-01T00:00:00+00:00",
                "forge_root_run_id": "run_A",
                "forge_run_id": "run_a2",
                "cost_micros": True,
            }
            f.write(json.dumps(corrupt) + "\n")
        join = sum_reported_cost_by_root({"run_A"})
        assert join.cost_micros == 100  # the bool contributed no dollars
        assert join.per_run == {"run_a1": 100}
        assert join.runs_with_records == {"run_a1", "run_a2"}  # presence still counted

    def test_root_join_empty_roots_no_disk_read(self, cost_log_dir: Path):
        from forge.proxy.cost_logger import sum_reported_cost_by_root

        # Common no-proxied-run case: returns empty without globbing shards.
        join = sum_reported_cost_by_root(set())
        assert not join.has_records and join.cost_micros is None

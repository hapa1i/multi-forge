"""Tests for spend cap enforcement (CostTracker)."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from forge.core.telemetry.caps import (
    CapState,
    cap_state_path,
    load_cap_state,
    write_cap_state,
)
from forge.proxy.cost_tracker import CostTracker


class TestParseRecordGuard:
    """`_parse_record` skips valid-but-non-object JSON lines (returns None)."""

    @pytest.mark.parametrize("bad_line", ["[]", "1", '"x"', "null", "true"])
    def test_parse_record_skips_non_object_line(self, bad_line: str) -> None:
        # Exercised directly: bootstrap_from_logs wraps _parse_record in a broad
        # `except Exception: continue`, so a bootstrap-level test passes even with
        # the bug present. The direct call is what proves the guard exists.
        assert CostTracker._parse_record(bad_line) is None


class TestCostTrackerBasic:
    def test_no_caps_never_exceeded(self):
        t = CostTracker()
        for _ in range(100):
            t.record(1_000_000)
        assert not t.check_cap().exceeded

    def test_daily_cap_blocks_when_exceeded(self):
        t = CostTracker(daily_cap_usd=1.00)
        t.record(500_000)
        assert not t.check_cap().exceeded

        t.record(600_000)
        result = t.check_cap()
        assert result.exceeded
        assert result.cap_type == "daily"

    def test_monthly_cap_blocks_when_exceeded(self):
        t = CostTracker(monthly_cap_usd=5.00)
        t.record(4_000_000)
        assert not t.check_cap().exceeded

        t.record(1_500_000)
        result = t.check_cap()
        assert result.exceeded
        assert result.cap_type == "monthly"

    def test_daily_checked_before_monthly(self):
        t = CostTracker(daily_cap_usd=1.00, monthly_cap_usd=100.00)
        t.record(1_500_000)
        result = t.check_cap()
        assert result.exceeded
        assert result.cap_type == "daily"

    def test_has_caps(self):
        assert not CostTracker().has_caps
        assert CostTracker(daily_cap_usd=1.0).has_caps
        assert CostTracker(monthly_cap_usd=5.0).has_caps

    def test_record_none_is_skipped(self):
        """Unavailable cost (None) advances no aggregate and never raises.

        Caps account for cost-reported requests only; a None would otherwise
        raise TypeError at the `<= 0` guard.
        """
        t = CostTracker(daily_cap_usd=1.00)
        t.record(None)
        assert t.daily_spend_micros() == 0
        assert t.monthly_spend_micros() == 0
        assert not t.check_cap().exceeded

    def test_parse_record_skips_null_cost(self):
        """A valid record whose cost_micros is null is skipped (cost unavailable).

        Direct call (deterministic, no month-window dependency): int(None) would
        otherwise raise, and the unavailable cost must never advance caps.
        """
        line = json.dumps({"ts": "2026-06-01T00:00:00Z", "cost_micros": None, "proxy_id": "p"})
        assert CostTracker._parse_record(line) is None


class TestCapSummary:
    def test_summary_with_both_caps(self):
        t = CostTracker(daily_cap_usd=10.00, monthly_cap_usd=100.00)
        t.record(2_000_000)
        summary = t.cap_summary()
        assert "daily" in summary
        assert "monthly" in summary
        assert summary["daily"]["current_usd"] == pytest.approx(2.0)
        assert summary["daily"]["limit_usd"] == pytest.approx(10.0)
        assert summary["monthly"]["current_usd"] == pytest.approx(2.0)

    def test_summary_no_caps(self):
        t = CostTracker()
        assert t.cap_summary() == {}


class TestBootstrap:
    def test_bootstrap_from_empty_dir(self, tmp_path: Path):
        t = CostTracker(daily_cap_usd=10.0)
        t.bootstrap_from_logs(tmp_path / "nonexistent")
        assert t.daily_spend_micros() == 0

    def test_bootstrap_reads_current_month(self, tmp_path: Path):
        log_dir = tmp_path / "costs" / "requests"
        log_dir.mkdir(parents=True)

        now = datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")
        path = log_dir / f"{month}_9999.jsonl"

        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(path, "w") as f:
            f.write(json.dumps({"ts": ts, "cost_micros": 500_000}) + "\n")
            f.write(json.dumps({"ts": ts, "cost_micros": 300_000}) + "\n")

        t = CostTracker(daily_cap_usd=10.0, monthly_cap_usd=100.0)
        t.bootstrap_from_logs(log_dir)

        assert t.daily_spend_micros() == 800_000
        assert t.monthly_spend_micros() == 800_000

    def test_bootstrap_skips_zero_cost(self, tmp_path: Path):
        log_dir = tmp_path / "costs" / "requests"
        log_dir.mkdir(parents=True)

        now = datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")
        path = log_dir / f"{month}_9999.jsonl"

        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(path, "w") as f:
            f.write(json.dumps({"ts": ts, "cost_micros": 0}) + "\n")
            f.write(json.dumps({"ts": ts, "cost_micros": 100_000}) + "\n")

        t = CostTracker(daily_cap_usd=10.0)
        t.bootstrap_from_logs(log_dir)
        assert t.daily_spend_micros() == 100_000

    def test_bootstrap_caps_survive_init(self, tmp_path: Path):
        """After bootstrap, check_cap uses the bootstrapped data."""
        log_dir = tmp_path / "costs" / "requests"
        log_dir.mkdir(parents=True)

        now = datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")
        path = log_dir / f"{month}_9999.jsonl"

        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(path, "w") as f:
            f.write(json.dumps({"ts": ts, "cost_micros": 5_500_000}) + "\n")

        t = CostTracker(daily_cap_usd=5.00)
        t.bootstrap_from_logs(log_dir)

        result = t.check_cap()
        assert result.exceeded
        assert result.cap_type == "daily"

    def test_bootstrap_reads_multiple_shards(self, tmp_path: Path):
        log_dir = tmp_path / "costs" / "requests"
        log_dir.mkdir(parents=True)

        now = datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        for pid in [1111, 2222]:
            path = log_dir / f"{month}_{pid}.jsonl"
            with open(path, "w") as f:
                f.write(json.dumps({"ts": ts, "cost_micros": 100_000}) + "\n")

        t = CostTracker(monthly_cap_usd=10.0)
        t.bootstrap_from_logs(log_dir)
        assert t.monthly_spend_micros() == 200_000

    def test_bootstrap_filters_by_proxy_id(self, tmp_path: Path):
        log_dir = tmp_path / "costs" / "requests"
        log_dir.mkdir(parents=True)

        now = datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        path = log_dir / f"{month}_9999.jsonl"
        with open(path, "w") as f:
            f.write(json.dumps({"ts": ts, "cost_micros": 100_000, "proxy_id": "proxy-a"}) + "\n")
            f.write(json.dumps({"ts": ts, "cost_micros": 200_000, "proxy_id": "proxy-b"}) + "\n")
            f.write(json.dumps({"ts": ts, "cost_micros": 300_000, "proxy_id": "proxy-a"}) + "\n")

        t = CostTracker(daily_cap_usd=10.0, monthly_cap_usd=100.0)
        t.bootstrap_from_logs(log_dir, proxy_id="proxy-a")

        assert t.daily_spend_micros() == 400_000
        assert t.monthly_spend_micros() == 400_000

    def test_bootstrap_no_proxy_id_reads_all(self, tmp_path: Path):
        log_dir = tmp_path / "costs" / "requests"
        log_dir.mkdir(parents=True)

        now = datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        path = log_dir / f"{month}_9999.jsonl"
        with open(path, "w") as f:
            f.write(json.dumps({"ts": ts, "cost_micros": 100_000, "proxy_id": "proxy-a"}) + "\n")
            f.write(json.dumps({"ts": ts, "cost_micros": 200_000, "proxy_id": "proxy-b"}) + "\n")
            f.write(json.dumps({"ts": ts, "cost_micros": 50_000}) + "\n")

        t = CostTracker(daily_cap_usd=10.0)
        t.bootstrap_from_logs(log_dir, proxy_id=None)
        assert t.daily_spend_micros() == 350_000

    def test_bootstrap_skips_records_without_proxy_id(self, tmp_path: Path):
        """Records without proxy_id are excluded when filtering is active."""
        log_dir = tmp_path / "costs" / "requests"
        log_dir.mkdir(parents=True)

        now = datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        path = log_dir / f"{month}_9999.jsonl"
        with open(path, "w") as f:
            f.write(json.dumps({"ts": ts, "cost_micros": 100_000, "proxy_id": "proxy-a"}) + "\n")
            f.write(json.dumps({"ts": ts, "cost_micros": 200_000}) + "\n")

        t = CostTracker(daily_cap_usd=10.0)
        t.bootstrap_from_logs(log_dir, proxy_id="proxy-a")
        assert t.daily_spend_micros() == 100_000

    def test_bootstrap_dedupes_downstream_event_id(self, tmp_path: Path):
        log_dir = tmp_path / "telemetry" / "downstream"
        log_dir.mkdir(parents=True)

        now = datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        path = log_dir / f"{month}_9999.jsonl"
        with open(path, "w") as f:
            for _ in range(2):
                f.write(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "kind": "attempt",
                            "downstream_event_id": "ds_same_attempt",
                            "ts": ts,
                            "cost_micros": 100_000,
                            "proxy_id": "proxy-a",
                        }
                    )
                    + "\n"
                )

        t = CostTracker(daily_cap_usd=10.0, monthly_cap_usd=100.0)
        t.bootstrap_from_logs(log_dir, proxy_id="proxy-a")

        assert t.daily_spend_micros() == 100_000
        assert t.monthly_spend_micros() == 100_000

    def test_corrupt_cap_state_falls_back_to_logs(self, tmp_path: Path, caplog: pytest.LogCaptureFixture):
        log_dir = tmp_path / "telemetry" / "downstream"
        log_dir.mkdir(parents=True)

        now = datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        path = log_dir / f"{month}_9999.jsonl"
        with open(path, "w") as f:
            f.write(json.dumps({"ts": ts, "cost_micros": 300_000, "proxy_id": "proxy-a"}) + "\n")

        snapshot = cap_state_path("proxy-a")
        snapshot.parent.mkdir(parents=True)
        snapshot.write_text("{not json")

        t = CostTracker(daily_cap_usd=10.0, monthly_cap_usd=100.0)
        with caplog.at_level("WARNING"):
            t.bootstrap_from_logs(log_dir, proxy_id="proxy-a")

        assert t.daily_spend_micros() == 300_000
        assert t.monthly_spend_micros() == 300_000
        assert any("Ignoring unreadable spend-cap state" in message for message in caplog.messages)
        assert any("will be rebuilt from cost logs on startup" in message for message in caplog.messages)

    def test_snapshot_and_logs_reconcile_by_max_not_sum(self, tmp_path: Path):
        log_dir = tmp_path / "telemetry" / "downstream"
        log_dir.mkdir(parents=True)

        now = datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        path = log_dir / f"{month}_9999.jsonl"
        with open(path, "w") as f:
            f.write(json.dumps({"ts": ts, "cost_micros": 500_000, "proxy_id": "proxy-a"}) + "\n")

        write_cap_state(
            CapState(
                proxy_id="proxy-a",
                monthly_key=month,
                monthly_total_micros=500_000,
                daily_window=[(time.time(), 500_000)],
            )
        )

        t = CostTracker(daily_cap_usd=10.0, monthly_cap_usd=100.0)
        t.bootstrap_from_logs(log_dir, proxy_id="proxy-a")

        assert t.daily_spend_micros() == 500_000
        assert t.monthly_spend_micros() == 500_000

    def test_legacy_current_month_import_prevents_clean_cut_reset(self, tmp_path: Path):
        downstream_dir = tmp_path / "telemetry" / "downstream"
        legacy_dir = tmp_path / "costs" / "requests"
        downstream_dir.mkdir(parents=True)
        legacy_dir.mkdir(parents=True)

        now = datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        path = legacy_dir / f"{month}_9999.jsonl"
        with open(path, "w") as f:
            f.write(json.dumps({"ts": ts, "cost_micros": 700_000, "proxy_id": "proxy-a"}) + "\n")

        t = CostTracker(daily_cap_usd=10.0, monthly_cap_usd=100.0)
        t.bootstrap_from_logs(downstream_dir, proxy_id="proxy-a", legacy_log_dir=legacy_dir)

        assert t.daily_spend_micros() == 700_000
        assert t.monthly_spend_micros() == 700_000

    def test_previous_month_snapshot_keeps_rolling_daily_window(self, tmp_path: Path):
        log_dir = tmp_path / "telemetry" / "downstream"
        log_dir.mkdir(parents=True)

        now = datetime.now(timezone.utc)
        previous_month = f"{now.year - 1}-12" if now.month == 1 else f"{now.year}-{now.month - 1:02d}"
        write_cap_state(
            CapState(
                proxy_id="proxy-a",
                monthly_key=previous_month,
                monthly_total_micros=900_000,
                daily_window=[(time.time(), 200_000)],
            )
        )

        t = CostTracker(daily_cap_usd=10.0, monthly_cap_usd=100.0)
        t.bootstrap_from_logs(log_dir, proxy_id="proxy-a")

        assert t.daily_spend_micros() == 200_000
        assert t.monthly_spend_micros() == 0

    def test_cap_state_persist_is_throttled_and_flushable(self, tmp_path: Path):
        log_dir = tmp_path / "telemetry" / "downstream"

        t = CostTracker(daily_cap_usd=10.0, monthly_cap_usd=100.0)
        t.bootstrap_from_logs(log_dir, proxy_id="proxy-a")

        t.record(100_000)
        state = load_cap_state("proxy-a")
        assert state is not None
        assert state.monthly_total_micros == 0

        t.flush_cap_state()
        state = load_cap_state("proxy-a")
        assert state is not None
        assert state.monthly_total_micros == 100_000


class TestDailyWindowRolling:
    def test_old_entries_pruned(self):
        t = CostTracker(daily_cap_usd=10.0)

        old_ts = time.time() - 90000  # 25 hours ago
        t._daily_window.append((old_ts, 5_000_000))
        t.record(100_000)

        assert t.daily_spend_micros() == 100_000


class TestMonthlyWindow:
    def test_month_rolls_during_preflight_check(self):
        """A long-running proxy should not reject new-month requests on stale spend."""
        t = CostTracker(monthly_cap_usd=1.00)
        t._monthly_key = "1999-01"
        t._monthly_total = 2_000_000

        result = t.check_cap()

        assert not result.exceeded
        assert t.monthly_spend_micros() == 0

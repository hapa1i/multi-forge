"""Spend cap enforcement with JSONL-bootstrapped tracking.

On proxy startup, reads the current (and previous) month's cost JSONL
logs to initialize in-memory spend counters. Caps are enforced per
request via check_cap().

One enforcement behavior: a request may cross a cap and complete; Forge
records its cost, then blocks (or warns on) the next request once
accumulated spend has exceeded the cap.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from forge.core.state import decode_json_object
from forge.core.telemetry.caps import (
    CapState,
    cap_state_path,
    load_cap_state,
    write_cap_state,
)

logger = logging.getLogger(__name__)

_MICROS_PER_DOLLAR = 1_000_000
_24H_SECONDS = 86400
_CAP_STATE_PERSIST_EVERY_RECORDS = 10
_CAP_STATE_PERSIST_INTERVAL_SECONDS = 5.0


@dataclass
class CapResult:
    """Result of a spend cap check."""

    exceeded: bool
    cap_type: str | None = None  # "daily" or "monthly"
    current_micros: int = 0
    limit_micros: int = 0


@dataclass(frozen=True)
class _ParsedCostRecord:
    ts_unix: float
    cost_micros: int
    month_key: str
    proxy_id: str | None
    downstream_event_id: str | None = None


class CostTracker:
    """In-memory spend tracking with cap enforcement.

    Thread-safe via the proxy's single-threaded async event loop
    (all calls happen on the main thread in FastAPI/uvicorn).
    """

    def __init__(
        self,
        *,
        daily_cap_usd: float | None = None,
        monthly_cap_usd: float | None = None,
        on_cap_hit: str = "reject",
    ) -> None:
        self.daily_cap_micros = int(daily_cap_usd * _MICROS_PER_DOLLAR) if daily_cap_usd is not None else None
        self.monthly_cap_micros = int(monthly_cap_usd * _MICROS_PER_DOLLAR) if monthly_cap_usd is not None else None
        self.on_cap_hit = on_cap_hit

        self._daily_window: deque[tuple[float, int]] = deque()
        self._monthly_total: int = 0
        self._monthly_key: str = ""
        self._proxy_id: str | None = None
        self._dirty_cap_records: int = 0
        self._last_cap_persisted_at: float = 0.0

    @property
    def has_caps(self) -> bool:
        return self.daily_cap_micros is not None or self.monthly_cap_micros is not None

    def bootstrap_from_logs(
        self,
        log_dir: Path,
        *,
        proxy_id: str | None = None,
    ) -> None:
        """Read existing cost logs to initialize spend counters.

        Reads current month + previous month (for rolling 24h window
        at month boundaries). Scans all PID shards.

        When proxy_id is set, only records matching that proxy are counted.
        Records without a proxy_id field are skipped (pre-proxy-id logs).
        When proxy_id is None, all records are counted (backward compat).
        """
        self._proxy_id = proxy_id
        now = datetime.now(timezone.utc)
        current_month = now.strftime("%Y-%m")
        self._monthly_key = current_month

        if now.month == 1:
            prev_month = f"{now.year - 1}-12"
        else:
            prev_month = f"{now.year}-{now.month - 1:02d}"

        cutoff = time.time() - _24H_SECONDS
        unkeyed_log_records: list[_ParsedCostRecord] = []
        keyed_log_records: dict[str, _ParsedCostRecord] = {}

        paths = list(sorted(log_dir.glob("*.jsonl"))) if log_dir.is_dir() else []

        for path in paths:
            fname = path.stem  # e.g., "2026-05_12345"
            file_month = fname.split("_")[0] if "_" in fname else fname

            if file_month not in (current_month, prev_month):
                continue

            try:
                with open(path) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = self._parse_record(line)
                        except Exception:
                            continue
                        if record is None:
                            continue

                        if proxy_id is not None and record.proxy_id != proxy_id:
                            continue

                        if record.downstream_event_id:
                            keyed_log_records[record.downstream_event_id] = record
                        else:
                            unkeyed_log_records.append(record)
            except OSError as e:
                logger.warning("Failed to read cost log %s: %s", path, e)

        log_daily_window: deque[tuple[float, int]] = deque()
        log_monthly_total = 0
        for record in [*unkeyed_log_records, *keyed_log_records.values()]:
            if record.month_key == current_month:
                log_monthly_total += record.cost_micros
            if record.ts_unix >= cutoff:
                log_daily_window.append((record.ts_unix, record.cost_micros))

        state = None
        if proxy_id:
            try:
                state = load_cap_state(proxy_id)
            except Exception as e:
                logger.warning(
                    "Ignoring unreadable spend-cap state at %s; will be rebuilt from cost logs on startup: %s",
                    cap_state_path(proxy_id),
                    e,
                )
        state_daily_window: deque[tuple[float, int]] = deque()
        state_monthly_total = 0
        if state:
            if state.monthly_key == current_month:
                state_monthly_total = state.monthly_total_micros
            for ts, cost in state.daily_window:
                if ts >= cutoff:
                    state_daily_window.append((ts, cost))

        log_daily_total = sum(c for _, c in log_daily_window)
        state_daily_total = sum(c for _, c in state_daily_window)
        self._monthly_total = max(log_monthly_total, state_monthly_total)
        self._daily_window = state_daily_window if state_daily_total > log_daily_total else log_daily_window

        if proxy_id:
            self._persist_cap_state()

        daily_total = sum(c for _, c in self._daily_window)
        logger.info(
            "Cost tracker bootstrapped: daily=$%.2f, monthly=$%.2f (%d records in window)",
            daily_total / _MICROS_PER_DOLLAR,
            self._monthly_total / _MICROS_PER_DOLLAR,
            len(self._daily_window),
        )

    @staticmethod
    def _parse_record(line: str) -> _ParsedCostRecord | None:
        """Parse a JSONL line into one cost-bearing record, or ``None`` when it has no cost."""
        # Skip blank / malformed / non-object lines (`[]`, `1`): return None rather than let
        # `.get` raise AttributeError (bootstrap's broad except would otherwise mask it).
        data = decode_json_object(line)
        if data is None:
            return None
        ts_str = data.get("ts", "")
        # Cost is nullable: a null (or absent) cost_micros means the route reported
        # no cost. It never advances spend caps, so skip it explicitly rather than let
        # int(None) raise (the bootstrap's broad except would otherwise mask the line).
        raw_cost = data.get("cost_micros")
        if raw_cost is None:
            return None
        cost_micros = int(raw_cost)
        if cost_micros <= 0:
            return None

        try:
            ts = datetime.fromisoformat(ts_str.rstrip("Z").removesuffix("+00:00") + "+00:00")
        except (ValueError, TypeError):
            return None

        month_key = ts.strftime("%Y-%m")
        record_proxy_id = data.get("proxy_id")
        event_id = data.get("downstream_event_id")
        return _ParsedCostRecord(
            ts_unix=ts.timestamp(),
            cost_micros=cost_micros,
            month_key=month_key,
            proxy_id=record_proxy_id if isinstance(record_proxy_id, str) else None,
            downstream_event_id=event_id if isinstance(event_id, str) and event_id else None,
        )

    def _persist_cap_state(self) -> None:
        if not self._proxy_id:
            return
        try:
            self._prune_daily_window()
            write_cap_state(
                CapState(
                    proxy_id=self._proxy_id,
                    monthly_key=self._monthly_key,
                    monthly_total_micros=self._monthly_total,
                    daily_window=list(self._daily_window),
                )
            )
            self._dirty_cap_records = 0
            self._last_cap_persisted_at = time.monotonic()
        except Exception as e:
            logger.warning("Failed to persist spend-cap state for %s: %s", self._proxy_id, e)

    def _maybe_persist_cap_state(self) -> None:
        if not self._proxy_id:
            return
        self._dirty_cap_records += 1
        elapsed = time.monotonic() - self._last_cap_persisted_at
        if (
            self._dirty_cap_records >= _CAP_STATE_PERSIST_EVERY_RECORDS
            or elapsed >= _CAP_STATE_PERSIST_INTERVAL_SECONDS
        ):
            self._persist_cap_state()

    def flush_cap_state(self) -> None:
        """Persist any throttled spend-cap snapshot before process shutdown."""
        if self._dirty_cap_records > 0:
            self._persist_cap_state()

    def record(self, cost_micros: int | None) -> None:
        """Record a completed request's cost.

        ``None`` means the route reported no cost (cost unavailable). Caps account
        only for cost-reported requests, so an unavailable cost is skipped rather
        than treated as ``0`` — and ``None <= 0`` would otherwise raise ``TypeError``.
        """
        if cost_micros is None or cost_micros <= 0:
            return

        now = time.time()
        self._roll_month_if_needed()

        self._monthly_total += cost_micros
        self._daily_window.append((now, cost_micros))
        self._maybe_persist_cap_state()

    def _roll_month_if_needed(self) -> None:
        """Reset the calendar-month accumulator when UTC month changes."""
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        if current_month != self._monthly_key:
            self._monthly_total = 0
            self._monthly_key = current_month

    def _prune_daily_window(self) -> None:
        """Remove entries older than 24 hours from the rolling window."""
        cutoff = time.time() - _24H_SECONDS
        while self._daily_window and self._daily_window[0][0] < cutoff:
            self._daily_window.popleft()

    def daily_spend_micros(self) -> int:
        """Current rolling 24h spend in microdollars."""
        self._prune_daily_window()
        return sum(c for _, c in self._daily_window)

    def monthly_spend_micros(self) -> int:
        """Current calendar month spend in microdollars."""
        self._roll_month_if_needed()
        return self._monthly_total

    def check_cap(self) -> CapResult:
        """Return whether accumulated spend has exceeded any configured cap.

        Enforcement is post-event: this checks already-recorded spend only, so a
        request may cross a cap and complete; the next request is what gets blocked.
        """
        if not self.has_caps:
            return CapResult(exceeded=False)

        if self.daily_cap_micros is not None:
            daily = self.daily_spend_micros()
            if daily >= self.daily_cap_micros:
                return CapResult(
                    exceeded=True,
                    cap_type="daily",
                    current_micros=daily,
                    limit_micros=self.daily_cap_micros,
                )

        if self.monthly_cap_micros is not None:
            monthly = self.monthly_spend_micros()
            if monthly >= self.monthly_cap_micros:
                return CapResult(
                    exceeded=True,
                    cap_type="monthly",
                    current_micros=monthly,
                    limit_micros=self.monthly_cap_micros,
                )

        return CapResult(exceeded=False)

    def cap_summary(self) -> dict[str, dict[str, float]]:
        """Return current spend vs caps for CLI display."""
        result: dict[str, dict[str, float]] = {}
        if self.daily_cap_micros is not None:
            daily = self.daily_spend_micros()
            result["daily"] = {
                "current_usd": daily / _MICROS_PER_DOLLAR,
                "limit_usd": self.daily_cap_micros / _MICROS_PER_DOLLAR,
                "percent": round(daily / self.daily_cap_micros * 100, 1) if self.daily_cap_micros > 0 else 0,
            }
        if self.monthly_cap_micros is not None:
            monthly = self.monthly_spend_micros()
            result["monthly"] = {
                "current_usd": monthly / _MICROS_PER_DOLLAR,
                "limit_usd": self.monthly_cap_micros / _MICROS_PER_DOLLAR,
                "percent": round(monthly / self.monthly_cap_micros * 100, 1) if self.monthly_cap_micros > 0 else 0,
            }
        return result

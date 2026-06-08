"""PID-sharded JSONL cost log writer.

Each proxy process writes to its own shard file to avoid interprocess
locking. The CLI aggregates across shards at query time.

Location: ~/.forge/costs/requests/YYYY-MM_<pid>.jsonl
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from forge.core.paths import get_forge_home
from forge.core.state import decode_json_object
from forge.core.usage.vocabulary import Confidence, Reporter

logger = logging.getLogger(__name__)

COST_SCHEMA_VERSION = 1

_lock = threading.Lock()

# One-time warning latch for records written by a newer Forge.
_warned_newer_schema = False


def _pid_suffix() -> str:
    return str(os.getpid())


def _costs_dir() -> Path:
    return get_forge_home() / "costs" / "requests"


def _current_log_path() -> Path:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return _costs_dir() / f"{month}_{_pid_suffix()}.jsonl"


def log_request_cost(
    *,
    proxy_id: str,
    model: str,
    tier: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
    cost_micros: int | None,
    latency_ms: float,
    failed: bool,
    request_id: str,
    reporter: Reporter | None = None,
    confidence: Confidence = "unknown",
    forge_run_id: str | None = None,
    forge_root_run_id: str | None = None,
) -> None:
    """Append a cost record to the PID-sharded JSONL log.

    ``cost_micros`` is ``None`` when no route reported a cost — distinct from a
    reported ``0`` (genuinely free). ``confidence`` records the dollar figure's
    provenance and ``reporter`` who supplied it; together they replace the old
    always-``estimated`` / ``pricing_source`` pair (the metric-evidence card:
    Forge is not a cost oracle).

    ``forge_run_id``/``forge_root_run_id`` (Slice 4g) carry the run-tree identity of
    the Forge ``claude -p`` subprocess that made this request, read+validated from
    the ``X-Forge-Run-ID``/``X-Forge-Root-Run-ID`` headers; ``None`` for the
    interactive harness and any non-Forge-originated traffic. They are the join key
    that makes proxied ``claude -p`` cost attributable to a run exactly (vs the
    concurrency-fragile snapshot delta). Additive + defaulted: old readers `.get`
    them as ``None``, so no ``COST_SCHEMA_VERSION`` bump (same precedent as
    ``reporter``/``confidence``). Best-effort: write failures are logged but never
    block the request.
    """
    record: dict[str, Any] = {
        "schema_version": COST_SCHEMA_VERSION,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "proxy_id": proxy_id,
        "model": model,
        "tier": tier,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "cost_micros": cost_micros,
        "reporter": reporter,
        "confidence": confidence,
        "latency_ms": round(latency_ms, 1),
        "failed": failed,
        "request_id": request_id,
        "forge_run_id": forge_run_id,
        "forge_root_run_id": forge_root_run_id,
    }

    try:
        from forge.core.state import open_secure_append

        log_path = _current_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        with _lock:
            with open_secure_append(log_path) as f:
                f.write(json.dumps(record, separators=(",", ":")) + "\n")
    except Exception as e:
        logger.warning("Failed to write cost log: %s", e)


def read_cost_logs(
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> list[dict[str, Any]]:
    """Read and aggregate cost records from all PID shards.

    Args:
        period_start: Only include records at or after this time (UTC).
        period_end: Only include records before this time (UTC).

    Returns:
        List of cost record dicts, sorted by timestamp.

    Skips malformed lines and records written by a newer Forge (schema_version >
    COST_SCHEMA_VERSION), surfacing the latter once at warning level. Legacy
    unversioned records (no schema_version) are read normally.
    """
    costs_dir = _costs_dir()
    if not costs_dir.is_dir():
        return []

    global _warned_newer_schema
    records: list[dict[str, Any]] = []
    for path in sorted(costs_dir.glob("*.jsonl")):
        try:
            with open(path) as f:
                for line in f:
                    record = decode_json_object(line)
                    if record is None:
                        continue

                    ver = record.get("schema_version")
                    if isinstance(ver, int) and ver > COST_SCHEMA_VERSION:
                        if not _warned_newer_schema:
                            logger.warning(
                                "Skipping cost records written by a newer Forge (schema_version=%s); upgrade Forge",
                                ver,
                            )
                            _warned_newer_schema = True
                        continue

                    if period_start or period_end:
                        ts_str = record.get("ts", "")
                        try:
                            ts = datetime.fromisoformat(ts_str.rstrip("Z").removesuffix("+00:00") + "+00:00")
                        except (ValueError, TypeError):
                            continue
                        if period_start and ts < period_start:
                            continue
                        if period_end and ts >= period_end:
                            continue

                    records.append(record)
        except OSError as e:
            logger.warning("Failed to read cost log %s: %s", path, e)

    records.sort(key=lambda r: r.get("ts", ""))
    return records


@dataclass
class RootCostJoin:
    """Result of joining cost records to a run tree by ``forge_root_run_id`` (Slice 4g).

    ``has_records`` (any record matched a root — the run went through a Forge proxy)
    and ``has_cost`` (any matched record reported a dollar figure) are deliberately
    distinct: an ``anthropic-passthrough`` / LiteLLM-streaming route writes records
    with ``cost_micros=None``, so a run can be present (suppress the snapshot
    estimate) yet have no exact dollars (render unavailable, not ``$0``).
    """

    roots_with_records: set[str] = field(default_factory=set)
    cost_micros: int | None = None  # summed reported cost; None when no matched record reported one
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    per_run: dict[str, int] = field(default_factory=dict)  # forge_run_id -> summed reported micros
    # Every forge_run_id seen on a matched record, INCLUDING dollar-less ones (per_run
    # holds only the dollar-bearing subset). Read-time suppression keys on this presence
    # set, not per_run, so a records-present/no-dollars run still supersedes its snapshot.
    runs_with_records: set[str] = field(default_factory=set)

    @property
    def has_records(self) -> bool:
        return bool(self.roots_with_records)

    @property
    def has_cost(self) -> bool:
        return self.cost_micros is not None


def sum_reported_cost_by_root(
    roots: set[str],
    *,
    since: datetime | None = None,
) -> RootCostJoin:
    """Sum cost records whose ``forge_root_run_id`` is in ``roots`` (Slice 4g).

    The race-free, authoritative join for proxied ``claude -p`` cost: the parent
    reads this at query time (``forge activity`` / ``forge +$Y``), long after every
    request flushed its record. Sums reported ``cost_micros`` only (a ``None`` cost
    is presence-without-dollars, not a measured $0). ``since`` bounds the scan
    (pass the session ``created_at``). Returns an empty :class:`RootCostJoin` for an
    empty ``roots`` set (the common no-proxied-run case) without touching disk.
    """
    out = RootCostJoin()
    if not roots:
        return out
    for record in read_cost_logs(period_start=since):
        root = record.get("forge_root_run_id")
        if root not in roots:
            continue
        out.roots_with_records.add(root)
        out.input_tokens += int(record.get("input_tokens") or 0)
        out.output_tokens += int(record.get("output_tokens") or 0)
        out.cached_tokens += int(record.get("cached_tokens") or 0)
        run = record.get("forge_run_id")
        if isinstance(run, str):
            out.runs_with_records.add(run)  # presence (dollars or not)
        micros = record.get("cost_micros")
        if isinstance(micros, int):
            out.cost_micros = (out.cost_micros or 0) + micros
            if isinstance(run, str):
                out.per_run[run] = out.per_run.get(run, 0) + micros
    return out

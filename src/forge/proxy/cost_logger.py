"""Proxy downstream cost record adapter.

The public functions keep the old cost-log API shape while the durable records live
in the downstream telemetry plane at ``~/.forge/telemetry/downstream``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from forge.core.telemetry.downstream import (
    DownstreamRecord,
    mint_downstream_event_id,
    read_downstream_records_with_stats,
    write_downstream_record,
)
from forge.core.usage.vocabulary import Confidence, Reporter

logger = logging.getLogger(__name__)

COST_SCHEMA_VERSION = 1

# One-time warning latch for records written by a newer Forge.
_warned_newer_schema = False


@dataclass(frozen=True)
class CostLogReadResult:
    records: list[dict[str, Any]]
    skipped_legacy_schema: int = 0


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
    downstream_event_id: str | None = None,
    backend_id: str | None = None,
) -> None:
    """Append a cost record to the downstream telemetry plane.

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
    downstream_id = downstream_event_id or mint_downstream_event_id()
    write_downstream_record(
        DownstreamRecord(
            kind="attempt",
            downstream_event_id=downstream_id,
            request_id=request_id,
            proxy_id=proxy_id,
            source_id=proxy_id,
            source_kind="proxy",
            backend_id=backend_id,
            model=model,
            mapped_model=model,
            tier=tier,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cost_micros=cost_micros,
            reporter=reporter,
            confidence=confidence,
            latency_ms=round(latency_ms, 1),
            failed=failed,
            forge_run_id=forge_run_id,
            forge_root_run_id=forge_root_run_id,
        )
    )


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

    Skips malformed downstream lines, records written by a newer Forge, and records
    from older downstream backend-identity schemas before projecting cost records.
    """
    return read_cost_logs_with_stats(
        period_start=period_start, period_end=period_end
    ).records


def read_cost_logs_with_stats(
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> CostLogReadResult:
    """Read projected cost records plus downstream schema-fence skip counts."""
    records: list[dict[str, Any]] = []
    downstream_read = read_downstream_records_with_stats(
        period_start, period_end, kind="attempt"
    )
    for rec in downstream_read.records:
        records.append(
            {
                "schema_version": COST_SCHEMA_VERSION,
                "ts": rec.ts,
                "proxy_id": rec.proxy_id,
                "model": rec.mapped_model or rec.model or "unknown",
                "tier": rec.tier or "unknown",
                "input_tokens": rec.input_tokens or 0,
                "output_tokens": rec.output_tokens or 0,
                "cached_tokens": rec.cached_tokens or 0,
                "cost_micros": rec.cost_micros,
                "reporter": rec.reporter,
                "confidence": rec.confidence,
                "latency_ms": rec.latency_ms or 0,
                "failed": bool(rec.failed),
                "request_id": rec.request_id,
                "forge_run_id": rec.forge_run_id,
                "forge_root_run_id": rec.forge_root_run_id,
                "backend_id": rec.backend_id,
            }
        )
    return CostLogReadResult(
        records=records,
        skipped_legacy_schema=downstream_read.stats.skipped_legacy_schema,
    )


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
    cost_micros: int | None = (
        None  # summed reported cost; None when no matched record reported one
    )
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    per_run: dict[str, int] = field(
        default_factory=dict
    )  # forge_run_id -> summed reported micros
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
    reads this at query time (``forge telemetry activity`` / ``forge +$Y``), long after every
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
        # bool is an int subclass; a corrupt `cost_micros: true` must not sum as 1.
        if isinstance(micros, int) and not isinstance(micros, bool):
            out.cost_micros = (out.cost_micros or 0) + micros
            if isinstance(run, str):
                out.per_run[run] = out.per_run.get(run, 0) + micros
    return out

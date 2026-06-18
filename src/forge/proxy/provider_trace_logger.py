"""Provider lifecycle/correlation projection over downstream telemetry.

The fourth local telemetry plane: provider **lifecycle/correlation evidence** for a
single OpenRouter request — "did it leave Forge, which route/generation, did the stream
start/finish or lose its final usage chunk?" Born from an incident where a supervised
fork's checks timed out before the final streaming usage chunk and left no trace locally
or in OpenRouter's UI.

Modeled on ``audit_logger.py`` (versioned write/prune, owner-only shards) with the
strict-dacite read of ``core/usage/ledger.py``. Records are **metadata-only**: no prompt,
completion, tool output, or replayable request body ever appears here. The header
allowlist is re-applied at the writer (defense in depth) so even a future caller that
bypasses the Phase 2 boundary cannot persist ``authorization``/``cookie``.

Location: provider trace fields now live on downstream attempt records under
``~/.forge/telemetry/downstream/YYYY-MM_<pid>.jsonl`` (owner-only, 0600). The legacy
append helpers remain only for old retention compatibility; current writes go through
``write_downstream_record`` and reset with the downstream plane.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from forge.core.telemetry.downstream import (
    DownstreamRecord,
    mint_downstream_event_id,
    read_downstream_records,
    write_downstream_record,
)

logger = logging.getLogger(__name__)

PROVIDER_TRACE_SCHEMA_VERSION = 1

# One-time warning latch for records written by a newer Forge (own latch, not audit's).
_warned_newer_schema = False

RequestMode = Literal["streaming", "non_streaming"]
LocalUsageStatus = Literal["available", "unavailable"]


@dataclass
class ProviderTraceRecord:
    """One provider-trace record: lifecycle + correlation evidence for a request.

    Metadata-only — there is deliberately NO prompt/completion/tool/body field. ``ts``
    and ``schema_version`` are auto-stamped by the writer. ``first_chunk_seen`` means the
    first *user-visible* content/tool chunk (the internal ``_provider_meta`` carrier does
    not count). ``timeout_seen`` is always False at the proxy boundary: the proxy observes
    only a client disconnect, never the parent's ``subprocess.run`` timeout — the field is
    a join target for later run-tree correlation.
    """

    schema_version: int
    ts: str
    request_id: str
    proxy_id: str
    mapped_model: str
    forge_run_id: str | None
    forge_root_run_id: str | None
    provider_session_id: str | None
    provider_command: str | None
    provider: str | None
    selected_provider: str | None
    provider_response_id: str | None
    provider_generation_id: str | None
    provider_request_id: str | None
    headers: dict[str, str] | None
    request_mode: RequestMode
    stream_started: bool
    first_chunk_seen: bool
    final_usage_seen: bool
    client_disconnected: bool
    local_usage_status: LocalUsageStatus
    timeout_seen: bool = False
    reported_cost_micros: int | None = None
    latency_ms: float | None = None


# --- Write path (best-effort; never raises into the request path) ------------


def write_provider_trace(
    *,
    request_id: str,
    proxy_id: str,
    mapped_model: str,
    forge_run_id: str | None,
    forge_root_run_id: str | None,
    provider_session_id: str | None,
    provider_command: str | None,
    provider_meta: dict[str, Any] | None,
    request_mode: RequestMode,
    stream_started: bool,
    first_chunk_seen: bool,
    final_usage_seen: bool,
    client_disconnected: bool,
    local_usage_status: LocalUsageStatus,
    reported_cost_micros: int | None,
    latency_ms: float | None,
    downstream_event_id: str | None = None,
) -> None:
    """Build and persist a metadata-only provider-trace record (no gate).

    Re-applies the Phase 2 header allowlist to ``provider_meta["headers"]`` so a future
    caller that bypasses that boundary still cannot persist auth/cookie headers — the
    allowlist stays the single source of truth, applied again at the persistence edge.
    """
    from forge.core.llm.clients.openai_compat import provider_trace_headers

    pm = provider_meta or {}
    write_downstream_record(
        DownstreamRecord(
            kind="attempt",
            downstream_event_id=downstream_event_id
            or mint_downstream_event_id(event_key=f"provider_trace:{proxy_id}:{request_id}"),
            request_id=request_id,
            proxy_id=proxy_id,
            source_id=proxy_id,
            source_kind="proxy",
            mapped_model=mapped_model,
            forge_run_id=forge_run_id,
            forge_root_run_id=forge_root_run_id,
            provider_session_id=provider_session_id,
            provider_command=provider_command,
            provider=pm.get("provider"),
            selected_provider=pm.get("selected_provider"),
            provider_response_id=pm.get("provider_response_id"),
            provider_generation_id=pm.get("provider_generation_id"),
            provider_request_id=pm.get("provider_request_id"),
            provider_headers=provider_trace_headers(pm.get("headers")),  # re-filter at the edge
            request_mode=request_mode,
            stream_started=stream_started,
            first_chunk_seen=first_chunk_seen,
            final_usage_seen=final_usage_seen,
            client_disconnected=client_disconnected,
            local_usage_status=local_usage_status,
            timeout_seen=False,
            reported_cost_micros=reported_cost_micros,
            latency_ms=latency_ms,
        )
    )


def record_provider_trace(
    *,
    provider_name: str,
    request_id: str,
    proxy_id: str,
    mapped_model: str,
    forge_run_id: str | None,
    forge_root_run_id: str | None,
    provider_session_id: str | None,
    provider_command: str | None,
    provider_meta: dict[str, Any] | None,
    request_mode: RequestMode,
    stream_started: bool,
    first_chunk_seen: bool,
    final_usage_seen: bool,
    client_disconnected: bool,
    reported_cost_micros: int | None,
    latency_ms: float | None,
    downstream_event_id: str | None = None,
) -> None:
    """Gate to the direct OpenRouter route, derive local_usage_status, and persist.

    The shared write entry point for both the converters seam (``server.py``) and the
    passthrough relay (``passthrough.py``) — it lives in this neutral leaf so neither
    caller has to import the other (avoids the ``server`` <-> ``passthrough`` cycle).

    Direct-OpenRouter-only by design: gateway-routed OpenRouter (LiteLLM -> OpenRouter)
    is out of scope for this card, so a ``litellm``/``unknown`` route writes nothing.

    Forward-ref: the ``unified_backend`` board proposal (find it with ``rg unified_backend``) migrates
    this provider-literal gate to a backend-id check, broadening beyond OpenRouter via
    ``selected_provider``. A deliberate clean break -- kept a hardcoded literal, not a premature seam,
    until that proposal runs. (Slug, not a board path -- cards move lanes.)
    """
    if provider_name != "openrouter":
        return
    # "available" only when the proxy locally observed a final figure; the incident path
    # (stream cancelled before the final usage chunk) is honestly "unavailable" — probe 2
    # confirmed an aborted stream is not remotely retrievable, so there is no remote lookup.
    local_usage_status: LocalUsageStatus = (
        "available" if (final_usage_seen or reported_cost_micros is not None) else "unavailable"
    )
    try:
        write_provider_trace(
            request_id=request_id,
            proxy_id=proxy_id,
            mapped_model=mapped_model,
            forge_run_id=forge_run_id,
            forge_root_run_id=forge_root_run_id,
            provider_session_id=provider_session_id,
            provider_command=provider_command,
            provider_meta=provider_meta,
            request_mode=request_mode,
            stream_started=stream_started,
            first_chunk_seen=first_chunk_seen,
            final_usage_seen=final_usage_seen,
            client_disconnected=client_disconnected,
            local_usage_status=local_usage_status,
            reported_cost_micros=reported_cost_micros,
            latency_ms=latency_ms,
            downstream_event_id=downstream_event_id,
        )
    except Exception as e:  # belt over the writer's own braces — never break the request
        logger.debug("provider trace record skipped: %s", e)


# --- Read path (for the Phase 4 CLI) -----------------------------------------


def read_provider_traces(
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    *,
    request_id: str | None = None,
    forge_run_id: str | None = None,
    forge_root_run_id: str | None = None,
    provider_session_id: str | None = None,
) -> list[ProviderTraceRecord]:
    """Read and merge provider-trace records across PID shards, sorted by timestamp.

    Skips, with a warning, lines that are malformed JSON, written by a newer Forge
    (``schema_version`` > ``PROVIDER_TRACE_SCHEMA_VERSION``, surfaced once), or that fail
    strict shape validation (unknown field / bad value type is corruption, not
    forward-compat). Filters apply to the raw record before the typed build.
    """
    records: list[ProviderTraceRecord] = []
    for rec in read_downstream_records(
        period_start,
        period_end,
        kind="attempt",
        request_id=request_id,
        forge_run_id=forge_run_id,
        forge_root_run_id=forge_root_run_id,
        provider_session_id=provider_session_id,
    ):
        if not any(
            (
                rec.provider_generation_id,
                rec.provider_response_id,
                rec.provider_request_id,
                rec.request_mode,
                rec.local_usage_status,
            )
        ):
            continue
        request_mode: RequestMode = rec.request_mode if rec.request_mode is not None else "non_streaming"
        local_usage_status: LocalUsageStatus = (
            rec.local_usage_status if rec.local_usage_status is not None else "unavailable"
        )
        records.append(
            ProviderTraceRecord(
                schema_version=PROVIDER_TRACE_SCHEMA_VERSION,
                ts=rec.ts,
                request_id=rec.request_id or "",
                proxy_id=rec.proxy_id or "",
                mapped_model=rec.mapped_model or rec.model or "",
                forge_run_id=rec.forge_run_id,
                forge_root_run_id=rec.forge_root_run_id,
                provider_session_id=rec.provider_session_id,
                provider_command=rec.provider_command,
                provider=rec.provider,
                selected_provider=rec.selected_provider,
                provider_response_id=rec.provider_response_id,
                provider_generation_id=rec.provider_generation_id,
                provider_request_id=rec.provider_request_id,
                headers=rec.provider_headers,
                request_mode=request_mode,
                stream_started=bool(rec.stream_started),
                first_chunk_seen=bool(rec.first_chunk_seen),
                final_usage_seen=bool(rec.final_usage_seen),
                client_disconnected=bool(rec.client_disconnected),
                local_usage_status=local_usage_status,
                timeout_seen=bool(rec.timeout_seen),
                reported_cost_micros=rec.reported_cost_micros,
                latency_ms=rec.latency_ms,
            )
        )
    return records


# --- Retention ---------------------------------------------------------------


def prune_provider_traces(*, retention_days: int, max_total_mb: int) -> None:
    """Delete trace shards older than retention_days, then prune oldest-first over
    max_total_mb. Best-effort: errors are ignored (telemetry, not critical path)."""
    from forge.core.telemetry.downstream import prune_downstream_records

    prune_downstream_records(retention_days=retention_days, max_total_mb=max_total_mb)

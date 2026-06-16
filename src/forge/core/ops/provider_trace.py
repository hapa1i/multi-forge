"""Shared provider-trace operations (command-core, openrouter_observability Phase 4).

UI-agnostic read surface over the provider-trace plane (the fourth telemetry plane,
``forge.proxy.provider_trace_logger``). Invoked from both:

- the CLI (``forge provider trace list|show|explain``), and
- the in-chat direct command dispatcher (``%provider trace ...``).

Returns structured DTOs and raises ``ForgeOpError`` on failure. ``explain`` answers the
incident's five questions from LOCAL records only (trace plane + cost plane) — it never
calls a remote endpoint (remote reconciliation is a separate card).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from forge.core.run_id import derive_provider_session_id
from forge.proxy.cost_logger import read_cost_logs
from forge.proxy.provider_trace_logger import ProviderTraceRecord, read_provider_traces

from .context import ExecutionContext
from .session import ForgeOpError

_log = logging.getLogger(__name__)

# Cost-plane lookup window around a trace's timestamp. The trace is written in the same
# proxy on_complete right after the cost record, so the two timestamps are sub-second
# apart; ±5m is a bounded, clock-robust scan (not a whole-day scan).
_COST_JOIN_WINDOW = timedelta(minutes=5)


@dataclass(frozen=True)
class ListProviderTracesResult:
    traces: list[ProviderTraceRecord]
    session: str | None
    root_run_id: str | None


@dataclass(frozen=True)
class ShowProviderTraceResult:
    record: ProviderTraceRecord


@dataclass(frozen=True)
class ProviderTraceExplanation:
    """Structured answer to the incident's five questions, from local records only.

    1. ``left_forge`` — did the request reach the provider?
    2. route — ``proxy_id`` / ``provider`` / ``mapped_model`` / ``selected_provider``.
    3. inspect ids — ``provider_generation_id`` / ``provider_session_id`` / ``provider_command``.
    4. lifecycle — ``stream_started`` / ``first_chunk_seen`` / ``final_usage_seen`` / ``client_disconnected``.
    5. cost — ``local_usage_status`` + ``reported_cost_micros`` (+ ``cost_confidence`` from the cost plane).

    ``remote_lookup_performed`` is always ``False``: this surface is local-only by design.
    """

    request_id: str
    left_forge: bool
    proxy_id: str
    provider: str | None
    mapped_model: str
    selected_provider: str | None
    provider_generation_id: str | None
    provider_session_id: str | None
    provider_command: str | None
    request_mode: str
    stream_started: bool
    first_chunk_seen: bool
    final_usage_seen: bool
    client_disconnected: bool
    local_usage_status: str
    reported_cost_micros: int | None
    cost_confidence: str | None
    remote_lookup_performed: bool = False


def list_provider_traces(
    *,
    ctx: ExecutionContext,
    session: str | None = None,
    root_run_id: str | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    limit: int = 50,
) -> ListProviderTracesResult:
    """List provider-trace records (most-recent ``limit``, oldest-first), optionally filtered.

    ``session`` is session-*label* filtering: it re-derives the ``forge_sess_<hash>`` prefix
    and prefix-matches the stored (hashed) ``provider_session_id``. The id hashes the label
    only — no ``forge_root``/project, and the record carries no project field — so two
    same-named sessions in one ``FORGE_HOME`` share a prefix; pair with ``root_run_id`` when
    exactness matters. Spawns with no session label (``forge_run_<hash>``) are reachable only
    via ``root_run_id``.

    Args:
        ctx: execution context (accepted for API consistency; the plane is global).
        session: human session name; re-hashed to a label prefix for matching.
        root_run_id: exact ``forge_root_run_id`` filter.
        period_start/period_end: UTC time window.
        limit: keep at most this many most-recent records (<=0 means no cap).

    Raises:
        ForgeOpError: if the trace plane cannot be read.
    """
    _log.debug("list_provider_traces: cwd=%s session=%s root=%s", ctx.cwd, session, root_run_id)

    try:
        records = read_provider_traces(period_start, period_end, forge_root_run_id=root_run_id)
    except Exception as e:  # plane read is best-effort; surface as a typed op error
        raise ForgeOpError(f"Could not read provider traces: {e}") from e

    if session:
        prefix = derive_provider_session_id(session, root_run_id="", role=None)
        records = [r for r in records if _session_matches(r.provider_session_id, prefix)]

    # read_provider_traces returns ascending by ts; keep the most-recent `limit`.
    if limit > 0:
        records = records[-limit:]

    return ListProviderTracesResult(traces=records, session=session, root_run_id=root_run_id)


def show_provider_trace(*, ctx: ExecutionContext, request_id: str) -> ShowProviderTraceResult:
    """Return the trace record for ``request_id`` (newest if more than one shard carries it).

    Raises:
        ForgeOpError: if no trace exists for ``request_id``.
    """
    _log.debug("show_provider_trace: request_id=%s", request_id)
    record = _latest_trace(request_id)
    return ShowProviderTraceResult(record=record)


def explain_provider_trace(*, ctx: ExecutionContext, request_id: str) -> ProviderTraceExplanation:
    """Build a local-only provenance explanation for ``request_id``.

    Reads the trace record (primary) plus a bounded cost-plane lookup for the cost
    record's ``confidence`` (provenance only — the trace already carries the dollars).
    Never calls a remote endpoint.

    Raises:
        ForgeOpError: if no trace exists for ``request_id``.
    """
    _log.debug("explain_provider_trace: request_id=%s", request_id)
    rec = _latest_trace(request_id)
    return ProviderTraceExplanation(
        request_id=rec.request_id,
        left_forge=rec.stream_started or rec.first_chunk_seen or rec.final_usage_seen,
        proxy_id=rec.proxy_id,
        provider=rec.provider,
        mapped_model=rec.mapped_model,
        selected_provider=rec.selected_provider,
        provider_generation_id=rec.provider_generation_id,
        provider_session_id=rec.provider_session_id,
        provider_command=rec.provider_command,
        request_mode=rec.request_mode,
        stream_started=rec.stream_started,
        first_chunk_seen=rec.first_chunk_seen,
        final_usage_seen=rec.final_usage_seen,
        client_disconnected=rec.client_disconnected,
        local_usage_status=rec.local_usage_status,
        reported_cost_micros=rec.reported_cost_micros,
        cost_confidence=_lookup_cost_confidence(rec),
        remote_lookup_performed=False,
    )


def render_explanation_lines(exp: ProviderTraceExplanation) -> list[str]:
    """Render an explanation as stable plain text (no Rich, no markup).

    A stable plain-text *contract* shared by ``forge provider trace explain`` and
    ``%provider trace explain`` so both surfaces render byte-identical output.
    Precedent: ``render_summary_line`` in ``usage_summary.py``.
    """
    provider_label = exp.provider or "the provider"
    upstream = f" (upstream: {exp.selected_provider})" if exp.selected_provider else ""

    lines: list[str] = []
    if exp.left_forge:
        lines.append(
            f"{exp.request_id} left Forge via proxy {exp.proxy_id} -> {provider_label} {exp.mapped_model}{upstream}."
        )
    else:
        lines.append(
            f"{exp.request_id} was handled by proxy {exp.proxy_id} -> {provider_label} {exp.mapped_model}{upstream}, "
            "but no stream or usage was observed leaving Forge."
        )

    lines.append(_lifecycle_line(exp))

    if exp.provider_generation_id or exp.provider_session_id:
        gen = exp.provider_generation_id or "(none)"
        sess = f" (session {exp.provider_session_id})" if exp.provider_session_id else ""
        lines.append(f"Provider generation id: {gen}{sess}.")

    lines.append(_cost_line(exp))
    lines.append("No remote lookup was performed.")
    return lines


# --- internal helpers --------------------------------------------------------


def _latest_trace(request_id: str) -> ProviderTraceRecord:
    """Read the newest trace record for ``request_id`` or raise ``ForgeOpError``."""
    try:
        records = read_provider_traces(request_id=request_id)
    except Exception as e:
        raise ForgeOpError(f"Could not read provider traces: {e}") from e
    if not records:
        raise ForgeOpError(f"No provider trace found for request '{request_id}'")
    return records[-1]


def _session_matches(psid: str | None, prefix: str) -> bool:
    """True if a stored ``provider_session_id`` matches a derived ``forge_sess_<hash>`` prefix.

    Records carry an optional ``_<role>`` suffix, so match the bare prefix OR ``prefix_<role>``.
    """
    if not psid:
        return False
    return psid == prefix or psid.startswith(prefix + "_")


def _lifecycle_line(exp: ProviderTraceExplanation) -> str:
    if exp.final_usage_seen:
        if exp.request_mode == "streaming":
            return "Stream started and emitted chunks; final usage was observed."
        return "Request completed; usage was observed."
    began = (
        "Stream started and emitted chunks"
        if exp.first_chunk_seen
        else ("Stream started" if exp.stream_started else "No stream was observed")
    )
    tail = "; final usage was not observed"
    if exp.client_disconnected:
        tail += "; client disconnected"
    return f"{began}{tail}."


def _cost_line(exp: ProviderTraceExplanation) -> str:
    if exp.reported_cost_micros is not None:
        dollars = exp.reported_cost_micros / 1_000_000
        conf = f" (confidence: {exp.cost_confidence})" if exp.cost_confidence else ""
        return f"Local cost: ${dollars:.6f}{conf}."
    if exp.local_usage_status == "available":
        return "Usage was observed but no cost was reported: unavailable, not zero."
    return "Local cost is unavailable, not zero."


def _lookup_cost_confidence(rec: ProviderTraceRecord) -> str | None:
    """Best-effort cost-plane provenance for one request, bounded to ±5m of the trace ts.

    The trace already carries ``reported_cost_micros``; this only attaches the cost
    record's ``confidence`` (reported / gateway_calculated / unavailable). Never raises —
    a missing/unparseable cost plane just yields ``None``.
    """
    ts = _parse_iso(rec.ts)
    if ts is None:
        return None
    try:
        records = read_cost_logs(ts - _COST_JOIN_WINDOW, ts + _COST_JOIN_WINDOW)
    except Exception as e:  # cost-plane enrichment is best-effort, never fatal to explain
        _log.debug("cost-plane lookup failed for %s: %s", rec.request_id, e)
        return None
    for cost in records:
        if cost.get("request_id") == rec.request_id:
            conf = cost.get("confidence")
            return conf if isinstance(conf, str) else None
    return None


def _parse_iso(ts_str: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts_str.rstrip("Z").removesuffix("+00:00") + "+00:00")
    except (ValueError, TypeError, AttributeError):
        return None

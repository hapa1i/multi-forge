"""PID-sharded JSONL provider-trace plane (openrouter_observability Phase 3).

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

Location: ``~/.forge/providers/openrouter/traces/YYYY-MM_<pid>.jsonl`` (owner-only, 0600).
Joined to the cost/usage planes by shared ``request_id`` and run-tree ids; NOT wiped by
``forge proxy costs reset`` (it is diagnostics, not spend truth).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import dacite

from forge.core.paths import get_forge_home
from forge.core.state import decode_json_object

logger = logging.getLogger(__name__)

PROVIDER_TRACE_SCHEMA_VERSION = 1

# Dedicated, non-reentrant lock — do NOT reuse audit_logger's; the append re-acquires it.
_lock = threading.Lock()

# One-time warning latch for records written by a newer Forge (own latch, not audit's).
_warned_newer_schema = False

RequestMode = Literal["streaming", "non_streaming"]
LocalUsageStatus = Literal["available", "unavailable"]


def _pid_suffix() -> str:
    return str(os.getpid())


def _traces_dir() -> Path:
    # Forward-ref: this hardcoded "openrouter" segment (and the record_provider_trace gate below) is the
    # model-source identity the `unified_backend` board proposal migrates to a backend id -- a deliberate
    # clean break, so it stays a literal, not a seam. (`rg unified_backend` finds the card; lane-stable slug.)
    return get_forge_home() / "providers" / "openrouter" / "traces"


def _current_log_path() -> Path:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return _traces_dir() / f"{month}_{_pid_suffix()}.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _append_provider_trace(record: dict[str, Any]) -> None:
    """Append a built record to the PID-sharded JSONL log. Best-effort: write failures
    are logged at warning and never block request handling."""
    record.setdefault("schema_version", PROVIDER_TRACE_SCHEMA_VERSION)
    record.setdefault("ts", _now_iso())
    try:
        from forge.core.state import open_secure_append

        log_path = _current_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Owner-only on ALL THREE levels (providers/, providers/openrouter/, .../traces/)
        # so neither the records nor the file-name timestamps leak to other local users.
        traces = _traces_dir()
        for secure_dir in (traces.parent.parent, traces.parent, traces):
            try:
                os.chmod(secure_dir, 0o700)
            except OSError:
                pass
        with _lock:
            with open_secure_append(log_path) as f:
                f.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
    except Exception as e:
        logger.warning("Failed to write provider trace: %s", e)


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
) -> None:
    """Build and persist a metadata-only provider-trace record (no gate).

    Re-applies the Phase 2 header allowlist to ``provider_meta["headers"]`` so a future
    caller that bypasses that boundary still cannot persist auth/cookie headers — the
    allowlist stays the single source of truth, applied again at the persistence edge.
    """
    from forge.core.llm.clients.openai_compat import provider_trace_headers

    pm = provider_meta or {}
    _append_provider_trace(
        {
            "schema_version": PROVIDER_TRACE_SCHEMA_VERSION,
            "ts": _now_iso(),
            "request_id": request_id,
            "proxy_id": proxy_id,
            "mapped_model": mapped_model,
            "forge_run_id": forge_run_id,
            "forge_root_run_id": forge_root_run_id,
            "provider_session_id": provider_session_id,
            "provider_command": provider_command,
            "provider": pm.get("provider"),
            "selected_provider": pm.get("selected_provider"),
            "provider_response_id": pm.get("provider_response_id"),
            "provider_generation_id": pm.get("provider_generation_id"),
            "provider_request_id": pm.get("provider_request_id"),
            "headers": provider_trace_headers(pm.get("headers")),  # re-filter at the edge
            "request_mode": request_mode,
            "stream_started": stream_started,
            "first_chunk_seen": first_chunk_seen,
            "final_usage_seen": final_usage_seen,
            "client_disconnected": client_disconnected,
            "local_usage_status": local_usage_status,
            "timeout_seen": False,
            "reported_cost_micros": reported_cost_micros,
            "latency_ms": latency_ms,
        }
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
) -> None:
    """Gate to the direct OpenRouter route, derive local_usage_status, and persist.

    The shared write entry point for both the converters seam (``server.py``) and the
    passthrough relay (``passthrough.py``) — it lives in this neutral leaf so neither
    caller has to import the other (avoids the ``server`` <-> ``passthrough`` cycle).

    Direct-OpenRouter-only by design: gateway-routed OpenRouter (LiteLLM -> OpenRouter)
    is out of scope for this card, so a ``litellm``/``unknown`` route writes nothing.

    Forward-ref: the ``unified_backend`` board proposal (find it with ``rg unified_backend``) migrates
    this provider-literal gate (and the ``_traces_dir`` path) to a backend-id check, broadening beyond
    OpenRouter via ``selected_provider``. A deliberate clean break -- kept a hardcoded literal, not a
    premature seam, until that proposal runs. (Slug, not a board path -- cards move lanes.)
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
    traces_dir = _traces_dir()
    if not traces_dir.is_dir():
        return []

    global _warned_newer_schema
    config = dacite.Config(strict=True)
    records: list[ProviderTraceRecord] = []
    for path in sorted(traces_dir.glob("*.jsonl")):
        try:
            with open(path) as f:
                for line in f:
                    record = decode_json_object(line)
                    if record is None:
                        continue

                    ver = record.get("schema_version")
                    if isinstance(ver, int) and ver > PROVIDER_TRACE_SCHEMA_VERSION:
                        if not _warned_newer_schema:
                            logger.warning(
                                "Skipping provider traces written by a newer Forge "
                                "(schema_version=%s); upgrade Forge",
                                ver,
                            )
                            _warned_newer_schema = True
                        continue

                    if request_id and record.get("request_id") != request_id:
                        continue
                    if forge_run_id and record.get("forge_run_id") != forge_run_id:
                        continue
                    if forge_root_run_id and record.get("forge_root_run_id") != forge_root_run_id:
                        continue
                    if provider_session_id and record.get("provider_session_id") != provider_session_id:
                        continue

                    if period_start or period_end:
                        ts_str = record.get("ts", "")
                        try:
                            ts = datetime.fromisoformat(ts_str.rstrip("Z").removesuffix("+00:00") + "+00:00")
                        except (ValueError, TypeError, AttributeError):
                            continue
                        if period_start and ts < period_start:
                            continue
                        if period_end and ts >= period_end:
                            continue

                    try:
                        records.append(dacite.from_dict(ProviderTraceRecord, record, config=config))
                    except (dacite.DaciteError, TypeError, KeyError, ValueError) as e:
                        logger.warning("Skipping malformed provider trace in %s: %s", path.name, e)
                        continue
        except OSError as e:
            logger.warning("Failed to read provider trace %s: %s", path, e)

    records.sort(key=lambda r: r.ts)
    return records


# --- Retention ---------------------------------------------------------------


def prune_provider_traces(*, retention_days: int, max_total_mb: int) -> None:
    """Delete trace shards older than retention_days, then prune oldest-first over
    max_total_mb. Best-effort: errors are ignored (telemetry, not critical path)."""
    traces_dir = _traces_dir()
    if not traces_dir.is_dir():
        return
    try:
        shards = sorted(traces_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return

    now = datetime.now(timezone.utc).timestamp()
    if retention_days > 0:
        cutoff = now - retention_days * 86400
        for shard in list(shards):
            try:
                if shard.stat().st_mtime < cutoff:
                    shard.unlink()
                    shards.remove(shard)
            except OSError:
                pass

    if max_total_mb > 0:
        limit = max_total_mb * 1024 * 1024
        try:
            total = sum(p.stat().st_size for p in shards)
        except OSError:
            return
        for shard in shards:  # oldest first
            if total <= limit:
                break
            try:
                size = shard.stat().st_size
                shard.unlink()
                total -= size
            except OSError:
                pass

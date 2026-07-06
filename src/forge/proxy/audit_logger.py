"""PID-sharded JSONL audit log writer (Phase 2 audit proxy).

Parallels ``cost_logger.py``. Records are persisted ALREADY REDACTED: the typed
builders (``write_metadata_record`` / ``write_full_body_record``) redact headers
and bodies before calling ``log_audit_record``, which performs no redaction and
only appends. This makes the redaction-before-persistence ordering structural —
no code path hands a raw body to the persistence function.

Location: ``~/.forge/telemetry/downstream/YYYY-MM_<pid>.jsonl`` (owner-only, 0600).
Drift baseline: ``~/.forge/proxies/<proxy_id>/audit_state.json`` in host mode, or
``~/.forge/telemetry/audit_state/<proxy_id>.json`` in proxy-id sidecars.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from forge.core.paths import get_forge_home
from forge.core.state import utc_timestamp_z
from forge.core.telemetry.downstream import (
    DownstreamKind,
    DownstreamRecord,
    mint_downstream_event_id,
    read_downstream_records,
    write_downstream_record,
)

logger = logging.getLogger(__name__)

AUDIT_SCHEMA_VERSION = 1

_lock = threading.Lock()

# In-memory per-process drift baseline: proxy_id -> {dimension: last_seen_hash}.
_drift_state: dict[str, dict[str, str]] = {}
# Proxy ids whose on-disk drift baseline was written by a NEWER Forge: never load
# (unknown shape) or downgrade-overwrite it.
_drift_state_frozen: set[str] = set()

# One-time warning latch for records written by a newer Forge.
_warned_newer_schema = False


# --- Hashing (pure; shared with the core pipeline) ---------------------------


def hash_system_prompt(system: Any) -> str | None:
    """Hash the normalized system prompt text. cache_control markers are ignored
    so toggling a cache breakpoint does not look like prompt drift.

    Accepts Any because the value may come straight from a raw passthrough body.
    """
    if system is None:
        return None
    if isinstance(system, str):
        text = system
    elif isinstance(system, list):
        # Only hash text blocks. A non-text system block (now or in a future API
        # revision) must not be folded into the prompt hash, or its appearance
        # would read as prompt drift. Dicts with no `type` are treated as text.
        parts = []
        for block in system:
            if isinstance(block, dict):
                if block.get("type") not in (None, "text"):
                    continue
                value = block.get("text")
            else:
                if getattr(block, "type", "text") != "text":
                    continue
                value = getattr(block, "text", None)
            if value:
                parts.append(value)
        text = "\n".join(parts)
    else:
        return None
    if not text:
        return None
    normalized = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n"))
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def hash_tool_surface(tools: Any) -> str | None:
    """Hash the tool contract (names + input schemas), ignoring human descriptions
    (prose churn is noise; a parameter change is real drift)."""
    if not tools or not isinstance(tools, list):
        return None
    contract = []
    for tool in tools:
        if isinstance(tool, dict):
            name = tool.get("name")
            schema = tool.get("input_schema")
        else:
            name = getattr(tool, "name", None)
            schema = getattr(tool, "input_schema", None)
        if schema is not None and not isinstance(schema, (dict, list, str, int, float, bool)):
            dump = getattr(schema, "model_dump", None)
            schema = dump() if callable(dump) else str(schema)
        contract.append({"name": name, "input_schema": schema})
    contract.sort(key=lambda c: str(c.get("name")))
    canonical = json.dumps(contract, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- Write path (best-effort; never raises into the request path) ------------


def log_audit_record(record: dict[str, Any]) -> None:
    """Append an ALREADY-REDACTED audit record to the PID-sharded JSONL log.

    Performs no redaction — callers redact before calling this. Best-effort:
    write failures are logged at warning and never block the request.
    """
    record.setdefault("schema_version", AUDIT_SCHEMA_VERSION)
    record.setdefault("ts", utc_timestamp_z())
    try:
        record_type = str(record.get("record_type") or "request")
        kind: DownstreamKind
        if record_type == "drift":
            kind = "drift"
        elif record_type == "mutation":
            kind = "mutation"
        else:
            kind = "audit"
        request_id = record.get("request_id")
        backend_id = record.get("backend_id")
        write_downstream_record(
            DownstreamRecord(
                kind=kind,
                downstream_event_id=mint_downstream_event_id(
                    event_key=f"{kind}:{request_id}:{record_type}:{record.get('dimension') or ''}",
                ),
                request_id=str(request_id) if request_id else None,
                proxy_id=str(record.get("proxy_id")) if record.get("proxy_id") else None,
                source_id=str(record.get("proxy_id")) if record.get("proxy_id") else None,
                source_kind="proxy" if record.get("proxy_id") else None,
                backend_id=str(backend_id) if backend_id else None,
                audit_record_type=record_type,
                payload=record,
            )
        )
    except Exception as e:
        logger.warning("Failed to write audit telemetry: %s", e)


def write_metadata_record(
    *,
    request_id: str,
    proxy_id: str,
    mode: str,
    route: dict[str, Any],
    system_prompt_hash: str | None,
    tool_surface_hash: str | None,
    thinking: dict[str, Any] | None = None,
    cache_markers: dict[str, int] | None = None,
    counts: dict[str, int] | None = None,
    backend_id: str | None = None,
) -> None:
    """Write a metadata-only audit record (no body text, no secrets)."""
    log_audit_record(
        {
            "record_type": "request",
            "request_id": request_id,
            "proxy_id": proxy_id,
            "mode": mode,
            "route": route,
            "full_body": False,
            "system_prompt_hash": system_prompt_hash,
            "tool_surface_hash": tool_surface_hash,
            "thinking": thinking,
            "cache_markers": cache_markers or {},
            "counts": counts or {},
            "backend_id": backend_id,
        }
    )


def write_full_body_record(
    *,
    request_id: str,
    proxy_id: str,
    mode: str,
    route: dict[str, Any],
    request_headers: dict[str, str] | None,
    request_body: dict[str, Any] | None,
    response_headers: dict[str, str] | None = None,
    response_body: dict[str, Any] | None = None,
    redact_header_names: set[str] | None = None,
    backend_id: str | None = None,
    **metadata: Any,
) -> None:
    """Write a full-body audit record with headers/bodies REDACTED before persistence.

    "Full body" means *redacted* structure (roles, block types, per-block lengths,
    header names) — never plaintext. Redaction runs here, before log_audit_record.
    """
    from forge.proxy.utils import _redact_body_for_log, redact_headers

    log_audit_record(
        {
            "record_type": "request",
            "request_id": request_id,
            "proxy_id": proxy_id,
            "mode": mode,
            "route": route,
            "full_body": True,
            "request_headers": redact_headers(request_headers, redact_header_names),
            "request_body": _redact_body_for_log(request_body),
            "response_headers": redact_headers(response_headers, redact_header_names),
            "response_body": _redact_body_for_log(response_body),
            "backend_id": backend_id,
            **metadata,
        }
    )


def write_drift_record(
    *,
    request_id: str,
    proxy_id: str,
    dimension: str,
    previous_hash: str,
    current_hash: str,
    route: dict[str, Any],
    backend_id: str | None = None,
) -> None:
    """Write a drift record (hashes only — safe even in metadata-only mode)."""
    log_audit_record(
        {
            "record_type": "drift",
            "request_id": request_id,
            "proxy_id": proxy_id,
            "dimension": dimension,
            "previous_hash": previous_hash,
            "current_hash": current_hash,
            "route": route,
            "backend_id": backend_id,
        }
    )


def write_mutation_record(
    *,
    request_id: str,
    proxy_id: str,
    route: dict[str, Any],
    mutation: dict[str, Any],
    backend_id: str | None = None,
) -> None:
    """Write an override before/after mutation record.

    ``mutation`` is the already-redacted payload from ``intercept.apply_override``
    (hashes, lengths, numeric budgets only — never plaintext augment text or matched
    guard content), so this writer adds no redaction of its own.
    """
    log_audit_record(
        {
            "record_type": "mutation",
            "request_id": request_id,
            "proxy_id": proxy_id,
            "mode": "override",
            "route": route,
            "backend_id": backend_id,
            **mutation,
        }
    )


# --- Drift detection (hybrid: in-memory baseline + per-proxy state file) ------


def _audit_state_path(proxy_id: str) -> Path:
    """Path to the per-proxy drift baseline.

    Host mode keeps it beside proxy.yaml. In a proxy-id sidecar that per-proxy config
    dir is mounted read-only, so redirect the baseline to the writable telemetry mount
    (``~/.forge/telemetry/audit_state/<id>.json``) — otherwise every restart loses the baseline
    and re-flags the first prompt as drift. Gated on FORGE_PROXY_ID too: template-only
    sidecars set FORGE_SIDECAR but mount no audit/ dir, so the redirect target would
    not exist for them.
    """
    if os.environ.get("FORGE_SIDECAR") and os.environ.get("FORGE_PROXY_ID"):
        return get_forge_home() / "telemetry" / "audit_state" / f"{proxy_id}.json"
    return get_forge_home() / "proxies" / proxy_id / "audit_state.json"


def _load_drift_baseline(proxy_id: str) -> dict[str, str]:
    """Return the in-memory baseline, seeding from the per-proxy state file once."""
    if proxy_id in _drift_state:
        return _drift_state[proxy_id]
    baseline: dict[str, str] = {}
    try:
        from forge.core.state import read_json

        data = read_json(_audit_state_path(proxy_id))
        if isinstance(data, dict):
            ver = data.get("schema_version")
            if isinstance(ver, int) and ver > AUDIT_SCHEMA_VERSION:
                # Written by a newer Forge: do not load (unknown shape) and freeze so a later
                # drift write cannot downgrade-overwrite it. Mirror read_audit_logs' one-time notice.
                global _warned_newer_schema
                if not _warned_newer_schema:
                    logger.warning(
                        "Skipping audit drift baseline written by a newer Forge " "(schema_version=%s); upgrade Forge",
                        ver,
                    )
                    _warned_newer_schema = True
                _drift_state_frozen.add(proxy_id)
            elif ver == AUDIT_SCHEMA_VERSION:
                seen = data.get("last_seen")
                if isinstance(seen, dict):
                    baseline = {str(k): str(v) for k, v in seen.items() if v}
    except Exception:
        # Missing/corrupt baseline is non-fatal — the first request reseeds it.
        baseline = {}
    _drift_state[proxy_id] = baseline
    return baseline


def _persist_drift_baseline(proxy_id: str, baseline: dict[str, str]) -> None:
    if proxy_id in _drift_state_frozen:
        # A newer-schema baseline exists on disk; never downgrade-overwrite it.
        return
    try:
        from forge.core.state import atomic_write_json

        atomic_write_json(
            _audit_state_path(proxy_id),
            {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "last_seen": baseline,
                "updated_at": utc_timestamp_z(),
            },
        )
        try:
            os.chmod(_audit_state_path(proxy_id), 0o600)
        except OSError:
            pass
    except Exception as e:
        logger.debug("Failed to persist audit drift baseline: %s", e)


def check_and_record_drift(
    *,
    proxy_id: str,
    dimension: str,
    current_hash: str | None,
    request_id: str,
    route: dict[str, Any],
    backend_id: str | None = None,
) -> bool:
    """Detect and record drift for one hash dimension. Returns True if drift fired.

    The first observation of a dimension establishes the baseline (not drift), so a
    fresh proxy does not flag every prompt as drifted.
    """
    if current_hash is None:
        return False

    # Mutate baseline under the lock; write the drift record OUTSIDE the lock
    # (log_audit_record re-acquires _lock — threading.Lock is not reentrant).
    with _lock:
        baseline = _load_drift_baseline(proxy_id)
        previous = baseline.get(dimension)
        if previous == current_hash:
            return False
        baseline[dimension] = current_hash
        _persist_drift_baseline(proxy_id, baseline)

    if previous is None:
        return False

    logger.warning("[%s] %s drift: %s -> %s", request_id, dimension, previous, current_hash)
    write_drift_record(
        request_id=request_id,
        proxy_id=proxy_id,
        dimension=dimension,
        previous_hash=previous,
        current_hash=current_hash,
        route=route,
        backend_id=backend_id,
    )
    return True


# --- Read path (for the CLI) -------------------------------------------------


def read_audit_logs(
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    *,
    proxy_id: str | None = None,
    record_type: str | None = None,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    """Read and merge audit records across PID shards, sorted by timestamp.

    Skips malformed lines and records written by a newer Forge (schema_version >
    AUDIT_SCHEMA_VERSION), surfacing the latter once at warning level.
    """
    records: list[dict[str, Any]] = []
    for rec in read_downstream_records(period_start, period_end, request_id=request_id, proxy_id=proxy_id):
        if rec.kind not in {"audit", "drift", "mutation"}:
            continue
        payload = dict(rec.payload or {})
        if not payload:
            continue
        if record_type and payload.get("record_type") != record_type:
            continue
        payload.setdefault("schema_version", AUDIT_SCHEMA_VERSION)
        payload.setdefault("ts", rec.ts)
        records.append(payload)
    return records


# --- Retention ---------------------------------------------------------------


def prune_audit_logs(*, retention_days: int, max_total_mb: int) -> None:
    """Delete audit shards older than retention_days, then prune oldest-first over
    max_total_mb. Best-effort: errors are ignored (telemetry, not critical path)."""
    from forge.core.telemetry.downstream import prune_downstream_records

    prune_downstream_records(retention_days=retention_days, max_total_mb=max_total_mb)

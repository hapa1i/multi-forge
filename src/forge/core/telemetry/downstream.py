"""Downstream model-call evidence ledger.

The downstream plane is session-blind and records evidence about physical model
attempts plus adjacent redacted audit/drift/mutation facts. Records are PID-sharded
under ``~/.forge/telemetry/downstream``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import dacite

from forge.core.paths import get_forge_home
from forge.core.state import decode_json_object

logger = logging.getLogger(__name__)

DOWNSTREAM_SCHEMA_VERSION = 1

DownstreamKind = Literal["attempt", "audit", "drift", "mutation"]
LocalUsageStatus = Literal["available", "unavailable"]
RequestMode = Literal["streaming", "non_streaming"]
Reporter = Literal["claude_code", "forge_proxy", "openrouter", "litellm", "provider", "codex_jsonl"]
Confidence = Literal["reported", "gateway_calculated", "inferred", "unavailable", "unknown"]

_lock = threading.Lock()
_warned_newer_schema = False
_DOWNSTREAM_EVENT_NAMESPACE = uuid.UUID("4fbcae84-0d9e-5b1b-b46d-f647dc8183f5")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _downstream_dir() -> Path:
    return get_forge_home() / "telemetry" / "downstream"


def _current_log_path() -> Path:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return _downstream_dir() / f"{month}_{os.getpid()}.jsonl"


def mint_downstream_event_id(*, event_key: str | None = None) -> str:
    """Return an id stable for one physical attempt.

    ``request_id`` is only a correlation value, not an idempotency key. Callers that
    can name one physical attempt should pass internal event-key material; otherwise
    this helper mints a fresh id so distinct attempts never collapse by accident.
    """
    if event_key:
        digest = uuid.uuid5(_DOWNSTREAM_EVENT_NAMESPACE, event_key).hex[:24]
        return f"ds_{digest}"
    return f"ds_{uuid.uuid4().hex[:24]}"


@dataclass
class DownstreamRecord:
    """One downstream evidence record.

    ``kind='attempt'`` records may be written more than once for the same
    ``downstream_event_id`` (for example cost first, provider lifecycle later). Readers
    merge duplicate ids by taking later non-null fields, so true double-writes count
    once while distinct retries use distinct ids.
    """

    kind: DownstreamKind
    downstream_event_id: str

    # Correlation / source.
    request_id: str | None = None
    proxy_id: str | None = None
    source_id: str | None = None
    source_kind: str | None = None
    backend_id: str | None = None
    forge_run_id: str | None = None
    forge_root_run_id: str | None = None
    provider_session_id: str | None = None
    provider_command: str | None = None

    # Model attempt metrics.
    provider: str | None = None
    selected_provider: str | None = None
    model: str | None = None
    mapped_model: str | None = None
    tier: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    cost_micros: int | None = None
    reporter: Reporter | None = None
    confidence: Confidence = "unknown"
    latency_ms: float | None = None
    failed: bool | None = None

    # Provider lifecycle / trace.
    provider_response_id: str | None = None
    provider_generation_id: str | None = None
    provider_request_id: str | None = None
    provider_headers: dict[str, str] | None = None
    request_mode: RequestMode | None = None
    stream_started: bool | None = None
    first_chunk_seen: bool | None = None
    final_usage_seen: bool | None = None
    client_disconnected: bool | None = None
    local_usage_status: LocalUsageStatus | None = None
    timeout_seen: bool | None = None
    reported_cost_micros: int | None = None

    # Audit/drift/mutation sub-stream payload. Already redacted by callers.
    audit_record_type: str | None = None
    payload: dict[str, Any] | None = None

    schema_version: int = DOWNSTREAM_SCHEMA_VERSION
    ts: str = field(default_factory=_now_iso)


def write_downstream_record(record: DownstreamRecord) -> None:
    """Append one downstream record. Best-effort; never raises into callers."""
    try:
        from forge.core.state import open_secure_append

        data = {k: v for k, v in asdict(record).items() if v is not None}
        log_path = _current_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        for secure_dir in (log_path.parent.parent, log_path.parent):
            try:
                os.chmod(secure_dir, 0o700)
            except OSError:
                pass
        with _lock:
            with open_secure_append(log_path) as f:
                f.write(json.dumps(data, separators=(",", ":"), default=str) + "\n")
    except Exception as e:
        logger.warning("Failed to write downstream telemetry: %s", e)


def _merge_attempt_records(records: list[DownstreamRecord]) -> list[DownstreamRecord]:
    merged: dict[str, DownstreamRecord] = {}
    ordered_keys: list[str] = []
    for rec in records:
        if rec.kind != "attempt":
            continue
        current = merged.get(rec.downstream_event_id)
        if current is None:
            merged[rec.downstream_event_id] = rec
            ordered_keys.append(rec.downstream_event_id)
            continue
        for key, value in asdict(rec).items():
            if key in {"schema_version", "downstream_event_id", "kind"}:
                continue
            if key == "confidence" and value == "unknown" and current.confidence != "unknown":
                continue
            if value is not None:
                setattr(current, key, value)
    passthrough = [rec for rec in records if rec.kind != "attempt"]
    attempts = [merged[key] for key in ordered_keys]
    return sorted([*attempts, *passthrough], key=lambda r: r.ts)


def read_downstream_records(
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    *,
    kind: DownstreamKind | None = None,
    request_id: str | None = None,
    proxy_id: str | None = None,
    backend_id: str | None = None,
    forge_run_id: str | None = None,
    forge_root_run_id: str | None = None,
    provider_session_id: str | None = None,
) -> list[DownstreamRecord]:
    """Read downstream records, sorted by timestamp.

    Attempt records with the same ``downstream_event_id`` are merged so duplicate
    writes for one physical attempt count once.
    """
    log_dir = _downstream_dir()
    if not log_dir.is_dir():
        return []

    global _warned_newer_schema
    config = dacite.Config(strict=True)
    records: list[DownstreamRecord] = []
    for path in sorted(log_dir.glob("*.jsonl")):
        try:
            with open(path) as f:
                for line in f:
                    record = decode_json_object(line)
                    if record is None:
                        continue
                    ver = record.get("schema_version")
                    if isinstance(ver, int) and ver > DOWNSTREAM_SCHEMA_VERSION:
                        if not _warned_newer_schema:
                            logger.warning(
                                "Skipping downstream telemetry from newer Forge (schema_version=%s); upgrade Forge",
                                ver,
                            )
                            _warned_newer_schema = True
                        continue
                    if kind and record.get("kind") != kind:
                        continue
                    if request_id and record.get("request_id") != request_id:
                        continue
                    if proxy_id and record.get("proxy_id") != proxy_id:
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
                        records.append(dacite.from_dict(DownstreamRecord, record, config=config))
                    except (dacite.DaciteError, TypeError, KeyError, ValueError) as e:
                        logger.warning(
                            "Skipping malformed downstream telemetry in %s: %s",
                            path.name,
                            e,
                        )
        except OSError as e:
            logger.warning("Failed to read downstream telemetry %s: %s", path, e)

    records.sort(key=lambda r: r.ts)
    merged = _merge_attempt_records(records)
    if backend_id:
        return [record for record in merged if record.backend_id == backend_id]
    return merged


def prune_downstream_records(*, retention_days: int, max_total_mb: int) -> None:
    """Apply shard retention to the shared downstream telemetry directory."""
    from forge.proxy.retention import prune_jsonl_shards

    current_month = datetime.now(timezone.utc).strftime("%Y-%m")

    def preserve_current_month(shard: Path) -> bool:
        shard_month = shard.stem.split("_", 1)[0]
        return shard_month == current_month

    prune_jsonl_shards(
        _downstream_dir(),
        retention_days=retention_days,
        max_total_mb=max_total_mb,
        preserve=preserve_current_month,
    )

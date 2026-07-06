"""Upstream operation-outcome ledger."""

from __future__ import annotations

import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import dacite

from forge.core.paths import get_forge_home
from forge.core.state import decode_json_object, utc_timestamp_z
from forge.core.telemetry.jsonl_io import append_jsonl_record

logger = logging.getLogger(__name__)

UPSTREAM_SCHEMA_VERSION = 1

UpstreamStatus = Literal["success", "warning", "fail_open", "deny", "needs_review", "error", "timeout", "skipped"]

_lock = threading.Lock()
_warned_newer_schema = False


def _upstream_dir() -> Path:
    return get_forge_home() / "telemetry" / "upstream"


def _current_log_path() -> Path:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return _upstream_dir() / f"{month}_{os.getpid()}.jsonl"


def _event_id() -> str:
    return f"up_{uuid.uuid4().hex[:16]}"


@dataclass
class UpstreamOutcome:
    """One Forge operation outcome."""

    command: str
    status: UpstreamStatus
    event_id: str = field(default_factory=_event_id)
    session: str | None = None
    run_id: str | None = None
    parent_run_id: str | None = None
    root_run_id: str | None = None
    origin: str | None = None
    operation: str | None = None
    policy_id: str | None = None
    tool_name: str | None = None
    target_path: str | None = None
    reason_code: str | None = None
    message: str | None = None
    cached: bool = False
    latency_ms: float | None = None
    schema_version: int = UPSTREAM_SCHEMA_VERSION
    ts: str = field(default_factory=utc_timestamp_z)


def should_record_upstream_outcome(status: str, *, cached: bool = False) -> bool:
    """Return whether the configured upstream volume should persist an outcome."""
    try:
        from forge.runtime_config import get_runtime_config

        record_all = get_runtime_config().upstream_event_volume == "all"
    except Exception:
        record_all = False
    if cached and status in {"success", "warning"}:
        return record_all
    if status != "success":
        return True
    return record_all


def write_upstream_outcome(outcome: UpstreamOutcome) -> None:
    """Append an upstream outcome when the volume policy allows it."""
    if not should_record_upstream_outcome(outcome.status, cached=outcome.cached):
        return
    data = {k: v for k, v in asdict(outcome).items() if v is not None}
    log_path = _current_log_path()
    append_jsonl_record(
        log_path,
        data,
        secure_dirs=(log_path.parent.parent, log_path.parent),
        lock=_lock,
        logger=logger,
        warning_message="Failed to write upstream telemetry: %s",
    )


def record_upstream_operation(
    *,
    command: str,
    status: UpstreamStatus,
    session: str | None = None,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    root_run_id: str | None = None,
    origin: str | None = None,
    operation: str | None = None,
    policy_id: str | None = None,
    tool_name: str | None = None,
    target_path: str | None = None,
    reason_code: str | None = None,
    message: str | None = None,
    cached: bool = False,
    latency_ms: float | None = None,
) -> None:
    """Best-effort helper for operation-boundary upstream outcomes.

    Explicit run ids win; missing ids are filled from the ambient Forge run
    identity when one exists.
    """
    try:
        if run_id is None or parent_run_id is None or root_run_id is None:
            try:
                from forge.core.reactive.env import get_run_identity

                identity = get_run_identity()
            except Exception:
                identity = None
            if identity is not None:
                run_id = run_id or identity.run_id
                parent_run_id = parent_run_id or identity.parent_run_id
                root_run_id = root_run_id or identity.root_run_id
        write_upstream_outcome(
            UpstreamOutcome(
                command=command,
                operation=operation,
                status=status,
                session=session,
                run_id=run_id,
                parent_run_id=parent_run_id,
                root_run_id=root_run_id,
                origin=origin,
                policy_id=policy_id,
                tool_name=tool_name,
                target_path=target_path,
                reason_code=reason_code,
                message=message,
                cached=cached,
                latency_ms=latency_ms,
            )
        )
    except Exception as e:
        logger.debug("upstream operation telemetry skipped for %s: %s", command, e)


def read_upstream_outcomes(
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    *,
    session: str | None = None,
    command: str | None = None,
    policy_id: str | None = None,
) -> list[UpstreamOutcome]:
    """Read upstream outcomes, sorted by timestamp."""
    log_dir = _upstream_dir()
    if not log_dir.is_dir():
        return []

    global _warned_newer_schema
    config = dacite.Config(strict=True)
    outcomes: list[UpstreamOutcome] = []
    for path in sorted(log_dir.glob("*.jsonl")):
        try:
            with open(path) as f:
                for line in f:
                    record = decode_json_object(line)
                    if record is None:
                        continue
                    ver = record.get("schema_version")
                    if isinstance(ver, int) and ver > UPSTREAM_SCHEMA_VERSION:
                        if not _warned_newer_schema:
                            logger.warning(
                                "Skipping upstream telemetry from newer Forge (schema_version=%s); upgrade Forge",
                                ver,
                            )
                            _warned_newer_schema = True
                        continue
                    if session and record.get("session") != session:
                        continue
                    if command and record.get("command") != command:
                        continue
                    if policy_id and record.get("policy_id") != policy_id:
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
                        outcomes.append(dacite.from_dict(UpstreamOutcome, record, config=config))
                    except (dacite.DaciteError, TypeError, KeyError, ValueError) as e:
                        logger.warning("Skipping malformed upstream telemetry in %s: %s", path.name, e)
        except OSError as e:
            logger.warning("Failed to read upstream telemetry %s: %s", path, e)

    outcomes.sort(key=lambda r: r.ts)
    return outcomes

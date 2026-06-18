"""Upstream operation-outcome ledger."""

from __future__ import annotations

import json
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
from forge.core.state import decode_json_object

logger = logging.getLogger(__name__)

UPSTREAM_SCHEMA_VERSION = 1

UpstreamStatus = Literal["success", "warning", "fail_open", "deny", "needs_review", "error", "timeout", "skipped"]

_lock = threading.Lock()
_warned_newer_schema = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    ts: str = field(default_factory=_now_iso)


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
    try:
        from forge.core.state import open_secure_append

        data = {k: v for k, v in asdict(outcome).items() if v is not None}
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
        logger.warning("Failed to write upstream telemetry: %s", e)


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

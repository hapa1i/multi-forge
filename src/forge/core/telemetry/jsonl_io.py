"""Shared JSONL mechanics for telemetry-style append-only state."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from forge.core.state import decode_json_object, try_parse_iso


@dataclass(frozen=True)
class JsonlReadRecord:
    """Carry one decoded object with its shard and lazy period bounds."""

    path: Path
    record: dict[str, Any]
    period_start: datetime | None = None
    period_end: datetime | None = None

    def matches_period(self) -> bool:
        """Return whether this record's timestamp falls within the half-open bounds."""
        if not self.period_start and not self.period_end:
            return True
        ts = try_parse_iso(self.record.get("ts", ""), assume_naive_utc=True)
        if ts is None:
            return False
        if self.period_start and ts < self.period_start:
            return False
        if self.period_end and ts >= self.period_end:
            return False
        return True


def iter_jsonl_records(
    log_dir: Path,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    *,
    logger: logging.Logger,
    read_error_message: str,
) -> Iterator[JsonlReadRecord]:
    """Yield decoded object records from sorted shards, skipping unreadable lines.

    Timestamp matching stays lazy on each yielded record so typed readers retain
    their plane-specific schema and filter ordering.
    """
    if not log_dir.is_dir():
        return
    for path in sorted(log_dir.glob("*.jsonl")):
        try:
            with path.open() as stream:
                for line in stream:
                    record = decode_json_object(line)
                    if record is not None:
                        yield JsonlReadRecord(path, record, period_start, period_end)
        except OSError as e:
            logger.warning(read_error_message, path, e)


def append_jsonl_record(
    log_path: Path,
    record: Mapping[str, Any],
    *,
    secure_dirs: Iterable[Path],
    lock: Any,
    logger: logging.Logger,
    warning_message: str,
) -> None:
    """Append one compact JSONL record best-effort, logging and swallowing failures."""
    try:
        from forge.core.state import open_secure_append

        log_path.parent.mkdir(parents=True, exist_ok=True)
        for secure_dir in secure_dirs:
            try:
                os.chmod(secure_dir, 0o700)
            except OSError:
                pass
        line = json.dumps(record, separators=(",", ":"), default=str) + "\n"
        with lock:
            with open_secure_append(log_path) as f:
                f.write(line)
    except Exception as e:
        logger.warning(warning_message, e)

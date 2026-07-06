"""Shared JSONL append mechanics for telemetry-style append-only state."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


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

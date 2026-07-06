"""Shared JSONL shard retention for append-only state planes.

The audit, provider-trace, and request-log planes all bound on-disk size the same way:
delete shards older than ``retention_days``, then prune oldest-first until total size is under
``max_total_mb``. This was duplicated byte-for-byte; centralizing it keeps the policy from
drifting between planes. Best-effort: telemetry retention must never raise into a request.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_BYTES_PER_MB = 1024 * 1024
_SECONDS_PER_DAY = 86400


def prune_jsonl_shards(
    directory: Path,
    *,
    retention_days: int,
    max_total_mb: int,
    pattern: str = "*.jsonl",
    preserve: Callable[[Path], bool] | None = None,
) -> None:
    """Delete shards older than ``retention_days``, then prune oldest-first over ``max_total_mb``.

    ``0`` disables that bound (matches the global ``log_retention_days`` convention). Errors are
    swallowed -- this is telemetry, not the critical path.
    """
    if not directory.is_dir():
        return
    try:
        shards = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime)
    except OSError:
        return

    def should_preserve(shard: Path) -> bool:
        if preserve is None:
            return False
        try:
            return preserve(shard)
        except Exception:
            return False

    now = datetime.now(timezone.utc).timestamp()
    if retention_days > 0:
        cutoff = now - retention_days * _SECONDS_PER_DAY
        for shard in list(shards):
            try:
                if should_preserve(shard):
                    continue
                if shard.stat().st_mtime < cutoff:
                    shard.unlink()
                    shards.remove(shard)
            except OSError:
                pass

    if max_total_mb > 0:
        limit = max_total_mb * _BYTES_PER_MB
        try:
            total = sum(p.stat().st_size for p in shards)
        except OSError:
            return
        for shard in shards:  # oldest first
            if total <= limit:
                break
            if should_preserve(shard):
                continue
            try:
                size = shard.stat().st_size
                shard.unlink()
                total -= size
            except OSError:
                pass

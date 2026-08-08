"""Shared JSONL shard retention for append-only state planes.

Downstream telemetry and per-proxy request diagnostics use the same age/size primitive.
Failures are returned to the owning surface rather than raised into request handling.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from stat import S_ISDIR

_BYTES_PER_MB = 1024 * 1024
_SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class PruneJsonlShardsResult:
    """Observable outcome from a best-effort shard prune."""

    removed: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def prune_jsonl_shards(
    directory: Path,
    *,
    retention_days: int,
    max_total_mb: int,
    pattern: str = "*.jsonl",
    preserve: Callable[[Path], bool] | None = None,
) -> PruneJsonlShardsResult:
    """Delete shards older than ``retention_days``, then prune oldest-first over ``max_total_mb``.

    ``0`` disables that bound (matches the global ``log_retention_days`` convention). Errors do
    not raise into the caller, but are returned so an owning surface can report degraded
    enforcement instead of silently claiming success.
    """
    removed: list[str] = []
    errors: list[str] = []
    try:
        directory_mode = directory.stat().st_mode
    except FileNotFoundError:
        return PruneJsonlShardsResult()
    except OSError as exc:
        return PruneJsonlShardsResult(errors=(f"could not inspect {directory}: {exc}",))
    if not S_ISDIR(directory_mode):
        return PruneJsonlShardsResult(errors=(f"retention path is not a directory: {directory}",))
    try:
        shards = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime)
    except OSError as exc:
        return PruneJsonlShardsResult(errors=(f"could not enumerate {directory}: {exc}",))

    preserve_decisions: dict[Path, bool] = {}

    def should_preserve(shard: Path) -> bool:
        if shard in preserve_decisions:
            return preserve_decisions[shard]
        if preserve is None:
            return False
        try:
            decision = preserve(shard)
        except Exception as exc:
            errors.append(f"could not evaluate preservation for {shard}: {exc}")
            decision = True
        # A preservation fact is evaluated once per operation. In particular, a
        # transient callback failure must keep the shard through both the age and
        # size passes rather than being retried into a destructive answer.
        preserve_decisions[shard] = decision
        return decision

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
                    removed.append(str(shard))
            except OSError as exc:
                errors.append(f"could not age-prune {shard}: {exc}")

    if max_total_mb > 0:
        limit = max_total_mb * _BYTES_PER_MB
        try:
            total = sum(p.stat().st_size for p in shards)
        except OSError as exc:
            errors.append(f"could not measure {directory}: {exc}")
            return PruneJsonlShardsResult(tuple(removed), tuple(errors))
        for shard in shards:  # oldest first
            if total <= limit:
                break
            if should_preserve(shard):
                continue
            try:
                size = shard.stat().st_size
                shard.unlink()
                total -= size
                removed.append(str(shard))
            except OSError as exc:
                errors.append(f"could not size-prune {shard}: {exc}")

    return PruneJsonlShardsResult(tuple(removed), tuple(errors))

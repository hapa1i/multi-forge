"""Shared JSONL shard pruning plus request-log per-file rotation.

``prune_jsonl_shards`` is the primitive shared by downstream telemetry and request-log
retention (delete-by-age, then oldest-first over a size budget; 0 disables a bound).
``_active_request_log_shard`` rolls to a numbered shard once the active one hits max_file_mb.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from forge.core.state import prune_jsonl_shards
from forge.proxy.utils import _active_request_log_shard, prune_request_logs


def _shard(directory: Path, name: str, *, size: int = 10, age_days: float = 0.0) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / name
    p.write_bytes(b"x" * size)
    if age_days:
        old = time.time() - age_days * 86400
        os.utime(p, (old, old))
    return p


# --- shared pruner ----------------------------------------------------------------------


def test_prune_removes_shards_older_than_retention(tmp_path: Path) -> None:
    old = _shard(tmp_path, "a.jsonl", age_days=30)
    also_old = _shard(tmp_path, "aa.jsonl", age_days=20)
    fresh = _shard(tmp_path, "b.jsonl", age_days=0)

    result = prune_jsonl_shards(tmp_path, retention_days=14, max_total_mb=0)

    assert not old.exists()
    assert not also_old.exists()
    assert fresh.exists()
    assert result.removed == (str(old), str(also_old))
    assert result.errors == ()


def test_prune_size_cap_removes_oldest_first(tmp_path: Path) -> None:
    mb = 1024 * 1024
    old = _shard(tmp_path, "old.jsonl", size=mb, age_days=2)
    mid = _shard(tmp_path, "mid.jsonl", size=mb, age_days=1)
    new = _shard(tmp_path, "new.jsonl", size=mb, age_days=0)

    prune_jsonl_shards(tmp_path, retention_days=0, max_total_mb=2)  # budget 2 MB, have 3

    assert not old.exists()  # oldest evicted first
    assert mid.exists() and new.exists()


def test_prune_zero_budgets_disable_both_bounds(tmp_path: Path) -> None:
    a = _shard(tmp_path, "a.jsonl", size=5 * 1024 * 1024, age_days=999)
    prune_jsonl_shards(tmp_path, retention_days=0, max_total_mb=0)
    assert a.exists()


def test_prune_pattern_scopes_the_glob(tmp_path: Path) -> None:
    match = _shard(tmp_path, "20260101_requests.123.jsonl", age_days=30)
    other = _shard(tmp_path, "unrelated.log", age_days=30)
    prune_jsonl_shards(tmp_path, retention_days=1, max_total_mb=0, pattern="*_requests.*.jsonl")
    assert not match.exists()
    assert other.exists()  # outside the pattern -> untouched


def test_prune_missing_dir_is_noop(tmp_path: Path) -> None:
    result = prune_jsonl_shards(tmp_path / "nope", retention_days=1, max_total_mb=1)
    assert result.removed == ()
    assert result.errors == ()


def test_prune_reports_when_retention_path_is_not_a_directory(tmp_path: Path) -> None:
    path = tmp_path / "downstream"
    path.write_text("not a directory")

    result = prune_jsonl_shards(path, retention_days=1, max_total_mb=1)

    assert result.removed == ()
    assert result.errors == (f"retention path is not a directory: {path}",)


def test_prune_reports_preservation_errors_and_keeps_the_shard(tmp_path: Path) -> None:
    old = _shard(tmp_path, "old.jsonl", size=2 * 1024 * 1024, age_days=30)
    calls = 0

    def fail_preservation(_path: Path) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected preservation fault")
        return False

    result = prune_jsonl_shards(
        tmp_path,
        retention_days=14,
        max_total_mb=1,
        preserve=fail_preservation,
    )

    assert old.exists()
    assert calls == 1
    assert result.removed == ()
    assert len(result.errors) == 1
    assert "injected preservation fault" in result.errors[0]


def test_prune_request_logs_targets_requests_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))
    req_dir = tmp_path / "forge_home" / "logs" / "requests"
    old = _shard(req_dir, "20260101_requests.99.jsonl", age_days=30)
    fresh = _shard(req_dir, "20260601_requests.99.jsonl", age_days=0)

    prune_request_logs(retention_days=14, max_total_mb=0)

    assert not old.exists()
    assert fresh.exists()


# --- per-file rotation ------------------------------------------------------------------


def test_rotation_unbounded_uses_base_name(tmp_path: Path) -> None:
    shard = _active_request_log_shard(tmp_path, "20260616", "123", 0)
    assert shard.name == "20260616_requests.123.jsonl"


def test_rotation_stays_on_seq0_until_cap(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "20260616_requests.123.jsonl").write_bytes(b"x" * 1024)  # well under cap
    shard = _active_request_log_shard(tmp_path, "20260616", "123", max_file_mb=1)
    assert shard.name == "20260616_requests.123.jsonl"


def test_rotation_rolls_to_next_shard_over_cap(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "20260616_requests.123.jsonl").write_bytes(b"x" * (1024 * 1024 + 1))  # over 1 MB
    shard = _active_request_log_shard(tmp_path, "20260616", "123", max_file_mb=1)
    assert shard.name == "20260616_requests.123.1.jsonl"

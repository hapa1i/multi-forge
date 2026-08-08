"""Regression for duplicate retention owners over shared downstream shards (D015).

Audit and provider-trace records coexist in ``~/.forge/telemetry/downstream``. The merged-main
startup path applied each proxy-local policy independently, so the stricter second pass could
delete a shard the first policy retained. Conflicting legacy policies must disable automatic
pruning until the user chooses the single global downstream policy.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

import forge.proxy.server as server

pytestmark = pytest.mark.regression


def test_conflicting_legacy_policies_skip_shared_downstream_pruning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from forge.core.telemetry import downstream

    monkeypatch.setenv("FORGE_HOME", str(tmp_path))

    proxy_path = tmp_path / "proxies" / "alpha" / "proxy.yaml"
    proxy_path.parent.mkdir(parents=True)
    proxy_path.write_text(
        yaml.safe_dump(
            {
                "proxy_format": 1,
                "template": "openrouter-anthropic",
                "template_digest": "sha256:test",
                "provider": "openrouter",
                "proxy_endpoint": "http://localhost:8085",
                "port": 8085,
                "upstream_base_url": "https://openrouter.ai/api/v1",
                "tiers": {"sonnet": "anthropic/claude-sonnet-4-6"},
                "audit": {"retention_days": 90, "max_total_mb": 512},
                "provider_trace": {"retention_days": 14, "max_total_mb": 512},
            }
        )
    )

    downstream_dir = tmp_path / "telemetry" / "downstream"
    downstream_dir.mkdir(parents=True)
    shard = downstream_dir / "2000-01_1.jsonl"
    shard.write_text("{}\n")
    old = time.time() - 30 * 86400
    os.utime(shard, (old, old))

    calls: list[dict[str, int]] = []
    real_prune = downstream.prune_downstream_records

    def record_prune(*, retention_days: int, max_total_mb: int) -> Any:
        calls.append({"retention_days": retention_days, "max_total_mb": max_total_mb})
        return real_prune(retention_days=retention_days, max_total_mb=max_total_mb)

    monkeypatch.setattr(downstream, "prune_downstream_records", record_prune)
    monkeypatch.setattr(server, "PROXY_ID", "alpha")
    # Reset both sides of the behavioral boundary so this retained test can run against
    # the dual-pruner admission commit as well as the single-owner implementation.
    monkeypatch.setattr(server, "_audit_pruned", False, raising=False)
    monkeypatch.setattr(server, "_provider_traces_pruned", False, raising=False)
    monkeypatch.setattr(server, "_downstream_pruned", False, raising=False)
    monkeypatch.setattr(server, "_downstream_retention_resolution", None, raising=False)
    monkeypatch.setattr(server, "_downstream_prune_error", None, raising=False)
    monkeypatch.setattr(server, "_request_logs_pruned", False, raising=False)
    monkeypatch.setattr(server, "_initialize_cost_tracker_from_config", lambda: None)

    server._ensure_runtime_state()

    # Keep the two ownership invariants in one assertion so a fail-on-base run records
    # both the duplicate calls and whether the second pass deleted the shared shard.
    assert (calls, shard.exists()) == ([], True)
    assert server._downstream_retention_resolution is not None
    assert server._downstream_retention_resolution.degraded

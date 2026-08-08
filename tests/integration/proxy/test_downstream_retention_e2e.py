"""Live proxy coverage for degraded downstream-retention startup status (D015)."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest
import yaml

from tests.fixtures.proxy import allocate_ephemeral_port, kill_process, wait_for_port

pytestmark = pytest.mark.integration


def _write_proxy_policy(forge_home: Path, proxy_id: str, section: str, retention_days: int) -> None:
    path = forge_home / "proxies" / proxy_id / "proxy.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({section: {"retention_days": retention_days, "max_total_mb": 512}}))


def test_live_proxy_reports_legacy_conflict_and_preserves_shared_shard(
    tmp_path: Path,
) -> None:
    forge_home = tmp_path / "forge-home"
    _write_proxy_policy(forge_home, "alpha", "audit", 90)
    _write_proxy_policy(forge_home, "beta", "provider_trace", 14)
    downstream = forge_home / "telemetry" / "downstream"
    downstream.mkdir(parents=True)
    shard = downstream / "2000-01_1.jsonl"
    shard.write_text("{}\n")
    old = time.time() - 30 * 86400
    os.utime(shard, (old, old))

    port = allocate_ephemeral_port()
    env = os.environ.copy()
    env["FORGE_HOME"] = str(forge_home)
    env["LITELLM_BASE_URL"] = "http://127.0.0.1:9/v1"
    env["LITELLM_API_KEY"] = "integration-test-key"
    process = subprocess.Popen(
        [
            "uv",
            "run",
            "python",
            "-m",
            "forge.proxy.server",
            "--template",
            "litellm-openai",
            "--port",
            str(port),
        ],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    try:
        if not wait_for_port(port, timeout=10):
            stderr = process.stderr.read().decode() if process.stderr else ""
            pytest.fail(f"Proxy failed to start: {stderr}")

        response = httpx.get(f"http://127.0.0.1:{port}/", timeout=10)
        response.raise_for_status()
        payload = response.json()

        assert payload["status"] == "degraded"
        retention = payload["downstream_retention"]
        assert retention["effective"] is None
        assert retention["source"] is None
        assert retention["pruning_enabled"] is False
        assert retention["degraded"] is True
        assert {
            proxy_id
            for conflict in retention["conflicts"]
            for value in conflict["values"]
            for proxy_id in value["proxy_ids"]
        } == {"alpha", "beta"}
        assert shard.exists()
    finally:
        kill_process(process.pid)

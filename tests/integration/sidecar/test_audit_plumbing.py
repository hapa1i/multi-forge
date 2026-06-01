"""Integration: sidecar audit plumbing (Slice 2e).

Spawns the REAL sidecar image + entrypoint on the HOST. A `claude` sleeper keeps
the container alive after the entrypoint starts the proxy under `--proxy-id`, so we
can assert the two end-to-end properties the slice promises:

1. In-container ``GET /`` reports the per-proxy intercept mode — proving the proxy
   loaded the overlay from the *read-only* ``proxy.yaml`` mount AND skipped
   host-registry startup validation (which would otherwise abort, since the
   registry isn't in the container and the port is fixed at 8085).
2. Audit records written inside the container are host-visible on the *writable*
   audit mount after the container stops (``forge proxy audit show`` reads them).

Primary target is macOS (Docker Desktop maps container-root writes to the host
user). On Linux the run mirrors container.py's ``--user`` mapping for fidelity.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from forge.sidecar.docker import is_docker_available

pytestmark = [pytest.mark.integration, pytest.mark.docker_host]

PROXY_ID = "forge-test-audit"
CONTAINER = "forge-test-audit-sidecar"


@pytest.fixture(scope="module", autouse=True)
def _require_docker() -> None:
    """Fail loudly if Docker is unavailable (never-skip policy)."""
    if not is_docker_available():
        pytest.fail("Docker not available. Start Docker and re-run integration tests.")


def _docker(*args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, **kwargs)  # type: ignore[call-overload]


def _forge(forge_home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "forge", *args],
        capture_output=True,
        text=True,
        env={**os.environ, "FORGE_HOME": str(forge_home)},
    )


def _claude_path(image: str) -> str:
    """Resolve the in-image `claude` path so we can shadow it with a sleeper."""
    result = _docker("run", "--rm", "--entrypoint", "sh", image, "-c", "command -v claude")
    path = result.stdout.strip()
    if not path:
        pytest.fail(f"Could not locate `claude` in {image}: {result.stderr}")
    return path


def test_sidecar_proxy_id_overlay_and_host_visible_audit(tmp_path: Path, sidecar_image: str) -> None:
    forge_home = tmp_path / "forge-home"

    # 1) Create the passthrough proxy (inspect by default) on the host.
    create = _forge(forge_home, "proxy", "create", "anthropic-passthrough", "--name", PROXY_ID, "--no-start")
    assert create.returncode == 0, f"proxy create failed: {create.stderr}"
    proxy_dir = forge_home / "proxies" / PROXY_ID
    assert (proxy_dir / "proxy.yaml").exists(), "proxy.yaml not written"
    audit_dir = forge_home / "audit"
    costs_dir = forge_home / "costs"
    audit_dir.mkdir(parents=True, exist_ok=True)
    costs_dir.mkdir(parents=True, exist_ok=True)

    # 2) `claude` sleeper keeps the container up after the entrypoint starts the proxy.
    sleeper = tmp_path / "claude"
    sleeper.write_text("#!/bin/sh\nexec sleep 300\n")
    sleeper.chmod(0o755)
    claude_path = _claude_path(sidecar_image)

    _docker("rm", "-f", CONTAINER)
    # NOTE: this intentionally mirrors the env + mounts that
    # forge.sidecar.container.run_sidecar_session / _ensure_audit_plumbing_mounts build
    # (FORGE_PROXY_ID, FORGE_HOME, proxies ro + audit/costs rw). We hand-roll `docker run`
    # because the real helper uses `-it` + `exec claude`, which a headless test can't drive.
    # If you change the helper's env/mounts, update this list (and its unit tests) too.
    run_cmd = [
        "run",
        "-d",
        "--name",
        CONTAINER,
        "-e",
        "FORGE_TEMPLATE=anthropic-passthrough",
        "-e",
        f"FORGE_PROXY_ID={PROXY_ID}",
        "-e",
        "FORGE_SIDECAR=1",
        "-e",
        "FORGE_HOME=/root/.forge",
        "-e",
        "ANTHROPIC_API_KEY=test-not-real",
        "-v",
        f"{proxy_dir}:/root/.forge/proxies/{PROXY_ID}:ro",
        "-v",
        f"{audit_dir}:/root/.forge/audit:rw",
        "-v",
        f"{costs_dir}:/root/.forge/costs:rw",
        "-v",
        f"{sleeper}:{claude_path}:ro",
    ]
    if sys.platform == "linux":
        run_cmd += ["--user", f"{os.getuid()}:{os.getgid()}"]
    run_cmd.append(sidecar_image)

    try:
        started = _docker(*run_cmd)
        assert started.returncode == 0, f"docker run failed: {started.stderr}"

        # 3) Entrypoint starts the proxy under --proxy-id; wait for health.
        root: dict[str, object] | None = None
        for _ in range(60):
            probe = _docker("exec", CONTAINER, "curl", "-sf", "http://localhost:8085/")
            if probe.returncode == 0 and probe.stdout.strip():
                root = json.loads(probe.stdout)
                break
            time.sleep(1)
        logs = _docker("logs", CONTAINER)
        assert root is not None, f"proxy never healthy.\nSTDOUT:\n{logs.stdout}\nSTDERR:\n{logs.stderr}"
        # Overlay loaded from the read-only mount; host-registry validation skipped.
        assert root["intercept_mode"] == "inspect"
        assert root["wire_shape"] == "anthropic_passthrough"

        # 4) One request -> inspect metadata record (written pre-forward, before the
        # upstream call to the fake key fails).
        body = {"model": "claude-sonnet-4-6", "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]}
        _docker(
            "exec",
            CONTAINER,
            "curl",
            "-s",
            "-o",
            "/dev/null",
            "-X",
            "POST",
            "http://localhost:8085/v1/messages",
            "-H",
            "content-type: application/json",
            "-d",
            json.dumps(body),
        )
        time.sleep(1)  # let the offloaded audit write flush to the mount
    finally:
        _docker("rm", "-f", CONTAINER)

    # 5) Host sees the record on the writable audit mount after the container is gone.
    shards = list((audit_dir / "requests").glob("*.jsonl"))
    assert shards, f"no audit shards under {audit_dir / 'requests'}"
    records = [json.loads(line) for shard in shards for line in shard.read_text().splitlines() if line.strip()]
    assert any(
        r.get("proxy_id") == PROXY_ID and r.get("record_type") == "request" for r in records
    ), f"no request record for {PROXY_ID}: {records}"

    # And the host CLI surfaces it (the Rich audit table prints to stderr).
    show = _forge(forge_home, "proxy", "audit", "show", PROXY_ID)
    assert show.returncode == 0, f"audit show failed: {show.stderr}"
    show_output = show.stdout + show.stderr
    assert PROXY_ID in show_output, f"audit show did not surface the record: {show_output!r}"

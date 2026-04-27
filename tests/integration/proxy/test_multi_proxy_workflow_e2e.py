"""Integration test for the multi-proxy workflow (design.md §3.10).

Goal:
- Validate that two concurrently running proxy instances (different base URLs / ports)
  represent two distinct proxy identities.
- Validate that routing defaults are proxy-owned:
  - default_tier comes from proxy config (family/proxy overlay)
  - session records are explicitly non-authoritative for routing

This is intentionally not a "full Claude workflow" test (no Claude CLI invocation).
It focuses on the core invariants that make the multi-proxy workflow possible.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import httpx
import pytest

# Import shared proxy utilities
from tests.fixtures.proxy import allocate_ephemeral_port, kill_process

pytestmark = pytest.mark.integration


def _start_proxy(*, template: str, port: int, forge_home: Path, proxy_id: str | None) -> subprocess.Popen:
    env = os.environ.copy()
    env["FORGE_HOME"] = str(forge_home)

    proc = subprocess.Popen(
        (
            [
                "uv",
                "run",
                "python",
                "-m",
                "forge.proxy.server",
                "--template",
                template,
                "--port",
                str(port),
                "--proxy-id",
                proxy_id,
            ]
            if proxy_id is not None
            else [
                "uv",
                "run",
                "python",
                "-m",
                "forge.proxy.server",
                "--template",
                template,
                "--port",
                str(port),
            ]
        ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=env,
    )

    return proc


def _wait_for_ready(*, base_url: str, proc: subprocess.Popen, timeout: float = 30.0) -> None:
    import time

    start = time.time()
    last_error: str | None = None
    while time.time() - start < timeout:
        # If the subprocess crashed, fail fast with stderr.
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            pytest.fail(f"Proxy exited during startup. Stderr (tail): {stderr[-4000:]}")

        try:
            with httpx.Client(timeout=2) as client:
                resp = client.get(f"{base_url}/")
            if resp.status_code == 200:
                return
            last_error = f"status={resp.status_code} body={resp.text[:200]}"
        except httpx.RequestError as e:
            last_error = str(e)
        time.sleep(0.1)

    stderr = proc.stderr.read().decode() if proc.stderr else ""
    pytest.fail(
        f"Proxy did not become ready at {base_url} within {timeout}s. " f"Last error: {last_error}. Stderr: {stderr}"
    )


def test_multi_proxy_two_proxies_distinct_proxy_identity_and_routing_defaults() -> None:
    # Use a shared forge home so the proxy can read the proxy registry.
    # Strict proxy startup validation requires:
    # - ~/.forge/proxies/index.json contains the proxy_id
    # - family and port match
    with tempfile.TemporaryDirectory(prefix="forge_multi_proxy_") as tmpdir:
        forge_home = Path(tmpdir)

        # Pick two different families so runtime truth reflects the separation clearly.
        # Note: these tests still rely on LiteLLM being reachable; we will skip if upstream is unavailable.
        family_a = "litellm-gemini-test"
        family_b = "litellm-openai"

        # Use ephemeral ports to avoid collisions with other tests
        # Retry if we get the same port twice (rare but possible with bind(0))
        port_a = allocate_ephemeral_port()
        port_b = allocate_ephemeral_port()
        if port_a == port_b:
            port_b = allocate_ephemeral_port()

        proxy_id_a = "proxy_test_a"
        proxy_id_b = "proxy_test_b"

        # Create proxy.yaml files (load_config requires them)
        from forge.config.loader import write_proxy_instance_config
        from forge.config.schema import (
            ProxyInstanceConfig,
            TierModels,
            TierOverride,
            TierOverrides,
        )

        # Set FORGE_HOME so write_proxy_instance_config uses our test directory
        old_forge_home = os.environ.get("FORGE_HOME")
        os.environ["FORGE_HOME"] = str(forge_home)

        try:
            # Create proxy A (litellm-gemini-test template)
            write_proxy_instance_config(
                proxy_id_a,
                ProxyInstanceConfig(
                    proxy_format=1,
                    template=family_a,
                    template_digest="sha256:test",
                    provider="litellm",
                    proxy_endpoint=f"http://localhost:{port_a}",
                    port=port_a,
                    upstream_base_url="http://localhost:4001",
                    tiers=TierModels(
                        haiku="gemini/gemini-3-flash-preview",
                        sonnet="gemini/gemini-3.1-pro-preview",
                        opus="gemini/gemini-3.1-pro-preview",
                    ),
                    tier_overrides=TierOverrides(
                        sonnet=TierOverride(reasoning_effort="medium"),
                        opus=TierOverride(reasoning_effort="high"),
                    ),
                    default_tier="sonnet",
                ),
            )

            # Create proxy B (litellm-openai template)
            write_proxy_instance_config(
                proxy_id_b,
                ProxyInstanceConfig(
                    proxy_format=1,
                    template=family_b,
                    template_digest="sha256:test",
                    provider="litellm",
                    proxy_endpoint=f"http://localhost:{port_b}",
                    port=port_b,
                    upstream_base_url="http://localhost:4001",
                    tiers=TierModels(
                        haiku="openai/gpt-5.1-mini",
                        sonnet="openai/gpt-5.1-codex",
                        opus="openai/gpt-5.2",
                    ),
                    default_tier="sonnet",
                ),
            )
        finally:
            # Restore original FORGE_HOME
            if old_forge_home is not None:
                os.environ["FORGE_HOME"] = old_forge_home
            else:
                os.environ.pop("FORGE_HOME", None)

        # Pre-register both proxies in the proxy registry so strict proxy startup passes.
        from forge.proxy.proxies import (
            ProxyEntry,
            ProxyRegistry,
            ProxyRegistryStore,
        )

        store = ProxyRegistryStore(registry_path=forge_home / "proxies" / "index.json")
        store.write(
            ProxyRegistry(
                proxies={
                    proxy_id_a: ProxyEntry(
                        proxy_id=proxy_id_a,
                        template=family_a,
                        base_url=f"http://localhost:{port_a}",
                        port=port_a,
                    ),
                    proxy_id_b: ProxyEntry(
                        proxy_id=proxy_id_b,
                        template=family_b,
                        base_url=f"http://localhost:{port_b}",
                        port=port_b,
                    ),
                }
            )
        )

        proc_a = _start_proxy(template=family_a, port=port_a, forge_home=forge_home, proxy_id=proxy_id_a)
        proc_b = _start_proxy(template=family_b, port=port_b, forge_home=forge_home, proxy_id=proxy_id_b)

        # If either proxy exits early (startup/config failure), surface stderr.
        # Note: they may still be starting, so we only treat as failure if already exited.
        for proc, label in ((proc_a, "A"), (proc_b, "B")):
            if proc.poll() is not None:
                stderr = proc.stderr.read().decode() if proc.stderr else ""
                pytest.fail(f"Proxy {label} exited during startup. Stderr: {stderr}")

        try:
            base_url_a = f"http://localhost:{port_a}"
            base_url_b = f"http://localhost:{port_b}"

            _wait_for_ready(base_url=base_url_a, proc=proc_a)
            _wait_for_ready(base_url=base_url_b, proc=proc_b)

            with httpx.Client(timeout=10) as client:
                resp_a = client.get(f"{base_url_a}/")
                resp_b = client.get(f"{base_url_b}/")

            # If upstream is unreachable, the proxy might still come up, but POST preflight used by
            # other integration tests would skip. Here we only depend on GET /.
            assert resp_a.status_code == 200
            assert resp_b.status_code == 200

            truth_a = resp_a.json()
            truth_b = resp_b.json()

            # Distinct proxy identities
            assert truth_a["proxy"]["proxy_id"] == proxy_id_a
            assert truth_b["proxy"]["proxy_id"] == proxy_id_b
            assert truth_a["proxy"]["base_url"] != truth_b["proxy"]["base_url"]

            # Distinct families (because we started with different --template)
            assert truth_a["proxy"]["template"] == family_a
            assert truth_b["proxy"]["template"] == family_b

            # Routing invariants: session is non-authoritative.
            assert "Session state" in truth_a["routing"]["note"]
            assert "not" in truth_a["routing"]["note"]
            assert "Session state" in truth_b["routing"]["note"]
            assert "not" in truth_b["routing"]["note"]

            # Proxy-owned routing defaults exist (default_tier should be present when config is valid)
            assert truth_a["routing"]["default_tier"] is not None
            assert truth_b["routing"]["default_tier"] is not None

        finally:
            kill_process(proc_a.pid)
            kill_process(proc_b.pid)

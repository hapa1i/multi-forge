"""PR 268: resolving credentials must not carry cached provider grouping into the probe home."""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from forge.core.paths import get_forge_home
from forge.runtime_config import get_runtime_config

pytestmark = pytest.mark.regression


@pytest.mark.asyncio
async def test_probe_reloads_config_after_resolving_original_credentials(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[2] / "scripts/experiments/jev/probe.py"
    spec = importlib.util.spec_from_file_location("jev_probe_config_regression", path)
    assert spec and spec.loader
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    monkeypatch.setattr(probe.CredentialManager, "_default_instance", None)
    previous_home = get_forge_home()
    previous_home.mkdir(parents=True, exist_ok=True)
    (previous_home / "config.yaml").write_text("provider_trace:\n  inject_provider_user: true\n")
    (previous_home / "credentials.yaml").write_text(
        "version: 1\nprofiles:\n  default:\n    OPENROUTER_API_KEY: file-synthetic\n"
    )
    monkeypatch.setattr("forge.runtime_config._config", None)
    assert get_runtime_config().provider_trace.inject_provider_user is True
    before = {str(p): p.read_bytes() for p in previous_home.rglob("*") if p.is_file()}
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.setenv("FORGE_HOME", str(previous_home))
    for name in ("FORGE_RUN_ID", "FORGE_ROOT_RUN_ID", "FORGE_SESSION", "FORGE_PARENT_RUN_ID"):
        monkeypatch.delenv(name, raising=False)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer file-synthetic"
        assert json.loads(request.content) == probe.manifest()["requests"][0]["payload"]
        assert get_runtime_config().provider_trace.inject_provider_user is False
        # Stop after a deliberate provider refusal; this test performs no network I/O.
        return httpx.Response(400, json={"error": {"code": 400}})

    monkeypatch.setattr(probe.httpx, "AsyncHTTPTransport", lambda **kw: httpx.MockTransport(handler))
    output = tmp_path / "capture"
    assert await probe.run_live(probe.manifest(), output) == 1
    assert len(calls) == 1
    assert get_forge_home() == output / "forge-home"
    assert {str(p): p.read_bytes() for p in previous_home.rglob("*") if p.is_file()} == before

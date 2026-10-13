"""A healthy proxy must not make an absent backend deployment workflow-ready."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import yaml
from click.testing import CliRunner

from forge.backend.creation import create_backend_config
from forge.cli.main import main
from forge.config.loader import write_proxy_instance_config
from forge.config.schema import ProxyInstanceConfig, TierModels
from forge.proxy.proxies import ProxyEntry, ProxyRegistry, ProxyRegistryStore
from forge.review.backend_readiness import WorkflowBackendReadiness
from forge.review.engine import preflight_check
from forge.review.models import AVAILABLE_MODELS, check_model_availability
from forge.review.routing import resolve_invocation_routing

pytestmark = pytest.mark.regression

ARGON = "gemini/gemini-4-argon"
OLD_PRO = "gemini/gemini-3.1-pro-preview"
SPEC = AVAILABLE_MODELS["gemini-4-argon"]


@dataclass
class BackendHarness:
    config_path: Path
    proxy_path: Path
    loaded_models: list[str]
    requests: list[httpx.Request]
    response: dict
    status: int = 200


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> BackendHarness:
    config_path = create_backend_config("litellm")
    loaded_models = [row["model_name"] for row in yaml.safe_load(config_path.read_text())["model_list"]]
    proxy_id = "saved-gemini"
    proxy_path = write_proxy_instance_config(
        proxy_id,
        ProxyInstanceConfig(
            proxy_format=1,
            template="litellm-gemini-local",
            template_digest="sha256:saved",
            provider="litellm",
            proxy_endpoint="http://localhost:8085",
            port=8085,
            upstream_base_url="http://localhost:4000",
            tiers=TierModels(haiku="gemini/gemini-3.8-flash", sonnet=OLD_PRO, opus=OLD_PRO),
        ),
    )
    ProxyRegistryStore().write(
        ProxyRegistry(
            proxies={
                proxy_id: ProxyEntry(
                    proxy_id=proxy_id,
                    template="litellm-gemini-local",
                    base_url="http://localhost:8085",
                    port=8085,
                    status="healthy",
                )
            }
        )
    )
    harness = BackendHarness(config_path, proxy_path, loaded_models, [], {})

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/models")
        assert request.url.params["return_wildcard_routes"] == "true"
        harness.requests.append(request)
        body = harness.response or {"data": [{"id": model} for model in harness.loaded_models]}
        return httpx.Response(harness.status, json=body)

    client = httpx.Client
    monkeypatch.setattr(
        "forge.review.backend_readiness.httpx.Client",
        lambda **kwargs: client(transport=httpx.MockTransport(handle), **kwargs),
    )
    monkeypatch.setattr("forge.core.reactive.routing._check_proxy_reachable", lambda *a, **kw: True)
    monkeypatch.setattr("forge.core.reactive.routing._probe_proxy_metadata", lambda *a, **kw: None)
    monkeypatch.setattr("forge.review.engine.shutil.which", lambda name: "/test/claude")
    monkeypatch.setattr("forge.review.models.available_model_specs", lambda: [SPEC])
    for name in ("ANTHROPIC_BASE_URL", "FORGE_SUBPROCESS_PROXY", "LITELLM_LOCAL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return harness


def _snapshot(path: Path) -> tuple[bytes, int, int]:
    stat = path.stat()
    return path.read_bytes(), stat.st_mtime_ns, stat.st_mode


def test_fresh_backend_is_ready_through_proxy_with_preserved_old_tiers(backend: BackendHarness) -> None:
    before = [_snapshot(path) for path in (backend.config_path, backend.proxy_path)]
    plan = resolve_invocation_routing([SPEC])

    assert plan.routes[0].route is not None
    assert plan.routes[0].route.model_ref == ARGON
    assert check_model_availability([SPEC])[0].status == "ready"
    assert preflight_check([SPEC], routing_plan=plan) == []
    listed = CliRunner().invoke(main, ["workflow", "list-models", "--available", "--json"])
    assert listed.exit_code == 0
    assert [row["name"] for row in json.loads(listed.output)] == [SPEC.name]
    assert [_snapshot(path) for path in (backend.config_path, backend.proxy_path)] == before


def test_saved_backend_without_argon_fails_before_worker_and_recovers_only_after_reload(
    backend: BackendHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    older = {"model_list": [{"model_name": OLD_PRO, "litellm_params": {"model": OLD_PRO}}]}
    backend.config_path.write_text(yaml.safe_dump(older))
    backend.loaded_models[:] = [OLD_PRO]
    before = [_snapshot(path) for path in (backend.config_path, backend.proxy_path)]
    worker = Mock(side_effect=AssertionError("worker must not launch"))
    monkeypatch.setattr("forge.review.engine.run_multi_review", worker)

    availability = check_model_availability([SPEC])[0]
    assert availability.status == "unavailable"
    assert ARGON in availability.reason
    assert "model_info" in availability.reason
    assert "restart that backend" in availability.reason
    listed = CliRunner().invoke(main, ["workflow", "list-models", "--available", "--json"])
    assert listed.exit_code == 0
    assert json.loads(listed.output) == []
    panel = CliRunner().invoke(main, ["workflow", "panel", "-p", "Review", "-m", SPEC.name, "--json"])
    assert panel.exit_code == 1
    assert "does not advertise model" in panel.output
    worker.assert_not_called()
    assert [_snapshot(path) for path in (backend.config_path, backend.proxy_path)] == before

    # Updating the user-owned file does not change an already loaded gateway inventory.
    create_backend_config("litellm")
    assert check_model_availability([SPEC])[0].status == "unavailable"
    backend.loaded_models[:] = [
        row["model_name"] for row in yaml.safe_load(backend.config_path.read_text())["model_list"]
    ]
    assert check_model_availability([SPEC])[0].status == "ready"
    assert preflight_check([SPEC], routing_plan=resolve_invocation_routing([SPEC])) == []
    assert _snapshot(backend.proxy_path) == before[1]


@pytest.mark.parametrize("pattern", ["*", "gemini/*", "gemini/gemini-4-*"])
def test_litellm_wildcard_deployments_remain_usable(backend: BackendHarness, pattern: str) -> None:
    backend.loaded_models[:] = [pattern]
    assert check_model_availability([SPEC])[0].status == "ready"


def test_inventory_is_cached_per_endpoint_for_one_check(backend: BackendHarness) -> None:
    specs = [SPEC, AVAILABLE_MODELS["gemini-3.1-pro-preview"], SPEC]
    assert all(item.status == "ready" for item in check_model_availability(specs))
    assert len(backend.requests) == 1
    assert preflight_check(specs, routing_plan=resolve_invocation_routing(specs)) == []
    assert len(backend.requests) == 2


@pytest.mark.parametrize("status,body", [(401, {}), (503, {}), (200, {"data": [{"name": ARGON}]})])
def test_unverifiable_inventory_fails_closed_without_recommending_config_replacement(
    backend: BackendHarness, status: int, body: dict
) -> None:
    backend.status = status
    backend.response = body
    result = check_model_availability([SPEC])[0]
    assert result.status == "unavailable"
    assert "Cannot verify" in result.reason
    assert "test-auth" in result.reason
    assert "Add the complete" not in result.reason


def test_openrouter_does_not_require_litellm_deployment_inventory(backend: BackendHarness) -> None:
    from dataclasses import replace

    result = resolve_invocation_routing([SPEC]).routes[0]
    assert result.route is not None
    openrouter = replace(result, route=replace(result.route, provider="openrouter", model_ref="google/gemini-4-argon"))
    assert WorkflowBackendReadiness().error_for(openrouter) is None
    assert backend.requests == []


@pytest.mark.parametrize("api_path", ["/api/v1", "/litellm/api"])
def test_remote_inventory_uses_gateway_credential_and_configured_api_prefix(
    backend: BackendHarness, monkeypatch: pytest.MonkeyPatch, api_path: str
) -> None:
    from dataclasses import replace

    from forge.config.loader import load_proxy_instance_config

    instance = load_proxy_instance_config("saved-gemini")
    assert instance is not None
    instance.upstream_base_url = f"https://gateway.example{api_path}/"
    write_proxy_instance_config("saved-gemini", instance)
    monkeypatch.setenv("LITELLM_API_KEY", "gateway-test-key")
    result = resolve_invocation_routing([SPEC]).routes[0]
    assert result.route is not None
    remote_model = "vertex_ai/gemini-4-argon"
    result = replace(result, route=replace(result.route, model_ref=remote_model))
    backend.response = {"data": [{"id": remote_model}]}
    assert WorkflowBackendReadiness().error_for(result) is None
    assert str(backend.requests[0].url) == f"https://gateway.example{api_path}/models?return_wildcard_routes=true"
    assert backend.requests[0].headers["Authorization"] == "Bearer gateway-test-key"


def test_sidecar_or_external_proxy_without_host_snapshot_keeps_existing_routing(backend: BackendHarness) -> None:
    result = resolve_invocation_routing([SPEC]).routes[0]
    backend.proxy_path.unlink()
    assert WorkflowBackendReadiness().error_for(result) is None
    assert backend.requests == []

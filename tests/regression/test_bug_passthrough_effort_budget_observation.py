"""Legacy native budget overrides must not be reported as untouched passthrough effort."""

import json

import pytest
from starlette.requests import Request

from forge.config import TierOverride, init_config
from forge.proxy import passthrough, server
from forge.proxy.effort_observation import EffortObservations
from tests.fixtures.proxy_transport import FakeResponse, ProxyTransportFake

pytestmark = pytest.mark.regression


@pytest.mark.asyncio
async def test_budget_override_is_reported_without_inventing_an_effort_level(monkeypatch):
    init_config(template="anthropic-passthrough", proxy_id=None)
    monkeypatch.setattr(server, "_ensure_runtime_state", lambda: None)
    monkeypatch.setattr(server, "cost_tracker", None)
    monkeypatch.setattr(server, "effort_observations", EffortObservations())
    monkeypatch.setattr(server.config.proxy.intercept, "mode", "override")
    monkeypatch.setattr(server.config.proxy.get_provider(), "base_url", "https://upstream.test")
    monkeypatch.setattr(server, "_get_tier_override", lambda tier: TierOverride(reasoning_effort="high"))
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda name: "fixture-key")
    transport = ProxyTransportFake(response=FakeResponse(content=b'{"usage":{"input_tokens":1,"output_tokens":1}}'))
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", transport.client)
    body = {
        "model": "claude-sonnet-4-5",
        "max_tokens": 32_000,
        "thinking": {"type": "enabled", "budget_tokens": 1024},
        "messages": [],
    }

    async def receive():
        return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}

    request = Request(
        {"type": "http", "headers": [(b"x-forge-launch", b"run_aaaaaaaaaaaa")], "state": {}},
        receive=receive,
    )
    response = await server._handle_anthropic_passthrough(request, "req_budget")
    assert response.status_code == 200
    assert transport.captured.json["thinking"]["budget_tokens"] > 1024
    observation = server.effort_observations.snapshot("run_aaaaaaaaaaaa")["sonnet"]
    assert observation["source"] == "override"
    assert observation["resolved"] is None and observation["applied"] is None
    assert observation["wire"] is None
    assert "thinking.budget_tokens" in observation["note"]

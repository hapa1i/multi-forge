"""Passthrough observations describe enforced policy and only run for tracked launches."""

import json
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from forge.config import TierOverride, init_config
from forge.proxy import passthrough, passthrough_ingress, server
from forge.proxy.effort_observation import EffortObservations
from tests.fixtures.proxy_transport import FakeResponse, ProxyTransportFake

pytestmark = pytest.mark.regression
LAUNCH = "run_aaaaaaaaaaaa"


@pytest.fixture
def native_proxy(monkeypatch):
    init_config(template="anthropic-passthrough", proxy_id=None)
    monkeypatch.setattr(server, "_ensure_runtime_state", lambda: None)
    monkeypatch.setattr(server, "cost_tracker", None)
    monkeypatch.setattr(server, "effort_observations", EffortObservations())
    monkeypatch.setattr(server, "_observe_request_side", AsyncMock(return_value=None))
    monkeypatch.setattr(server.config.proxy.get_provider(), "base_url", "https://upstream.test")
    monkeypatch.setattr(server, "_get_tier_override", lambda tier: TierOverride(reasoning_effort="high"))
    monkeypatch.setattr(
        "forge.core.auth.template_secrets.resolve_env_or_credential",
        lambda name: "fixture-key",
    )
    transport = ProxyTransportFake(response=FakeResponse(content=b'{"usage":{"input_tokens":1,"output_tokens":1}}'))
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", transport.client)
    return transport


def _request(launch: str | None) -> Request:
    body = {
        "model": "claude-opus-4-6",
        "max_tokens": 100,
        "output_config": {"effort": "low"},
        "messages": [],
    }

    async def receive():
        return {
            "type": "http.request",
            "body": json.dumps(body).encode(),
            "more_body": False,
        }

    headers = [(b"x-forge-launch", launch.encode())] if launch is not None else []
    return Request({"type": "http", "headers": headers, "state": {}}, receive=receive)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["passthrough", "inspect", "override"])
async def test_native_floor_is_reported_only_when_override_enforces_it(monkeypatch, native_proxy, mode):
    monkeypatch.setattr(server.config.proxy.intercept, "mode", mode)
    response = await server._handle_anthropic_passthrough(_request(LAUNCH), "req_floor")
    assert response.status_code == 200
    observation = server.effort_observations.snapshot(LAUNCH)["opus"]
    assert observation["floor"] == ("high" if mode == "override" else None)
    assert observation["applied"] == native_proxy.captured.json["output_config"]["effort"]
    assert observation["applied"] == ("high" if mode == "override" else "low")
    assert observation["source"] == ("override" if mode == "override" else "passthrough")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["passthrough", "override"])
@pytest.mark.parametrize("launch", [None, "bad-launch", "run_aaaaaaaaaaaa\n"])
async def test_untracked_native_request_skips_observation_work(monkeypatch, native_proxy, mode, launch):
    monkeypatch.setattr(server.config.proxy.intercept, "mode", mode)

    def unexpected(*args, **kwargs):
        pytest.fail("Untracked requests must skip effort observation catalog/record work")

    monkeypatch.setattr(passthrough_ingress, "_native_effort_support", unexpected)
    monkeypatch.setattr(passthrough_ingress, "EffortResolution", unexpected)
    response = await server._handle_anthropic_passthrough(_request(launch), "req_untracked")
    assert response.status_code == 200
    assert native_proxy.captured.json["output_config"]["effort"] == ("high" if mode == "override" else "low")
    assert server.effort_observations.snapshot(LAUNCH) == {}

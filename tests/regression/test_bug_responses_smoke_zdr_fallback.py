"""A direct smoke must apply the requested default model's ZDR fallback once."""

import json

import httpx
import pytest

from forge.proxy import proxy_orchestrator

pytestmark = pytest.mark.regression


def test_smoke_sends_the_requested_default_when_the_fallback_also_has_a_mapping(monkeypatch):
    mappings = {"requested/model": "fallback/model", "fallback/model": "different/model"}
    dispatched = []

    def handle(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "wire_shape": "openai_responses_passthrough",
                    "runtime": {
                        "tier_mappings": {"sonnet": "fallback/model"},
                        "responses_policy": {
                            "requested_default_model": "requested/model",
                            "zdr_fallbacks": mappings,
                            "on_unreported_cost": "reject",
                        },
                    },
                },
            )
        selected = json.loads(request.content)["model"]
        dispatched.append(mappings.get(selected, selected))
        return httpx.Response(200, json={"output_text": "hi"}, headers={"X-Request-Cost": "0.000000"})

    client_type = httpx.Client
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(proxy_orchestrator.httpx, "Client", lambda **kw: client_type(transport=transport, **kw))
    assert proxy_orchestrator.smoke_test_proxy(base_url="http://127.0.0.1:8106") == (True, "hi")
    assert dispatched == ["fallback/model"]

"""Only a readable live route can select a smoke endpoint and model."""

import json

import httpx
import pytest

from forge.proxy import proxy_orchestrator

pytestmark = pytest.mark.regression


def smoke(monkeypatch, handler):
    client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        proxy_orchestrator.httpx,
        "Client",
        lambda **kw: client(transport=transport, **kw),
    )
    monkeypatch.setattr(proxy_orchestrator.time, "sleep", lambda _: None)
    return proxy_orchestrator.smoke_test_proxy(base_url="http://localhost:1234")


def test_messages_retry_refreshes_the_model_before_the_second_post(monkeypatch):
    models = iter(("old-model", "new-model"))
    requests = []

    def handle(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "wire_shape": "anthropic_passthrough",
                    "tiers": {"sonnet": next(models)},
                },
            )
        assert request.url.path == "/v1/messages"
        requests.append(json.loads(request.content)["model"])
        if len(requests) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"content": [{"text": "hi"}]})

    assert smoke(monkeypatch, handle) == (True, "hi")
    assert requests == ["old-model", "new-model"]


def test_translated_openrouter_messages_retries_after_503(monkeypatch):
    paths = []
    statuses = iter((503, 200))

    def handle(request):
        paths.append(request.url.path)
        if request.method == "GET":
            return httpx.Response(200, json={"wire_shape": "openai_translated", "provider": "openrouter"})
        assert json.loads(request.content)["model"] == "sonnet"
        return httpx.Response(next(statuses), json={"content": [{"text": "hi"}]})

    assert smoke(monkeypatch, handle) == (True, "hi")
    assert paths == ["/", "/v1/messages", "/", "/v1/messages"]


@pytest.mark.parametrize("first_get_fails", [False, True])
def test_direct_responses_allows_root_retry_but_only_one_create(monkeypatch, first_get_fails):
    paths = []

    def handle(request):
        paths.append(request.url.path)
        if first_get_fails and len(paths) == 1:
            return httpx.Response(503)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "wire_shape": "openai_responses_passthrough",
                    "provider": "openrouter",
                    "capabilities": {"responses_ingress": True},
                    "runtime": {
                        "responses_policy": {
                            "on_unreported_cost": "reject",
                            "required_zdr": True,
                            "zdr_fallbacks": {},
                            "cost_scope": "openrouter_credit",
                            "requested_default_model": "fixture/model",
                        }
                    },
                },
            )
        return httpx.Response(503, text="upstream unavailable")

    assert smoke(monkeypatch, handle) == (False, "HTTP 503: upstream unavailable")
    assert paths == (["/"] if first_get_fails else []) + ["/", "/v1/responses"]


def test_unidentified_route_sends_no_generation(monkeypatch):
    paths = []

    def handle(request):
        paths.append(request.url.path)
        return httpx.Response(200, json={})

    ok, detail = smoke(monkeypatch, handle)
    assert not ok and "wire shape" in detail
    assert paths == ["/", "/"]

"""Argon Vertex unary requests must not use the catalog's larger streaming limit."""

import json
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

from forge.core.llm import get_client
from forge.core.llm.clients.litellm import LiteLLMClient
from forge.core.llm.clients.openrouter import OpenRouterClient
from forge.core.llm.types import Message, ModelHyperparameters
from forge.core.models import get_max_output_tokens
from forge.core.provider_types import ProviderType
from forge.proxy.client_adapter import AdapterProviderType, CoreLLMClientAdapter
from forge.proxy.client_factory import ModelProvider, TierClientFactory

pytestmark = [pytest.mark.regression, pytest.mark.asyncio]

VERTEX_MODEL = "vertex_ai/gemini-4-argon"


@pytest.mark.parametrize("provider", ["litellm_remote", "litellm_local"])
@pytest.mark.parametrize("requested", [None, 65_536, 8_192])
async def test_vertex_unary_caps_default_and_explicit_limits(provider: ProviderType, requested: int | None) -> None:
    defaults = TierClientFactory()._resolve_tier_hyperparams(ModelProvider.LITELLM, "sonnet", VERTEX_MODEL)
    assert defaults.max_tokens == 65_536
    client = get_client(VERTEX_MODEL, provider=provider, default_hyperparams=defaults)
    assert isinstance(client, LiteLLMClient)
    params = ModelHyperparameters(max_tokens=requested) if requested is not None else None
    requests: list[dict[str, Any]] = []

    async with _recording_sdk(requests) as sdk:
        client._client = sdk
        response = await client.complete([Message(role="user", content="hello")], hyperparams=params)

    assert response.text == "hello"
    assert len(requests) == 1
    assert requests[0]["max_tokens"] == min(requested or defaults.max_tokens, 32_768)
    assert not requests[0].get("stream", False)
    assert defaults.max_tokens == get_max_output_tokens(VERTEX_MODEL) == 65_536
    if params is not None:
        assert params.max_tokens == requested


@pytest.mark.parametrize("provider", ["litellm_remote", "litellm_local"])
@pytest.mark.parametrize("requested", [None, 65_536])
async def test_translated_proxy_uses_vertex_unary_cap(provider: AdapterProviderType, requested: int | None) -> None:
    defaults = TierClientFactory()._resolve_tier_hyperparams(ModelProvider.LITELLM, "sonnet", VERTEX_MODEL)
    adapter = CoreLLMClientAdapter(
        VERTEX_MODEL,
        provider,
        max_tokens_override=defaults.max_tokens,
        default_hyperparams=defaults,
    )
    assert isinstance(adapter._client, LiteLLMClient)
    request: dict[str, Any] = {"messages": [{"role": "user", "content": "hello"}]}
    if requested is not None:
        request["max_tokens"] = requested
    requests: list[dict[str, Any]] = []

    async with _recording_sdk(requests) as sdk:
        adapter._client._client = sdk
        response = await adapter.create_completion(request, "test-argon-limit")

    assert response["choices"][0]["message"]["content"] == "hello"
    assert len(requests) == 1
    assert requests[0]["model"] == VERTEX_MODEL
    assert requests[0]["max_tokens"] == 32_768


@pytest.mark.parametrize("provider", ["litellm_remote", "litellm_local"])
async def test_vertex_streaming_keeps_full_catalog_limit(
    provider: ProviderType,
) -> None:
    client = get_client(
        VERTEX_MODEL,
        provider=provider,
        default_hyperparams=ModelHyperparameters(max_tokens=65_536),
    )
    assert isinstance(client, LiteLLMClient)
    requests: list[dict[str, Any]] = []

    async with _recording_sdk(requests) as sdk:
        client._client = sdk
        events = [event async for event in client.stream([Message(role="user", content="hello")])]

    assert events[-1].type == "response_end"
    assert len(requests) == 1
    assert requests[0]["stream"] is True
    assert requests[0]["max_tokens"] == 65_536


@pytest.mark.parametrize(
    ("model", "provider"),
    [
        ("gemini/gemini-4-argon", "litellm_local"),
        ("google/gemini-4-argon", "openrouter"),
        ("vertex_ai/gemini-3.1-pro-preview", "litellm_remote"),
    ],
)
async def test_other_routes_keep_their_unary_limit(model: str, provider: ProviderType) -> None:
    client = get_client(
        model,
        provider=provider,
        default_hyperparams=ModelHyperparameters(max_tokens=65_536),
    )
    assert isinstance(client, (LiteLLMClient, OpenRouterClient))
    requests: list[dict[str, Any]] = []

    async with _recording_sdk(requests) as sdk:
        client._client = sdk
        response = await client.complete([Message(role="user", content="hello")])

    assert response.text == "hello"
    assert len(requests) == 1
    assert requests[0]["max_tokens"] == 65_536


@pytest.mark.parametrize(
    ("token_field", "nested"),
    [
        ("max_tokens", False),
        ("max_completion_tokens", False),
        ("max_tokens", True),
        ("max_completion_tokens", True),
        ("max_output_tokens", True),
        ("maxOutputTokens", True),
    ],
)
async def test_vertex_unary_caps_provider_extras_without_mutating_them(token_field: str, nested: bool) -> None:
    extra: dict[str, Any] = {token_field: 65_536}
    if nested:
        extra = {"extra_body": extra}
    params = ModelHyperparameters(max_tokens=8_192, extra={"openai": extra})
    original = params.model_dump()
    client = LiteLLMClient(VERTEX_MODEL, provider="litellm_remote")
    requests: list[dict[str, Any]] = []

    async with _recording_sdk(requests) as sdk:
        client._client = sdk
        response = await client.complete([Message(role="user", content="hello")], hyperparams=params)

    assert response.text == "hello"
    assert len(requests) == 1
    assert requests[0][token_field] == 32_768
    assert params.model_dump() == original


def _recording_sdk(requests: list[dict[str, Any]]) -> AsyncOpenAI:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if body.get("stream"):
            return httpx.Response(
                200,
                text="data: [DONE]\n\n",
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(
            200,
            json={
                "id": "test-argon-response",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello"}}],
            },
        )

    return AsyncOpenAI(
        api_key="test-key",
        base_url="https://gateway.invalid/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )

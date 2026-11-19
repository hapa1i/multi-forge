"""Neon and Hydrogen send four native thinking levels through LiteLLM and keep the full unary output limit."""

import json
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

from forge.core.llm import get_client
from forge.core.llm.clients.litellm import LiteLLMClient
from forge.core.llm.clients.openrouter import OpenRouterClient
from forge.core.llm.types import Message, ModelHyperparameters, ModelReasoningEffort
from forge.core.provider_types import ProviderType

pytestmark = pytest.mark.asyncio

MODELS = ("gemini-4-neon", "gemini-4-hydrogen")


@pytest.mark.parametrize("model", [f"{prefix}{model}" for model in MODELS for prefix in ("gemini/", "vertex_ai/", "")])
@pytest.mark.parametrize("effort", [None, "low", "medium", "high", "xhigh"])
@pytest.mark.parametrize("stream", [False, True])
async def test_sends_native_thinking_config(model: str, effort: ModelReasoningEffort | None, stream: bool) -> None:
    client = LiteLLMClient(model, provider="litellm_local")
    params = ModelHyperparameters(max_tokens=16_384, reasoning_effort=effort, temperature=0.7, top_p=0.8)
    requests: list[dict[str, Any]] = []

    async with _recording_sdk(requests) as sdk:
        client._client = sdk
        if stream:
            events = [
                event async for event in client.stream([Message(role="user", content="hello")], hyperparams=params)
            ]
            assert events[-1].type == "response_end"
        else:
            response = await client.complete([Message(role="user", content="hello")], hyperparams=params)
            assert response.text == "hello"

    assert len(requests) == 1
    request = requests[0]
    assert request["thinkingConfig"] == {"thinkingLevel": effort or "high", "includeThoughts": True}
    assert "reasoning_effort" not in request
    assert "temperature" not in request
    assert "top_p" not in request
    assert request["max_tokens"] == 16_384
    assert params.reasoning_effort == effort


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("effort", ["minimal", "max", "disable", "none"])
async def test_rejects_unsupported_effort_before_dispatch(model: str, effort: ModelReasoningEffort) -> None:
    client = LiteLLMClient(f"gemini/{model}", provider="litellm_local")

    with pytest.raises(ValueError, match="reasoning_effort"):
        client._build_request_kwargs([], None, ModelHyperparameters(reasoning_effort=effort))


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize(
    ("prefix", "provider"),
    [("vertex_ai", "litellm_remote"), ("vertex_ai", "litellm_local"), ("gemini", "litellm_local")],
)
async def test_unary_request_keeps_the_full_output_limit(model: str, prefix: str, provider: ProviderType) -> None:
    client = get_client(
        f"{prefix}/{model}", provider=provider, default_hyperparams=ModelHyperparameters(max_tokens=65_536)
    )
    assert isinstance(client, LiteLLMClient)
    requests: list[dict[str, Any]] = []

    async with _recording_sdk(requests) as sdk:
        client._client = sdk
        response = await client.complete([Message(role="user", content="hello")])

    assert response.text == "hello"
    assert len(requests) == 1
    assert not requests[0].get("stream", False)
    assert requests[0]["max_tokens"] == 65_536


@pytest.mark.parametrize("model", MODELS)
async def test_openrouter_keeps_standard_reasoning_effort(model: str) -> None:
    client = OpenRouterClient(f"google/{model}", provider="openrouter")
    requests: list[dict[str, Any]] = []

    async with _recording_sdk(requests) as sdk:
        client._client = sdk
        response = await client.complete(
            [Message(role="user", content="hello")], hyperparams=ModelHyperparameters(reasoning_effort="xhigh")
        )

    assert response.text == "hello"
    assert len(requests) == 1
    assert requests[0]["reasoning"] == {"effort": "xhigh"}
    assert "thinkingConfig" not in requests[0]


def _recording_sdk(requests: list[dict[str, Any]]) -> AsyncOpenAI:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if body.get("stream"):
            return httpx.Response(200, text="data: [DONE]\n\n", headers={"content-type": "text/event-stream"})
        return httpx.Response(
            200,
            json={
                "id": "test-gemini-4-response",
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

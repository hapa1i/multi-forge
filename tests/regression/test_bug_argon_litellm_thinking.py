"""Argon needs native thinking levels because LiteLLM 1.102 maps its effort to budgets."""

import json
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

from forge.core.llm.clients.litellm import LiteLLMClient
from forge.core.llm.clients.openrouter import OpenRouterClient
from forge.core.llm.types import Message, ModelHyperparameters, ModelReasoningEffort

pytestmark = [pytest.mark.regression, pytest.mark.asyncio]


@pytest.mark.parametrize("model", ["gemini/gemini-4-argon", "vertex_ai/gemini-4-argon", "gemini-4-argon"])
@pytest.mark.parametrize("effort", [None, "low", "medium", "high"])
@pytest.mark.parametrize("stream", [False, True])
async def test_argon_sends_native_thinking_config(
    model: str, effort: ModelReasoningEffort | None, stream: bool
) -> None:
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
    assert request["thinkingConfig"] == {"thinkingLevel": effort or "medium", "includeThoughts": True}
    assert "reasoning_effort" not in request
    assert "temperature" not in request
    assert "top_p" not in request
    assert request["max_tokens"] == 16_384
    assert params.reasoning_effort == effort


@pytest.mark.parametrize("nested_effort", [None, "low", "medium", "high"])
async def test_argon_maps_final_effort_and_replaces_conflicting_native_extras(nested_effort: str | None) -> None:
    client = LiteLLMClient("gemini/gemini-4-argon", provider="litellm_local")
    params = ModelHyperparameters(
        max_tokens=65_536,
        reasoning_effort="high",
        extra={
            "openai": {
                "thinkingConfig": {"thinkingBudget": 4_096},
                "extra_body": {
                    "reasoning_effort": nested_effort,
                    "thinkingConfig": {"thinkingLevel": "minimal", "thinkingBudget": 4_096},
                    "temperature": 0.5,
                    "top_p": 0.8,
                    "top_k": 20,
                },
                "tool_choice": "auto",
            }
        },
    )
    original = params.model_dump()
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]
    requests: list[dict[str, Any]] = []

    async with _recording_sdk(requests) as sdk:
        client._client = sdk
        response = await client.complete([Message(role="user", content="hello")], hyperparams=params, tools=tools)

    assert response.text == "hello"
    assert len(requests) == 1
    request = requests[0]
    assert request["thinkingConfig"] == {"thinkingLevel": nested_effort or "medium", "includeThoughts": True}
    assert not {"reasoning_effort", "temperature", "top_p", "top_k"}.intersection(request)
    assert request["max_tokens"] == 65_536
    assert request["tools"] == tools
    assert request["tool_choice"] == "auto"
    assert params.model_dump() == original


async def test_openrouter_keeps_standard_reasoning_effort() -> None:
    client = OpenRouterClient("google/gemini-4-argon", provider="openrouter")
    requests: list[dict[str, Any]] = []

    async with _recording_sdk(requests) as sdk:
        client._client = sdk
        response = await client.complete(
            [Message(role="user", content="hello")], hyperparams=ModelHyperparameters(reasoning_effort="medium")
        )

    assert response.text == "hello"
    assert len(requests) == 1
    assert requests[0]["reasoning"] == {"effort": "medium"}
    assert "thinkingConfig" not in requests[0]


@pytest.mark.parametrize("effort", ["minimal", "max", "disable", "none"])
async def test_argon_rejects_unsupported_effort_before_dispatch(effort: ModelReasoningEffort) -> None:
    client = LiteLLMClient("gemini/gemini-4-argon", provider="litellm_local")

    with pytest.raises(ValueError, match="reasoning_effort"):
        client._build_request_kwargs([], None, ModelHyperparameters(reasoning_effort=effort))


def _recording_sdk(requests: list[dict[str, Any]]) -> AsyncOpenAI:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if body.get("stream"):
            return httpx.Response(200, text="data: [DONE]\n\n", headers={"content-type": "text/event-stream"})
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

"""Gemini 4 rejects tool history without a thought signature, which another model's tool call cannot carry."""

import base64
import json
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

from forge.core.llm.clients.litellm import LiteLLMClient
from forge.core.llm.clients.openrouter import OpenRouterClient
from forge.core.llm.types import Message, ToolCall

pytestmark = [pytest.mark.regression, pytest.mark.asyncio]

GEMINI_4_ROUTES = [
    f"{prefix}{model}"
    for model in ("gemini-4-neon", "gemini-4-hydrogen", "gemini-4-carbon", "gemini-4-argon")
    for prefix in ("gemini/", "vertex_ai/", "")
]
PLACEHOLDER = {"thought_signature": base64.b64encode(b"skip_thought_signature_validator").decode()}
# LiteLLM returns a Gemini signature inside the tool call ID, after this separator.
SIGNED_ID = "call_7f3a__thought__c2lnbmVkLWJ5LWdlbWluaQ=="


def _step(*call_ids: str) -> list[Message]:
    calls = [ToolCall(id=call_id, name="get_value", arguments={"key": call_id}) for call_id in call_ids]
    results = [Message(role="tool", content="42", tool_call_id=call_id) for call_id in call_ids]
    return [Message(role="assistant", content="", tool_calls=calls), *results]


async def _sent_tool_calls(client: LiteLLMClient | OpenRouterClient, history: list[Message], stream: bool) -> list:
    requests: list[dict[str, Any]] = []
    messages = [Message(role="user", content="Read both values."), *history]
    async with _recording_sdk(requests) as sdk:
        client._client = sdk
        if stream:
            async for _ in client.stream(messages):
                pass
        else:
            await client.complete(messages)

    assert len(requests) == 1
    sent = requests[0]["messages"]
    assert [message.get("tool_call_id") for message in sent] == [message.tool_call_id for message in messages]
    return [message["tool_calls"] for message in sent if message.get("tool_calls")]


@pytest.mark.parametrize("model", GEMINI_4_ROUTES)
@pytest.mark.parametrize("stream", [False, True])
async def test_first_unsigned_call_of_each_step_gets_the_placeholder(model: str, stream: bool) -> None:
    # A parallel Claude step followed by a single Claude step, replayed after a switch to Gemini 4.
    history = [*_step("toolu_01A", "toolu_01B"), *_step("toolu_01C")]

    parallel, single = await _sent_tool_calls(LiteLLMClient(model, provider="litellm_local"), history, stream)

    assert [call["id"] for call in parallel] == ["toolu_01A", "toolu_01B"]
    assert parallel[0]["provider_specific_fields"] == PLACEHOLDER
    # Gemini signs only the first call of a parallel batch, so later calls stay unsigned.
    assert "provider_specific_fields" not in parallel[1]
    assert single[0]["id"] == "toolu_01C"
    assert single[0]["provider_specific_fields"] == PLACEHOLDER


@pytest.mark.parametrize("model", GEMINI_4_ROUTES)
async def test_gemini_signed_call_keeps_its_own_signature(model: str) -> None:
    (signed,) = await _sent_tool_calls(LiteLLMClient(model, provider="litellm_local"), _step(SIGNED_ID), stream=False)

    assert signed[0]["id"] == SIGNED_ID
    assert "provider_specific_fields" not in signed[0]


@pytest.mark.parametrize(
    "client",
    [
        # LiteLLM signs unsigned history itself for Gemini 3 names.
        LiteLLMClient("gemini/gemini-3.8-flash", provider="litellm_local"),
        LiteLLMClient("anthropic/claude-sonnet-5-5", provider="litellm_local"),
        # OpenRouter accepts unsigned history for both models.
        OpenRouterClient("google/gemini-4-neon", provider="openrouter"),
        OpenRouterClient("google/gemini-4-hydrogen", provider="openrouter"),
    ],
    ids=lambda client: client.model,
)
async def test_other_routes_send_unsigned_history_unchanged(client: LiteLLMClient | OpenRouterClient) -> None:
    (unsigned,) = await _sent_tool_calls(client, _step("toolu_01A"), stream=False)

    assert "provider_specific_fields" not in unsigned[0]


def _recording_sdk(requests: list[dict[str, Any]]) -> AsyncOpenAI:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if body.get("stream"):
            return httpx.Response(200, text="data: [DONE]\n\n", headers={"content-type": "text/event-stream"})
        return httpx.Response(
            200,
            json={
                "id": "test-tool-history-response",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "42"}}],
            },
        )

    return AsyncOpenAI(
        api_key="test-key",
        base_url="https://gateway.invalid/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )

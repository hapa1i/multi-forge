"""The core/proxy adapter must retain cutoff reasons even with partial tool calls."""

import json
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

from forge.core.llm.clients.litellm import LiteLLMClient
from forge.core.llm.clients.openrouter import OpenRouterClient
from forge.proxy.client_adapter import AdapterProviderType, CoreLLMClientAdapter
from forge.proxy.converters import (
    convert_openai_to_anthropic,
    convert_openai_to_anthropic_sse,
)
from forge.proxy.data_models import MessagesRequest

pytestmark = [pytest.mark.regression, pytest.mark.asyncio]


@pytest.mark.parametrize(
    ("model", "provider"),
    [("vertex_ai/gemini-4-argon", "litellm_remote"), ("google/gemini-4-argon", "openrouter")],
)
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    ("finish_reason", "partial_tool", "expected_stop"),
    [
        ("length", False, "max_tokens"),
        ("length", True, "max_tokens"),
        ("content_filter", False, "content_filtered"),
        ("stop", False, "end_turn"),
        ("tool_calls", True, "tool_use"),
    ],
)
async def test_translated_response_preserves_provider_termination(
    model: str, provider: AdapterProviderType, stream: bool, finish_reason: str, partial_tool: bool, expected_stop: str
) -> None:
    adapter = CoreLLMClientAdapter(model, provider)
    assert isinstance(adapter._client, (LiteLLMClient, OpenRouterClient))
    upstream_requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        upstream_requests.append(body)
        tool = {
            "id": "call_partial",
            "type": "function",
            "function": {"name": "Read", "arguments": '{"file_path": "'},
        }
        message: dict[str, Any] = {"content": "unfinished"}
        if partial_tool:
            message = {"tool_calls": [{**tool, **({"index": 0} if stream else {})}]}
        response: dict[str, Any] = {"id": "cutoff", "created": 0, "model": model}
        usage = {"prompt_tokens": 4, "completion_tokens": body["max_tokens"], "total_tokens": body["max_tokens"] + 4}
        if stream:
            chunks = [
                {**response, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": message}]},
                {
                    **response,
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
                },
                {**response, "object": "chat.completion.chunk", "choices": [], "usage": usage},
            ]
            return httpx.Response(
                200,
                text="".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n",
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(
            200,
            json={
                **response,
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", **message}, "finish_reason": finish_reason}],
                "usage": usage,
            },
        )

    async with AsyncOpenAI(
        api_key="test-key",
        base_url="https://gateway.invalid/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as sdk:
        adapter._client._client = sdk
        request: dict[str, Any] = {"messages": [{"role": "user", "content": "hello"}], "max_tokens": 64_000}
        if stream:
            events = [
                json.loads(line[6:])
                async for event in convert_openai_to_anthropic_sse(
                    adapter.create_streaming_completion(request, "cutoff"),
                    MessagesRequest(model="claude-sonnet-4-6", **request),
                    "cutoff",
                )
                for line in event.splitlines()
                if line.startswith("data: ")
            ]
            final = next(
                event for event in events if event["type"] == "message_delta" and "stop_reason" in event["delta"]
            )
            assert final["delta"]["stop_reason"] == expected_stop
            assert final["usage"]["output_tokens"] == 64_000
            assert events[-1]["type"] == "message_stop"
        else:
            translated = await adapter.create_completion(request, "cutoff")
            assert translated["choices"][0]["finish_reason"] == finish_reason
            result = convert_openai_to_anthropic(translated)
            assert result is not None
            assert result.stop_reason == expected_stop
            assert result.usage.output_tokens == (32_768 if provider == "litellm_remote" else 64_000)
            if partial_tool:
                assert any(block.type == "tool_use" for block in result.content)

    assert len(upstream_requests) == 1
    assert upstream_requests[0]["max_tokens"] == (32_768 if provider == "litellm_remote" and not stream else 64_000)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("partial_tool", [False, True])
@pytest.mark.parametrize(
    ("incomplete_reason", "finish_reason", "expected_stop"),
    [
        ("max_output_tokens", "length", "max_tokens"),
        ("content_filter", "content_filter", "content_filtered"),
        (None, "length", "max_tokens"),
        ("unknown", "length", "max_tokens"),
    ],
)
async def test_responses_incomplete_retains_reason_in_streaming_fallback(
    stream: bool, partial_tool: bool, incomplete_reason: str | None, finish_reason: str, expected_stop: str
) -> None:
    adapter = CoreLLMClientAdapter("openai/gpt-6-astra", "litellm_remote")
    assert isinstance(adapter._client, LiteLLMClient)

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        output: dict[str, Any] = {
            "type": "message",
            "id": "msg_partial",
            "role": "assistant",
            "status": "incomplete",
            "content": [{"type": "output_text", "text": "unfinished", "annotations": []}],
        }
        if partial_tool:
            output = {
                "type": "function_call",
                "id": "fc_partial",
                "call_id": "call_partial",
                "name": "Read",
                "arguments": '{"file_path": "',
                "status": "incomplete",
            }
        return httpx.Response(
            200,
            json={
                "id": "resp_partial",
                "object": "response",
                "created_at": 0,
                "model": "gpt-6-astra",
                "status": "incomplete",
                "incomplete_details": {"reason": incomplete_reason} if incomplete_reason else None,
                "output": [output],
            },
        )

    async with AsyncOpenAI(
        api_key="test-key",
        base_url="https://gateway.invalid/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as sdk:
        adapter._client._client = sdk
        request: dict[str, Any] = {"messages": [{"role": "user", "content": "hello"}], "max_tokens": 16_384}
        if stream:
            events = [
                json.loads(line[6:])
                async for event in convert_openai_to_anthropic_sse(
                    adapter.create_streaming_completion(request, "cutoff"),
                    MessagesRequest(model="claude-sonnet-4-6", **request),
                    "cutoff",
                )
                for line in event.splitlines()
                if line.startswith("data: ")
            ]
            final = next(
                event for event in events if event["type"] == "message_delta" and "stop_reason" in event["delta"]
            )
            assert final["delta"]["stop_reason"] == expected_stop
        else:
            translated = await adapter.create_completion(request, "cutoff")
            assert translated["choices"][0]["finish_reason"] == finish_reason
            result = convert_openai_to_anthropic(translated)
            assert result is not None
            assert result.stop_reason == expected_stop

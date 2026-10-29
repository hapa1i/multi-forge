"""Tests for LiteLLM cost capture from response headers and streamed usage."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from openai import AsyncOpenAI

from forge.core.llm.clients.litellm import (
    LITELLM_COST_HEADER,
    LiteLLMClient,
    cost_from_response_headers,
)
from forge.core.llm.detection import ProviderType
from forge.core.llm.types import (
    CompletionResponse,
    Message,
    ModelHyperparameters,
    ProviderTraceMeta,
)


def _client() -> LiteLLMClient:
    return LiteLLMClient(
        model="openai/gpt-4o",
        provider="litellm_remote",
        default_hyperparams=ModelHyperparameters(max_tokens=4096),
    )


class TestCostFromResponseHeaders:
    """The LiteLLM gateway returns computed spend in a response header."""

    def test_reads_cost_header(self):
        headers = httpx.Headers({LITELLM_COST_HEADER: "0.00045"})
        assert cost_from_response_headers(headers) == 0.00045

    def test_plain_dict_headers(self):
        assert cost_from_response_headers({LITELLM_COST_HEADER: "0.0012"}) == 0.0012

    def test_missing_header_is_none(self):
        assert cost_from_response_headers(httpx.Headers({})) is None

    def test_none_headers_is_none(self):
        assert cost_from_response_headers(None) is None

    def test_malformed_value_is_none(self):
        """A non-numeric header degrades to None (cost unavailable), never crashes."""
        assert cost_from_response_headers({LITELLM_COST_HEADER: "free"}) is None


class TestMergeHeaderCost:
    """Body cost wins; the gateway header fills the gap."""

    def test_header_fills_when_body_reports_none(self):
        merged = _client()._merge_header_cost(
            CompletionResponse(text="hi", cost_usd=None),
            {LITELLM_COST_HEADER: "0.0007"},
        )
        assert merged.cost_usd == 0.0007

    def test_body_cost_wins_over_header(self):
        merged = _client()._merge_header_cost(
            CompletionResponse(text="hi", cost_usd=0.005),
            {LITELLM_COST_HEADER: "0.0007"},
        )
        assert merged.cost_usd == 0.005

    def test_no_header_no_body_stays_none(self):
        merged = _client()._merge_header_cost(CompletionResponse(text="hi", cost_usd=None), {})
        assert merged.cost_usd is None


class TestMergeResponseMetadata:
    """_merge_response_metadata adds gateway cost AND allowlisted trace headers."""

    def test_populates_provider_meta_headers(self):
        completion = CompletionResponse(text="hi", provider_meta=ProviderTraceMeta(provider="litellm"))
        merged = _client()._merge_response_metadata(
            completion,
            httpx.Headers({"x-request-id": "req-7", "authorization": "Bearer s"}),
        )
        assert merged.provider_meta is not None
        assert merged.provider_meta.headers == {"x-request-id": "req-7"}

    def test_creates_provider_meta_when_absent(self):
        merged = _client()._merge_response_metadata(
            CompletionResponse(text="hi"),  # provider_meta None
            httpx.Headers({"x-generation-id": "gen-1"}),
        )
        assert merged.provider_meta is not None
        assert merged.provider_meta.headers == {"x-generation-id": "gen-1"}

    def test_no_allowlisted_headers_leaves_meta_unchanged(self):
        meta = ProviderTraceMeta(provider="litellm", provider_generation_id="gen-x")
        merged = _client()._merge_response_metadata(
            CompletionResponse(text="hi", provider_meta=meta),
            httpx.Headers({"content-type": "application/json"}),
        )
        assert merged.provider_meta is not None
        assert merged.provider_meta.headers is None
        assert merged.provider_meta.provider_generation_id == "gen-x"  # preserved

    def test_still_merges_cost_alongside_headers(self):
        merged = _client()._merge_response_metadata(
            CompletionResponse(text="hi", cost_usd=None),
            httpx.Headers({LITELLM_COST_HEADER: "0.003", "x-request-id": "req-1"}),
        )
        assert merged.cost_usd == 0.003
        assert merged.provider_meta is not None
        assert merged.provider_meta.headers == {"x-request-id": "req-1"}


class TestCompleteReadsHeaderCost:
    """complete() reads the header via with_raw_response.create().parse() + .headers."""

    @pytest.mark.asyncio
    async def test_non_streaming_reads_response_cost_header(self):
        client = _client()
        parsed = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hi", tool_calls=None))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15, prompt_tokens_details=None),
            error=None,
            model_dump=lambda: {},
        )
        raw = SimpleNamespace(parse=lambda: parsed, headers={LITELLM_COST_HEADER: "0.00088"})

        mock_openai = AsyncMock()
        mock_openai.chat.completions.with_raw_response.create = AsyncMock(return_value=raw)
        client._client = mock_openai

        with patch.object(client, "_credentials") as mock_cm:
            mock_cm.get_credentials = AsyncMock(return_value={"api_key": "k", "base_url": "http://x"})
            result = await client.complete(messages=[Message(role="user", content="hi")])

        assert result.cost_usd == 0.00088
        assert result.text == "hi"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["litellm_local", "litellm_remote"])
@pytest.mark.parametrize(
    "cost,include_usage",
    [(0.0007, True), (0.0, True), (None, True), (None, False)],
    ids=["body-cost", "explicit-zero", "cost-omitted", "usage-omitted"],
)
async def test_stream_cost_through_sdk_transport(
    provider: ProviderType, cost: float | None, include_usage: bool
) -> None:
    usage: dict[str, Any] = {
        "prompt_tokens": 120,
        "completion_tokens": 3,
        "total_tokens": 123,
        "prompt_tokens_details": {"cached_tokens": 40},
    }
    if cost is not None:
        usage["cost"] = cost
    chunk_base = {"id": "stream-cost", "model": "gemini/gemini-3.8-flash", "created": 0}
    chunks = [
        {**chunk_base, "choices": [{"index": 0, "delta": {"content": "ok"}}]},
        {**chunk_base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    if include_usage:
        chunks.append({**chunk_base, "choices": [], "usage": usage})
    payload = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
    requests: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        assert body["stream"] is True
        assert body["stream_options"] == {"include_usage": True}
        return httpx.Response(
            200,
            content=payload.encode(),
            # Stream-start headers are not final spend evidence, even when the body has no cost.
            headers={"content-type": "text/event-stream", LITELLM_COST_HEADER: "999"},
        )

    async with AsyncOpenAI(
        api_key="fixture-key",
        base_url="http://litellm.invalid/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(serve)),
    ) as sdk:
        client = LiteLLMClient(model="gemini/gemini-3.8-flash", provider=provider)
        client._client = sdk
        events = [event async for event in client.stream([Message(role="user", content="cost fixture")])]

    assert len(requests) == 1
    assert not [event for event in events if event.type == "error"]
    assert "".join(event.text or "" for event in events if event.type == "text_delta") == "ok"
    terminal = [event for event in events if event.type == "response_end"]
    usage_events = [event for event in events if event.type == "usage"]
    assert len(terminal) == 1
    assert len(usage_events) == int(include_usage)
    for event in terminal + usage_events:
        assert event.cost_usd == cost
        assert event.usage == (
            {
                "prompt_tokens": 120,
                "completion_tokens": 3,
                "total_tokens": 123,
                "cached_tokens": 40,
            }
            if include_usage
            else None
        )

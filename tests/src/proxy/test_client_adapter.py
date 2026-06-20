"""Tests for proxy core.llm adapter behavior.

These tests focus on request-shaping edge cases where the proxy converts
Anthropic-style history into OpenAI-like messages and then into core.llm types.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from forge.config import init_config
from forge.core.llm.types import CompletionResponse, ProviderTraceMeta, StreamEvent
from forge.proxy.client_adapter import (
    CoreLLMClientAdapter,
    _extract_cache_info,
    _sanitize_header_value,
)


def test_openai_messages_to_core_handles_tool_calls_with_null_content() -> None:
    # Ensure unified config is initialized (adapter construction relies on core.llm routing).
    init_config(template="litellm-openai", proxy_id=None)

    adapter = CoreLLMClientAdapter(model="openai/gpt-5.2", provider="litellm_remote")

    openai_messages: list[dict[str, Any]] = [
        {
            "role": "assistant",
            "content": None,  # OpenAI tool-call messages commonly use null content
            "tool_calls": [
                {
                    "id": "toolu_1",
                    "type": "function",
                    "function": {
                        "name": "Read",
                        "arguments": '{"file_path": "/tmp/a"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "toolu_1", "content": "ok"},
    ]

    core_messages = adapter._openai_messages_to_core(openai_messages)

    assert len(core_messages) == 2
    assert core_messages[0].role == "assistant"
    assert core_messages[0].content == ""
    assert core_messages[0].tool_calls is not None
    assert core_messages[0].tool_calls[0].id == "toolu_1"
    assert core_messages[0].tool_calls[0].name == "Read"
    assert core_messages[0].tool_calls[0].arguments == {"file_path": "/tmp/a"}


# ---------------------------------------------------------------------------
# _extract_cache_info tests
# ---------------------------------------------------------------------------


class TestExtractCacheInfo:
    """Tests for the _extract_cache_info() helper."""

    def test_with_cached_tokens(self) -> None:
        usage = {
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "total_tokens": 1200,
            "cached_tokens": 800,
        }
        result = _extract_cache_info(usage)
        assert result["cached_tokens"] == 800
        assert result["cache_hit_rate"] == pytest.approx(80.0)

    def test_no_cache_data(self) -> None:
        usage = {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200}
        assert _extract_cache_info(usage) == {}

    def test_zero_cached_tokens(self) -> None:
        usage = {
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "total_tokens": 1200,
            "cached_tokens": 0,
        }
        assert _extract_cache_info(usage) == {}

    def test_none_usage(self) -> None:
        assert _extract_cache_info(None) == {}

    def test_zero_prompt_tokens_no_division_error(self) -> None:
        usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 100,
        }
        result = _extract_cache_info(usage)
        assert result["cached_tokens"] == 100
        assert result["cache_hit_rate"] == 0

    def test_partial_cache_hit(self) -> None:
        usage = {"prompt_tokens": 5000, "cached_tokens": 1250}
        result = _extract_cache_info(usage)
        assert result["cache_hit_rate"] == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# Cache hit logging integration tests
# ---------------------------------------------------------------------------


def _make_adapter_with_mock_client() -> CoreLLMClientAdapter:
    """Create an adapter with a mocked core.llm client (no real LLM calls)."""
    init_config(template="litellm-openai", proxy_id=None)
    adapter = CoreLLMClientAdapter(model="openai/gpt-5.2", provider="litellm_remote")
    adapter._client = MagicMock()
    return adapter


@pytest.mark.asyncio
async def test_create_completion_logs_cache_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter = _make_adapter_with_mock_client()
    adapter._client = MagicMock(  # type: ignore[assignment]
        complete=AsyncMock(
            return_value=CompletionResponse(
                text="Hello",
                usage={
                    "prompt_tokens": 1000,
                    "completion_tokens": 50,
                    "total_tokens": 1050,
                    "cached_tokens": 600,
                },
            )
        )
    )

    with caplog.at_level(logging.INFO, logger="forge.proxy.client_adapter"):
        result = await adapter.create_completion(
            {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 100},
            request_id="req-1",
        )

    assert result["usage"]["prompt_tokens"] == 1000
    # Verify cache info appeared in log
    assert any("cached_tokens=600" in msg and "60.0% cache hit" in msg for msg in caplog.messages)


@pytest.mark.asyncio
async def test_create_completion_logs_without_cache_when_absent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter = _make_adapter_with_mock_client()
    adapter._client = MagicMock(  # type: ignore[assignment]
        complete=AsyncMock(
            return_value=CompletionResponse(
                text="Hello",
                usage={
                    "prompt_tokens": 500,
                    "completion_tokens": 50,
                    "total_tokens": 550,
                },
            )
        )
    )

    with caplog.at_level(logging.INFO, logger="forge.proxy.client_adapter"):
        await adapter.create_completion(
            {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 100},
            request_id="req-2",
        )

    # Token usage logged but no cache info
    assert any("input_tokens=500" in msg for msg in caplog.messages)
    assert not any("cached_tokens" in msg for msg in caplog.messages)


@pytest.mark.asyncio
async def test_create_streaming_completion_logs_cache_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter = _make_adapter_with_mock_client()

    async def _fake_stream(*args, **kwargs):  # type: ignore[no-untyped-def]
        yield StreamEvent(type="text_delta", text="Hi")
        yield StreamEvent(
            type="usage",
            usage={
                "prompt_tokens": 2000,
                "completion_tokens": 100,
                "total_tokens": 2100,
                "cached_tokens": 1500,
            },
        )
        yield StreamEvent(type="response_end")

    adapter._client = MagicMock(stream=_fake_stream)  # type: ignore[assignment]

    chunks = []
    with caplog.at_level(logging.INFO, logger="forge.proxy.client_adapter"):
        async for chunk in adapter.create_streaming_completion(
            {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 100},
            request_id="req-3",
        ):
            chunks.append(chunk)

    assert len(chunks) >= 2  # text_delta + usage + response_end
    # Verify cache info appeared in post-stream log
    assert any("cached_tokens=1500" in msg and "75.0% cache hit" in msg for msg in caplog.messages)


# ---------------------------------------------------------------------------
# Reported-cost threading tests (Phase 2 Step 2)
# ---------------------------------------------------------------------------


class TestReportedCostThreading:
    """cost_usd rides into the OpenAI dict as an internal _reported_cost_micros key."""

    def test_core_response_carries_reported_cost(self) -> None:
        adapter = _make_adapter_with_mock_client()
        resp = CompletionResponse(
            text="hi",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            cost_usd=0.0023,
        )
        out = adapter._core_response_to_openai(resp, "openai/gpt-5.2")
        assert out["_reported_cost_micros"] == 2300  # 0.0023 USD → micros

    def test_core_response_omits_cost_when_none(self) -> None:
        adapter = _make_adapter_with_mock_client()
        resp = CompletionResponse(text="hi", cost_usd=None)
        out = adapter._core_response_to_openai(resp, "openai/gpt-5.2")
        assert "_reported_cost_micros" not in out

    def test_reported_zero_is_carried_not_dropped(self) -> None:
        """A reported $0 still produces the carrier key (0), distinct from unavailable."""
        adapter = _make_adapter_with_mock_client()
        resp = CompletionResponse(text="hi", cost_usd=0.0)
        out = adapter._core_response_to_openai(resp, "openai/gpt-5.2")
        assert out["_reported_cost_micros"] == 0

    @pytest.mark.asyncio
    async def test_create_completion_threads_cost(self) -> None:
        adapter = _make_adapter_with_mock_client()
        adapter._client = MagicMock(  # type: ignore[assignment]
            complete=AsyncMock(return_value=CompletionResponse(text="hi", cost_usd=0.0019))
        )
        result = await adapter.create_completion(
            {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 100},
            request_id="req-cost",
        )
        assert result["_reported_cost_micros"] == 1900

    @pytest.mark.asyncio
    async def test_streaming_usage_chunk_carries_cost(self) -> None:
        adapter = _make_adapter_with_mock_client()

        async def _fake_stream(*args, **kwargs):  # type: ignore[no-untyped-def]
            yield StreamEvent(type="text_delta", text="Hi")
            yield StreamEvent(
                type="usage",
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                cost_usd=0.0023,
            )
            yield StreamEvent(type="response_end", cost_usd=0.0023)

        adapter._client = MagicMock(stream=_fake_stream)  # type: ignore[assignment]

        usage_chunks = [
            c
            async for c in adapter.create_streaming_completion(
                {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 100},
                request_id="req-stream-cost",
            )
            if c.get("usage")
        ]
        assert usage_chunks
        assert usage_chunks[0]["usage"]["reported_cost_micros"] == 2300

    @pytest.mark.asyncio
    async def test_streaming_usage_chunk_omits_cost_when_none(self) -> None:
        adapter = _make_adapter_with_mock_client()

        async def _fake_stream(*args, **kwargs):  # type: ignore[no-untyped-def]
            yield StreamEvent(type="text_delta", text="Hi")
            yield StreamEvent(
                type="usage",
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
            yield StreamEvent(type="response_end")

        adapter._client = MagicMock(stream=_fake_stream)  # type: ignore[assignment]

        usage_chunks = [
            c
            async for c in adapter.create_streaming_completion(
                {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 100},
                request_id="req-stream-nocost",
            )
            if c.get("usage")
        ]
        assert usage_chunks
        assert "reported_cost_micros" not in usage_chunks[0]["usage"]


class TestProviderMetaThreading:
    """provider_meta rides into the OpenAI dict as an internal carrier, separate from the
    synthetic chatcmpl id."""

    def test_core_response_carries_provider_meta(self) -> None:
        adapter = _make_adapter_with_mock_client()
        resp = CompletionResponse(
            text="hi",
            provider_meta=ProviderTraceMeta(provider="openrouter", provider_generation_id="gen-abc"),
        )
        out = adapter._core_response_to_openai(resp, "openrouter/gpt-5.2")
        assert out["_provider_meta"] == {"provider": "openrouter", "provider_generation_id": "gen-abc"}

    def test_core_response_omits_provider_meta_when_none(self) -> None:
        adapter = _make_adapter_with_mock_client()
        out = adapter._core_response_to_openai(CompletionResponse(text="hi"), "openrouter/gpt-5.2")
        assert "_provider_meta" not in out

    def test_synthetic_id_distinct_from_generation_id(self) -> None:
        """The minted chatcmpl-<ts> id must never equal the provider generation id."""
        adapter = _make_adapter_with_mock_client()
        resp = CompletionResponse(
            text="hi",
            provider_meta=ProviderTraceMeta(provider="openrouter", provider_generation_id="gen-abc"),
        )
        out = adapter._core_response_to_openai(resp, "openrouter/gpt-5.2")
        assert out["id"].startswith("chatcmpl-")
        assert out["id"] != out["_provider_meta"]["provider_generation_id"]

    @pytest.mark.asyncio
    async def test_streaming_emits_provider_meta_carrier_chunk(self) -> None:
        """provider_meta rides its own carrier chunk (choices=[]) the instant it first appears,
        not nested in the usage chunk -- so the Phase 3 seam stashes it before any cancellation."""
        adapter = _make_adapter_with_mock_client()

        async def _fake_stream(*args, **kwargs):  # type: ignore[no-untyped-def]
            yield StreamEvent(
                type="text_delta",
                text="Hi",
                provider_meta=ProviderTraceMeta(provider="openrouter", provider_generation_id="gen-stream"),
            )
            yield StreamEvent(
                type="usage",
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
            yield StreamEvent(type="response_end")

        adapter._client = MagicMock(stream=_fake_stream)  # type: ignore[assignment]

        chunks = [
            c
            async for c in adapter.create_streaming_completion(
                {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 100},
                request_id="req-stream-meta",
            )
        ]
        carrier = [c for c in chunks if "_provider_meta" in c]
        assert len(carrier) == 1  # emitted at most once
        assert carrier[0]["_provider_meta"] == {
            "provider": "openrouter",
            "provider_generation_id": "gen-stream",
        }
        assert carrier[0]["choices"] == []  # metadata-only carrier, no content
        assert carrier[0]["id"].startswith("chatcmpl-")  # synthetic id, never the gen id
        # provider_meta no longer nested in the usage chunk's usage dict.
        usage_chunks = [c for c in chunks if c.get("usage")]
        assert usage_chunks
        assert "provider_meta" not in usage_chunks[0]["usage"]

    @pytest.mark.asyncio
    async def test_streaming_provider_meta_survives_end_before_usage(self) -> None:
        """The incident path: a stream that ends before the final usage chunk still delivers
        provider_meta, because the carrier chunk fires on the first content event (R1)."""
        adapter = _make_adapter_with_mock_client()

        async def _fake_stream(*args, **kwargs):  # type: ignore[no-untyped-def]
            yield StreamEvent(
                type="text_delta",
                text="partial",
                provider_meta=ProviderTraceMeta(provider="openrouter", provider_generation_id="gen-cut"),
            )
            # No usage / response_end -- mirrors a cancellation before final accounting.

        adapter._client = MagicMock(stream=_fake_stream)  # type: ignore[assignment]

        chunks = [
            c
            async for c in adapter.create_streaming_completion(
                {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 100},
                request_id="req-cancel",
            )
        ]
        carrier = [c for c in chunks if "_provider_meta" in c]
        assert len(carrier) == 1
        assert carrier[0]["_provider_meta"]["provider_generation_id"] == "gen-cut"


# ---------------------------------------------------------------------------
# User-Agent forwarding tests
# ---------------------------------------------------------------------------


class TestSanitizeHeaderValue:
    """Tests for header injection prevention via control char stripping."""

    def test_clean_value_unchanged(self) -> None:
        assert _sanitize_header_value("claude-code/2.1.0") == "claude-code/2.1.0"

    def test_strips_crlf(self) -> None:
        assert _sanitize_header_value("bad\r\nheader") == "badheader"

    def test_strips_null_bytes(self) -> None:
        assert _sanitize_header_value("bad\x00header") == "badheader"

    def test_strips_all_ascii_control_chars(self) -> None:
        """All C0 controls (0x01-0x1F) and DEL (0x7F) are stripped."""
        # Tab, bell, escape, DEL
        assert _sanitize_header_value("a\tb\x07c\x1bd\x7fe") == "abcde"

    def test_preserves_non_ascii(self) -> None:
        """Non-ASCII chars (e.g., UTF-8 accented letters) are preserved."""
        assert _sanitize_header_value("café") == "café"

    def test_caps_length(self) -> None:
        long = "x" * 500
        assert len(_sanitize_header_value(long)) == 256

    def test_custom_max_length(self) -> None:
        assert _sanitize_header_value("abcdef", max_length=3) == "abc"


@pytest.mark.asyncio
async def test_create_completion_forwards_user_agent() -> None:
    """User-Agent from _user_agent metadata flows to extra_headers in hyperparams."""
    adapter = _make_adapter_with_mock_client()
    mock_complete = AsyncMock(
        return_value=CompletionResponse(
            text="ok",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
    )
    adapter._client = MagicMock(complete=mock_complete)  # type: ignore[assignment]

    await adapter.create_completion(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 100,
            "_user_agent": "claude-code/2.1.0",
        },
        request_id="req-ua",
    )

    # Verify the hyperparams passed to core.llm include extra_headers
    call_kwargs = mock_complete.call_args
    hyperparams = call_kwargs.kwargs.get("hyperparams") or call_kwargs[1].get("hyperparams")
    assert hyperparams is not None
    assert hyperparams.extra["openai"]["extra_headers"] == {"User-Agent": "claude-code/2.1.0"}


@pytest.mark.asyncio
async def test_create_completion_no_user_agent_no_extra_headers() -> None:
    """Without _user_agent, extra should be empty (no extra_headers injected)."""
    adapter = _make_adapter_with_mock_client()
    mock_complete = AsyncMock(
        return_value=CompletionResponse(
            text="ok",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
    )
    adapter._client = MagicMock(complete=mock_complete)  # type: ignore[assignment]

    await adapter.create_completion(
        {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 100},
        request_id="req-no-ua",
    )

    call_kwargs = mock_complete.call_args
    hyperparams = call_kwargs.kwargs.get("hyperparams") or call_kwargs[1].get("hyperparams")
    assert hyperparams is not None
    assert hyperparams.extra == {}


@pytest.mark.asyncio
async def test_streaming_completion_forwards_user_agent() -> None:
    """User-Agent forwarding also works on the streaming path."""
    adapter = _make_adapter_with_mock_client()

    captured_hyperparams = []

    async def _fake_stream(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured_hyperparams.append(kwargs.get("hyperparams"))
        yield StreamEvent(type="text_delta", text="Hi")
        yield StreamEvent(type="response_end")

    adapter._client = MagicMock(stream=_fake_stream)  # type: ignore[assignment]

    chunks = []
    async for chunk in adapter.create_streaming_completion(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 100,
            "_user_agent": "claude-code/2.1.0",
        },
        request_id="req-stream-ua",
    ):
        chunks.append(chunk)

    assert len(captured_hyperparams) == 1
    hp = captured_hyperparams[0]
    assert hp.extra["openai"]["extra_headers"] == {"User-Agent": "claude-code/2.1.0"}


# ---------------------------------------------------------------------------
# _forge_user -> extra["openai"]["user"] forwarding (provider-user grouping)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_completion_forwards_forge_user() -> None:
    """`_forge_user` from the server flows to extra["openai"]["user"]."""
    adapter = _make_adapter_with_mock_client()
    mock_complete = AsyncMock(
        return_value=CompletionResponse(
            text="ok", usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        )
    )
    adapter._client = MagicMock(complete=mock_complete)  # type: ignore[assignment]

    await adapter.create_completion(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 100,
            "_forge_user": "forge_sess_7e81a1bb765d_supervisor",
        },
        request_id="req-fu",
    )

    call_kwargs = mock_complete.call_args
    hp = call_kwargs.kwargs.get("hyperparams") or call_kwargs[1].get("hyperparams")
    assert hp is not None
    assert hp.extra["openai"]["user"] == "forge_sess_7e81a1bb765d_supervisor"


@pytest.mark.asyncio
async def test_streaming_completion_forwards_forge_user() -> None:
    """`_forge_user` forwarding also works on the streaming path."""
    adapter = _make_adapter_with_mock_client()
    captured_hyperparams = []

    async def _fake_stream(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured_hyperparams.append(kwargs.get("hyperparams"))
        yield StreamEvent(type="text_delta", text="Hi")
        yield StreamEvent(type="response_end")

    adapter._client = MagicMock(stream=_fake_stream)  # type: ignore[assignment]

    async for _chunk in adapter.create_streaming_completion(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 100,
            "_forge_user": "forge_run_7e81a1bb765d",
        },
        request_id="req-stream-fu",
    ):
        pass

    assert len(captured_hyperparams) == 1
    assert captured_hyperparams[0].extra["openai"]["user"] == "forge_run_7e81a1bb765d"


@pytest.mark.asyncio
async def test_create_completion_forge_user_coexists_with_user_agent() -> None:
    """`_forge_user` and `_user_agent` share the extra["openai"] dict without clobbering."""
    adapter = _make_adapter_with_mock_client()
    mock_complete = AsyncMock(
        return_value=CompletionResponse(
            text="ok", usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        )
    )
    adapter._client = MagicMock(complete=mock_complete)  # type: ignore[assignment]

    await adapter.create_completion(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 100,
            "_user_agent": "claude-code/2.1.0",
            "_forge_user": "forge_sess_7e81a1bb765d_supervisor",
        },
        request_id="req-both",
    )

    call_kwargs = mock_complete.call_args
    hp = call_kwargs.kwargs.get("hyperparams") or call_kwargs[1].get("hyperparams")
    assert hp.extra["openai"]["extra_headers"] == {"User-Agent": "claude-code/2.1.0"}
    assert hp.extra["openai"]["user"] == "forge_sess_7e81a1bb765d_supervisor"


@pytest.mark.asyncio
async def test_create_completion_no_forge_user_no_user_key() -> None:
    """Without `_forge_user`, no `user` key is injected (flag-off path is byte-identical)."""
    adapter = _make_adapter_with_mock_client()
    mock_complete = AsyncMock(
        return_value=CompletionResponse(
            text="ok", usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        )
    )
    adapter._client = MagicMock(complete=mock_complete)  # type: ignore[assignment]

    await adapter.create_completion(
        {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 100, "_user_agent": "claude-code/2.1.0"},
        request_id="req-no-fu",
    )

    call_kwargs = mock_complete.call_args
    hp = call_kwargs.kwargs.get("hyperparams") or call_kwargs[1].get("hyperparams")
    assert "user" not in hp.extra["openai"]


# ---------------------------------------------------------------------------
# cached_tokens propagation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_core_response_includes_cached_tokens() -> None:
    """_core_response_to_openai must propagate cached_tokens from core.llm response."""
    adapter = _make_adapter_with_mock_client()
    adapter._client = MagicMock(  # type: ignore[assignment]
        complete=AsyncMock(
            return_value=CompletionResponse(
                text="Hi",
                usage={
                    "prompt_tokens": 1000,
                    "completion_tokens": 50,
                    "total_tokens": 1050,
                    "cached_tokens": 600,
                },
            )
        )
    )

    result = await adapter.create_completion(
        {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 100},
        request_id="req-cached",
    )

    assert result["usage"]["cached_tokens"] == 600


@pytest.mark.asyncio
async def test_core_response_cached_tokens_zero_when_absent() -> None:
    """cached_tokens defaults to 0 when not present in core.llm response."""
    adapter = _make_adapter_with_mock_client()
    adapter._client = MagicMock(  # type: ignore[assignment]
        complete=AsyncMock(
            return_value=CompletionResponse(
                text="Hi",
                usage={"prompt_tokens": 500, "completion_tokens": 50, "total_tokens": 550},
            )
        )
    )

    result = await adapter.create_completion(
        {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 100},
        request_id="req-no-cache",
    )

    assert result["usage"]["cached_tokens"] == 0


@pytest.mark.asyncio
async def test_streaming_usage_chunk_includes_cached_tokens() -> None:
    """Streaming usage chunks must propagate cached_tokens from core.llm events."""
    adapter = _make_adapter_with_mock_client()

    async def _fake_stream(*args, **kwargs):  # type: ignore[no-untyped-def]
        yield StreamEvent(type="text_delta", text="Hi")
        yield StreamEvent(
            type="usage",
            usage={
                "prompt_tokens": 2000,
                "completion_tokens": 100,
                "total_tokens": 2100,
                "cached_tokens": 1500,
            },
        )
        yield StreamEvent(type="response_end")

    adapter._client = MagicMock(stream=_fake_stream)  # type: ignore[assignment]

    usage_chunks = []
    async for chunk in adapter.create_streaming_completion(
        {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 100},
        request_id="req-stream-cached",
    ):
        if chunk.get("usage"):
            usage_chunks.append(chunk["usage"])

    assert len(usage_chunks) == 1
    assert usage_chunks[0]["cached_tokens"] == 1500


@pytest.mark.asyncio
async def test_user_agent_sanitized_before_forwarding() -> None:
    """Malicious User-Agent values are sanitized (CRLF stripped)."""
    adapter = _make_adapter_with_mock_client()
    mock_complete = AsyncMock(
        return_value=CompletionResponse(
            text="ok",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
    )
    adapter._client = MagicMock(complete=mock_complete)  # type: ignore[assignment]

    await adapter.create_completion(
        {
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 100,
            "_user_agent": "evil\r\nX-Injected: true",
        },
        request_id="req-evil",
    )

    call_kwargs = mock_complete.call_args
    hyperparams = call_kwargs.kwargs.get("hyperparams") or call_kwargs[1].get("hyperparams")
    forwarded_ua = hyperparams.extra["openai"]["extra_headers"]["User-Agent"]
    assert "\r" not in forwarded_ua
    assert "\n" not in forwarded_ua
    assert forwarded_ua == "evilX-Injected: true"

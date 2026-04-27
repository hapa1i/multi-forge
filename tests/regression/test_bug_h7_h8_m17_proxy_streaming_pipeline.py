"""Regression tests for proxy streaming pipeline bug fixes (H7, H8, M17).

H7: Tool-call index must be stable (id → ordinal mapping, not dict size).
    Bug: len(accumulated_tool_calls) - 1 used as index, causing multi-tool
    interleave corruption. Fix: tool_call_indices dict for stable id→ordinal.
H8: Error chunks must be dicts (not raw SSE strings).
    Bug: server.py yielded raw SSE text into dict pipeline; converter skipped
    non-dicts silently. Fix: yield dict error chunks, converter maps to SSE.
M17: Text after tool_result must not be silently dropped.
    Bug: is_tool_response_message=True skipped final message assembly.
    Fix: flush content_list after tool_result loop.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from forge.proxy.converters import (
    convert_anthropic_to_openai,
    convert_openai_to_anthropic_sse,
)
from forge.proxy.data_models import (
    ContentBlockText,
    ContentBlockToolResult,
    Message,
    MessagesRequest,
)

pytestmark = pytest.mark.regression

# =============================================================================
# H7: Stable Tool-Call Index
# =============================================================================


class TestToolCallIndexStability:
    """Verify tool-call indices are stable across interleaved chunks."""

    @pytest.fixture
    def adapter(self):
        """Create a CoreLLMClientAdapter with mocked client."""
        from forge.proxy.client_adapter import CoreLLMClientAdapter

        adapter = CoreLLMClientAdapter.__new__(CoreLLMClientAdapter)
        adapter.model_name = "claude-sonnet-4"
        adapter._provider = "litellm_local"
        adapter._client = AsyncMock()
        return adapter

    def _make_tool_call_event(self, tool_id: str | None, name: str | None, args: str, *, index: int = 0):
        """Create a mock StreamEvent for a tool_call_delta."""
        from forge.core.llm.types import StreamEvent, ToolCallDelta

        delta = ToolCallDelta(index=index, id=tool_id, name=name, arguments_json=args)
        return StreamEvent(type="tool_call_delta", tool_call_delta=delta)

    @pytest.mark.asyncio
    async def test_interleaved_tool_calls_have_stable_indices(self, adapter):
        """Two tool calls interleaving arguments maintain stable indices."""
        from forge.core.llm.types import StreamEvent

        events = [
            # Tool A starts (index 0)
            self._make_tool_call_event("call_A", "read_file", '{"path":', index=0),
            # Tool B starts (index 1)
            self._make_tool_call_event("call_B", "write_file", '{"path":', index=1),
            # Tool A gets more args (no id — real OpenAI behavior)
            self._make_tool_call_event(None, None, '"/foo"}', index=0),
            # Tool B gets more args (no id)
            self._make_tool_call_event(None, None, '"/bar"}', index=1),
            # End
            StreamEvent(type="response_end"),
        ]

        async def mock_stream(*args, **kwargs):
            for e in events:
                yield e

        adapter._client.stream = mock_stream

        chunks = []
        openai_request = {
            "model": "claude-sonnet-4",
            "messages": [{"role": "user", "content": "test"}],
        }
        async for chunk in adapter.create_streaming_completion(openai_request, "req-1"):
            if "choices" in chunk:
                delta = chunk["choices"][0].get("delta", {})
                if "tool_calls" in delta:
                    tc = delta["tool_calls"][0]
                    chunks.append({"id": tc.get("id"), "index": tc["index"]})

        # Tool A should always be index 0, Tool B always index 1
        assert chunks[0] == {"id": "call_A", "index": 0}
        assert chunks[1] == {"id": "call_B", "index": 1}
        assert chunks[2] == {"id": None, "index": 0}  # Tool A continuation
        assert chunks[3] == {"id": None, "index": 1}  # Tool B continuation

    @pytest.mark.asyncio
    async def test_sequential_tool_calls_get_correct_indices(self, adapter):
        """Sequential (non-interleaved) tool calls get indices 0, 1, 2..."""
        from forge.core.llm.types import StreamEvent

        events = [
            self._make_tool_call_event("call_X", "tool_x", '{"a": 1}', index=0),
            self._make_tool_call_event("call_Y", "tool_y", '{"b": 2}', index=1),
            self._make_tool_call_event("call_Z", "tool_z", '{"c": 3}', index=2),
            StreamEvent(type="response_end"),
        ]

        async def mock_stream(*args, **kwargs):
            for e in events:
                yield e

        adapter._client.stream = mock_stream

        indices = []
        openai_request = {
            "model": "claude-sonnet-4",
            "messages": [{"role": "user", "content": "test"}],
        }
        async for chunk in adapter.create_streaming_completion(openai_request, "req-2"):
            if "choices" in chunk:
                delta = chunk["choices"][0].get("delta", {})
                if "tool_calls" in delta:
                    indices.append(delta["tool_calls"][0]["index"])

        assert indices == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_single_tool_call_always_index_zero(self, adapter):
        """Single tool call with multiple chunks is always index 0."""
        from forge.core.llm.types import StreamEvent

        events = [
            self._make_tool_call_event("call_only", "my_tool", '{"key":', index=0),
            self._make_tool_call_event(None, None, '"value"}', index=0),
            StreamEvent(type="response_end"),
        ]

        async def mock_stream(*args, **kwargs):
            for e in events:
                yield e

        adapter._client.stream = mock_stream

        indices = []
        openai_request = {
            "model": "claude-sonnet-4",
            "messages": [{"role": "user", "content": "test"}],
        }
        async for chunk in adapter.create_streaming_completion(openai_request, "req-3"):
            if "choices" in chunk:
                delta = chunk["choices"][0].get("delta", {})
                if "tool_calls" in delta:
                    indices.append(delta["tool_calls"][0]["index"])

        assert indices == [0, 0]


# =============================================================================
# H8: Error Chunks as Dicts
# =============================================================================


class TestStreamingErrorFormat:
    """Verify error chunks are dicts and converter handles them."""

    @pytest.mark.asyncio
    async def test_converter_handles_error_dict_chunk(self):
        """Converter maps error dict to proper Anthropic event: error SSE."""

        async def error_stream():
            yield {"error": {"type": "overloaded_error", "message": "Service overloaded"}}

        request = MessagesRequest(
            model="claude-sonnet-4",
            messages=[Message(role="user", content="test")],
            max_tokens=100,
        )

        events = []
        async for event in convert_openai_to_anthropic_sse(error_stream(), request, "req-err"):
            events.append(event)

        # Should have message_start, then error event
        error_events = [e for e in events if "event: error" in e]
        assert len(error_events) == 1

        # Parse the error SSE
        error_line = error_events[0]
        data_line = [line for line in error_line.split("\n") if line.startswith("data: ")][0]
        error_data = json.loads(data_line[6:])  # Strip "data: " prefix
        assert error_data["type"] == "error"
        assert error_data["error"]["type"] == "overloaded_error"
        assert error_data["error"]["message"] == "Service overloaded"

    @pytest.mark.asyncio
    async def test_stream_terminates_after_error(self):
        """No more chunks after error event."""

        async def error_then_data_stream():
            yield {"error": {"type": "api_error", "message": "fail"}}
            yield {
                "choices": [{"delta": {"content": "should not appear"}, "finish_reason": None}],
            }

        request = MessagesRequest(
            model="claude-sonnet-4",
            messages=[Message(role="user", content="test")],
            max_tokens=100,
        )

        events = []
        async for event in convert_openai_to_anthropic_sse(error_then_data_stream(), request, "req-term"):
            events.append(event)

        # Should have message_start + error only, no content_block events
        content_events = [e for e in events if "content_block_delta" in e]
        assert len(content_events) == 0

    @pytest.mark.asyncio
    async def test_error_without_type_defaults_to_api_error(self):
        """Error chunk without explicit type defaults to api_error."""

        async def minimal_error_stream():
            yield {"error": {"message": "Something went wrong"}}

        request = MessagesRequest(
            model="claude-sonnet-4",
            messages=[Message(role="user", content="test")],
            max_tokens=100,
        )

        events = []
        async for event in convert_openai_to_anthropic_sse(minimal_error_stream(), request, "req-def"):
            events.append(event)

        error_events = [e for e in events if "event: error" in e]
        assert len(error_events) == 1
        data_line = [line for line in error_events[0].split("\n") if line.startswith("data: ")][0]
        error_data = json.loads(data_line[6:])
        assert error_data["error"]["type"] == "api_error"


# =============================================================================
# M17: Text After Tool Result
# =============================================================================


class TestTextAfterToolResult:
    """Verify text content after tool_result blocks is preserved."""

    def _make_request(self, messages: list[Message]) -> MessagesRequest:
        return MessagesRequest(
            model="claude-sonnet-4",
            messages=messages,
            max_tokens=100,
        )

    def test_text_after_tool_result_preserved(self):
        """[tool_result, text] → text not dropped."""
        request = self._make_request(
            [
                Message(
                    role="user",
                    content=[
                        ContentBlockToolResult(
                            type="tool_result",
                            tool_use_id="toolu_1",
                            content="result data",
                        ),
                        ContentBlockText(type="text", text="Now do the next step"),
                    ],
                ),
            ]
        )

        result = convert_anthropic_to_openai(request)
        messages = result["messages"]

        # Should have: tool message + user message with trailing text
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        user_msgs = [m for m in messages if m["role"] == "user"]

        assert len(tool_msgs) == 1
        assert tool_msgs[0]["content"] == "result data"
        assert len(user_msgs) == 1
        assert "Now do the next step" in str(user_msgs[0]["content"])

    def test_text_before_and_after_tool_result(self):
        """[text_A, tool_result, text_B] → 3 messages in correct order."""
        request = self._make_request(
            [
                Message(
                    role="user",
                    content=[
                        ContentBlockText(type="text", text="Before tool"),
                        ContentBlockToolResult(
                            type="tool_result",
                            tool_use_id="toolu_2",
                            content="tool output",
                        ),
                        ContentBlockText(type="text", text="After tool"),
                    ],
                ),
            ]
        )

        result = convert_anthropic_to_openai(request)
        messages = result["messages"]

        # Should have: user("Before tool") → tool(result) → user("After tool")
        assert len(messages) >= 3

        # Find the messages in order
        roles = [m["role"] for m in messages]
        assert roles == ["user", "tool", "user"]

        # Verify content
        assert "Before tool" in str(messages[0]["content"])
        assert messages[1]["content"] == "tool output"
        assert "After tool" in str(messages[2]["content"])

    def test_multiple_tool_results_with_trailing_text(self):
        """[tool_result, tool_result, text] → trailing text preserved."""
        request = self._make_request(
            [
                Message(
                    role="user",
                    content=[
                        ContentBlockToolResult(
                            type="tool_result",
                            tool_use_id="toolu_3a",
                            content="result A",
                        ),
                        ContentBlockToolResult(
                            type="tool_result",
                            tool_use_id="toolu_3b",
                            content="result B",
                        ),
                        ContentBlockText(type="text", text="Please continue"),
                    ],
                ),
            ]
        )

        result = convert_anthropic_to_openai(request)
        messages = result["messages"]

        tool_msgs = [m for m in messages if m["role"] == "tool"]
        user_msgs = [m for m in messages if m["role"] == "user"]

        assert len(tool_msgs) == 2
        assert len(user_msgs) == 1
        assert "Please continue" in str(user_msgs[0]["content"])

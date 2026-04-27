"""Regression: thinking blocks in --resume history cause 422 on proxy.

Bug: Forking from a direct Anthropic session (with thinking blocks) to a proxy
session fails with 422 because ContentBlock union doesn't include thinking/
redacted_thinking types.  Pydantic rejects the request before converters run.

Root cause: data_models.ContentBlock was missing ContentBlockThinking and
ContentBlockRedactedThinking.  converters.convert_anthropic_to_openai had no
handler for thinking blocks (moot since validation failed first).

Affected: src/forge/proxy/data_models.py, src/forge/proxy/converters.py
"""

import pytest

from forge.proxy.converters import convert_anthropic_to_openai
from forge.proxy.data_models import (
    ContentBlockRedactedThinking,
    ContentBlockText,
    ContentBlockThinking,
    ContentBlockToolResult,
    ContentBlockToolUse,
    Message,
    MessagesRequest,
)

pytestmark = pytest.mark.regression


def _request_with_thinking() -> MessagesRequest:
    """Mimic a --resume --fork-session request containing thinking history."""
    return MessagesRequest(
        model="claude-3-5-sonnet",
        messages=[
            Message(role="user", content="What's the status?"),
            Message(
                role="assistant",
                content=[
                    ContentBlockThinking(
                        type="thinking",
                        thinking="Let me check the codebase...",
                        signature="Ep0DClkIDBgC...",
                    ),
                    ContentBlockText(type="text", text="Here's the summary."),
                ],
            ),
            Message(role="user", content="Fork and continue"),
        ],
        max_tokens=4096,
    )


def test_thinking_blocks_accepted_by_pydantic():
    """MessagesRequest validates messages with thinking blocks (was 422)."""
    req = _request_with_thinking()
    assert len(req.messages) == 3
    assert len(req.messages[1].content) == 2  # type: ignore[arg-type]


def test_thinking_blocks_stripped_in_conversion():
    """Thinking blocks are stripped when converting to OpenAI format."""
    req = _request_with_thinking()
    result = convert_anthropic_to_openai(req)
    openai_messages = result["messages"]

    assistant_msgs = [m for m in openai_messages if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0]["content"] == "Here's the summary."


def test_redacted_thinking_blocks_accepted():
    """Redacted thinking blocks (opaque continuity tokens) are accepted."""
    req = MessagesRequest(
        model="claude-3-5-sonnet",
        messages=[
            Message(role="user", content="Hello"),
            Message(
                role="assistant",
                content=[
                    ContentBlockRedactedThinking(type="redacted_thinking", data="opaque-base64-data"),
                    ContentBlockText(type="text", text="Response"),
                ],
            ),
        ],
        max_tokens=1024,
    )
    result = convert_anthropic_to_openai(req)
    assistant_msgs = [m for m in result["messages"] if m["role"] == "assistant"]
    assert assistant_msgs[0]["content"] == "Response"


def test_thinking_only_assistant_message():
    """Assistant message with only thinking blocks gets empty content."""
    req = MessagesRequest(
        model="claude-3-5-sonnet",
        messages=[
            Message(role="user", content="Think about it"),
            Message(
                role="assistant",
                content=[
                    ContentBlockThinking(type="thinking", thinking="deep thoughts", signature="sig"),
                ],
            ),
            Message(role="user", content="What did you conclude?"),
        ],
        max_tokens=1024,
    )
    result = convert_anthropic_to_openai(req)
    assistant_msgs = [m for m in result["messages"] if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0]["content"] == ""


def test_thinking_stripped_but_tool_use_survives():
    """Thinking + tool_use in same message: thinking stripped, tool call kept."""
    req = MessagesRequest(
        model="claude-3-5-sonnet",
        messages=[
            Message(role="user", content="Read the file"),
            Message(
                role="assistant",
                content=[
                    ContentBlockThinking(type="thinking", thinking="planning...", signature="sig"),
                    ContentBlockToolUse(
                        type="tool_use",
                        id="toolu_01",
                        name="Read",
                        input={"file_path": "/tmp/test.py"},
                    ),
                ],
            ),
            Message(
                role="user",
                content=[
                    ContentBlockToolResult(
                        type="tool_result",
                        tool_use_id="toolu_01",
                        content="file contents here",
                    )
                ],
            ),
        ],
        max_tokens=1024,
    )
    result = convert_anthropic_to_openai(req)
    assistant_msgs = [m for m in result["messages"] if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1
    assert "tool_calls" in assistant_msgs[0]
    assert assistant_msgs[0]["tool_calls"][0]["function"]["name"] == "Read"


def test_text_ordering_preserved_around_thinking():
    """text/thinking/text: both text blocks survive in order, thinking stripped."""
    req = MessagesRequest(
        model="claude-3-5-sonnet",
        messages=[
            Message(role="user", content="Explain"),
            Message(
                role="assistant",
                content=[
                    ContentBlockText(type="text", text="First part."),
                    ContentBlockThinking(type="thinking", thinking="hmm...", signature="sig"),
                    ContentBlockText(type="text", text="Second part."),
                ],
            ),
        ],
        max_tokens=1024,
    )
    result = convert_anthropic_to_openai(req)
    assistant_msgs = [m for m in result["messages"] if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1
    content = assistant_msgs[0]["content"]
    assert isinstance(content, list)
    texts = [c["text"] for c in content]
    assert texts == ["First part.", "Second part."]

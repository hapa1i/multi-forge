"""Tests for prompt caching / cache_control support in the proxy.

Verifies that cache_control directives reach explicit-marker (Anthropic) backends and are
stripped for other backends, decided by the resolved backend's catalog mechanism; that
content simplification doesn't erase them; and that Claude Code's mid-conversation system
messages travel as user-role reminders.
"""

from __future__ import annotations

import pytest

from forge.proxy.converters import (
    _model_supports_cache_control,
    convert_anthropic_to_openai,
)
from forge.proxy.data_models import (
    CacheControl,
    ContentBlockText,
    Message,
    MessagesRequest,
    SystemContent,
)
from tests.fixtures.claude_code_requests import (
    ENVIRONMENT,
    MARKER,
    claude_code_tool_loop,
    message_markers,
)


class TestModelSupportsCacheControl:
    """Test _model_supports_cache_control() detection."""

    def test_anthropic_model(self) -> None:
        assert _model_supports_cache_control("anthropic/claude-3-opus") is True

    def test_claude_model(self) -> None:
        assert _model_supports_cache_control("claude-3-5-sonnet") is True

    def test_bedrock_anthropic(self) -> None:
        assert _model_supports_cache_control("bedrock/anthropic.claude-3") is True

    def test_gemini_model(self) -> None:
        assert _model_supports_cache_control("gemini/gemini-3-pro") is False

    def test_openai_model(self) -> None:
        assert _model_supports_cache_control("openai/gpt-5") is False

    def test_empty_string(self) -> None:
        assert _model_supports_cache_control("") is False

    def test_none_model(self) -> None:
        assert _model_supports_cache_control(None) is False

    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            ("anthropic/claude-opus-5.5", True),
            ("google/gemini-4-argon", False),
            ("google/gemini-3.8-flash", False),
            ("moonshotai/kimi-k3", False),
            ("openai/gpt-6-astra", False),
        ],
    )
    def test_catalog_mechanism_decides(self, model: str, expected: bool) -> None:
        assert _model_supports_cache_control(model) is expected


class TestPydanticCacheControlParsing:
    """Test that Pydantic models correctly parse cache_control fields."""

    def test_content_block_text_with_cache_control(self) -> None:
        block = ContentBlockText(type="text", text="hello", cache_control=CacheControl(type="ephemeral"))
        assert block.cache_control is not None
        assert block.cache_control.type == "ephemeral"

    def test_content_block_text_without_cache_control(self) -> None:
        block = ContentBlockText(type="text", text="hello")
        assert block.cache_control is None

    def test_system_content_with_cache_control(self) -> None:
        block = SystemContent(type="text", text="system prompt", cache_control=CacheControl())
        assert block.cache_control is not None

    def test_message_with_cache_control_blocks(self) -> None:
        """Ensure Pydantic union discriminator handles cache_control blocks."""
        msg = Message(
            role="user",
            content=[
                ContentBlockText(type="text", text="cached", cache_control=CacheControl()),
                ContentBlockText(type="text", text="not cached"),
            ],
        )
        blocks = msg.content
        assert isinstance(blocks, list)
        assert len(blocks) == 2
        first = blocks[0]
        second = blocks[1]
        assert isinstance(first, ContentBlockText)
        assert isinstance(second, ContentBlockText)
        assert first.cache_control is not None
        assert second.cache_control is None

    def test_cache_control_from_dict(self) -> None:
        """Ensure JSON dict input with cache_control parses correctly."""
        data = {
            "type": "text",
            "text": "hello",
            "cache_control": {"type": "ephemeral"},
        }
        block = ContentBlockText.model_validate(data)
        assert block.cache_control is not None
        assert block.cache_control.type == "ephemeral"


class TestMessageCacheControl:
    """Test cache_control preservation on message content blocks."""

    def _make_request(self, model: str, cache_control: bool = True) -> MessagesRequest:
        """Build a minimal MessagesRequest with optional cache_control."""
        cc = CacheControl() if cache_control else None
        return MessagesRequest(
            model=model,
            messages=[
                Message(
                    role="user",
                    content=[
                        ContentBlockText(type="text", text="hello", cache_control=cc),
                    ],
                )
            ],
            max_tokens=100,
        )

    def test_preserved_for_anthropic_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """cache_control on text block is preserved for Anthropic models."""
        # Bypass model mapping (it would fail for unknown model)
        monkeypatch.setattr(
            "forge.proxy.data_models.map_model_name",
            lambda v: "anthropic/claude-3-opus",
        )
        request = self._make_request("anthropic/claude-3-opus")
        result = convert_anthropic_to_openai(request, provider="litellm")

        # Find user message (skip system if present)
        user_msgs = [m for m in result["messages"] if m["role"] == "user"]
        assert len(user_msgs) == 1

        content = user_msgs[0]["content"]
        # Should be array format (not simplified to string) because cache_control is present
        assert isinstance(content, list), "Content should be array when cache_control present"
        assert content[0]["cache_control"] == {"type": "ephemeral"}

    def test_stripped_for_non_anthropic_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """cache_control on text block is stripped for non-Anthropic models."""
        monkeypatch.setattr("forge.proxy.data_models.map_model_name", lambda v: "gemini/gemini-3-pro")
        request = self._make_request("gemini/gemini-3-pro")
        result = convert_anthropic_to_openai(request, provider="litellm")

        user_msgs = [m for m in result["messages"] if m["role"] == "user"]
        assert len(user_msgs) == 1

        content = user_msgs[0]["content"]
        # Should be simplified to string (cache_control stripped → plain text)
        assert isinstance(content, str), "Content should be string when cache_control stripped"

    def test_no_cache_control_simplifies_to_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Text block without cache_control still simplifies to string (no regression)."""
        monkeypatch.setattr(
            "forge.proxy.data_models.map_model_name",
            lambda v: "anthropic/claude-3-opus",
        )
        request = self._make_request("anthropic/claude-3-opus", cache_control=False)
        result = convert_anthropic_to_openai(request, provider="litellm")

        user_msgs = [m for m in result["messages"] if m["role"] == "user"]
        content = user_msgs[0]["content"]
        assert isinstance(content, str), "Single text block without cache_control should simplify"


class TestSystemPromptCacheControl:
    """Test cache_control on system prompts."""

    def test_preserved_for_anthropic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """System prompt cache_control preserved for Anthropic models."""
        monkeypatch.setattr(
            "forge.proxy.data_models.map_model_name",
            lambda v: "anthropic/claude-3-opus",
        )
        request = MessagesRequest(
            model="anthropic/claude-3-opus",
            messages=[Message(role="user", content="hi")],
            system=[SystemContent(type="text", text="Be helpful.", cache_control=CacheControl())],
            max_tokens=100,
        )
        result = convert_anthropic_to_openai(request, provider="litellm")

        system_msgs = [m for m in result["messages"] if m["role"] == "system"]
        assert len(system_msgs) == 1

        content = system_msgs[0]["content"]
        assert isinstance(content, list), "System with cache_control should use array format"
        assert content[0]["cache_control"] == {"type": "ephemeral"}

    def test_stripped_for_non_anthropic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """System prompt cache_control stripped for non-Anthropic models."""
        monkeypatch.setattr("forge.proxy.data_models.map_model_name", lambda v: "gemini/gemini-3-pro")
        request = MessagesRequest(
            model="gemini/gemini-3-pro",
            messages=[Message(role="user", content="hi")],
            system=[SystemContent(type="text", text="Be helpful.", cache_control=CacheControl())],
            max_tokens=100,
        )
        result = convert_anthropic_to_openai(request, provider="litellm")

        system_msgs = [m for m in result["messages"] if m["role"] == "system"]
        assert len(system_msgs) == 1

        content = system_msgs[0]["content"]
        assert isinstance(content, str), "System without cache_control should be plain string"

    def test_system_string_no_regression(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """String system prompt (no blocks) still works as before."""
        monkeypatch.setattr(
            "forge.proxy.data_models.map_model_name",
            lambda v: "anthropic/claude-3-opus",
        )
        request = MessagesRequest(
            model="anthropic/claude-3-opus",
            messages=[Message(role="user", content="hi")],
            system="Be helpful.",
            max_tokens=100,
        )
        result = convert_anthropic_to_openai(request, provider="litellm")

        system_msgs = [m for m in result["messages"] if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0]["content"] == "Be helpful."


class TestCacheControlTtl:
    """Client marker fields beyond ``type`` survive translation."""

    def test_ttl_forwarded_for_claude_backend(self) -> None:
        request = MessagesRequest(
            model="claude-opus-5-5",
            messages=[Message(role="user", content="hi")],
            system=[SystemContent(type="text", text="Be helpful.", cache_control=CacheControl(ttl="1h"))],
            max_tokens=100,
        )
        result = convert_anthropic_to_openai(request, provider="openrouter", resolved_model="anthropic/claude-opus-5.5")

        assert result["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


class TestToolResultCacheControl:
    """Markers on tool results (other Anthropic clients' rolling breakpoint) are kept."""

    @staticmethod
    def _request(marker: dict) -> MessagesRequest:
        return MessagesRequest.model_validate(
            {
                "model": "claude-opus-5-5",
                "max_tokens": 64,
                "messages": [
                    {"role": "user", "content": "go"},
                    {
                        "role": "assistant",
                        "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "a"}}],
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": "t1", "content": "body", "cache_control": marker}
                        ],
                    },
                ],
            }
        )

    def test_marker_and_ttl_reach_claude_backend(self) -> None:
        marker = {"type": "ephemeral", "ttl": "1h"}
        result = convert_anthropic_to_openai(
            self._request(marker), provider="openrouter", resolved_model="anthropic/claude-haiku-4.5"
        )

        [tool] = [m for m in result["messages"] if m["role"] == "tool"]
        assert tool["content"] == [{"type": "text", "text": "body", "cache_control": marker}]

    def test_marker_stripped_for_gemini_backend(self) -> None:
        result = convert_anthropic_to_openai(
            self._request({"type": "ephemeral"}), provider="openrouter", resolved_model="google/gemini-4-argon"
        )

        [tool] = [m for m in result["messages"] if m["role"] == "tool"]
        assert tool["content"] == "body"


class TestMidConversationSystemReminders:
    """Claude Code's mid-conversation system messages travel as user-role reminders in place."""

    def test_claude_code_tool_loop_for_claude_backend(self) -> None:
        request = claude_code_tool_loop("claude-opus-5-5", completed_tool_turns=1)
        result = convert_anthropic_to_openai(request, provider="openrouter", resolved_model="anthropic/claude-opus-5.5")

        messages = result["messages"]
        assert [m["role"] for m in messages] == ["system", "user", "user", "assistant", "tool", "user"]
        assert messages[2]["content"] == f"<system-reminder>\n{ENVIRONMENT}\n</system-reminder>"
        assert messages[-1]["content"] == [
            {
                "type": "text",
                "text": "<system-reminder>\n<total_tokens>997766 tokens left</total_tokens>\n</system-reminder>",
                "cache_control": MARKER,
            }
        ]
        assert message_markers(result) == [MARKER, MARKER]  # system prompt + rolling marker

    def test_leading_system_message_stays_system(self) -> None:
        request = MessagesRequest.model_validate(
            {
                "model": "claude-opus-5-5",
                "max_tokens": 64,
                "messages": [{"role": "system", "content": "Leading context."}, {"role": "user", "content": "hi"}],
            }
        )
        result = convert_anthropic_to_openai(request, provider="openrouter", resolved_model="google/gemini-4-argon")

        assert result["messages"][0] == {"role": "system", "content": "Leading context."}

    def test_existing_reminder_tag_not_double_wrapped(self) -> None:
        request = MessagesRequest.model_validate(
            {
                "model": "claude-opus-5-5",
                "max_tokens": 64,
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "system", "content": "<system-reminder>\nnote\n</system-reminder>"},
                ],
            }
        )
        result = convert_anthropic_to_openai(request, provider="openrouter", resolved_model="google/gemini-4-argon")

        assert result["messages"][-1] == {"role": "user", "content": "<system-reminder>\nnote\n</system-reminder>"}

"""Tests for canonical LLM types."""

import pytest
from pydantic import ValidationError

from forge.core.llm.types import (
    CompletionResponse,
    InjectionPoint,
    Message,
    ModelHyperparameters,
    PromptCachingConfig,
    StreamEvent,
    ThinkingConfig,
    ToolCall,
    ToolCallDelta,
)


class TestToolCall:
    """Tests for ToolCall type."""

    def test_create_basic(self):
        tc = ToolCall(id="tc_1", name="get_weather", arguments={"city": "NYC"})
        assert tc.id == "tc_1"
        assert tc.name == "get_weather"
        assert tc.arguments == {"city": "NYC"}

    def test_arguments_must_be_dict(self):
        with pytest.raises(ValidationError):
            ToolCall(id="tc_1", name="test", arguments="not a dict")  # type: ignore

    def test_serialization(self):
        tc = ToolCall(id="tc_1", name="search", arguments={"query": "test"})
        data = tc.model_dump()
        assert data == {"id": "tc_1", "name": "search", "arguments": {"query": "test"}}


class TestToolCallDelta:
    """Tests for ToolCallDelta type."""

    def test_create_partial(self):
        delta = ToolCallDelta(id="tc_1", name="search")
        assert delta.id == "tc_1"
        assert delta.name == "search"
        assert delta.arguments_json == ""

    def test_accumulate_json(self):
        delta = ToolCallDelta(id="tc_1")
        delta.arguments_json += '{"que'
        delta.arguments_json += 'ry": "test"}'
        assert delta.arguments_json == '{"query": "test"}'


class TestMessage:
    """Tests for Message type."""

    def test_user_message(self):
        msg = Message(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.tool_call_id is None
        assert msg.tool_calls is None

    def test_assistant_with_tool_calls(self):
        tc = ToolCall(id="tc_1", name="search", arguments={"q": "test"})
        msg = Message(role="assistant", content="", tool_calls=[tc])
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "search"

    def test_tool_result_message(self):
        msg = Message(role="tool", content="Result data", tool_call_id="tc_1")
        assert msg.role == "tool"
        assert msg.tool_call_id == "tc_1"

    def test_content_can_be_list(self):
        """Content can be a list of content blocks (multimodal)."""
        msg = Message(
            role="user",
            content=[
                {"type": "text", "text": "What's in this image?"},
                {"type": "image_url", "image_url": {"url": "http://..."}},
            ],
        )
        assert isinstance(msg.content, list)
        assert len(msg.content) == 2

    def test_invalid_role_rejected(self):
        with pytest.raises(ValidationError):
            Message(role="invalid", content="test")  # type: ignore


class TestModelHyperparameters:
    """Tests for ModelHyperparameters type."""

    def test_defaults(self):
        params = ModelHyperparameters()
        assert params.max_tokens == 4096
        assert params.temperature is None
        assert params.reasoning_effort is None
        assert params.strict is False
        assert params.extra == {}

    def test_with_reasoning_effort(self):
        params = ModelHyperparameters(reasoning_effort="high")
        assert params.reasoning_effort == "high"

    def test_invalid_reasoning_effort_rejected(self):
        with pytest.raises(ValidationError):
            ModelHyperparameters(reasoning_effort="invalid")  # type: ignore

    def test_thinking_config(self):
        thinking = ThinkingConfig(type="enabled", budget_tokens=16384)
        params = ModelHyperparameters(thinking=thinking)
        assert params.thinking is not None
        assert params.thinking.budget_tokens == 16384

    def test_extra_namespace(self):
        params = ModelHyperparameters(extra={"openai": {"presence_penalty": 0.5}, "anthropic": {"top_k": 10}})
        assert params.extra["openai"]["presence_penalty"] == 0.5
        assert params.extra["anthropic"]["top_k"] == 10

    def test_temperature_valid_range(self):
        """Temperature must be between 0.0 and 2.0."""
        # Valid temperatures
        params = ModelHyperparameters(temperature=0.0)
        assert params.temperature == 0.0

        params = ModelHyperparameters(temperature=1.5)
        assert params.temperature == 1.5

        params = ModelHyperparameters(temperature=2.0)
        assert params.temperature == 2.0

    def test_temperature_out_of_range_rejected(self):
        """Temperature outside 0.0-2.0 is rejected."""
        with pytest.raises(ValidationError, match="temperature must be between"):
            ModelHyperparameters(temperature=2.5)

        with pytest.raises(ValidationError, match="temperature must be between"):
            ModelHyperparameters(temperature=-0.1)

    def test_top_p_valid_range(self):
        """top_p must be between 0.0 and 1.0."""
        params = ModelHyperparameters(top_p=0.0)
        assert params.top_p == 0.0

        params = ModelHyperparameters(top_p=0.9)
        assert params.top_p == 0.9

        params = ModelHyperparameters(top_p=1.0)
        assert params.top_p == 1.0

    def test_top_p_out_of_range_rejected(self):
        """top_p outside 0.0-1.0 is rejected."""
        with pytest.raises(ValidationError, match="top_p must be between"):
            ModelHyperparameters(top_p=1.5)

        with pytest.raises(ValidationError, match="top_p must be between"):
            ModelHyperparameters(top_p=-0.1)

    def test_max_tokens_must_be_positive(self):
        """max_tokens must be positive."""
        with pytest.raises(ValidationError, match="max_tokens must be positive"):
            ModelHyperparameters(max_tokens=0)

        with pytest.raises(ValidationError, match="max_tokens must be positive"):
            ModelHyperparameters(max_tokens=-100)

    def test_max_tokens_upper_bound(self):
        """max_tokens has an upper bound of 1M."""
        # Valid large value
        params = ModelHyperparameters(max_tokens=1_000_000)
        assert params.max_tokens == 1_000_000

        # Exceeds maximum
        with pytest.raises(ValidationError, match="max_tokens exceeds maximum"):
            ModelHyperparameters(max_tokens=1_000_001)

    def test_thinking_budget_must_be_positive_when_enabled(self):
        """ThinkingConfig budget_tokens must be positive when type=enabled."""
        with pytest.raises(ValidationError, match="budget_tokens must be positive"):
            ThinkingConfig(type="enabled", budget_tokens=0)

        with pytest.raises(ValidationError, match="budget_tokens must be positive"):
            ThinkingConfig(type="enabled", budget_tokens=-1)

        # Disabled thinking allows any budget (ignored)
        thinking = ThinkingConfig(type="disabled", budget_tokens=0)
        assert thinking.budget_tokens == 0

    def test_timeout_valid_range(self):
        """Timeout must be positive and not exceed 600s."""
        # Valid timeouts
        params = ModelHyperparameters(timeout=30)
        assert params.timeout == 30

        params = ModelHyperparameters(timeout=300)
        assert params.timeout == 300

        params = ModelHyperparameters(timeout=600)
        assert params.timeout == 600

    def test_timeout_out_of_range_rejected(self):
        """Timeout outside valid range is rejected."""
        with pytest.raises(ValidationError, match="timeout must be positive"):
            ModelHyperparameters(timeout=0)

        with pytest.raises(ValidationError, match="timeout must be positive"):
            ModelHyperparameters(timeout=-1)

        with pytest.raises(ValidationError, match="timeout exceeds maximum"):
            ModelHyperparameters(timeout=601)

    def test_prompt_caching_passthrough(self):
        """Prompt caching passthrough policy (default)."""
        config = PromptCachingConfig()
        assert config.policy == "passthrough"
        assert config.injection_points is None

    def test_prompt_caching_auto_inject(self):
        """Prompt caching auto_inject policy adds default injection points."""
        config = PromptCachingConfig(policy="auto_inject")
        assert config.policy == "auto_inject"
        # Should have default injection points for system messages
        assert config.injection_points is not None
        assert len(config.injection_points) == 1
        assert config.injection_points[0].role == "system"

    def test_prompt_caching_auto_inject_custom_points(self):
        """Prompt caching auto_inject with custom injection points."""
        config = PromptCachingConfig(
            policy="auto_inject",
            injection_points=[InjectionPoint(location="message", index=-1)],
        )
        assert config.policy == "auto_inject"
        assert config.injection_points is not None
        assert len(config.injection_points) == 1
        assert config.injection_points[0].index == -1

    def test_hyperparams_with_prompt_caching(self):
        """ModelHyperparameters can include prompt caching config."""
        caching = PromptCachingConfig(policy="auto_inject")
        params = ModelHyperparameters(timeout=120, prompt_caching=caching)
        assert params.timeout == 120
        assert params.prompt_caching is not None
        assert params.prompt_caching.policy == "auto_inject"

    def test_injection_point_typed(self):
        """InjectionPoint provides typed structure for cache control injection."""
        # By role
        point = InjectionPoint(role="system")
        assert point.location == "message"
        assert point.role == "system"
        assert point.index is None

        # By index
        point = InjectionPoint(index=-1)
        assert point.index == -1
        assert point.role is None


class TestCompletionResponse:
    """Tests for CompletionResponse type."""

    def test_basic_response(self):
        resp = CompletionResponse(text="Hello, world!")
        assert resp.text == "Hello, world!"
        assert resp.tool_calls is None
        assert resp.usage is None

    def test_with_usage(self):
        resp = CompletionResponse(
            text="Hi",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        assert resp.usage is not None
        assert resp.usage["total_tokens"] == 15

    def test_with_tool_calls(self):
        tc = ToolCall(id="tc_1", name="search", arguments={})
        resp = CompletionResponse(text="", tool_calls=[tc])
        assert resp.tool_calls is not None
        assert len(resp.tool_calls) == 1

    def test_cost_usd_defaults_none(self):
        """cost_usd is None unless the route reported a cost (None != $0)."""
        resp = CompletionResponse(text="hi")
        assert resp.cost_usd is None

    def test_cost_usd_carried(self):
        resp = CompletionResponse(text="hi", cost_usd=0.00234)
        assert resp.cost_usd == 0.00234


class TestStreamEvent:
    """Tests for StreamEvent type."""

    def test_text_delta(self):
        event = StreamEvent(type="text_delta", text="Hello")
        assert event.type == "text_delta"
        assert event.text == "Hello"

    def test_tool_call_delta(self):
        delta = ToolCallDelta(id="tc_1", name="search")
        event = StreamEvent(type="tool_call_delta", tool_call_delta=delta)
        assert event.type == "tool_call_delta"
        assert event.tool_call_delta is not None
        assert event.tool_call_delta.name == "search"

    def test_response_end(self):
        event = StreamEvent(
            type="response_end",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        assert event.type == "response_end"
        assert event.usage is not None

    def test_error_event(self):
        event = StreamEvent(type="error", error="Connection failed")
        assert event.type == "error"
        assert event.error == "Connection failed"

    def test_cost_usd_defaults_none(self):
        """Streaming cost carrier defaults to None (no cost reported)."""
        event = StreamEvent(type="usage", usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
        assert event.cost_usd is None

    def test_cost_usd_carried_on_final_event(self):
        event = StreamEvent(type="response_end", cost_usd=0.0019)
        assert event.cost_usd == 0.0019

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            StreamEvent(type="invalid")  # type: ignore

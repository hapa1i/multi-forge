"""Sonnet 5.5 thinking modes must retain budget and sampling restrictions."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from forge.config.schema import (
    ProxyInstanceConfig,
    TierModels,
    TierOverride,
    TierOverrides,
)
from forge.core.llm import Message, ModelHyperparameters
from forge.core.llm.clients.openai_compat import build_chat_completion_kwargs
from forge.proxy.intercept import ReasoningOverrideError, apply_override
from forge.proxy.reasoning import resolve_reasoning_effort

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("model", ["anthropic/claude-sonnet-5-5", "anthropic/claude-sonnet-5.5"])
def test_sonnet55_translated_requests_drop_sampling_after_provider_extras(model: str) -> None:
    params = ModelHyperparameters(
        temperature=0.7,
        top_p=0.9,
        reasoning_effort="xhigh",
        extra={"openai": {"extra_body": {"temperature": 0.5, "top_p": 0.8, "top_k": 42}}},
    )
    original = params.model_dump()

    body = build_chat_completion_kwargs(model, [Message(role="user", content="Hello")], None, params)

    assert not {"temperature", "top_p", "top_k"}.intersection(body)
    assert not {"temperature", "top_p", "top_k"}.intersection(body["extra_body"])
    assert body["reasoning_effort"] == "xhigh"
    assert params.model_dump() == original


def test_sonnet55_config_rejects_manual_budget() -> None:
    with pytest.raises(ValueError, match="thinking_budget_tokens is not supported"):
        ProxyInstanceConfig(
            proxy_format=1,
            template="test",
            template_digest="sha256:test",
            provider="litellm",
            proxy_endpoint="http://localhost:8084",
            port=8084,
            upstream_base_url="https://litellm.test.example.com",
            tiers=TierModels(sonnet="anthropic/claude-sonnet-5-5"),
            tier_overrides=TierOverrides(sonnet=TierOverride(thinking_budget_tokens=4096)),
        )


@pytest.mark.parametrize("thinking", [{"type": "enabled"}, {"type": "adaptive", "budget_tokens": 4096}])
def test_sonnet55_passthrough_rejects_manual_controls_before_mutation(thinking: dict) -> None:
    body = {
        "model": "claude-sonnet-5-5",
        "system": [{"type": "text", "text": "Original instructions"}],
        "thinking": thinking,
        "messages": [{"role": "user", "content": "Hello"}],
    }
    original = deepcopy(body)

    with pytest.raises(ReasoningOverrideError, match="manual thinking"):
        apply_override(body, system_prompt_augment="Extra instructions")

    assert body == original


def test_between_tools_maps_to_lowest_translated_effort() -> None:
    request = SimpleNamespace(reasoning_effort=None, thinking={"type": "between_tools"})

    assert (
        resolve_reasoning_effort(
            request, tier_override=None, model_id="anthropic/claude-sonnet-5-5", request_id="sonnet55"
        )
        == "low"
    )


@pytest.mark.parametrize("mode", ["adaptive", "between_tools"])
def test_native_thinking_mode_and_history_survive_override(mode: str) -> None:
    body = {
        "model": "claude-sonnet-5-5",
        "thinking": {"type": mode},
        "output_config": {"effort": "high"},
        "messages": [{"role": "assistant", "content": [{"type": "thinking", "signature": "signed", "thinking": ""}]}],
    }
    original = deepcopy(body)

    assert apply_override(body, reasoning_floor_effort="high").body == original

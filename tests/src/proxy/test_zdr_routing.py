"""Direct OpenRouter ZDR routing and transport tests."""

from __future__ import annotations

import pytest

from forge.config import load_config
from forge.core.llm.clients.base import merge_hyperparams
from forge.core.llm.clients.openai_compat import build_chat_completion_kwargs
from forge.core.llm.clients.openrouter import OpenRouterClient
from forge.core.llm.types import Message, ModelHyperparameters


def _factory_for(monkeypatch: pytest.MonkeyPatch, template: str):
    import forge.proxy.client_factory as client_factory_module

    loaded = load_config(template=template)
    monkeypatch.setattr(client_factory_module, "config", loaded)
    monkeypatch.setattr(client_factory_module.TierClientFactory, "_instance", None)
    return client_factory_module.TierClientFactory(), loaded


def test_openrouter_requires_zdr_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    factory, _ = _factory_for(monkeypatch, "openrouter-qwen")

    hyperparams = factory.get_default_hyperparams_for_tier(
        provider="openrouter",
        tier="sonnet",
        model_name="qwen/qwen3.8-27b",
    )

    assert hyperparams.extra == {"openai": {"extra_body": {"provider": {"zdr": True}}}}


def test_openrouter_explicit_non_zdr_opt_in_omits_request_requirement(monkeypatch: pytest.MonkeyPatch) -> None:
    factory, loaded = _factory_for(monkeypatch, "openrouter-qwen")
    loaded.proxy.openrouter.allow_non_zdr = True

    hyperparams = factory.get_default_hyperparams_for_tier(
        provider="openrouter",
        tier="opus",
        model_name="qwen/qwen3.8-max",
    )

    assert hyperparams.extra == {}


def test_litellm_has_no_zdr_transport_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    factory, _ = _factory_for(monkeypatch, "litellm-gemini")

    hyperparams = factory.get_default_hyperparams_for_tier(
        provider="litellm",
        tier="sonnet",
        model_name="gemini/gemini-3.1-pro-preview",
    )

    assert hyperparams.extra == {}


def test_zdr_survives_call_metadata_and_reasoning_translation(monkeypatch: pytest.MonkeyPatch) -> None:
    factory, _ = _factory_for(monkeypatch, "openrouter-glm")
    defaults = factory.get_default_hyperparams_for_tier(
        provider="openrouter",
        tier="opus",
        model_name="z-ai/glm-5.3",
    )
    call_time = ModelHyperparameters(
        reasoning_effort="max",
        extra={
            "openai": {
                "extra_headers": {"User-Agent": "claude-code/test"},
                "user": "forge_session_test",
            }
        },
    )

    merged = merge_hyperparams(defaults, call_time)
    kwargs = build_chat_completion_kwargs(
        "z-ai/glm-5.3",
        [Message(role="user", content="Reply with OK.")],
        None,
        merged,
    )
    translated = OpenRouterClient._translate_params(kwargs)

    assert translated["extra_body"] == {
        "provider": {"zdr": True},
        "reasoning": {"effort": "max"},
    }
    assert translated["extra_headers"] == {"User-Agent": "claude-code/test"}
    assert translated["user"] == "forge_session_test"

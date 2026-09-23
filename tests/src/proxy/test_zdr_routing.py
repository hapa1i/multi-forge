"""Direct OpenRouter ZDR routing and transport tests."""

from __future__ import annotations

import pytest

from forge.config import load_config
from forge.core.llm.clients.base import merge_hyperparams
from forge.core.llm.clients.openai_compat import build_chat_completion_kwargs
from forge.core.llm.clients.openrouter import OpenRouterClient
from forge.core.llm.types import Message, ModelHyperparameters
from forge.proxy.model_routes import effective_proxy_model_maps


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


def test_openrouter_explicit_non_zdr_opt_in_omits_request_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, loaded = _factory_for(monkeypatch, "openrouter-qwen")
    loaded.proxy.openrouter.allow_non_zdr = True

    hyperparams = factory.get_default_hyperparams_for_tier(
        provider="openrouter",
        tier="opus",
        model_name="qwen/qwen3.8-max",
    )

    assert hyperparams.extra == {}
    assert "extra" not in hyperparams.model_dump(exclude_unset=True)


@pytest.mark.parametrize("allow_non_zdr", [False, True])
def test_new_qwen_alternatives_resolve_without_rewriting_configured_models(
    allow_non_zdr: bool,
) -> None:
    loaded = load_config(template="openrouter-qwen")
    provider = loaded.proxy.openrouter
    provider.allow_non_zdr = allow_non_zdr

    _, alternatives = effective_proxy_model_maps(loaded.proxy)

    assert alternatives["opus"]["qwen3.8-flash"] == ("qwen/qwen3.8-flash" if allow_non_zdr else "qwen/qwen3.8-27b")
    assert alternatives["opus"]["qwen3.8-max-0902"] == (
        "qwen/qwen3.8-max-0902" if allow_non_zdr else "qwen/qwen3.8-2.4t-a95b"
    )
    assert provider.model_alternatives["opus"]["qwen3.8-flash"] == "qwen/qwen3.8-flash"
    assert provider.model_alternatives["opus"]["qwen3.8-max-0902"] == "qwen/qwen3.8-max-0902"


def test_litellm_has_no_zdr_transport_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    factory, _ = _factory_for(monkeypatch, "litellm-gemini")

    hyperparams = factory.get_default_hyperparams_for_tier(
        provider="litellm",
        tier="sonnet",
        model_name="gemini/gemini-3.1-pro-preview",
    )

    assert hyperparams.extra == {}
    assert "extra" not in hyperparams.model_dump(exclude_unset=True)


def test_zdr_survives_call_metadata_and_reasoning_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

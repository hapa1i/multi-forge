"""Regression coverage for bundled models without OpenRouter ZDR endpoints.

Without request-level enforcement and pre-dispatch replacements, old proxy
snapshots can either fail late or route without Forge making the privacy choice
explicit.
"""

from __future__ import annotations

import pytest

from forge.config import load_config
from forge.proxy.data_models import MessagesRequest

pytestmark = pytest.mark.regression


def test_qwen_max_defaults_to_zdr_fallback_and_request_enforcement(monkeypatch: pytest.MonkeyPatch) -> None:
    import forge.proxy.client_factory as client_factory_module
    import forge.proxy.server as server

    loaded = load_config(template="openrouter-qwen")
    # Simulate a proxy.yaml created before the fallback key shipped.
    loaded.proxy.openrouter.zdr_fallbacks = {}
    monkeypatch.setattr(client_factory_module, "config", loaded)
    monkeypatch.setattr(server, "config", loaded)
    monkeypatch.setattr(client_factory_module.TierClientFactory, "_instance", None)

    request = MessagesRequest(
        model="claude-opus-4-5-20251101",
        messages=[],
        max_tokens=1,
    )
    route = server._resolve_model_with_alternatives(request)
    hyperparams = client_factory_module.TierClientFactory().get_default_hyperparams_for_tier(
        provider="openrouter",
        tier="opus",
        model_name=route.model,
    )

    assert route.model == "qwen/qwen3.8-2.4t-a95b"
    assert hyperparams.extra == {"openai": {"extra_body": {"provider": {"zdr": True}}}}


def test_qwen_max_requires_explicit_non_zdr_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    import forge.proxy.client_factory as client_factory_module
    import forge.proxy.server as server

    loaded = load_config(template="openrouter-qwen")
    loaded.proxy.openrouter.allow_non_zdr = True
    monkeypatch.setattr(client_factory_module, "config", loaded)
    monkeypatch.setattr(server, "config", loaded)
    monkeypatch.setattr(client_factory_module.TierClientFactory, "_instance", None)

    assert server._model_for_zdr_policy("qwen/qwen3.8-max") == "qwen/qwen3.8-max"
    hyperparams = client_factory_module.TierClientFactory().get_default_hyperparams_for_tier(
        provider="openrouter",
        tier="opus",
        model_name="qwen/qwen3.8-max",
    )
    assert hyperparams.extra == {}


def test_old_qwen_flash_default_resolves_to_a_zdr_capable_model(monkeypatch: pytest.MonkeyPatch) -> None:
    import forge.proxy.server as server

    loaded = load_config(template="openrouter-qwen")
    loaded.proxy.openrouter.tiers.haiku = "qwen/qwen3.6-flash"
    loaded.proxy.openrouter.zdr_fallbacks = {}
    monkeypatch.setattr(server, "config", loaded)

    request = MessagesRequest(
        model="claude-haiku-4-5-20251001",
        messages=[],
        max_tokens=1,
    )

    assert server._resolve_model_with_alternatives(request).model == "qwen/qwen3.8-27b"

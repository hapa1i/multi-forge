"""Regression: proxy client construction requires explicit tier provenance."""

from __future__ import annotations

from typing import Any

import pytest

from forge.core.llm.types import ModelHyperparameters
from forge.proxy.client_factory import ModelProvider, TierClientFactory

pytestmark = pytest.mark.regression


@pytest.mark.asyncio
async def test_legacy_model_environment_cannot_supply_or_replace_client_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_name = "openai/gpt-5.5"
    monkeypatch.setattr(TierClientFactory, "_instance", None)
    monkeypatch.setenv("LITELLM_OPUS_MODEL", model_name)
    factory = TierClientFactory()
    monkeypatch.setattr(factory, "_detect_provider", lambda _model: ModelProvider.LITELLM)
    monkeypatch.setattr(
        factory,
        "_resolve_tier_hyperparams",
        lambda _provider, _tier, _model: ModelHyperparameters(),
    )

    captured: dict[str, Any] = {}

    class _FakeAdapter:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    factory._client_classes[ModelProvider.LITELLM] = _FakeAdapter

    with pytest.raises(TypeError):
        await factory.get_client(model_name)  # type: ignore[call-arg]

    client = await factory.get_client(model_name, tier="haiku")

    assert isinstance(client, _FakeAdapter)
    assert captured["tier"] == "haiku"
    assert (model_name, "haiku") in factory._cache
    assert (model_name, "opus") not in factory._cache

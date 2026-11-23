"""Tests for the tier client factory's authentication-refresh contract."""

from __future__ import annotations

from typing import Any

import pytest

from forge.core.llm.types import ModelHyperparameters
from forge.proxy.client_factory import ModelProvider, TierClientFactory

_MAX_TOKENS_BY_TIER = {"opus": 4096, "sonnet": 2048}


class _RecordingClient:
    """Adapter stand-in that keeps the arguments the factory built it with."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


@pytest.fixture
def recording_factory(monkeypatch: pytest.MonkeyPatch, tier_client_factory: TierClientFactory) -> TierClientFactory:
    """Factory that builds ``_RecordingClient`` adapters with tier-specific hyperparameters."""
    monkeypatch.setattr(tier_client_factory, "_client_classes", {ModelProvider.LITELLM: _RecordingClient})
    monkeypatch.setattr(tier_client_factory, "_import_client_class", lambda _provider: None)
    monkeypatch.setattr(
        tier_client_factory,
        "_resolve_tier_hyperparams",
        lambda _provider, tier, _model_name: ModelHyperparameters(max_tokens=_MAX_TOKENS_BY_TIER[tier]),
    )
    return tier_client_factory


@pytest.mark.asyncio
async def test_invalidate_and_retry_rebuilds_only_the_failed_entry(recording_factory: TierClientFactory) -> None:
    """A sibling tier and a second model keep their cached clients; the rebuild keeps the failed tier."""
    failed = await recording_factory.get_client("openai/gpt-5.5", tier="opus")
    sibling_tier = await recording_factory.get_client("openai/gpt-5.5", tier="sonnet")
    second_model = await recording_factory.get_client("openai/gpt-5.4", tier="opus")

    rebuilt = await recording_factory.invalidate_and_retry("openai/gpt-5.5", tier="opus")

    assert rebuilt is not failed
    assert rebuilt.kwargs["model"] == "openai/gpt-5.5"
    assert rebuilt.kwargs["tier"] == "opus"
    assert rebuilt.kwargs["default_hyperparams"].max_tokens == _MAX_TOKENS_BY_TIER["opus"]
    assert await recording_factory.get_client("openai/gpt-5.5", tier="opus") is rebuilt
    assert await recording_factory.get_client("openai/gpt-5.5", tier="sonnet") is sibling_tier
    assert await recording_factory.get_client("openai/gpt-5.4", tier="opus") is second_model

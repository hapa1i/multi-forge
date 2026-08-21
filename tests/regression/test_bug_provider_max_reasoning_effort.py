"""Regression coverage for provider-specific ``max`` reasoning effort.

GLM 5.3 advertises ``low/high/max`` through OpenRouter. The proxy validated the
catalog and resolved ``max`` correctly, but core.llm's transport model reused
the narrower tier-1 checker vocabulary and raised before provider dispatch.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from forge.config import load_config
from forge.core.llm.types import CompletionResponse
from forge.proxy.client_adapter import CoreLLMClientAdapter
from forge.proxy.client_factory import TierClientFactory

pytestmark = pytest.mark.regression


def test_glm_opus_default_hyperparameters_accept_provider_max(monkeypatch: pytest.MonkeyPatch) -> None:
    import forge.proxy.client_factory as client_factory_module

    monkeypatch.setattr(client_factory_module, "config", load_config(template="openrouter-glm"))
    monkeypatch.setattr(TierClientFactory, "_instance", None)

    hyperparams = TierClientFactory().get_default_hyperparams_for_tier(
        provider="openrouter",
        tier="opus",
        model_name="z-ai/glm-5.3",
    )

    assert hyperparams.reasoning_effort == "max"


@pytest.mark.asyncio
async def test_proxy_adapter_forwards_request_provider_max() -> None:
    adapter = CoreLLMClientAdapter(model="z-ai/glm-5.3", provider="openrouter")
    complete = AsyncMock(return_value=CompletionResponse(text="ok"))
    adapter._client = MagicMock(complete=complete)  # type: ignore[assignment]

    await adapter.create_completion(
        {
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "max_tokens": 64,
            "reasoning_effort": "max",
        },
        request_id="req-glm-max",
    )

    assert complete.await_args is not None
    assert complete.await_args.kwargs["hyperparams"].reasoning_effort == "max"

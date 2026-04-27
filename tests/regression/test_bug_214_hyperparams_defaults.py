"""Regression tests for proxy adapter hyperparameter merging.

2.1.4: Default (proxy-owned) hyperparameters must not be erased by request-time
missing fields.

In particular, call-time ModelHyperparameters must only include fields explicitly
set by the request; otherwise core.llm merge_hyperparams() will treat None as an
explicit override.
"""

from __future__ import annotations

from typing import Any

import pytest

from forge.core.llm.types import ModelHyperparameters
from forge.proxy.client_adapter import CoreLLMClientAdapter

pytestmark = pytest.mark.regression


@pytest.mark.asyncio
async def test_adapter_does_not_override_defaults_with_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StubClient:
        def __init__(self):
            self.seen_hyperparams: ModelHyperparameters | None = None

        async def complete(
            self,
            _messages: list[Any],
            *,
            tools: object | None = None,
            hyperparams: ModelHyperparameters | None = None,
        ):
            self.seen_hyperparams = hyperparams

            from forge.core.llm.types import CompletionResponse

            return CompletionResponse(text="ok")

    stub = _StubClient()

    # Avoid constructing a real core.llm client
    monkeypatch.setattr("forge.proxy.client_adapter.get_client", lambda *a, **k: stub)

    adapter = CoreLLMClientAdapter(
        model="openai/gpt-5.2",
        provider="litellm_remote",
        tier="sonnet",
        default_hyperparams=ModelHyperparameters(
            reasoning_effort="high",
            verbosity="low",
            temperature=1.0,
            max_tokens=1234,
        ),
    )

    await adapter.create_completion(
        openai_request={
            "messages": [{"role": "user", "content": "hi"}],
            # No temperature/reasoning/verbosity/max_tokens keys
        },
        request_id="test",
    )

    assert stub.seen_hyperparams is not None

    # The adapter should not inject missing fields as explicit overrides.
    assert stub.seen_hyperparams.model_dump(exclude_unset=True) == {}

    # Prove that core.llm merge semantics preserve defaults when request hyperparams
    # are fully unset.
    from forge.core.llm.clients.base import merge_hyperparams

    merged = merge_hyperparams(
        ModelHyperparameters(
            reasoning_effort="high",
            verbosity="low",
            temperature=1.0,
            max_tokens=1234,
        ),
        stub.seen_hyperparams,
    )

    assert merged.reasoning_effort == "high"
    assert merged.verbosity == "low"
    assert merged.temperature == 1.0
    assert merged.max_tokens == 1234

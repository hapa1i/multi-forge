"""Regression: proxy auth retry must not deadlock rebuilding a client.

Bug: after an upstream auth failure, ``invalidate_and_retry()`` held the
factory refresh lock while calling ``get_client()``, which tries to acquire the
same lock. The proxy accepted later requests but parked forever before opening
the upstream LiteLLM/OpenAI connection.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from forge.proxy.client_factory import ModelProvider, TierClientFactory

pytestmark = pytest.mark.regression


def _seed_factory(monkeypatch: pytest.MonkeyPatch) -> TierClientFactory:
    factory = TierClientFactory()
    monkeypatch.setattr(factory, "_refresh_lock", asyncio.Lock())
    monkeypatch.setattr(
        factory,
        "_cache",
        {
            ("openai/gpt-5.5", "opus"): ("old-opus", time.monotonic(), ModelProvider.LITELLM),
            ("openai/gpt-5.5", "sonnet"): ("old-sonnet", time.monotonic(), ModelProvider.LITELLM),
            ("openai/gpt-5.4", "opus"): ("unrelated", time.monotonic(), ModelProvider.LITELLM),
        },
    )
    return factory


@pytest.mark.asyncio
async def test_invalidate_and_retry_all_tiers_rebuilds_client_after_releasing_refresh_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _seed_factory(monkeypatch)
    cache_seen_by_get_client = None
    calls: list[tuple[str, str | None]] = []

    async def fake_get_client(model_name: str, tier: str | None = None) -> str:
        nonlocal cache_seen_by_get_client
        assert not factory._refresh_lock.locked()
        calls.append((model_name, tier))
        cache_seen_by_get_client = dict(factory._cache)
        return "fresh-client"

    monkeypatch.setattr(factory, "get_client", fake_get_client)

    client = await factory.invalidate_and_retry("openai/gpt-5.5")

    assert client == "fresh-client"
    assert calls == [("openai/gpt-5.5", None)]
    assert cache_seen_by_get_client == {("openai/gpt-5.4", "opus"): factory._cache[("openai/gpt-5.4", "opus")]}


@pytest.mark.asyncio
async def test_invalidate_and_retry_single_tier_rebuilds_client_after_releasing_refresh_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _seed_factory(monkeypatch)
    cache_seen_by_get_client = None
    calls: list[tuple[str, str | None]] = []

    async def fake_get_client(model_name: str, tier: str | None = None) -> str:
        nonlocal cache_seen_by_get_client
        assert not factory._refresh_lock.locked()
        calls.append((model_name, tier))
        cache_seen_by_get_client = dict(factory._cache)
        return "fresh-opus-client"

    monkeypatch.setattr(factory, "get_client", fake_get_client)

    client = await factory.invalidate_and_retry("openai/gpt-5.5", tier="opus")

    assert client == "fresh-opus-client"
    assert calls == [("openai/gpt-5.5", "opus")]
    assert cache_seen_by_get_client == {
        ("openai/gpt-5.5", "sonnet"): factory._cache[("openai/gpt-5.5", "sonnet")],
        ("openai/gpt-5.4", "opus"): factory._cache[("openai/gpt-5.4", "opus")],
    }

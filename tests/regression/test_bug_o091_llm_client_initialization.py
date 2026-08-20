"""Regression O091: concurrent cold starts must share one LLM HTTP client.

Both adapters used to check their client cache before awaiting credential
resolution. Concurrent first callers could therefore construct different
``AsyncOpenAI`` instances, leaking the instance overwritten in the cache.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from forge.core.llm.clients import litellm, openrouter
from forge.core.llm.clients.litellm import LiteLLMClient
from forge.core.llm.clients.openrouter import OpenRouterClient

pytestmark = pytest.mark.regression


def _make_litellm_client() -> LiteLLMClient:
    return LiteLLMClient(model="openai/gpt-5.5", provider="litellm_remote", credentials=MagicMock())


def _make_openrouter_client() -> OpenRouterClient:
    return OpenRouterClient(model="openai/gpt-5.5", provider="openrouter", credentials=MagicMock())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("client_factory", "client_module", "credentials"),
    [
        (
            _make_litellm_client,
            litellm,
            {"api_key": "litellm-key", "base_url": "https://litellm.example.test"},
        ),
        (
            _make_openrouter_client,
            openrouter,
            {
                "api_key": "openrouter-key",
                "base_url": "https://openrouter.example.test",
            },
        ),
    ],
    ids=("litellm", "openrouter"),
)
async def test_concurrent_cold_start_constructs_one_client(
    monkeypatch: pytest.MonkeyPatch,
    client_factory: Callable[[], LiteLLMClient | OpenRouterClient],
    client_module: Any,
    credentials: dict[str, str],
) -> None:
    """A second cold caller must reuse the first caller's initialized client."""
    client = client_factory()
    release_credentials = asyncio.Event()
    credential_calls = 0

    async def get_credentials(_provider: str) -> dict[str, str]:
        nonlocal credential_calls
        credential_calls += 1
        if credential_calls == 1:
            # gather() schedules the second caller before this callback. Without
            # initialization serialization, both callers reach credential lookup
            # before the event opens; with it, the second waits on the client lock.
            asyncio.get_running_loop().call_soon(release_credentials.set)
        await release_credentials.wait()
        return credentials

    credentials_manager = MagicMock()
    credentials_manager.get_credentials = AsyncMock(side_effect=get_credentials)
    client._credentials = credentials_manager
    constructed_clients: list[MagicMock] = []

    def construct_client(**_kwargs: Any) -> MagicMock:
        constructed = MagicMock()
        constructed_clients.append(constructed)
        return constructed

    constructor = MagicMock(side_effect=construct_client)
    monkeypatch.setattr(client_module, "AsyncOpenAI", constructor)

    first, second = await asyncio.gather(client._get_client(), client._get_client())

    assert credential_calls == 1
    constructor.assert_called_once()
    assert len(constructed_clients) == 1
    assert first is second is constructed_clients[0]
    assert client._client is first


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport_close_error",
    [None, RuntimeError("transport cleanup failed")],
    ids=("close-succeeds", "close-fails"),
)
async def test_litellm_constructor_failure_closes_custom_ca_transport(
    monkeypatch: pytest.MonkeyPatch,
    transport_close_error: RuntimeError | None,
) -> None:
    """Custom transport cleanup must not replace the construction exception."""
    client = _make_litellm_client()
    credentials_manager = MagicMock()
    credentials_manager.get_credentials = AsyncMock(
        return_value={
            "api_key": "litellm-key",
            "base_url": "https://litellm.example.test",
            "ssl_cert": "/configured/root-ca.pem",
        }
    )
    client._credentials = credentials_manager
    ssl_context = MagicMock()
    transport = MagicMock()
    transport.aclose = AsyncMock(side_effect=transport_close_error)
    constructor_error = RuntimeError("client construction failed")

    monkeypatch.setattr(litellm.ssl, "create_default_context", MagicMock(return_value=ssl_context))
    monkeypatch.setattr(litellm.httpx, "AsyncClient", MagicMock(return_value=transport))
    monkeypatch.setattr(litellm, "AsyncOpenAI", MagicMock(side_effect=constructor_error))

    with pytest.raises(RuntimeError) as raised:
        await client._get_client()

    assert raised.value is constructor_error
    transport.aclose.assert_awaited_once_with()
    assert client._client is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client_factory",
    [_make_litellm_client, _make_openrouter_client],
    ids=("litellm", "openrouter"),
)
async def test_hot_cache_skips_credential_resolution(
    client_factory: Callable[[], LiteLLMClient | OpenRouterClient],
) -> None:
    """An initialized adapter must keep its lock-free cache-hit path."""
    client = client_factory()
    cached_client = MagicMock()
    client._client = cached_client
    credentials_manager = MagicMock()
    credentials_manager.get_credentials = AsyncMock(side_effect=AssertionError("unexpected credential lookup"))
    client._credentials = credentials_manager

    assert await client._get_client() is cached_client
    credentials_manager.get_credentials.assert_not_awaited()

"""Component integration tests for authentication refresh across the proxy's cache layers.

Three caches sit between a proxy request and its upstream. ``TierClientFactory`` caches adapters by
``(model, tier)``, each core client caches one HTTP client, and ``CredentialManager`` caches credentials
by provider. These tests pin how cached clients recover after their shared credential is replaced.

pytestmark: integration (CIT level -- client factory + client adapter + core client + credential manager).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import AuthenticationError as UpstreamAuthenticationError

from forge.core.llm.credentials import CredentialManager
from forge.core.llm.errors import AuthenticationError
from forge.core.llm.types import ModelHyperparameters
from forge.proxy.base_client import ProxyStreamError
from forge.proxy.client_factory import TierClientFactory

pytestmark = pytest.mark.integration

_REQUEST: dict[str, Any] = {"messages": [{"role": "user", "content": "ping"}], "max_tokens": 16}


class _Upstream:
    """In-memory LiteLLM gateway that accepts one API key and records every request."""

    def __init__(self, accepted_key: str) -> None:
        self.accepted_key = accepted_key
        self.accepted: list[tuple[str, str]] = []
        self.rejected: list[tuple[str, str]] = []

    def authorize(self, model: str, api_key: str) -> None:
        if api_key == self.accepted_key:
            self.accepted.append((model, api_key))
            return
        self.rejected.append((model, api_key))
        request = httpx.Request("POST", "https://litellm.invalid/chat/completions")
        # The core client recognizes an authentication failure by these words in the error text.
        raise UpstreamAuthenticationError(
            "Error code: 401 - {'error': {'message': 'Authentication Error, invalid API key'}}",
            response=httpx.Response(401, request=request),
            body=None,
        )


class _SDKClient:
    """``AsyncOpenAI`` stand-in bound to the API key it was constructed with."""

    def __init__(self, upstream: _Upstream, api_key: str) -> None:
        self._upstream = upstream
        self._api_key = api_key
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=self._create_stream,
                with_raw_response=SimpleNamespace(create=self._create),
            )
        )

    async def _create(self, **kwargs: Any) -> SimpleNamespace:
        self._upstream.authorize(kwargs["model"], self._api_key)
        message = SimpleNamespace(content="pong", tool_calls=None)
        usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2, prompt_tokens_details=None)
        parsed = SimpleNamespace(
            choices=[SimpleNamespace(message=message)], usage=usage, error=None, model_dump=lambda: {}
        )
        return SimpleNamespace(parse=lambda: parsed, headers={})

    async def _create_stream(self, **kwargs: Any) -> AsyncIterator[SimpleNamespace]:
        self._upstream.authorize(kwargs["model"], self._api_key)
        return _stream_chunks()

    async def close(self) -> None:
        return None


class _Secrets:
    """Secrets provider whose LiteLLM API key can be replaced while clients are cached."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def get(self, key: str, default: Any = None) -> Any:
        return self.api_key if key == "LITELLM_API_KEY" else default

    def require(self, key: str) -> str:
        value = self.get(key)
        if not value:
            raise KeyError(key)
        return str(value)


async def _stream_chunks() -> AsyncIterator[SimpleNamespace]:
    delta = SimpleNamespace(content="pong", tool_calls=None)
    yield SimpleNamespace(usage=None, choices=[SimpleNamespace(finish_reason="stop", delta=delta)])


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> _Upstream:
    """Route every ``AsyncOpenAI`` the LiteLLM core client builds to one in-memory gateway."""
    gateway = _Upstream(accepted_key="key-1")
    monkeypatch.setattr(
        "forge.core.llm.clients.litellm.AsyncOpenAI",
        lambda **kwargs: _SDKClient(gateway, kwargs["api_key"]),
    )
    return gateway


@pytest.fixture
def secrets(monkeypatch: pytest.MonkeyPatch) -> _Secrets:
    """Install a credential manager whose LiteLLM key the test can replace."""
    store = _Secrets("key-1")
    monkeypatch.setattr(CredentialManager, "_default_instance", CredentialManager(secrets=store))
    monkeypatch.setenv("LITELLM_BASE_URL", "https://litellm.invalid")
    # A configured CA bundle would make the core client open a real HTTP transport.
    for name in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        monkeypatch.delenv(name, raising=False)
    return store


@pytest.fixture
def factory(
    monkeypatch: pytest.MonkeyPatch,
    tier_client_factory: TierClientFactory,
    upstream: _Upstream,
    secrets: _Secrets,
) -> TierClientFactory:
    """Factory that builds real adapters over the in-memory gateway."""
    monkeypatch.setattr(
        tier_client_factory,
        "_resolve_tier_hyperparams",
        lambda _provider, _tier, _model_name: ModelHyperparameters(max_tokens=1024),
    )
    return tier_client_factory


def _replace_credential(upstream: _Upstream, secrets: _Secrets, api_key: str) -> None:
    """Revoke the cached key upstream and store its replacement."""
    upstream.accepted_key = api_key
    secrets.api_key = api_key


async def _send(factory: TierClientFactory, model: str, tier: str) -> dict[str, Any]:
    """Send one non-streaming request as the Messages handler does: one retry after an auth failure."""
    client = await factory.get_client(model, tier=tier)
    try:
        return await client.create_completion(_REQUEST, "req-test")
    except AuthenticationError:
        client = await factory.invalidate_and_retry(model, tier=tier)
        return await client.create_completion(_REQUEST, "req-test")


async def _stream(adapter: Any) -> list[dict[str, Any]]:
    return [chunk async for chunk in adapter.create_streaming_completion(_REQUEST, "req-test")]


@pytest.mark.asyncio
async def test_stale_siblings_recover_on_their_own_authentication_failure(
    factory: TierClientFactory, upstream: _Upstream, secrets: _Secrets
) -> None:
    """A sibling tier and a second model sharing the credential each fail once, then recover."""
    await _send(factory, "openai/gpt-4o", "opus")
    await _send(factory, "openai/gpt-4o", "sonnet")
    await _send(factory, "openai/gpt-4o-mini", "opus")
    sibling_tier = await factory.get_client("openai/gpt-4o", tier="sonnet")
    second_model = await factory.get_client("openai/gpt-4o-mini", tier="opus")
    _replace_credential(upstream, secrets, "key-2")

    await _send(factory, "openai/gpt-4o", "opus")

    # The retry evicted only the failed entry. Both siblings are still the adapters built with key-1.
    assert upstream.rejected == [("openai/gpt-4o", "key-1")]
    assert await factory.get_client("openai/gpt-4o", tier="sonnet") is sibling_tier
    assert await factory.get_client("openai/gpt-4o-mini", tier="opus") is second_model

    for _round in range(2):
        await _send(factory, "openai/gpt-4o", "sonnet")
        await _send(factory, "openai/gpt-4o-mini", "opus")

    # Each sibling made exactly one rejected request before it resolved the replacement key.
    assert upstream.rejected == [
        ("openai/gpt-4o", "key-1"),
        ("openai/gpt-4o", "key-1"),
        ("openai/gpt-4o-mini", "key-1"),
    ]
    assert [api_key for _model, api_key in upstream.accepted] == ["key-1"] * 3 + ["key-2"] * 5


@pytest.mark.asyncio
async def test_streaming_authentication_failure_surfaces_and_the_same_adapter_recovers(
    factory: TierClientFactory, upstream: _Upstream, secrets: _Secrets
) -> None:
    """A streaming auth failure reaches the caller without a factory retry; the next request recovers."""
    adapter = await factory.get_client("openai/gpt-4o", tier="opus")
    assert await _stream(adapter)
    _replace_credential(upstream, secrets, "key-2")

    with pytest.raises(ProxyStreamError) as raised:
        await _stream(adapter)

    assert raised.value.error_type == "authentication_error"
    assert upstream.rejected == [("openai/gpt-4o", "key-1")]
    assert await _stream(adapter)
    assert upstream.accepted[-1] == ("openai/gpt-4o", "key-2")
    assert await factory.get_client("openai/gpt-4o", tier="opus") is adapter

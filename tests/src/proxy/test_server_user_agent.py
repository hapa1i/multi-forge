"""Tests for translated-route User-Agent metadata forwarding."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, AsyncIterator, Callable
from unittest.mock import AsyncMock

import pytest

from forge.proxy.client_factory import ModelProvider


class _AnthropicResponse:
    def model_dump(self) -> dict[str, object]:
        return {"content": []}


class _CapturingClient:
    def __init__(self, captured: dict[str, Any]) -> None:
        self._captured = captured

    async def create_completion(
        self,
        openai_request: dict[str, Any],
        _request_id: str,
        *,
        on_provider_dispatch: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        if on_provider_dispatch is not None:
            on_provider_dispatch()
        self._captured["request"] = openai_request
        return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    async def create_streaming_completion(
        self,
        openai_request: dict[str, Any],
        _request_id: str,
        *,
        on_provider_dispatch: Callable[[], None] | None = None,
    ) -> AsyncIterator[bytes]:
        if on_provider_dispatch is not None:
            on_provider_dispatch()
        self._captured["request"] = openai_request
        yield b"data: {}\n\n"


class _StaticFactory:
    def __init__(self, provider: ModelProvider, captured: dict[str, Any]) -> None:
        self._provider = provider
        self._client = _CapturingClient(captured)

    def detect_provider_for_model(self, _model: str) -> ModelProvider:
        return self._provider

    async def get_client(self, _model: str, *, tier: str) -> _CapturingClient:
        return self._client


async def _run_translated_route(
    monkeypatch: pytest.MonkeyPatch,
    *,
    factory: Any,
    captured: dict[str, Any],
    headers: dict[str, str],
    stream: bool,
) -> dict[str, Any]:
    import forge.proxy.server as server

    monkeypatch.setattr(server, "client_factory", factory)
    monkeypatch.setattr(server.config, "proxy", SimpleNamespace(intercept=None))
    monkeypatch.setattr(server, "cost_tracker", None)
    monkeypatch.setattr(server, "_ensure_runtime_state", lambda: None)
    monkeypatch.setattr(
        server,
        "_resolve_model_with_alternatives",
        lambda _request, **_kwargs: SimpleNamespace(
            tier="sonnet",
            tier_source="explicit",
            model="openai/gpt-5.6-sol",
            explicit_backend=True,
        ),
    )
    monkeypatch.setattr(server, "convert_anthropic_to_openai", lambda *_args, **_kwargs: {"messages": []})
    monkeypatch.setattr(server, "convert_openai_to_anthropic", lambda *_args, **_kwargs: _AnthropicResponse())

    async def _relay_stream(chunks: AsyncIterator[bytes], *_args: object, **_kwargs: object) -> AsyncIterator[bytes]:
        async for chunk in chunks:
            yield chunk

    monkeypatch.setattr(server, "convert_openai_to_anthropic_sse", _relay_stream)
    monkeypatch.setattr(server, "_check_client_tool_failures", AsyncMock())
    monkeypatch.setattr(server, "_backend_instance_id", lambda: None)
    monkeypatch.setattr(server, "_inject_provider_user_enabled", lambda: False)
    monkeypatch.setattr(server, "_get_tier_override", lambda _tier: None)
    monkeypatch.setattr(server, "resolve_reasoning_effort", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "_calc_and_log_cost", lambda **_kwargs: 0)
    monkeypatch.setattr(server.proxy_metrics, "record_request", lambda **_kwargs: None)
    monkeypatch.setattr(server, "record_provider_trace", lambda **_kwargs: None)
    monkeypatch.setattr(server, "log_request_response", AsyncMock())
    monkeypatch.setattr(server, "log_request_beautifully", lambda **_kwargs: None)
    monkeypatch.setattr(server, "_cumulative_cost_header", lambda: {})
    monkeypatch.setattr(server, "_request_cost_header", lambda _cost: {})

    request_data = SimpleNamespace(
        messages=[],
        tools=None,
        system=None,
        original_model_name="openai/gpt-5.6-sol",
        stream=stream,
        temperature=None,
        max_tokens=16,
        top_p=None,
        stop_sequences=None,
        verbosity=None,
        tier="sonnet",
        model_dump=lambda: {},
    )
    raw_request = SimpleNamespace(
        state=SimpleNamespace(request_id="req_user_agent", downstream_event_id=None),
        headers=headers,
    )

    response = await server.create_message(request_data, raw_request)  # type: ignore[arg-type]
    if stream:
        assert [chunk async for chunk in response.body_iterator] == [b"data: {}\n\n"]
    else:
        assert response.status_code == 200

    return captured


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upstream_base_url", "expected_core_provider"),
    [
        ("http://127.0.0.1:4000/v1", "litellm_local"),
        ("https://litellm.example.test/v1", "litellm_remote"),
    ],
)
@pytest.mark.parametrize("stream", [False, True])
async def test_litellm_local_and_remote_routes_forward_user_agent(
    monkeypatch: pytest.MonkeyPatch,
    upstream_base_url: str,
    expected_core_provider: str,
    stream: bool,
) -> None:
    """Local/remote adapter selection stays downstream of the shared LiteLLM metadata gate."""
    import forge.proxy.client_factory as factory_module

    monkeypatch.delenv("PREFERRED_PROVIDER", raising=False)
    monkeypatch.delenv("MODEL_FAMILY", raising=False)
    monkeypatch.setattr(
        factory_module,
        "config",
        SimpleNamespace(proxy=SimpleNamespace(litellm=SimpleNamespace(top_p=None, tier_overrides={}))),
    )
    monkeypatch.setattr(factory_module, "_enforce_max_output_tokens_cap", lambda *_args, **_kwargs: 4096)
    monkeypatch.setattr(factory_module.TierClientFactory, "_instance", None)
    factory = factory_module.TierClientFactory()
    monkeypatch.setattr(factory, "_get_upstream_base_url", lambda: upstream_base_url)
    monkeypatch.setattr("forge.core.llm.detection.detect_provider", lambda _model: "litellm_remote")

    captured: dict[str, Any] = {}

    class _Adapter(_CapturingClient):
        def __init__(self, *, provider: str, **_kwargs: object) -> None:
            captured["core_provider"] = provider
            super().__init__(captured)

    factory._client_classes[ModelProvider.LITELLM] = _Adapter

    result = await _run_translated_route(
        monkeypatch,
        factory=factory,
        captured=captured,
        headers={"user-agent": "claude-code/route-matrix"},
        stream=stream,
    )

    assert captured["core_provider"] == expected_core_provider
    assert result["request"]["_user_agent"] == "claude-code/route-matrix"


@pytest.mark.asyncio
async def test_openrouter_route_keeps_user_agent_forwarding(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    factory = _StaticFactory(ModelProvider.OPENROUTER, captured)

    result = await _run_translated_route(
        monkeypatch,
        factory=factory,
        captured=captured,
        headers={"user-agent": "claude-code/openrouter-parity"},
        stream=False,
    )

    assert result["request"]["_user_agent"] == "claude-code/openrouter-parity"


@pytest.mark.asyncio
async def test_missing_user_agent_remains_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    factory = _StaticFactory(ModelProvider.LITELLM, captured)

    result = await _run_translated_route(
        monkeypatch,
        factory=factory,
        captured=captured,
        headers={},
        stream=False,
    )

    assert "_user_agent" not in result["request"]


@pytest.mark.asyncio
async def test_route_forwards_only_user_agent_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    factory = _StaticFactory(ModelProvider.LITELLM, captured)

    result = await _run_translated_route(
        monkeypatch,
        factory=factory,
        captured=captured,
        headers={
            "user-agent": "claude-code/header-boundary",
            "authorization": "Bearer secret",
            "cookie": "session=secret",
            "x-forge-session": "forge_sess_7e81a1bb765d_supervisor",
            "x-forge-command": "supervisor",
        },
        stream=False,
    )

    metadata_keys = {key for key in result["request"] if key.startswith("_")}
    assert metadata_keys == {"_user_agent"}

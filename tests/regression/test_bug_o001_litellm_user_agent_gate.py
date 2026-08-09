"""Regression for O001: translated LiteLLM requests lost inbound User-Agent metadata."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from forge.proxy.client_factory import ModelProvider

pytestmark = pytest.mark.regression


class _AnthropicResponse:
    def model_dump(self) -> dict[str, object]:
        return {"content": []}


@pytest.mark.asyncio
async def test_bug_o001_translated_litellm_route_carries_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """The collapsed LiteLLM routing enum must enter the route's metadata handoff."""
    import forge.proxy.server as server

    captured: dict[str, object] = {}

    class _Client:
        async def create_completion(self, openai_request: dict[str, object], _request_id: str) -> dict[str, object]:
            captured.update(openai_request)
            return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    async def _get_client(*_args: object, **_kwargs: object) -> _Client:
        return _Client()

    monkeypatch.setattr(server.config, "proxy", SimpleNamespace(intercept=None))
    monkeypatch.setattr(server, "_ensure_runtime_state", lambda: None)
    monkeypatch.setattr(
        server,
        "_resolve_model_with_alternatives",
        lambda _request: SimpleNamespace(
            tier="sonnet",
            tier_source="explicit",
            model="openai/gpt-5.6-sol",
            explicit_backend=True,
        ),
    )
    monkeypatch.setattr(server.client_factory, "detect_provider_for_model", lambda _model: ModelProvider.LITELLM)
    monkeypatch.setattr(server.client_factory, "get_client", _get_client)
    monkeypatch.setattr(server, "convert_anthropic_to_openai", lambda *_args, **_kwargs: {"messages": []})
    monkeypatch.setattr(server, "convert_openai_to_anthropic", lambda *_args, **_kwargs: _AnthropicResponse())
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
        stream=False,
        temperature=None,
        max_tokens=16,
        top_p=None,
        stop_sequences=None,
        verbosity=None,
        tier="sonnet",
        model_dump=lambda: {},
    )
    raw_request = SimpleNamespace(
        state=SimpleNamespace(request_id="req_o001", downstream_event_id=None),
        headers={"user-agent": "claude-code/o001-regression"},
    )

    response = await server.create_message(request_data, raw_request)  # type: ignore[arg-type]

    assert response.status_code == 200
    assert captured["_user_agent"] == "claude-code/o001-regression"

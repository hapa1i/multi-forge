"""Unsupported tool choices fail before translated dispatch, including streaming."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from forge.config import load_config
from forge.proxy.converters import convert_anthropic_to_openai
from forge.proxy.data_models import MessagesRequest

pytestmark = [pytest.mark.regression, pytest.mark.asyncio]


@pytest.mark.parametrize("template", ["litellm-anthropic-local", "openrouter-anthropic"])
@pytest.mark.parametrize("model", ["claude-sonnet", "claude-opus"])
@pytest.mark.parametrize("choice", [{"type": "any"}, {"type": "tool", "name": "ping"}])
@pytest.mark.parametrize("stream", [False, True])
async def test_forced_claude55_tools_return_actionable_400_before_upstream(
    monkeypatch: pytest.MonkeyPatch, template: str, model: str, choice: dict, stream: bool
) -> None:
    import forge.proxy.server as server

    configured = load_config(template=template)
    monkeypatch.setattr(server.config, "proxy", configured.proxy)
    monkeypatch.setattr(server, "_ensure_runtime_state", lambda: None)
    monkeypatch.setattr(server, "_check_client_tool_failures", AsyncMock())
    monkeypatch.setattr(
        server.client_factory,
        "detect_provider_for_model",
        lambda _model: SimpleNamespace(value=configured.proxy.preferred_provider),
    )
    get_client = AsyncMock(side_effect=AssertionError("Invalid request reached upstream"))
    monkeypatch.setattr(server.client_factory, "get_client", get_client)
    request = MessagesRequest.model_validate(
        {
            "model": model,
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Ping"}],
            "tools": [{"name": "ping", "input_schema": {"type": "object", "properties": {}}}],
            "tool_choice": choice,
            "stream": stream,
        }
    )
    raw_request = Request({"type": "http", "headers": [], "state": {"request_id": "forced-tools"}})

    with pytest.raises(HTTPException) as error:
        await server.create_message(request, raw_request)

    assert error.value.status_code == 400
    detail = error.value.detail
    assert isinstance(detail, dict)
    assert detail["type"] == "invalid_request_error"
    assert "tool_choice" in detail["message"]
    assert "auto" in detail["message"]
    get_client.assert_not_awaited()


@pytest.mark.parametrize(
    ("resolved_model", "choice", "expected"),
    [
        ("anthropic/claude-sonnet-5", {"type": "any"}, "required"),
        ("openai/gpt-6.1-sol", {"type": "any"}, "required"),
        ("anthropic/claude-sonnet-5-5", {"type": "auto"}, "auto"),
        ("anthropic/claude-opus-5.5", {"type": "none"}, "none"),
    ],
)
async def test_tool_choice_validation_uses_resolved_alternative_and_preserves_valid_choices(
    resolved_model: str, choice: dict, expected: str
) -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "claude-sonnet-5-5",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Ping"}],
            "tools": [{"name": "ping", "input_schema": {"type": "object", "properties": {}}}],
            "tool_choice": choice,
        }
    )

    converted = convert_anthropic_to_openai(request, provider="openrouter", resolved_model=resolved_model)

    assert converted["tool_choice"] == expected

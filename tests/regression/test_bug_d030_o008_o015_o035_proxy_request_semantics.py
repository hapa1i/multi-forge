"""Regression guards for Wave 6 proxy tier and translated-request semantics."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from forge.config.schema import TierOverride, TierOverrides
from forge.core.llm.errors import AuthenticationError
from forge.core.llm.types import CompletionResponse
from forge.proxy import intercept
from forge.proxy.client_adapter import CoreLLMClientAdapter
from forge.proxy.data_models import (
    Message,
    MessagesRequest,
    ToolDefinition,
    ToolInputSchema,
)

pytestmark = pytest.mark.regression


@dataclass
class _ProviderConfig:
    top_p: float | None = 0.7
    tier_overrides: TierOverrides = field(
        default_factory=lambda: TierOverrides(
            opus=TierOverride(
                reasoning_effort="high",
                verbosity="high",
                temperature=0.3,
                thinking_budget_tokens=4096,
            )
        )
    )


@dataclass
class _ProxyConfig:
    litellm: _ProviderConfig = field(default_factory=_ProviderConfig)
    openrouter: _ProviderConfig = field(default_factory=_ProviderConfig)


@dataclass
class _Config:
    proxy: _ProxyConfig = field(default_factory=_ProxyConfig)


@pytest.mark.parametrize(
    ("provider_name", "env_prefix"),
    [("litellm", "LITELLM"), ("openrouter", "OPENROUTER")],
)
def test_d030_proxy_tier_hyperparameters_ignore_undocumented_environment_overrides(
    monkeypatch: pytest.MonkeyPatch,
    provider_name: str,
    env_prefix: str,
) -> None:
    import forge.proxy.client_factory as client_factory_module

    monkeypatch.setattr(client_factory_module, "config", _Config())
    monkeypatch.setattr(client_factory_module.TierClientFactory, "_instance", None)
    monkeypatch.setattr(
        client_factory_module,
        "_enforce_max_output_tokens_cap",
        lambda _model, requested, **_kwargs: 8192 if requested is None else requested,
    )
    monkeypatch.setenv(f"{env_prefix}_OPUS_MAX_TOKENS", "1111")
    monkeypatch.setenv(f"{env_prefix}_OPUS_REASONING_EFFORT", "low")
    monkeypatch.setenv(f"{env_prefix}_OPUS_VERBOSITY", "low")
    monkeypatch.setenv(f"{env_prefix}_OPUS_THINKING_TYPE", "enabled")
    monkeypatch.setenv(f"{env_prefix}_OPUS_THINKING_BUDGET_TOKENS", "1200")

    hyperparameters = client_factory_module.TierClientFactory().get_default_hyperparams_for_tier(
        provider=provider_name,
        tier="opus",
        model_name="openai/gpt-5.5",
    )

    assert hyperparameters.max_tokens == 8192
    assert hyperparameters.reasoning_effort == "high"
    assert hyperparameters.verbosity == "high"
    assert hyperparameters.temperature == 0.3
    assert hyperparameters.top_p == 0.7
    assert hyperparameters.thinking is not None
    assert hyperparameters.thinking.budget_tokens == 4096


def test_o008_reasoning_pin_removes_incompatible_sampling_parameters() -> None:
    body = {
        "model": "claude-opus-4-6",
        "max_tokens": 64000,
        "messages": [{"role": "user", "content": "review"}],
        "temperature": 0.6,
        "top_p": 0.8,
        "top_k": 40,
    }

    result = intercept.apply_override(body, reasoning_floor_effort="high")

    assert body["thinking"] == {"type": "enabled", "budget_tokens": 10000}
    assert "temperature" not in body
    assert "top_p" not in body
    assert "top_k" not in body
    assert result.mutation_record is not None
    reasoning_pin = next(
        mutation for mutation in result.mutation_record["mutations"] if mutation["action"] == "reasoning_pin"
    )
    assert reasoning_pin["removed_sampling_parameters"] == ["temperature", "top_k", "top_p"]
    assert "0.6" not in json.dumps(result.mutation_record)


def test_o008_no_reasoning_mutation_preserves_sampling_parameters() -> None:
    body = {
        "model": "claude-opus-4-6",
        "max_tokens": 64000,
        "messages": [{"role": "user", "content": "review"}],
        "temperature": 0.6,
        "top_p": 0.8,
        "top_k": 40,
    }

    result = intercept.apply_override(body)

    assert body["temperature"] == 0.6
    assert body["top_p"] == 0.8
    assert body["top_k"] == 40
    assert result.mutation_record is None


def test_o008_satisfied_reasoning_floor_preserves_sampling_parameters() -> None:
    body = {
        "model": "claude-opus-4-6",
        "max_tokens": 64000,
        "messages": [{"role": "user", "content": "review"}],
        "thinking": {"type": "enabled", "budget_tokens": 12000},
        "temperature": 0.6,
        "top_p": 0.8,
        "top_k": 40,
    }
    expected_body = deepcopy(body)

    result = intercept.apply_override(body, reasoning_floor_effort="high")

    assert (body, result.mutation_record) == (expected_body, None)


class _RequestState:
    request_id = "req_o015"
    downstream_event_id = "evt_o015"
    forge_run_id = None
    forge_root_run_id = None
    forge_session = None
    forge_command = None


class _RawRequest:
    state = _RequestState()
    headers: dict[str, str] = {}


class _AnthropicResponse:
    def model_dump(self) -> dict[str, Any]:
        return {"content": [], "usage": {"input_tokens": 5, "output_tokens": 7}}


class _ProviderConfigForServer:
    tiers = SimpleNamespace(haiku="openai/gpt-haiku", sonnet="openai/gpt-sonnet", opus="openai/gpt-opus")
    model_alternatives: dict[str, dict[str, str]] = {}
    tier_overrides = TierOverrides()


class _ProxyConfigForServer:
    active_template = "unit-test"
    intercept = None
    logging = None
    preferred_provider = "litellm"
    default_tier = "sonnet"
    backend = ""
    tool_prefixes_to_ignore = ["mcp__*"]

    def get_provider(self, name: str | None = None) -> _ProviderConfigForServer:
        return _ProviderConfigForServer()

    def get_model_for_tier(self, tier: str) -> str:
        return cast(str, getattr(_ProviderConfigForServer.tiers, tier))


@pytest.mark.asyncio
async def test_o015_authentication_retry_preserves_resolved_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    import forge.proxy.server as server

    initial_client = SimpleNamespace(
        create_completion=AsyncMock(side_effect=AuthenticationError("openai", "expired credential"))
    )
    retry_client = SimpleNamespace(
        create_completion=AsyncMock(
            return_value={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 7, "cached_tokens": 2},
            }
        )
    )
    invalidate_and_retry = AsyncMock(return_value=retry_client)

    async def _no_op_async(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(server, "_ensure_runtime_state", lambda: None)
    monkeypatch.setattr(server.config, "proxy", _ProxyConfigForServer())
    monkeypatch.setattr(server.client_factory, "get_client", AsyncMock(return_value=initial_client))
    monkeypatch.setattr(server.client_factory, "invalidate_and_retry", invalidate_and_retry)
    monkeypatch.setattr(server.client_factory, "detect_provider_for_model", lambda *_: SimpleNamespace(value="openai"))
    monkeypatch.setattr(server, "convert_anthropic_to_openai", lambda *_args, **_kwargs: {"messages": []})
    monkeypatch.setattr(server, "convert_openai_to_anthropic", lambda *_args, **_kwargs: _AnthropicResponse())
    monkeypatch.setattr(server, "_check_client_tool_failures", _no_op_async)
    monkeypatch.setattr(server, "_calc_and_log_cost", lambda **_kwargs: 0)
    monkeypatch.setattr(server, "log_request_response", _no_op_async)
    monkeypatch.setattr(server, "log_request_beautifully", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "record_provider_trace", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "_provider_user_value", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server.proxy_metrics, "record_request", lambda *_args, **_kwargs: None)

    request = MessagesRequest(
        model="claude-opus-4-6",
        max_tokens=1,
        messages=[Message(role="user", content="review")],
    )
    response = await server.create_message(request, cast(Any, _RawRequest()))

    assert response.status_code == 200
    invalidate_and_retry.assert_awaited_once_with("openai/gpt-opus", tier="opus")


def test_o035_anthropic_any_requires_an_openai_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("forge.proxy.converters.asyncio.create_task", lambda coro: coro.close())
    request = MessagesRequest(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[Message(role="user", content="read the file")],
        tools=[
            ToolDefinition(
                name="Read",
                description="Read a file",
                input_schema=ToolInputSchema(
                    properties={"file_path": {"type": "string"}},
                    required=["file_path"],
                ),
            )
        ],
        tool_choice={"type": "any"},
    )

    from forge.proxy.converters import convert_anthropic_to_openai

    converted = convert_anthropic_to_openai(request, provider="litellm")

    assert converted["tool_choice"] == "required"


@pytest.mark.asyncio
async def test_o035_required_tool_choice_reaches_the_upstream_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("forge.proxy.converters.asyncio.create_task", lambda coro: coro.close())
    request = MessagesRequest(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[Message(role="user", content="read the file")],
        tools=[
            ToolDefinition(
                name="Read",
                description="Read a file",
                input_schema=ToolInputSchema(
                    properties={"file_path": {"type": "string"}},
                    required=["file_path"],
                ),
            )
        ],
        tool_choice={"type": "any"},
    )

    from forge.proxy.converters import convert_anthropic_to_openai

    converted = convert_anthropic_to_openai(request, provider="litellm")
    complete = AsyncMock(return_value=CompletionResponse(text="ok"))
    adapter = CoreLLMClientAdapter.__new__(CoreLLMClientAdapter)
    adapter.model_name = "openai/gpt-5.5"
    adapter.max_tokens_override = None
    adapter._client = SimpleNamespace(complete=complete)

    await adapter.create_completion(converted, request_id="req_o035")

    await_args = complete.await_args
    assert await_args is not None
    hyperparameters = await_args.kwargs["hyperparams"]
    assert hyperparameters.extra["openai"]["tool_choice"] == "required"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_o035_unsatisfiable_required_tool_choice_returns_400_before_upstream(
    monkeypatch: pytest.MonkeyPatch,
    stream: bool,
) -> None:
    """Filtering every required tool is a client error for both response modes."""
    import forge.proxy.server as server

    get_client = AsyncMock()
    monkeypatch.setattr(server, "_ensure_runtime_state", lambda: None)
    monkeypatch.setattr(server.config, "proxy", _ProxyConfigForServer())
    monkeypatch.setattr(server.client_factory, "get_client", get_client)
    monkeypatch.setattr(server.client_factory, "detect_provider_for_model", lambda *_: SimpleNamespace(value="openai"))
    request = MessagesRequest(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[Message(role="user", content="use the tool")],
        tools=[
            ToolDefinition(
                name="mcp__only",
                description="Filtered tool",
                input_schema=ToolInputSchema(properties={}),
            )
        ],
        tool_choice={"type": "any"},
        stream=stream,
    )

    with pytest.raises(HTTPException) as exc_info:
        await server.create_message(request, cast(Any, _RawRequest()))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == {
        "type": "invalid_request_error",
        "message": "tool_choice 'any' requires at least one available tool after proxy filtering",
    }
    get_client.assert_not_awaited()

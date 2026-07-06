"""Characterization tests for proxy model resolution shared by messages/count_tokens."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

import pytest

from forge.proxy.data_models import Message, MessagesRequest, TokenCountRequest


@dataclass(frozen=True)
class ResolutionCase:
    name: str
    model: str
    preferred_provider: str
    default_tier: str
    expected_tier: str
    expected_model: str


RESOLUTION_CASES = [
    ResolutionCase(
        name="litellm-explicit-backend",
        model="vertex_ai/gemini-3.1-pro",
        preferred_provider="litellm",
        default_tier="sonnet",
        expected_tier="sonnet",
        expected_model="vertex_ai/gemini-3.1-pro",
    ),
    ResolutionCase(
        name="openrouter-slash-passthrough",
        model="google/gemini-2.5-pro",
        preferred_provider="openrouter",
        default_tier="sonnet",
        expected_tier="sonnet",
        expected_model="google/gemini-2.5-pro",
    ),
    ResolutionCase(
        name="tier-alias-alternative",
        model="claude-fable[1m]",
        preferred_provider="litellm",
        default_tier="sonnet",
        expected_tier="opus",
        expected_model="anthropic/claude-opus-special",
    ),
    ResolutionCase(
        name="ambiguous-default-tier",
        model="claude-3",
        preferred_provider="litellm",
        default_tier="haiku",
        expected_tier="haiku",
        expected_model="openai/gpt-haiku-test",
    ),
]


class _RequestState:
    request_id = "req_model_resolution"
    downstream_event_id = "evt_model_resolution"
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


class _ProviderCfg:
    tiers = SimpleNamespace(
        haiku="openai/gpt-haiku-test",
        sonnet="openai/gpt-sonnet-test",
        opus="openai/gpt-opus-test",
    )
    model_alternatives = {"opus": {"claude-fable": "anthropic/claude-opus-special"}}


class _ProxyCfg:
    active_template = "unit-test"
    intercept = None
    logging = None

    def __init__(self, *, preferred_provider: str, default_tier: str) -> None:
        self.preferred_provider = preferred_provider
        self.default_tier = default_tier
        self.gemini = _ProviderCfg()

    def get_provider(self, name: str | None = None) -> _ProviderCfg:
        return _ProviderCfg()

    def get_model_for_tier(self, tier: str) -> str:
        return getattr(_ProviderCfg.tiers, tier)


def _install_server_stubs(monkeypatch: pytest.MonkeyPatch, case: ResolutionCase) -> dict[str, Any]:
    import forge.proxy.server as server

    captured: dict[str, Any] = {
        "client_calls": [],
        "cost_calls": [],
    }

    async def _fake_get_client(model: str, *, tier: str | None = None):
        captured["client_calls"].append({"model": model, "tier": tier})

        async def _create_completion(openai_request: dict[str, Any], request_id: str) -> dict[str, Any]:
            captured["openai_request"] = openai_request
            captured["completion_request_id"] = request_id
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 7, "cached_tokens": 2},
                "_reported_cost_micros": 1234,
            }

        async def _count_tokens(messages: list[dict[str, Any]]) -> int:
            captured["count_messages"] = messages
            return 42

        return SimpleNamespace(create_completion=_create_completion, count_tokens=_count_tokens)

    def _capture_cost(**kwargs: Any) -> int:
        captured["cost_calls"].append(kwargs)
        return 1234

    async def _no_op_async(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(server, "_ensure_runtime_state", lambda: None)
    monkeypatch.setattr(
        server.config,
        "proxy",
        _ProxyCfg(preferred_provider=case.preferred_provider, default_tier=case.default_tier),
    )
    monkeypatch.setattr(server.client_factory, "get_client", _fake_get_client)
    monkeypatch.setattr(server.client_factory, "detect_provider_for_model", lambda *_: SimpleNamespace(value="openai"))
    monkeypatch.setattr(server, "convert_anthropic_to_openai", lambda *a, **k: {"messages": [{"role": "user"}]})
    monkeypatch.setattr(server, "convert_openai_to_anthropic", lambda *a, **k: _AnthropicResponse())
    monkeypatch.setattr(server, "_check_client_tool_failures", _no_op_async)
    monkeypatch.setattr(server, "_calc_and_log_cost", _capture_cost)
    monkeypatch.setattr(server, "log_request_response", _no_op_async)
    monkeypatch.setattr(server, "log_request_beautifully", lambda *a, **k: None)
    monkeypatch.setattr(server, "record_provider_trace", lambda *a, **k: None)
    monkeypatch.setattr(server, "_provider_user_value", lambda *a, **k: None)
    monkeypatch.setattr(server.proxy_metrics, "record_request", lambda *a, **k: None)
    return captured


@pytest.mark.asyncio
@pytest.mark.parametrize("case", RESOLUTION_CASES, ids=[case.name for case in RESOLUTION_CASES])
async def test_create_message_resolves_model_tier_and_cost_target(
    monkeypatch: pytest.MonkeyPatch, case: ResolutionCase
) -> None:
    import forge.proxy.server as server

    captured = _install_server_stubs(monkeypatch, case)
    request_data = MessagesRequest(
        model=case.model,
        max_tokens=1,
        messages=[Message(role="user", content="hello")],
    )

    response = await server.create_message(request_data, cast(Any, _RawRequest()))

    assert response.status_code == 200
    assert response.headers["X-Resolved-Tier"] == case.expected_tier
    assert response.headers["X-Resolved-Model"] == case.expected_model
    assert request_data.tier == case.expected_tier
    assert captured["client_calls"] == [{"model": case.expected_model, "tier": case.expected_tier}]
    assert captured["openai_request"]["model"] == case.expected_model
    assert len(captured["cost_calls"]) == 1
    cost_call = captured["cost_calls"][0]
    assert cost_call["model"] == case.expected_model
    assert cost_call["tier"] == case.expected_tier
    assert cost_call["input_tokens"] == 5
    assert cost_call["output_tokens"] == 7
    assert cost_call["cached_tokens"] == 2
    assert cost_call["failed"] is False
    assert cost_call["request_id"] == "req_model_resolution"
    assert cost_call["reported_cost_micros"] == 1234
    assert cost_call["forge_run_id"] is None
    assert cost_call["forge_root_run_id"] is None
    assert cost_call["downstream_event_id"] == "evt_model_resolution"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", RESOLUTION_CASES, ids=[case.name for case in RESOLUTION_CASES])
async def test_count_tokens_resolves_model_and_tier_like_messages(
    monkeypatch: pytest.MonkeyPatch, case: ResolutionCase
) -> None:
    import forge.proxy.server as server

    captured = _install_server_stubs(monkeypatch, case)
    request_data = TokenCountRequest(
        model=case.model,
        messages=[Message(role="user", content="hello")],
    )

    response = await server.count_tokens(request_data, cast(Any, _RawRequest()))

    assert response.status_code == 200
    assert json.loads(response.body) == {"input_tokens": 42}
    assert request_data.tier == case.expected_tier
    assert captured["client_calls"] == [{"model": case.expected_model, "tier": case.expected_tier}]
    assert captured["count_messages"] == [{"role": "user"}]

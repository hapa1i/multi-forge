"""Tests for the shared single-call LLM transport."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from forge.core.llm import CompletionResponse, Message, ModelHyperparameters
from forge.core.reactive.llm_call import complete_llm_call


@patch("forge.core.reactive.llm_call.time.monotonic", side_effect=[10.0, 10.125])
@patch("forge.core.usage.resolve_client_base_url", return_value=None)
@patch("forge.core.llm.get_client")
@patch("forge.core.llm.SyncAdapter")
def test_completes_with_model_resolved_target(
    mock_adapter_cls: MagicMock,
    mock_get_client: MagicMock,
    mock_resolve_client_base_url: MagicMock,
    mock_monotonic: MagicMock,
) -> None:
    response = CompletionResponse(text="ok")
    adapter = MagicMock()
    adapter.complete.return_value = response
    mock_adapter_cls.return_value = adapter
    messages = [Message(role="user", content="hello")]

    actual, latency_ms, request_id = complete_llm_call(model="gemini/test", messages=messages)

    assert actual is response
    assert latency_ms == 125.0
    assert request_id is None
    mock_get_client.assert_called_once_with("gemini/test", provider=None)
    mock_resolve_client_base_url.assert_called_once_with("gemini/test")
    adapter.complete.assert_called_once_with(messages, hyperparams=None)


@patch("forge.core.usage.mint_request_id", return_value="req_fixed")
@patch("forge.core.usage.target_is_forge_proxy", return_value=True)
@patch("forge.core.usage.resolve_client_base_url")
@patch(
    "forge.core.llm.credentials.resolve_provider_base_url",
    return_value="http://localhost:8084",
)
@patch("forge.core.llm.get_client")
@patch("forge.core.llm.SyncAdapter")
def test_explicit_provider_resolves_target_and_appends_request_id_last(
    mock_adapter_cls: MagicMock,
    mock_get_client: MagicMock,
    mock_resolve_provider_base_url: MagicMock,
    mock_resolve_client_base_url: MagicMock,
    mock_target_is_forge_proxy: MagicMock,
    mock_mint_request_id: MagicMock,
) -> None:
    adapter = MagicMock()
    adapter.complete.return_value = CompletionResponse(text="ok")
    mock_adapter_cls.return_value = adapter
    original = ModelHyperparameters(reasoning_effort="high", extra={"openai": {"user": "group"}})

    _, _, request_id = complete_llm_call(
        model="google/test",
        provider="openrouter",
        messages=[Message(role="user", content="hello")],
        hyperparams=original,
    )

    assert request_id == "req_fixed"
    mock_get_client.assert_called_once_with("google/test", provider="openrouter")
    mock_resolve_provider_base_url.assert_called_once_with("openrouter")
    mock_resolve_client_base_url.assert_not_called()
    mock_target_is_forge_proxy.assert_called_once_with("http://localhost:8084")
    mock_mint_request_id.assert_called_once_with()
    forwarded = adapter.complete.call_args.kwargs["hyperparams"]
    assert forwarded.reasoning_effort == "high"
    assert forwarded.extra["openai"]["user"] == "group"
    assert forwarded.extra["openai"]["extra_headers"]["X-Request-ID"] == "req_fixed"
    assert original.extra == {"openai": {"user": "group"}}


@patch("forge.core.usage.resolve_client_base_url", return_value=None)
@patch("forge.core.llm.get_client")
@patch("forge.core.llm.SyncAdapter")
def test_transport_exception_propagates(
    mock_adapter_cls: MagicMock,
    mock_get_client: MagicMock,
    mock_resolve_client_base_url: MagicMock,
) -> None:
    adapter = MagicMock()
    adapter.complete.side_effect = RuntimeError("down")
    mock_adapter_cls.return_value = adapter

    with pytest.raises(RuntimeError, match="down"):
        complete_llm_call(model="gemini/test", messages=[Message(role="user", content="hello")])

"""Regression for O007: non-streaming response conversion failed as a success.

The converter returned a normal assistant ``end_turn`` containing exception text when
provider output could not be represented as an Anthropic response. Both translated
route paths then returned HTTP 200 and recorded successful accounting. Conversion
failure must instead remain metadata-only, preserve the completed provider attempt's
usage/cost/trace evidence, and fail the client request consistently.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from forge.core.llm.errors import AuthenticationError
from forge.proxy.converters import convert_openai_to_anthropic
from forge.proxy.data_models import Message, MessagesRequest
from forge.proxy.metrics import proxy_metrics

pytestmark = pytest.mark.regression

_CANARY = "O007_PROVIDER_RESPONSE_CANARY"
_REQUEST_ID = "req_o007"
_REPORTED_COST_MICROS = 12_345
_USAGE = {
    "prompt_tokens": 321,
    "completion_tokens": 45,
    "total_tokens": 366,
    "cached_tokens": 123,
}
_ZERO_USAGE = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "cached_tokens": 0,
}
_PROVIDER_META = {
    "provider": "openrouter",
    "provider_generation_id": "gen-o007",
}


class _RawRequest:
    def __init__(self, request_id: str = _REQUEST_ID) -> None:
        self.state = SimpleNamespace(request_id=request_id, downstream_event_id="evt-o007")
        self.headers: dict[str, str] = {}


def _request() -> MessagesRequest:
    return MessagesRequest(
        model="claude-sonnet-4-6",
        messages=[Message(role="user", content="hello")],
        max_tokens=16,
        stream=False,
    )


def _invalid_provider_response() -> dict[str, Any]:
    return {
        "id": {"provider_value": _CANARY},
        "request_id": _REQUEST_ID,
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": "provider response"},
            }
        ],
        "usage": dict(_USAGE),
        "_reported_cost_micros": _REPORTED_COST_MICROS,
        "_provider_meta": dict(_PROVIDER_META),
    }


@pytest.fixture(autouse=True)
def _reset_proxy_metrics() -> Iterator[None]:
    proxy_metrics.reset()
    yield
    proxy_metrics.reset()


def _stub_route(
    monkeypatch: pytest.MonkeyPatch,
    server: Any,
    *,
    retry_after_auth_failure: bool,
    provider_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cost_calls: list[dict[str, Any]] = []
    trace_calls: list[dict[str, Any]] = []
    request_logs: list[dict[str, Any]] = []
    beautiful_logs: list[dict[str, Any]] = []

    monkeypatch.setattr(server, "_ensure_runtime_state", lambda: None)
    monkeypatch.setattr(server, "cost_tracker", None)
    monkeypatch.setattr(
        server,
        "_resolve_model_with_alternatives",
        lambda _request: SimpleNamespace(
            tier="sonnet",
            tier_source="explicit",
            model="openai/gpt-5.5",
            explicit_backend=False,
        ),
    )
    monkeypatch.setattr(server, "_forge_run_ids", lambda _request: ("run-o007", "root-o007"))
    monkeypatch.setattr(
        server,
        "_forge_session_command",
        lambda _request: ("session-o007", "forge call"),
    )
    monkeypatch.setattr(server, "_backend_instance_id", lambda: "openrouter")
    monkeypatch.setattr(server, "_inject_provider_user_enabled", lambda: False)
    monkeypatch.setattr(server, "_get_tier_override", lambda _tier: None)
    monkeypatch.setattr(server, "resolve_reasoning_effort", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "_check_client_tool_failures", AsyncMock())
    monkeypatch.setattr(
        server,
        "convert_anthropic_to_openai",
        lambda *_args, **_kwargs: {"messages": []},
    )
    monkeypatch.setattr(
        server.client_factory,
        "detect_provider_for_model",
        lambda _model: SimpleNamespace(value="openai"),
    )

    def _capture_cost(**kwargs: Any) -> int:
        cost_calls.append(kwargs)
        return _REPORTED_COST_MICROS

    def _capture_trace(**kwargs: Any) -> None:
        trace_calls.append(kwargs)

    async def _capture_request_log(**kwargs: Any) -> None:
        request_logs.append(kwargs)

    monkeypatch.setattr(server, "_calc_and_log_cost", _capture_cost)
    monkeypatch.setattr(server, "record_provider_trace", _capture_trace)
    monkeypatch.setattr(server, "log_request_response", _capture_request_log)
    monkeypatch.setattr(
        server,
        "log_request_beautifully",
        lambda **kwargs: beautiful_logs.append(kwargs),
    )

    response = provider_response if provider_response is not None else _invalid_provider_response()
    initial_client = AsyncMock()
    retry_client = AsyncMock()
    if retry_after_auth_failure:
        initial_client.create_completion = AsyncMock(side_effect=AuthenticationError("openai", "expired credential"))
        retry_client.create_completion = AsyncMock(return_value=response)
    else:
        initial_client.create_completion = AsyncMock(return_value=response)
        retry_client.create_completion = AsyncMock(side_effect=AssertionError("unexpected authentication retry"))

    get_client = AsyncMock(return_value=initial_client)
    invalidate_and_retry = AsyncMock(return_value=retry_client)
    monkeypatch.setattr(server.client_factory, "get_client", get_client)
    monkeypatch.setattr(server.client_factory, "invalidate_and_retry", invalidate_and_retry)

    return {
        "cost_calls": cost_calls,
        "trace_calls": trace_calls,
        "request_logs": request_logs,
        "beautiful_logs": beautiful_logs,
        "invalidate_and_retry": invalidate_and_retry,
    }


def test_conversion_failure_returns_explicit_signal_without_plaintext(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger="forge.proxy.converters")

    converted = convert_openai_to_anthropic(_invalid_provider_response(), "claude-sonnet-4-6")

    assert converted is None
    assert "error_type=ValidationError" in caplog.text
    assert _CANARY not in caplog.text
    assert "Traceback" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def _assert_route_failure(
    server: Any,
    captures: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    *,
    expected_usage: dict[str, int] | None = None,
    expected_conversion_error_type: str = "ValidationError",
) -> None:
    expected_usage = _USAGE if expected_usage is None else expected_usage
    with pytest.raises(HTTPException) as exc_info:
        await server.create_message(_request(), _RawRequest())

    await asyncio.sleep(0)

    error = exc_info.value
    assert error.status_code == 500
    assert error.detail == {
        "type": "api_error",
        "message": "Failed to convert response",
    }
    assert _CANARY not in str(error.detail)

    assert len(captures["cost_calls"]) == 1
    cost = captures["cost_calls"][0]
    assert cost["input_tokens"] == expected_usage["prompt_tokens"]
    assert cost["output_tokens"] == expected_usage["completion_tokens"]
    assert cost["cached_tokens"] == expected_usage["cached_tokens"]
    assert cost["failed"] is True
    assert cost["reported_cost_micros"] == _REPORTED_COST_MICROS
    assert cost["downstream_event_id"] == "evt-o007"

    snapshot = proxy_metrics.snapshot()
    assert snapshot["total_requests"] == 1
    assert snapshot["total_failures"] == 1
    assert snapshot["failures_by_type"] == {"api_error": 1}
    assert snapshot["tokens"]["input"] == expected_usage["prompt_tokens"]
    assert snapshot["tokens"]["output"] == expected_usage["completion_tokens"]
    assert snapshot["tokens"]["cached"] == expected_usage["cached_tokens"]
    assert snapshot["tokens"]["failed_input"] == expected_usage["prompt_tokens"]
    assert snapshot["tokens"]["failed_output"] == expected_usage["completion_tokens"]
    assert snapshot["costs"]["total_micros"] == _REPORTED_COST_MICROS
    assert snapshot["costs"]["failed_micros"] == _REPORTED_COST_MICROS

    assert len(captures["trace_calls"]) == 1
    trace = captures["trace_calls"][0]
    assert trace["request_mode"] == "non_streaming"
    assert trace["provider_meta"] == _PROVIDER_META
    assert trace["stream_started"] is True
    assert trace["first_chunk_seen"] is True
    assert trace["final_usage_seen"] is True
    assert trace["client_disconnected"] is False
    assert trace["reported_cost_micros"] == _REPORTED_COST_MICROS
    assert trace["downstream_event_id"] == "evt-o007"

    assert len(captures["request_logs"]) == 1
    request_log = captures["request_logs"][0]
    assert request_log["status_code"] == 500
    assert request_log["response_body"] is None
    assert request_log["error"] == "Failed to convert response"
    assert captures["beautiful_logs"][0]["status_code"] == 500

    assert f"error_type={expected_conversion_error_type}" in caplog.text
    assert "Unexpected error" not in caplog.text
    assert _CANARY not in caplog.text
    assert "Traceback" not in caplog.text


@pytest.mark.asyncio
async def test_initial_conversion_failure_is_http_500_with_failed_accounting(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import forge.proxy.server as server

    caplog.set_level(logging.ERROR, logger="forge.proxy")
    captures = _stub_route(monkeypatch, server, retry_after_auth_failure=False)

    await _assert_route_failure(server, captures, caplog)

    captures["invalidate_and_retry"].assert_not_awaited()


@pytest.mark.asyncio
async def test_auth_retry_conversion_failure_matches_initial_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import forge.proxy.server as server

    caplog.set_level(logging.ERROR, logger="forge.proxy")
    captures = _stub_route(monkeypatch, server, retry_after_auth_failure=True)

    await _assert_route_failure(server, captures, caplog)

    captures["invalidate_and_retry"].assert_awaited_once_with("openai/gpt-5.5", tier="sonnet")


@pytest.mark.asyncio
async def test_malformed_usage_cannot_bypass_failure_accounting_or_provider_trace(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import forge.proxy.server as server

    caplog.set_level(logging.ERROR, logger="forge.proxy")
    malformed_usage_values: tuple[tuple[object, str], ...] = (
        ("N/A", "AttributeError"),
        (
            {
                "prompt_tokens": "many",
                "completion_tokens": [],
                "cached_tokens": True,
            },
            "ValidationError",
        ),
    )

    for malformed_usage, expected_error_type in malformed_usage_values:
        proxy_metrics.reset()
        caplog.clear()
        response = _invalid_provider_response()
        response["usage"] = malformed_usage
        captures = _stub_route(
            monkeypatch,
            server,
            retry_after_auth_failure=False,
            provider_response=response,
        )

        await _assert_route_failure(
            server,
            captures,
            caplog,
            expected_usage=_ZERO_USAGE,
            expected_conversion_error_type=expected_error_type,
        )

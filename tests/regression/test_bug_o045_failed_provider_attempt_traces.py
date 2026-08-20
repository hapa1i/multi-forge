"""Regression O045: failed billable provider attempts must leave one lifecycle trace.

Root causes: ``server.py`` and ``responses_passthrough.py`` recorded cost and metrics after a provider dispatch failed
without recording the same attempt in provider-trace telemetry. The non-200 Responses seam also discarded the observed
response lifecycle, causing trace explanation to misreport that the request had not left Forge. A later marker placed
before adapter validation then mislabeled local request rejection as provider dispatch.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import forge.proxy.responses_passthrough as responses_passthrough
from forge.core.ops import explain_provider_trace, render_explanation_lines
from forge.core.ops.context import ExecutionContext
from forge.proxy.client_adapter import CoreLLMClientAdapter
from forge.proxy.converters import RequestConversionError
from forge.proxy.data_models import Message, MessagesRequest
from tests.fixtures.proxy_transport import FakeStream, ProxyTransportFake

pytestmark = pytest.mark.regression


class _RequestState:
    request_id = "req_o045_messages"
    downstream_event_id = "ds_o045_messages"
    forge_run_id = "run_o045"
    forge_root_run_id = "root_o045"
    forge_session = "session_o045"
    forge_command = "session"


class _RawRequest:
    state = _RequestState()
    headers: dict[str, str] = {}


class _ProxyConfig:
    intercept = None
    backend = "openrouter"
    logging = None
    default_tier = "sonnet"
    preferred_provider = "openai"

    @staticmethod
    def get_provider() -> SimpleNamespace:
        return SimpleNamespace(tier_overrides={})


def _message_request(*, stream: bool = False, temperature: float | None = None) -> MessagesRequest:
    return MessagesRequest(
        model="openai/gpt-5.5",
        max_tokens=16,
        stream=stream,
        temperature=temperature,
        messages=[Message(role="user", content="hello")],
    )


def _install_message_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    client: Any | None = None,
    completion_error: Exception | None = None,
    conversion_error: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], AsyncMock, AsyncMock]:
    import forge.proxy.server as server

    traces: list[dict[str, Any]] = []
    costs: list[dict[str, Any]] = []

    async def _complete(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        on_provider_dispatch = kwargs.get("on_provider_dispatch")
        if on_provider_dispatch is not None:
            on_provider_dispatch()
        if completion_error is not None:
            raise completion_error
        return {}

    completion = AsyncMock(side_effect=_complete)
    test_client = client if client is not None else SimpleNamespace(create_completion=completion)
    get_client = AsyncMock(return_value=test_client)

    async def _no_op_async(*_args: Any, **_kwargs: Any) -> None:
        return None

    def _convert(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        if conversion_error:
            raise RequestConversionError("cannot preserve request")
        return {"messages": [{"role": "user", "content": "hello"}]}

    def _capture_cost(**kwargs: Any) -> int:
        costs.append(kwargs)
        return 0

    monkeypatch.setattr(server, "_ensure_runtime_state", lambda: None)
    monkeypatch.setattr(server, "PROXY_ID", "proxy_o045")
    monkeypatch.setattr(server, "cost_tracker", None)
    monkeypatch.setattr(server.config, "proxy", _ProxyConfig())
    monkeypatch.setattr(
        server,
        "_resolve_model_with_alternatives",
        lambda _request: SimpleNamespace(
            tier="sonnet",
            tier_source="explicit",
            model="openai/gpt-5.5",
            explicit_backend=True,
        ),
    )
    monkeypatch.setattr(
        server.client_factory, "detect_provider_for_model", lambda _model: SimpleNamespace(value="openai")
    )
    monkeypatch.setattr(server.client_factory, "get_client", get_client)
    monkeypatch.setattr(server, "convert_anthropic_to_openai", _convert)
    monkeypatch.setattr(server, "resolve_reasoning_effort", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "_check_client_tool_failures", _no_op_async)
    monkeypatch.setattr(server, "_inject_provider_user_enabled", lambda: False)
    monkeypatch.setattr(server, "_provider_user_value", lambda **_kwargs: None)
    monkeypatch.setattr(server, "_calc_and_log_cost", _capture_cost)
    monkeypatch.setattr(server.proxy_metrics, "record_request", lambda **_kwargs: None)
    monkeypatch.setattr(server, "log_request_response", _no_op_async)
    monkeypatch.setattr(server, "log_request_beautifully", lambda **_kwargs: None)
    monkeypatch.setattr(server, "record_provider_trace", lambda **kwargs: traces.append(kwargs))
    return traces, costs, get_client, completion


def _responses_trace_context(request_id: str) -> dict[str, Any]:
    return {
        "backend_id": "codex-responses-local",
        "proxy_id": "proxy_o045",
        "mapped_model": "openai/gpt-5.5-codex",
        "request_id": request_id,
        "forge_run_id": "run_o045",
        "forge_root_run_id": "root_o045",
        "provider_session_id": "session_o045",
        "provider_command": "session",
        "downstream_event_id": f"ds_{request_id}",
    }


def _assert_incomplete_trace(
    trace: dict[str, Any],
    *,
    request_mode: str,
    downstream_event_id: str,
    stream_started: bool = False,
    reported_cost_micros: int | None = None,
) -> None:
    assert trace["request_mode"] == request_mode
    assert trace["stream_started"] is stream_started
    assert trace["first_chunk_seen"] is False
    assert trace["final_usage_seen"] is False
    assert trace["client_disconnected"] is False
    assert trace["reported_cost_micros"] == reported_cost_micros
    assert trace["downstream_event_id"] == downstream_event_id


@pytest.mark.asyncio
async def test_messages_provider_call_failure_records_one_joined_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    import forge.proxy.server as server

    traces, costs, _get_client, completion = _install_message_stubs(
        monkeypatch,
        completion_error=RuntimeError("upstream unavailable"),
    )

    with pytest.raises(HTTPException) as raised:
        await server.create_message(_message_request(), cast(Any, _RawRequest()))

    assert raised.value.status_code == 500
    completion.assert_awaited_once()
    assert len(costs) == 1
    assert costs[0]["failed"] is True
    assert costs[0]["downstream_event_id"] == "ds_o045_messages"
    assert len(traces) == 1
    _assert_incomplete_trace(
        traces[0],
        request_mode="non_streaming",
        downstream_event_id="ds_o045_messages",
    )


@pytest.mark.asyncio
async def test_messages_pre_dispatch_conversion_failure_remains_trace_free(monkeypatch: pytest.MonkeyPatch) -> None:
    import forge.proxy.server as server

    traces, costs, get_client, completion = _install_message_stubs(monkeypatch, conversion_error=True)

    with pytest.raises(HTTPException) as raised:
        await server.create_message(_message_request(), cast(Any, _RawRequest()))

    assert raised.value.status_code == 400
    get_client.assert_not_awaited()
    completion.assert_not_awaited()
    assert costs == []
    assert traces == []


@pytest.mark.asyncio
async def test_messages_adapter_validation_before_dispatch_remains_trace_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import forge.proxy.server as server

    upstream_complete = AsyncMock()
    adapter = CoreLLMClientAdapter.__new__(CoreLLMClientAdapter)
    adapter.model_name = "openai/gpt-5.5"
    adapter.max_tokens_override = None
    adapter._client = MagicMock(complete=upstream_complete)  # type: ignore[assignment]
    traces, costs, _get_client, _completion = _install_message_stubs(monkeypatch, client=adapter)

    with pytest.raises(HTTPException) as raised:
        await server.create_message(_message_request(temperature=3.0), cast(Any, _RawRequest()))

    assert raised.value.status_code == 500
    upstream_complete.assert_not_awaited()
    assert len(costs) == 1
    assert traces == []


@pytest.mark.asyncio
async def test_messages_streaming_adapter_validation_before_dispatch_remains_trace_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import forge.proxy.server as server

    upstream_stream = MagicMock()
    adapter = CoreLLMClientAdapter.__new__(CoreLLMClientAdapter)
    adapter.model_name = "openai/gpt-5.5"
    adapter.max_tokens_override = None
    adapter._client = MagicMock(stream=upstream_stream)  # type: ignore[assignment]
    traces, costs, _get_client, _completion = _install_message_stubs(monkeypatch, client=adapter)

    response = await server.create_message(
        _message_request(stream=True, temperature=3.0),
        cast(Any, _RawRequest()),
    )
    _ = [chunk async for chunk in response.body_iterator]

    assert response.status_code == 200
    upstream_stream.assert_not_called()
    assert len(costs) == 1
    assert traces == []


@pytest.mark.asyncio
async def test_responses_non_stream_request_failure_records_one_trace(
    monkeypatch: pytest.MonkeyPatch,
    responses_provider_traces: list[dict[str, Any]],
) -> None:
    transport = ProxyTransportFake(request_error=responses_passthrough.httpx.ConnectError("request failed"))
    monkeypatch.setattr(responses_passthrough.httpx, "AsyncClient", transport.client)
    completions: list[tuple[bool, str | None]] = []

    response = await responses_passthrough.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "openai/gpt-5.5-codex", "input": "hello"},
        query_string="",
        inbound_headers={},
        base_url="https://upstream.test",
        api_key="key",
        request_id="req_o045_nonstream",
        on_complete=lambda _u, _c, failed, error: completions.append((failed, error)),
        provider_trace_ctx=_responses_trace_context("req_o045_nonstream"),
    )

    assert response.status_code == 502
    assert completions == [(True, "upstream_error")]
    assert len(responses_provider_traces) == 1
    _assert_incomplete_trace(
        responses_provider_traces[0],
        request_mode="non_streaming",
        downstream_event_id="ds_req_o045_nonstream",
    )


@pytest.mark.asyncio
async def test_responses_stream_open_failure_records_one_trace(
    monkeypatch: pytest.MonkeyPatch,
    responses_provider_traces: list[dict[str, Any]],
) -> None:
    transport = ProxyTransportFake(
        stream_response=FakeStream(enter_error=responses_passthrough.httpx.ConnectError("open failed"))
    )
    monkeypatch.setattr(responses_passthrough.httpx, "AsyncClient", transport.client)

    response = await responses_passthrough.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "openai/gpt-5.5-codex", "input": "hello", "stream": True},
        query_string="",
        inbound_headers={},
        base_url="https://upstream.test",
        api_key="key",
        request_id="req_o045_open",
        on_complete=lambda _u, _c, _failed, _error: None,
        provider_trace_ctx=_responses_trace_context("req_o045_open"),
    )

    assert response.status_code == 502
    assert len(responses_provider_traces) == 1
    _assert_incomplete_trace(
        responses_provider_traces[0],
        request_mode="streaming",
        downstream_event_id="ds_req_o045_open",
    )


@pytest.mark.asyncio
async def test_responses_stream_context_construction_failure_remains_trace_free(
    monkeypatch: pytest.MonkeyPatch,
    responses_provider_traces: list[dict[str, Any]],
) -> None:
    transport = ProxyTransportFake(stream_error=responses_passthrough.httpx.ConnectError("context build failed"))
    monkeypatch.setattr(responses_passthrough.httpx, "AsyncClient", transport.client)

    response = await responses_passthrough.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "openai/gpt-5.5-codex", "input": "hello", "stream": True},
        query_string="",
        inbound_headers={},
        base_url="https://upstream.test",
        api_key="key",
        request_id="req_o045_context",
        on_complete=lambda _u, _c, _failed, _error: None,
        provider_trace_ctx=_responses_trace_context("req_o045_context"),
    )

    assert response.status_code == 502
    assert responses_provider_traces == []


@pytest.mark.asyncio
async def test_responses_non_200_stream_records_cost_without_changing_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream_body = b'{"error":{"message":"rate limited"}}'
    responses_provider_traces: list[dict[str, Any]] = []
    real_record_provider_trace = responses_passthrough.record_provider_trace

    def _capture_and_record(**kwargs: Any) -> None:
        responses_provider_traces.append(kwargs)
        real_record_provider_trace(**kwargs)

    monkeypatch.setattr(responses_passthrough, "record_provider_trace", _capture_and_record)
    transport = ProxyTransportFake(
        stream_response=FakeStream(
            status_code=429,
            chunks=(upstream_body,),
            headers={
                "content-type": "application/json",
                "x-litellm-response-cost": "0.000321",
            },
        )
    )
    monkeypatch.setattr(responses_passthrough.httpx, "AsyncClient", transport.client)

    response = await responses_passthrough.forward(
        method="POST",
        url_path="/v1/responses",
        body={"model": "openai/gpt-5.5-codex", "input": "hello", "stream": True},
        query_string="",
        inbound_headers={},
        base_url="https://upstream.test",
        api_key="key",
        request_id="req_o045_non200",
        on_complete=lambda _u, _c, _failed, _error: None,
        provider_trace_ctx=_responses_trace_context("req_o045_non200"),
    )

    assert response.status_code == 429
    assert response.body == upstream_body
    assert len(responses_provider_traces) == 1
    _assert_incomplete_trace(
        responses_provider_traces[0],
        request_mode="streaming",
        downstream_event_id="ds_req_o045_non200",
        stream_started=True,
        reported_cost_micros=321,
    )

    explanation = explain_provider_trace(ctx=ExecutionContext.from_cwd(), request_id="req_o045_non200")
    assert explanation.left_forge is True
    rendered = "\n".join(render_explanation_lines(explanation))
    assert "left Forge via proxy proxy_o045" in rendered
    assert "Stream started; final usage was not observed." in rendered

"""Regression for D053: provider conversion failures exposed response data in logs.

Both response-conversion catch-alls rendered exception messages and tracebacks in
ordinary proxy logs, and the nested streaming error-delivery handler also rendered its
exception. Pydantic validation details and arbitrary streaming failures can carry
provider-controlled plaintext.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Callable
from typing import Any

import pytest

from forge.proxy.converters import (
    convert_openai_to_anthropic,
    convert_openai_to_anthropic_sse,
)
from forge.proxy.data_models import Message, MessagesRequest

pytestmark = pytest.mark.regression

_LOGGER_NAME = "forge.proxy.converters"
_NON_STREAM_CANARY = "D053NSCANARY"
_STREAM_CANARY = "D053_STREAM_PROVIDER_CANARY"
_DELIVERY_CANARY = "D053_STREAM_DELIVERY_CANARY"
_REQUEST_ID = "req_d053"


def _log_text(caplog: pytest.LogCaptureFixture) -> str:
    return caplog.text


def _request() -> MessagesRequest:
    return MessagesRequest(
        model="claude-sonnet-4-6",
        messages=[Message(role="user", content="hello")],
        max_tokens=16,
        stream=True,
    )


async def _raise_after(chunks: list[dict[str, Any]], error: Exception) -> AsyncGenerator[dict[str, Any], None]:
    for chunk in chunks:
        yield chunk
    raise error


async def _drain_stream(
    response_generator: AsyncGenerator[dict[str, Any], None],
    on_complete: Callable[[dict[str, Any], bool, str | None], None],
) -> list[str]:
    return [
        event
        async for event in convert_openai_to_anthropic_sse(
            response_generator,
            _request(),
            _REQUEST_ID,
            on_complete=on_complete,
        )
    ]


def test_non_streaming_conversion_error_log_is_metadata_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    response = {
        "id": {"provider_value": _NON_STREAM_CANARY},
        "request_id": _REQUEST_ID,
        "choices": [],
        "usage": {},
    }

    converted = convert_openai_to_anthropic(response, "claude-sonnet-4-6")
    log_text = _log_text(caplog)

    # O007 replaces D053's temporary assistant fallback with an explicit failure
    # signal; the diagnostic boundary remains metadata-only.
    assert converted is None

    assert f"[{_REQUEST_ID}] Failed to convert adapted OpenAI response to Anthropic format" in log_text
    assert "error_type=ValidationError" in log_text
    assert _NON_STREAM_CANARY not in log_text
    assert "Traceback" not in log_text
    assert all(record.exc_info is None for record in caplog.records if record.name == _LOGGER_NAME)


@pytest.mark.asyncio
async def test_streaming_conversion_error_log_is_metadata_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    completions: list[tuple[dict[str, Any], bool, str | None]] = []

    events = await _drain_stream(
        _raise_after([], ValueError(_STREAM_CANARY)),
        lambda usage, failed, error_type: completions.append((usage, failed, error_type)),
    )
    log_text = _log_text(caplog)

    assert events[-2:] == [
        "event: error\ndata: "
        '{"type": "error", "error": {"type": "internal_server_error", "message": "Stream processing error"}}\n\n',
        'event: message_stop\ndata: {"type": "message_stop"}\n\n',
    ]
    assert _STREAM_CANARY not in "".join(events)
    assert len(completions) == 1
    usage, failed, error_type = completions[0]
    assert failed is True
    assert error_type == "internal_error"
    assert usage["_provider_trace"]["lifecycle"] == {
        "stream_started": True,
        "first_chunk_seen": False,
        "final_usage_seen": False,
        "client_disconnected": False,
    }

    assert f"[{_REQUEST_ID}] Error during Anthropic SSE stream conversion" in log_text
    assert "exception_type=ValueError" in log_text
    assert "stream error chunks=0 first_chunk=n final_usage=n error_type=internal_error" in log_text
    assert _STREAM_CANARY not in log_text
    assert "Traceback" not in log_text
    assert all(record.exc_info is None for record in caplog.records if record.name == _LOGGER_NAME)


@pytest.mark.asyncio
async def test_streaming_error_delivery_failure_log_is_metadata_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    completions: list[tuple[dict[str, Any], bool, str | None]] = []
    stream = convert_openai_to_anthropic_sse(
        _raise_after([], ValueError(_STREAM_CANARY)),
        _request(),
        _REQUEST_ID,
        on_complete=lambda usage, failed, error_type: completions.append((usage, failed, error_type)),
    )

    assert (await anext(stream)).startswith("event: message_start\n")
    assert await anext(stream) == 'event: ping\ndata: {"type": "ping"}\n\n'
    assert (await anext(stream)).startswith("event: error\n")
    with pytest.raises(StopAsyncIteration):
        await stream.athrow(RuntimeError(_DELIVERY_CANARY))

    log_text = _log_text(caplog)
    assert f"[{_REQUEST_ID}] Failed to send error event to client; exception_type=RuntimeError" in log_text
    assert _STREAM_CANARY not in log_text
    assert _DELIVERY_CANARY not in log_text
    assert "Traceback" not in log_text
    assert all(record.exc_info is None for record in caplog.records if record.name == _LOGGER_NAME)
    assert len(completions) == 1
    _, failed, error_type = completions[0]
    assert failed is True
    assert error_type == "internal_error"

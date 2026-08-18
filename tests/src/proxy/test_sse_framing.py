"""Contract tests for the shared incremental SSE JSON framer."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol
from unittest.mock import Mock

import pytest

from forge.proxy import passthrough
from forge.proxy import responses_passthrough as responses
from forge.proxy.sse_framing import SseJsonDataFramer


class _FramedAccumulator(Protocol):
    _framer: SseJsonDataFramer

    def feed(self, chunk: bytes) -> None: ...


def test_sse_json_data_framer_delivers_split_and_multiple_events_in_order() -> None:
    events: list[object] = []
    framer = SseJsonDataFramer(events.append)

    framer.feed(b'data: {"kind":"fir')
    assert events == []

    framer.feed(b'st"}\n\ndata: [1, 2]\n\n')
    assert events == [{"kind": "first"}, [1, 2]]


def test_sse_json_data_framer_ignores_noise_without_logging_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[object] = []
    framer = SseJsonDataFramer(events.append)
    payload_canary = "SSE_PAYLOAD_CANARY"

    with caplog.at_level(logging.DEBUG, logger="forge.proxy.sse_framing"):
        framer.feed(b"event: response.completed\r\n")
        framer.feed(b": keep-alive\r\n")
        framer.feed(b"data:\r\n")
        framer.feed(b"data: [DONE]\r\n")
        framer.feed(f"data: {payload_canary}\r\n".encode())
        framer.feed(b'data: \xff{"valid": true}\r\n')

    assert events == [{"valid": True}]
    assert "Ignoring malformed SSE JSON data line" in caplog.text
    assert "Ignoring invalid UTF-8 bytes in SSE chunk" in caplog.text
    assert payload_canary not in caplog.text


@pytest.mark.parametrize(
    "factory",
    [passthrough._UsageAccumulator, responses._ResponsesUsageAccumulator],
    ids=["anthropic", "responses"],
)
def test_passthrough_accumulators_delegate_framing(
    factory: Callable[[], _FramedAccumulator], monkeypatch: pytest.MonkeyPatch
) -> None:
    accumulator = factory()
    feed = Mock()
    monkeypatch.setattr(accumulator._framer, "feed", feed)

    accumulator.feed(b"data: {}\n\n")

    feed.assert_called_once_with(b"data: {}\n\n")

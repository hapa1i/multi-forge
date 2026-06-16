"""Phase 3: provider-trace lifecycle flags + _provider_meta carrier handling at the SSE seam.

The converter packs observed lifecycle into ``final_usage["_provider_trace"]`` for
``_on_stream_complete``; the internal ``_provider_meta`` carrier chunk is consumed (never
emitted to the client); a client disconnect (``CancelledError``/``GeneratorExit``) records
``client_disconnected`` and re-raises.
"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator

import pytest

from forge.proxy.converters import convert_openai_to_anthropic_sse
from forge.proxy.data_models import Message, MessagesRequest

CARRIER: dict[str, Any] = {
    "choices": [],
    "_provider_meta": {"provider": "openrouter", "provider_generation_id": "gen-incident"},
}


def _request() -> MessagesRequest:
    return MessagesRequest(
        model="claude-3-5-sonnet",
        messages=[Message(role="user", content="hi")],
        max_tokens=256,
        stream=True,
    )


async def _gen(chunks: list[dict[str, Any]]) -> AsyncGenerator[dict[str, Any], None]:
    for c in chunks:
        yield c


async def _gen_then_raise(chunks: list[dict[str, Any]], exc: BaseException) -> AsyncGenerator[dict[str, Any], None]:
    for c in chunks:
        yield c
    raise exc


async def _drain(generator: AsyncGenerator[dict[str, Any], None], on_complete: Any) -> list[dict]:
    events = []
    async for sse_text in convert_openai_to_anthropic_sse(generator, _request(), "rid", on_complete=on_complete):
        for block in sse_text.strip().split("\n\n"):
            event_type = data = None
            for line in block.strip().split("\n"):
                if line.startswith("event: "):
                    event_type = line[7:]
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
            if event_type and data:
                events.append({"event": event_type, "data": data})
    return events


def _trace(captured: list) -> dict:
    """Extract the _provider_trace payload from the captured on_complete usage dict."""
    assert len(captured) == 1
    usage = captured[0][0]
    return usage["_provider_trace"]


class TestCleanStream:
    @pytest.mark.asyncio
    async def test_lifecycle_flags_on_clean_text_stream(self) -> None:
        captured: list = []
        chunks: list[dict[str, Any]] = [
            CARRIER,
            {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]},
            {
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        ]
        await _drain(_gen(chunks), lambda u, f, e: captured.append((u, f, e)))
        trace = _trace(captured)
        assert trace["lifecycle"] == {
            "stream_started": True,
            "first_chunk_seen": True,
            "final_usage_seen": True,
            "client_disconnected": False,
        }
        assert trace["provider_meta"] == CARRIER["_provider_meta"]

    @pytest.mark.asyncio
    async def test_carrier_is_consumed_not_emitted_to_client(self) -> None:
        chunks: list[dict[str, Any]] = [CARRIER, {"choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}]}]
        events = await _drain(_gen(chunks), None)
        # No client-facing event carries the internal key.
        for e in events:
            assert "_provider_meta" not in e["data"]
            assert "_provider_meta" not in json.dumps(e)


class TestCarrierSemantics:
    @pytest.mark.asyncio
    async def test_carrier_alone_does_not_set_first_chunk_seen(self) -> None:
        # provider_meta arrives, but no visible text/tool content follows.
        captured: list = []
        chunks = [CARRIER, {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 0}}]
        await _drain(_gen(chunks), lambda u, f, e: captured.append((u, f, e)))
        trace = _trace(captured)
        assert trace["provider_meta"]["provider_generation_id"] == "gen-incident"
        assert trace["lifecycle"]["first_chunk_seen"] is False  # carrier is pre-content
        assert trace["lifecycle"]["final_usage_seen"] is True


class TestDisconnect:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("exc_type", [__import__("asyncio").CancelledError, GeneratorExit])
    async def test_incident_carrier_then_disconnect_before_content(self, exc_type: type[BaseException]) -> None:
        """The incident: provider_meta captured, then the client drops before any content
        and before the final usage chunk. The trace must still carry the generation id and
        flag the disconnect; the exception must propagate (not be swallowed)."""
        captured: list = []
        chunks = [CARRIER]  # carrier only, then the generator raises mid-stream

        with pytest.raises(exc_type):
            await _drain(_gen_then_raise(chunks, exc_type()), lambda u, f, e: captured.append((u, f, e)))

        trace = _trace(captured)
        assert trace["provider_meta"]["provider_generation_id"] == "gen-incident"
        assert trace["lifecycle"] == {
            "stream_started": True,
            "first_chunk_seen": False,
            "final_usage_seen": False,
            "client_disconnected": True,
        }

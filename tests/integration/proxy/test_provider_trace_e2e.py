"""End-to-end: provider-trace fields through the real OpenRouter proxy.

Drives a real streaming request Anthropic -> proxy -> core.llm -> OpenRouter and asserts the
durable downstream attempt record the seam wrote. The clean-stream case proves the whole path
(real SSE -> R1 carrier chunk -> converter lifecycle -> record_provider_trace -> downstream
JSONL shard) with a real ``gen-`` id; the cancel case is the incident this card exists for --
a stream dropped before the final usage chunk that still surfaces its generation id.

The disconnect lifecycle itself is exhaustively unit-tested (both CancelledError and
GeneratorExit) in tests/src/proxy/test_converters_lifecycle.py; this confirms it survives the
real ASGI/httpx teardown and reaches disk.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_HEADERS = {"x-api-key": "test", "user-agent": "claude-code/integration-test"}


def _read_traces(forge_home: Path) -> list[dict[str, Any]]:
    downstream_dir = forge_home / "telemetry" / "downstream"
    raw: list[dict[str, Any]] = []
    if downstream_dir.is_dir():
        for shard in sorted(downstream_dir.glob("*.jsonl")):
            for line in shard.read_text().splitlines():
                line = line.strip()
                if line:
                    raw.append(json.loads(line))
    merged: dict[str, dict[str, Any]] = {}
    ordered: list[str] = []
    for record in raw:
        if record.get("kind") != "attempt":
            continue
        key = str(record.get("downstream_event_id") or record.get("request_id") or len(ordered))
        if key not in merged:
            merged[key] = {}
            ordered.append(key)
        for field, value in record.items():
            if field == "confidence" and value == "unknown" and merged[key].get("confidence") != "unknown":
                continue
            if value is not None:
                merged[key][field] = value
    return [merged[key] for key in ordered]


def _poll_for_trace(
    forge_home: Path, predicate: Callable[[dict[str, Any]], bool], timeout: float = 12.0
) -> dict[str, Any] | None:
    """Poll the trace shards until a record matches (the seam writes after stream teardown)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for rec in _read_traces(forge_home):
            if predicate(rec):
                return rec
        time.sleep(0.25)
    return None


class TestProviderTraceE2E:
    def test_clean_stream_persists_trace_with_generation_id(
        self, proxy_server_openrouter: str, module_forge_home: Path
    ) -> None:
        """A fully-consumed stream writes an 'available' trace carrying the real gen- id."""
        request_id: str | None = None
        with httpx.Client(timeout=60) as client:
            with client.stream(
                "POST",
                f"{proxy_server_openrouter}/v1/messages",
                json={
                    "model": "claude-3-5-haiku-20241022",
                    "max_tokens": 16,
                    "temperature": 0,
                    "stream": True,
                    "messages": [{"role": "user", "content": "Say hello in one word."}],
                },
                headers=_HEADERS,
            ) as resp:
                assert resp.status_code == 200, resp.read()[:300]
                request_id = resp.headers.get("x-request-id")
                for _ in resp.iter_raw():
                    pass  # consume the whole stream → final usage chunk arrives

        def _match(rec: dict[str, Any]) -> bool:
            return rec.get("request_mode") == "streaming" and (
                request_id is None or rec.get("request_id") == request_id
            )

        rec = _poll_for_trace(module_forge_home, _match)
        assert rec is not None, "no provider trace written for the streaming request"
        assert rec["provider"] == "openrouter"
        assert rec["stream_started"] is True
        assert rec["final_usage_seen"] is True
        assert rec["client_disconnected"] is False
        assert rec["local_usage_status"] == "available"
        # The probe-1 surface: OpenRouter's gen- id reaches disk via the carrier chunk.
        assert (rec.get("provider_generation_id") or "").startswith("gen-")
        # Metadata-only: no payload field leaked.
        assert {"messages", "content", "completion", "response_body"}.isdisjoint(rec)

    def test_cancelled_stream_records_disconnect(self, proxy_server_openrouter: str, module_forge_home: Path) -> None:
        """The incident: drop the stream before the final usage chunk. The trace still carries
        the generation id and flags client_disconnected / unavailable."""
        request_id: str | None = None
        with httpx.Client(timeout=60) as client:
            with client.stream(
                "POST",
                f"{proxy_server_openrouter}/v1/messages",
                json={
                    "model": "claude-3-5-haiku-20241022",
                    "max_tokens": 512,  # long enough that we can break mid-stream
                    "temperature": 0,
                    "stream": True,
                    "messages": [{"role": "user", "content": "Count slowly from 1 to 200."}],
                },
                headers=_HEADERS,
            ) as resp:
                assert resp.status_code == 200
                request_id = resp.headers.get("x-request-id")
                saw_content = False
                for raw in resp.iter_raw():
                    if b"content_block_delta" in raw:
                        saw_content = True
                        break  # exit the context → close the connection before final usage
                assert saw_content, "never saw streamed content to cancel after"

        def _match(rec: dict[str, Any]) -> bool:
            return rec.get("request_id") == request_id or (
                request_id is None and rec.get("client_disconnected") is True
            )

        rec = _poll_for_trace(module_forge_home, _match)
        assert rec is not None, "no provider trace written for the cancelled stream"
        assert rec["client_disconnected"] is True
        assert rec["final_usage_seen"] is False
        assert rec["local_usage_status"] == "unavailable"
        # First-seen capture means the gen id survives even though we cancelled early.
        assert (rec.get("provider_generation_id") or "").startswith("gen-")

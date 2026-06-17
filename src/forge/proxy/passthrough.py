"""Anthropic-shaped passthrough forwarding (Phase 2 audit proxy).

Forward the raw Anthropic Messages request to the upstream ``/v1/messages``
endpoint WITHOUT the OpenAI translation round-trip. The default
``openai_translated`` wire shape strips ``thinking``/``redacted_thinking`` blocks
during conversion (converters.py), so signed reasoning does not survive a
round-trip. Passthrough preserves the request and response byte-for-byte, which
is the only signature-safe wire shape.

The forwarding helpers take plain dicts (not a FastAPI ``Request``) so they are
unit-testable without the server. The server resolves config/credentials and
hands the raw body here, plus an ``on_complete`` callback that does spend/cost
accounting once the upstream usage is known (server owns the cost machinery; this
module only extracts usage and forwards bytes).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any

import httpx
from fastapi.responses import Response, StreamingResponse

from forge.proxy.provider_trace_logger import record_provider_trace
from forge.proxy.utils import format_stream_lifecycle_summary

logger = logging.getLogger(__name__)

# (usage, response_body, failed) -> None. response_body is the parsed upstream
# body for non-streaming responses, None for streaming (only usage is tapped).
OnComplete = Callable[[dict[str, int], "dict[str, Any] | None", bool], None]

# Anthropic API behavior flags worth forwarding upstream (not secrets).
_FORWARD_REQUEST_HEADERS = frozenset({"anthropic-version", "anthropic-beta"})

# Long read timeout for slow generations; short connect timeout to fail fast.
_PASSTHROUGH_TIMEOUT = httpx.Timeout(600.0, connect=10.0)

_DEFAULT_ANTHROPIC_VERSION = "2023-06-01"


def build_upstream_headers(inbound: Mapping[str, str], api_key: str) -> dict[str, str]:
    """Build upstream headers: injected credential + forwarded Anthropic API flags.

    The client's inbound credentials (authorization/x-api-key) are never
    forwarded; the proxy injects its own resolved upstream key.
    """
    headers: dict[str, str] = {"content-type": "application/json", "x-api-key": api_key}
    for name, value in inbound.items():
        if name.lower() in _FORWARD_REQUEST_HEADERS:
            headers[name.lower()] = value
    headers.setdefault("anthropic-version", _DEFAULT_ANTHROPIC_VERSION)
    return headers


# --- Usage extraction (best-effort; never alters forwarded bytes) -------------


def _normalize_usage(usage: Any) -> dict[str, int]:
    """Map an Anthropic ``usage`` object onto the cost fields the proxy logs.

    ``cache_read_input_tokens`` is the discounted-read analog of the translated
    path's ``cached_tokens``; cache *creation* is billed as normal input, so it
    is left in ``input_tokens`` rather than counted as cached.
    """
    if not isinstance(usage, Mapping):
        return {}
    out: dict[str, int] = {}
    if usage.get("input_tokens") is not None:
        out["input_tokens"] = int(usage.get("input_tokens") or 0)
    if usage.get("output_tokens") is not None:
        out["output_tokens"] = int(usage.get("output_tokens") or 0)
    if usage.get("cache_read_input_tokens") is not None:
        out["cached_tokens"] = int(usage.get("cache_read_input_tokens") or 0)
    return out


def extract_usage_from_message(payload: Any) -> dict[str, int]:
    """Extract usage from a non-streaming Anthropic Messages response body."""
    if not isinstance(payload, Mapping):
        return {}
    return _normalize_usage(payload.get("usage"))


class _UsageAccumulator:
    """Tolerant SSE side-tap that reconstructs final usage from the event stream.

    Fed a COPY of each forwarded chunk — it must never raise into the stream or
    mutate the bytes the client receives. Anthropic emits initial usage on
    ``message_start`` (input + cache) and the cumulative ``output_tokens`` on the
    final ``message_delta``; this keeps the last value seen for each.
    """

    def __init__(self) -> None:
        self.usage: dict[str, int] = {}
        self._buf = ""
        # Lifecycle side-signals for the Phase 3 provider-trace mirror.
        self.saw_content = False  # first user-visible content_block_start/delta seen
        self.saw_final_usage = False  # final message_delta carried output_tokens

    def feed(self, chunk: bytes) -> None:
        try:
            self._buf += chunk.decode("utf-8", errors="ignore")
        except Exception:  # pragma: no cover - decode is already lenient
            return
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if not data or data == "[DONE]":
                continue
            try:
                event = json.loads(data)
            except (ValueError, TypeError):
                continue
            self._merge(event)

    def _merge(self, event: Any) -> None:
        if not isinstance(event, dict):
            return
        etype = event.get("type")
        if etype == "message_start":
            parsed = _normalize_usage((event.get("message") or {}).get("usage"))
            for key in ("input_tokens", "cached_tokens", "output_tokens"):
                if key in parsed:
                    self.usage[key] = parsed[key]
        elif etype == "message_delta":
            parsed = _normalize_usage(event.get("usage"))
            if "output_tokens" in parsed:  # cumulative; last wins
                self.usage["output_tokens"] = parsed["output_tokens"]
                self.saw_final_usage = True
        elif etype in ("content_block_start", "content_block_delta"):
            self.saw_content = True


# --- Forwarding ---------------------------------------------------------------


async def forward(
    *,
    raw_body: dict[str, Any],
    inbound_headers: Mapping[str, str],
    base_url: str,
    api_key: str,
    request_id: str,
    path: str = "/v1/messages",
    on_complete: OnComplete | None = None,
    extra_headers: Mapping[str, str] | None = None,
    provider_trace_ctx: Mapping[str, Any] | None = None,
) -> Response:
    """Forward a raw Anthropic request to ``{base_url}{path}`` and return the response.

    Streams the response when ``raw_body['stream']`` is truthy. The request body
    is forwarded unchanged (raw dict), so unknown/future fields and historical
    thinking blocks are preserved. ``on_complete(usage, response_body, failed)``
    fires once usage is known (after the response for non-streaming, at stream end
    for streaming) so the caller can log cost and write response-side audit.
    """
    url = base_url.rstrip("/") + path
    headers = build_upstream_headers(inbound_headers, api_key)

    resp_headers: dict[str, str] = {"X-Request-ID": request_id}
    if extra_headers:
        resp_headers.update(extra_headers)

    if raw_body.get("stream"):
        stream_headers = dict(resp_headers)
        stream_headers["Cache-Control"] = "no-cache"
        client_cm = httpx.AsyncClient(timeout=_PASSTHROUGH_TIMEOUT)
        stream_cm = None
        try:
            client = await client_cm.__aenter__()
            stream_cm = client.stream("POST", url, headers=headers, json=raw_body)
            resp = await stream_cm.__aenter__()
        except httpx.HTTPError as e:
            logger.warning("[%s] passthrough upstream stream failed: %s", request_id, e)
            await client_cm.__aexit__(None, None, None)
            _safe_on_complete(on_complete, {}, None, True, request_id)
            return Response(
                status_code=502,
                content=b'{"type":"error","error":{"type":"upstream_error","message":"passthrough upstream stream failed"}}',
                media_type="application/json",
                headers=resp_headers,
            )

        if resp.status_code != 200:
            body = await resp.aread()
            logger.warning("[%s] passthrough upstream %s", request_id, resp.status_code)
            await stream_cm.__aexit__(None, None, None)
            await client_cm.__aexit__(None, None, None)
            _safe_on_complete(on_complete, {}, None, True, request_id)
            return Response(
                status_code=resp.status_code,
                content=body,
                media_type=resp.headers.get("content-type", "application/json"),
                headers=resp_headers,
            )

        return StreamingResponse(
            _stream_opened_upstream(
                client_cm,
                stream_cm,
                resp,
                request_id,
                on_complete=on_complete,
                provider_trace_ctx=provider_trace_ctx,
            ),
            media_type="text/event-stream",
            headers=stream_headers,
        )

    try:
        async with httpx.AsyncClient(timeout=_PASSTHROUGH_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=raw_body)
    except httpx.HTTPError as e:
        logger.warning("[%s] passthrough upstream request failed: %s", request_id, e)
        _safe_on_complete(on_complete, {}, None, True, request_id)
        return Response(
            status_code=502,
            content=b'{"type":"error","error":{"type":"upstream_error","message":"passthrough upstream request failed"}}',
            media_type="application/json",
            headers={"X-Request-ID": request_id},
        )

    failed = resp.status_code >= 400
    if on_complete is not None:
        response_body: dict[str, Any] | None = None
        if "json" in resp.headers.get("content-type", ""):
            try:
                parsed = json.loads(resp.content)
                response_body = parsed if isinstance(parsed, dict) else None
            except (ValueError, TypeError):
                response_body = None
        _safe_on_complete(on_complete, extract_usage_from_message(response_body), response_body, failed, request_id)

    # Return the upstream body unchanged (byte-for-byte) so response thinking
    # blocks / signatures survive for the client's next --resume turn.
    return Response(
        status_code=resp.status_code,
        content=resp.content,
        media_type=resp.headers.get("content-type", "application/json"),
        headers=resp_headers,
    )


async def _stream_opened_upstream(
    client_cm: Any,
    stream_cm: Any,
    resp: httpx.Response,
    request_id: str,
    on_complete: OnComplete | None = None,
    provider_trace_ctx: Mapping[str, Any] | None = None,
) -> AsyncIterator[bytes]:
    """Stream raw SSE bytes from upstream back to the client unchanged.

    Usage is side-tapped from a copy of each chunk; ``on_complete`` fires once at
    stream end (even on early client disconnect, via ``finally``). The same lifecycle
    is mirrored into the provider-trace plane (Phase 3) when ``provider_trace_ctx`` is
    supplied -- latent today (the trace helper gates on direct OpenRouter, which never
    rides the passthrough wire), but ready for a future passthrough-routed provider.
    """
    accumulator = _UsageAccumulator()
    failed = False
    stream_started = False
    client_disconnected = False
    chunk_count = 0
    try:
        async for chunk in resp.aiter_bytes():
            stream_started = True
            chunk_count += 1
            yield chunk  # byte-faithful, unchanged
            accumulator.feed(chunk)  # tolerant side-tap (copy); never alters bytes
    except httpx.HTTPError as e:
        failed = True
        logger.warning("[%s] passthrough upstream stream failed: %s", request_id, e)
        yield b'{"type":"error","error":{"type":"upstream_error","message":"passthrough upstream stream failed"}}'
    except (asyncio.CancelledError, GeneratorExit):
        # Client dropped the relay. Both are BaseException (the httpx.HTTPError handler
        # never sees them); record the disconnect, then re-raise for clean teardown.
        client_disconnected = True
        raise
    finally:
        await stream_cm.__aexit__(None, None, None)
        await client_cm.__aexit__(None, None, None)
        _safe_on_complete(on_complete, accumulator.usage, None, failed, request_id)
        _record_passthrough_trace(
            provider_trace_ctx,
            stream_started=stream_started,
            first_chunk_seen=accumulator.saw_content,
            final_usage_seen=accumulator.saw_final_usage,
            client_disconnected=client_disconnected,
        )
        # Shared compact lifecycle line (proxy_log_hygiene). DEBUG normally; INFO on a
        # client disconnect, which the relay otherwise logs nowhere (the incident class).
        _summary = format_stream_lifecycle_summary(
            request_id,
            first_chunk_seen=accumulator.saw_content,
            final_usage_seen=accumulator.saw_final_usage,
            client_disconnected=client_disconnected,
            failed=failed,
            error_type="upstream_error" if failed else None,
            chunk_count=chunk_count,
        )
        if client_disconnected:
            logger.info(_summary)
        else:
            logger.debug(_summary)


def _record_passthrough_trace(
    provider_trace_ctx: Mapping[str, Any] | None,
    *,
    stream_started: bool,
    first_chunk_seen: bool,
    final_usage_seen: bool,
    client_disconnected: bool,
) -> None:
    """Mirror the passthrough relay's lifecycle into the provider-trace plane (Phase 3).

    Forward-wiring: ``record_provider_trace`` gates on ``provider_name == "openrouter"``
    and passthrough never carries OpenRouter, so this writes nothing today -- the call
    exists so the plane lights up with no seam change once a passthrough-routed provider
    populates ``provider_meta``. Best-effort; never raises into the relay teardown.
    """
    if provider_trace_ctx is None:
        return
    try:
        record_provider_trace(
            **provider_trace_ctx,
            request_mode="streaming",
            provider_meta=None,  # no provider_meta carrier on the Anthropic-native wire
            stream_started=stream_started,
            first_chunk_seen=first_chunk_seen,
            final_usage_seen=final_usage_seen,
            client_disconnected=client_disconnected,
            reported_cost_micros=None,  # passthrough cost is structurally unavailable
            latency_ms=None,
        )
    except Exception as e:
        logger.debug("passthrough provider trace skipped: %s", e)


def _safe_on_complete(
    on_complete: OnComplete | None,
    usage: dict[str, int],
    response_body: dict[str, Any] | None,
    failed: bool,
    request_id: str,
) -> None:
    """Invoke on_complete without ever letting accounting break the response path."""
    if on_complete is None:
        return
    try:
        on_complete(usage, response_body, failed)
    except Exception as e:  # best-effort: cost/audit must not break forwarding
        logger.debug("[%s] passthrough on_complete failed: %s", request_id, e)

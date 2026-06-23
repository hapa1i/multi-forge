"""OpenAI Responses-shaped passthrough forwarding (Codex-facing ingress).

Forward Codex's raw OpenAI Responses traffic to an upstream that serves the
Responses API, WITHOUT translation, so reasoning items survive byte-for-byte
(signature-safe) -- the same rationale as ``passthrough.py`` for Anthropic. The
whole ``/v1/responses*`` surface is method- and body-agnostic: create (streamed),
retrieve, cancel, input_items, delete, compact, input_tokens.

The subtle streaming teardown is shared with the Anthropic passthrough via
``stream_relay.relay_upstream``; this module owns only the Responses-specific
header shape, usage/cost side-tap, and request forwarding. Like ``passthrough``,
the forwarding helpers take plain values (not a FastAPI ``Request``) so they are
unit-testable without the server.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

import httpx
from fastapi.responses import Response, StreamingResponse

from forge.proxy.provider_trace_logger import record_provider_trace
from forge.proxy.stream_relay import relay_upstream
from forge.proxy.utils import format_stream_lifecycle_summary

logger = logging.getLogger(__name__)

# (usage, reported_cost_micros, failed, error_type) -> None. Fires once usage/cost
# are known (after the response for non-streaming, at stream end for streaming).
# error_type is set only when failed (transport error or a terminal response.failed).
OnComplete = Callable[[dict[str, int], "int | None", bool, "str | None"], None]

# Request headers worth forwarding upstream (behavior flags, not secrets). Note
# the absence of authorization/x-api-key AND OpenAI-Organization/OpenAI-Project:
# the proxy's upstream credential owns auth + org/project selection, not the child.
_FORWARD_REQUEST_HEADERS = frozenset({"openai-beta"})

# Upstream response headers NOT relayed to the client: hop-by-hop framing (which
# would corrupt the relayed stream), security-sensitive headers, and proxy-owned
# headers the proxy stamps itself. ``x-request-id`` is proxy-owned -- forwarding
# upstream's too would emit a duplicate, case-insensitively colliding header that
# shadows the proxy's correlation id. Everything else (OpenAI processing-ms,
# version, etc.) is forwarded as useful.
_RESPONSE_HEADER_DENYLIST = frozenset(
    {
        "connection",
        "keep-alive",
        "transfer-encoding",
        "content-length",
        "content-encoding",
        "te",
        "trailer",
        "upgrade",
        "proxy-authenticate",
        "proxy-authorization",
        "set-cookie",
        "www-authenticate",
        "x-request-id",
    }
)

# Long read timeout for slow generations; short connect timeout to fail fast.
_RESPONSES_TIMEOUT = httpx.Timeout(600.0, connect=10.0)

_ERROR_BODY = (
    b'{"type":"error","error":{"type":"upstream_error","message":"responses passthrough upstream stream failed"}}'
)


def build_upstream_headers(inbound: Mapping[str, str], api_key: str) -> dict[str, str]:
    """Build upstream headers: injected Bearer credential + forwarded OpenAI flags.

    The client's inbound credentials (authorization) and any client-supplied
    ``OpenAI-Organization``/``OpenAI-Project`` are never forwarded; the proxy
    injects its own resolved upstream key and owns org/project selection.
    """
    headers: dict[str, str] = {"content-type": "application/json", "authorization": f"Bearer {api_key}"}
    for name, value in inbound.items():
        if name.lower() in _FORWARD_REQUEST_HEADERS:
            headers[name.lower()] = value
    return headers


def relay_response_headers(upstream: Mapping[str, str], request_id: str) -> dict[str, str]:
    """Forward safe upstream response headers, stripping hop-by-hop/security ones."""
    out: dict[str, str] = {"X-Request-ID": request_id}
    for name, value in upstream.items():
        if name.lower() not in _RESPONSE_HEADER_DENYLIST:
            out[name] = value
    return out


def reported_cost_micros_from_headers(headers: Any) -> int | None:
    """Read the LiteLLM-reported cost (USD) from response headers as microdollars.

    Reuses ``cost_from_response_headers`` (lazy import keeps this module light and
    server-free) and converts USD->micros to match the proxy's reported-cost
    convention (client_adapter.py). A negative/absent/malformed value degrades to
    ``None`` (cost 'unavailable'), never a guessed figure.
    """
    from forge.core.llm.clients.litellm import cost_from_response_headers

    usd = cost_from_response_headers(headers)
    if usd is None or usd < 0:
        return None
    return round(usd * 1_000_000)


def _normalize_usage(usage: Any) -> dict[str, int]:
    """Map a Responses ``usage`` object onto the cost fields the proxy logs."""
    if not isinstance(usage, Mapping):
        return {}
    out: dict[str, int] = {}
    if usage.get("input_tokens") is not None:
        out["input_tokens"] = int(usage.get("input_tokens") or 0)
    if usage.get("output_tokens") is not None:
        out["output_tokens"] = int(usage.get("output_tokens") or 0)
    details = usage.get("input_tokens_details")
    if isinstance(details, Mapping) and details.get("cached_tokens") is not None:
        out["cached_tokens"] = int(details.get("cached_tokens") or 0)
    return out


def extract_usage_from_response(payload: Any) -> dict[str, int]:
    """Extract usage from a non-streaming Responses object body."""
    if not isinstance(payload, Mapping):
        return {}
    return _normalize_usage(payload.get("usage"))


def _failure_from_terminal_status(status: str | None) -> tuple[bool, str | None]:
    """Map a Responses terminal status to ``(failed, error_type)`` for metrics.

    A terminal ``failed`` status on an HTTP 200 is a real generation failure (the
    transport succeeded but the model run did not), so it must not be recorded as a
    success. ``incomplete`` is a normal early stop (e.g. ``max_output_tokens`` or a
    content filter): tokens were generated and billed, so it is a partial success,
    not a failure. Unknown/None -> not failed (fail-open, matching the side-tap's
    tolerance -- a missing terminal event should not invent a failure).
    """
    if status == "failed":
        return True, "response_failed"
    return False, None


class _ResponsesUsageAccumulator:
    """Tolerant Responses-SSE side-tap that reconstructs final usage.

    Fed a COPY of each forwarded chunk -- must never raise into the stream or
    mutate the bytes. The terminal ``response.completed`` event carries the
    Responses object (with ``usage``); content/tool deltas mark first-chunk-seen.
    Cost is header-based (not in the SSE), so ``reported_cost_micros`` stays None
    here and the forwarder supplies it from the response headers.
    """

    def __init__(self) -> None:
        self.usage: dict[str, int] = {}
        self._buf = ""
        self.first_chunk_seen = False
        self.final_usage_seen = False
        self.reported_cost_micros: int | None = None
        # Terminal application outcome (completed | incomplete | failed | None),
        # distinct from transport success -- a 200 stream can still end in failed.
        self.terminal_status: str | None = None

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
        if etype in ("response.output_text.delta", "response.output_item.added"):
            self.first_chunk_seen = True
        elif etype in ("response.completed", "response.incomplete", "response.failed"):
            self.terminal_status = etype.split(".", 1)[1]  # completed | incomplete | failed
            response_obj = event.get("response")
            parsed = _normalize_usage(response_obj.get("usage") if isinstance(response_obj, Mapping) else None)
            if parsed:
                self.usage = parsed
                self.final_usage_seen = True


async def forward(
    *,
    method: str,
    url_path: str,
    body: dict[str, Any] | None,
    query_string: str,
    inbound_headers: Mapping[str, str],
    base_url: str,
    api_key: str,
    request_id: str,
    on_complete: OnComplete | None = None,
    provider_trace_ctx: Mapping[str, Any] | None = None,
) -> Response:
    """Forward a raw Responses-API request to ``{base_url}{url_path}``.

    Method-aware and body-optional: bodyless ``GET``/``DELETE`` (retrieve, etc.)
    send no JSON; ``POST`` create streams when ``body['stream']`` is truthy. The
    query string is preserved. ``on_complete(usage, reported_cost_micros, failed,
    error_type)`` fires once usage/cost are known so the caller can log cost + audit;
    pass ``on_complete=None`` for non-generation endpoints that must not be accounted.
    """
    url = base_url.rstrip("/") + url_path
    if query_string:
        url = f"{url}?{query_string}"
    headers = build_upstream_headers(inbound_headers, api_key)
    is_stream = body is not None and bool(body.get("stream"))

    if is_stream:
        return await _forward_streaming(
            url=url,
            body=body,
            headers=headers,
            request_id=request_id,
            on_complete=on_complete,
            provider_trace_ctx=provider_trace_ctx,
        )

    try:
        async with httpx.AsyncClient(timeout=_RESPONSES_TIMEOUT) as client:
            resp = await client.request(method, url, headers=headers, json=body if body is not None else None)
    except httpx.HTTPError as e:
        logger.warning("[%s] responses passthrough upstream request failed: %s", request_id, e)
        _safe_on_complete(on_complete, {}, None, True, "upstream_error", request_id)
        return Response(
            status_code=502,
            content=_ERROR_BODY,
            media_type="application/json",
            headers={"X-Request-ID": request_id},
        )

    if on_complete is not None:
        response_body: dict[str, Any] | None = None
        if "json" in resp.headers.get("content-type", ""):
            try:
                parsed = json.loads(resp.content)
                response_body = parsed if isinstance(parsed, dict) else None
            except (ValueError, TypeError):
                response_body = None
        # Fail on transport status OR a terminal application status of "failed"
        # (a 200 body can still carry "status": "failed").
        status_failed, status_error = _failure_from_terminal_status(
            (response_body or {}).get("status") if isinstance(response_body, Mapping) else None
        )
        http_failed = resp.status_code >= 400
        _safe_on_complete(
            on_complete,
            extract_usage_from_response(response_body),
            reported_cost_micros_from_headers(resp.headers),
            http_failed or status_failed,
            "upstream_error" if http_failed else status_error,
            request_id,
        )

    return Response(
        status_code=resp.status_code,
        content=resp.content,
        media_type=resp.headers.get("content-type", "application/json"),
        headers=relay_response_headers(resp.headers, request_id),
    )


async def _forward_streaming(
    *,
    url: str,
    body: dict[str, Any] | None,
    headers: Mapping[str, str],
    request_id: str,
    on_complete: OnComplete | None,
    provider_trace_ctx: Mapping[str, Any] | None,
) -> Response:
    client_cm = httpx.AsyncClient(timeout=_RESPONSES_TIMEOUT)
    stream_cm = None
    try:
        client = await client_cm.__aenter__()
        stream_cm = client.stream("POST", url, headers=headers, json=body)
        resp = await stream_cm.__aenter__()
    except httpx.HTTPError as e:
        logger.warning("[%s] responses passthrough upstream stream failed: %s", request_id, e)
        await client_cm.__aexit__(None, None, None)
        _safe_on_complete(on_complete, {}, None, True, "upstream_error", request_id)
        return Response(
            status_code=502,
            content=_ERROR_BODY,
            media_type="application/json",
            headers={"X-Request-ID": request_id},
        )

    if resp.status_code != 200:
        upstream_body = await resp.aread()
        logger.warning("[%s] responses passthrough upstream %s", request_id, resp.status_code)
        await stream_cm.__aexit__(None, None, None)
        await client_cm.__aexit__(None, None, None)
        _safe_on_complete(on_complete, {}, None, True, "upstream_error", request_id)
        return Response(
            status_code=resp.status_code,
            content=upstream_body,
            media_type=resp.headers.get("content-type", "application/json"),
            headers=relay_response_headers(resp.headers, request_id),
        )

    # Cost is on the response headers (x-litellm-response-cost), known at open.
    cost_micros = reported_cost_micros_from_headers(resp.headers)
    accumulator = _ResponsesUsageAccumulator()

    def _on_end(*, failed: bool, client_disconnected: bool, stream_started: bool, chunk_count: int) -> None:
        # `failed` here is transport-only; fold in the terminal application status so
        # a 200 stream ending in response.failed is not recorded as a success.
        status_failed, status_error = _failure_from_terminal_status(accumulator.terminal_status)
        combined_failed = failed or status_failed
        error_type = "upstream_error" if failed else status_error
        _safe_on_complete(on_complete, accumulator.usage, cost_micros, combined_failed, error_type, request_id)
        _record_responses_trace(
            provider_trace_ctx,
            stream_started=stream_started,
            first_chunk_seen=accumulator.first_chunk_seen,
            final_usage_seen=accumulator.final_usage_seen,
            client_disconnected=client_disconnected,
            reported_cost_micros=cost_micros,
        )
        _summary = format_stream_lifecycle_summary(
            request_id,
            first_chunk_seen=accumulator.first_chunk_seen,
            final_usage_seen=accumulator.final_usage_seen,
            client_disconnected=client_disconnected,
            failed=combined_failed,
            error_type=error_type,
            chunk_count=chunk_count,
        )
        if client_disconnected:
            logger.info(_summary)
        else:
            logger.debug(_summary)

    stream_headers = relay_response_headers(resp.headers, request_id)
    stream_headers["Cache-Control"] = "no-cache"
    return StreamingResponse(
        relay_upstream(
            client_cm,
            stream_cm,
            resp,
            request_id,
            accumulator=accumulator,
            on_end=_on_end,
            error_body=_ERROR_BODY,
        ),
        media_type="text/event-stream",
        headers=stream_headers,
    )


def _record_responses_trace(
    provider_trace_ctx: Mapping[str, Any] | None,
    *,
    stream_started: bool,
    first_chunk_seen: bool,
    final_usage_seen: bool,
    client_disconnected: bool,
    reported_cost_micros: int | None,
) -> None:
    """Mirror the Responses relay's lifecycle into the provider-trace plane.

    ``record_provider_trace`` gates on source capability; best-effort, never
    raises into the relay teardown.
    """
    if provider_trace_ctx is None:
        return
    try:
        record_provider_trace(
            **provider_trace_ctx,
            request_mode="streaming",
            provider_meta=None,
            stream_started=stream_started,
            first_chunk_seen=first_chunk_seen,
            final_usage_seen=final_usage_seen,
            client_disconnected=client_disconnected,
            reported_cost_micros=reported_cost_micros,
            latency_ms=None,
        )
    except Exception as e:
        logger.debug("responses passthrough provider trace skipped: %s", e)


def _safe_on_complete(
    on_complete: OnComplete | None,
    usage: dict[str, int],
    reported_cost_micros: int | None,
    failed: bool,
    error_type: str | None,
    request_id: str,
) -> None:
    """Invoke on_complete without letting accounting break the response path."""
    if on_complete is None:
        return
    try:
        on_complete(usage, reported_cost_micros, failed, error_type)
    except Exception as e:  # best-effort: cost/audit must not break forwarding
        logger.debug("[%s] responses passthrough on_complete failed: %s", request_id, e)

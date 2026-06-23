"""Wire-agnostic SSE byte-relay core shared by the passthrough wire shapes.

Both ``anthropic_passthrough`` and ``openai_responses_passthrough`` relay raw
upstream SSE bytes to the client unchanged and side-tap usage from a copy of each
chunk. The subtle part -- the stream/client context-manager teardown,
client-disconnect handling, and the once-only end callback in ``finally`` -- lives
here so neither wire duplicates it. The wire-specific event parsing lives in each
wire's accumulator; the wire-specific cost/trace lives in each wire's ``on_end``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)


class StreamUsageAccumulator(Protocol):
    """Tolerant SSE side-tap fed a COPY of each forwarded chunk.

    Implementations must never raise into the relay or mutate forwarded bytes.
    ``feed`` parses events; the remaining fields are read by the wire's ``on_end``.
    """

    usage: dict[str, int]
    reported_cost_micros: int | None

    @property
    def first_chunk_seen(self) -> bool: ...

    @property
    def final_usage_seen(self) -> bool: ...

    def feed(self, chunk: bytes) -> None: ...


# on_end(*, failed, client_disconnected, stream_started, chunk_count) -> None.
# Invoked exactly once in the relay's finally (even on early client disconnect).
StreamEndCallback = Callable[..., None]


async def relay_upstream(
    client_cm: Any,
    stream_cm: Any,
    resp: httpx.Response,
    request_id: str,
    *,
    accumulator: StreamUsageAccumulator,
    on_end: StreamEndCallback,
    error_body: bytes,
) -> AsyncIterator[bytes]:
    """Relay raw SSE bytes upstream->client unchanged, feeding ``accumulator``.

    ``on_end`` fires once in ``finally`` with the lifecycle flags so the caller can
    do cost/metrics/provider-trace. ``error_body`` is the wire-shaped error frame
    yielded if the upstream stream itself errors mid-flight. Client disconnect
    (``CancelledError``/``GeneratorExit``) is recorded and re-raised for clean
    teardown -- never swallowed.
    """
    failed = False
    stream_started = False
    client_disconnected = False
    chunk_count = 0
    try:
        async for chunk in resp.aiter_bytes():
            stream_started = True
            chunk_count += 1
            yield chunk  # byte-faithful, unchanged
            try:
                accumulator.feed(chunk)  # tolerant side-tap (copy); never alters bytes
            except Exception:
                # Defense-in-depth: the Protocol promises feed never raises, but the
                # byte relay must not depend on that -- a side-tap bug on one chunk must
                # not corrupt the stream. NOT BaseException: client disconnect
                # (CancelledError/GeneratorExit) must still propagate to the handler below.
                logger.debug("[%s] passthrough usage side-tap raised; continuing relay", request_id)
    except httpx.HTTPError as e:
        failed = True
        logger.warning("[%s] passthrough upstream stream failed: %s", request_id, e)
        yield error_body
    except (asyncio.CancelledError, GeneratorExit):
        # Client dropped the relay. Both are BaseException (the httpx.HTTPError
        # handler never sees them); record the disconnect, then re-raise.
        client_disconnected = True
        raise
    finally:
        await stream_cm.__aexit__(None, None, None)
        await client_cm.__aexit__(None, None, None)
        on_end(
            failed=failed,
            client_disconnected=client_disconnected,
            stream_started=stream_started,
            chunk_count=chunk_count,
        )

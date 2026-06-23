"""Unit tests for the shared SSE byte-relay core (``stream_relay``).

Focus: the relay's defense-in-depth contract -- a side-tap accumulator that raises on
``feed()`` must never corrupt the byte stream or skip the once-only end callback. Both
passthrough wire shapes (Anthropic + Responses) share this relay, so the guard protects
every streamed generation, not just one wire.
"""

from __future__ import annotations

import pytest

from forge.proxy.stream_relay import relay_upstream


class _RaisingAccumulator:
    """A side-tap whose ``feed`` always raises -- the relay must absorb it."""

    usage: dict[str, int] = {}
    reported_cost_micros: int | None = None
    first_chunk_seen: bool = False
    final_usage_seen: bool = False

    def __init__(self) -> None:
        self.fed = 0

    def feed(self, chunk: bytes) -> None:
        self.fed += 1
        raise ValueError("simulated side-tap bug")


class _FakeCM:
    """Stand-in for the httpx stream/client context managers (teardown only)."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeUpstream:
    """Minimal httpx.Response stand-in exposing just ``aiter_bytes``."""

    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


@pytest.mark.asyncio
async def test_relay_absorbs_accumulator_feed_exception():
    """Issue 4 defense-in-depth: a ``feed`` that raises must not break the byte relay --
    every chunk still reaches the client and ``on_end`` fires once, not-failed."""
    chunks = (b"a", b"b", b"c")
    acc = _RaisingAccumulator()
    ended: list = []

    def _on_end(*, failed, client_disconnected, stream_started, chunk_count):
        ended.append((failed, client_disconnected, stream_started, chunk_count))

    out = b"".join(
        [
            chunk
            async for chunk in relay_upstream(
                _FakeCM(),
                _FakeCM(),
                _FakeUpstream(chunks),  # type: ignore[arg-type]  # fake exposes aiter_bytes, all the relay reads
                "req_guard",
                accumulator=acc,
                on_end=_on_end,
                error_body=b"ERR",
            )
        ]
    )

    assert out == b"abc"  # every chunk relayed despite feed() raising on each
    assert acc.fed == 3  # feed attempted for all chunks (the guard does not short-circuit the loop)
    assert ended == [(False, False, True, 3)]  # on_end once: not failed, not disconnected, all 3 chunks

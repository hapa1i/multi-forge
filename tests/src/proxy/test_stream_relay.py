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


class _TerminalAccumulator:
    """A side-tap that marks final usage as soon as it sees the first chunk."""

    usage: dict[str, int] = {"input_tokens": 1, "output_tokens": 1}
    reported_cost_micros: int | None = None
    first_chunk_seen: bool = False
    final_usage_seen: bool = False

    def feed(self, chunk: bytes) -> None:
        self.first_chunk_seen = True
        self.final_usage_seen = True


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


@pytest.mark.asyncio
async def test_relay_side_taps_chunk_before_yield_to_survive_disconnect_after_terminal_chunk():
    """Regression: if a client disconnects after receiving the terminal usage chunk,
    the side-tap must already have seen that chunk before the generator is closed."""
    acc = _TerminalAccumulator()
    ended: list = []

    def _on_end(*, failed, client_disconnected, stream_started, chunk_count):
        ended.append(
            (
                failed,
                client_disconnected,
                stream_started,
                chunk_count,
                acc.first_chunk_seen,
                acc.final_usage_seen,
            )
        )

    gen = relay_upstream(
        _FakeCM(),
        _FakeCM(),
        _FakeUpstream((b"terminal-usage",)),  # type: ignore[arg-type]
        "req_disconnect_after_terminal",
        accumulator=acc,
        on_end=_on_end,
        error_body=b"ERR",
    )

    assert await gen.__anext__() == b"terminal-usage"
    await gen.aclose()

    assert ended == [(False, True, True, 1, True, True)]

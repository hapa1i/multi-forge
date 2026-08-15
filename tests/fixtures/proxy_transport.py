"""Instance-owned HTTP transport fakes shared by proxy tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CapturedRequest:
    """One outbound request observed by a fake async client."""

    method: str
    url: str
    headers: dict[str, str] | None
    json: Any


@dataclass(slots=True)
class FakeResponse:
    """Configurable stand-in for an httpx non-streaming response."""

    status_code: int = 200
    content: bytes = b""
    headers: dict[str, str] = field(default_factory=lambda: {"content-type": "application/json"})


@dataclass(slots=True)
class FakeStream:
    """Configurable stand-in for an httpx streaming response context manager."""

    status_code: int = 200
    chunks: tuple[bytes, ...] = ()
    headers: dict[str, str] = field(default_factory=lambda: {"content-type": "text/event-stream"})
    read_error: BaseException | None = None
    iteration_error: BaseException | None = None
    enter_error: BaseException | None = None
    exit_count: int = field(default=0, init=False)

    async def __aenter__(self) -> FakeStream:
        if self.enter_error is not None:
            raise self.enter_error
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        self.exit_count += 1
        return False

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk
        if self.iteration_error is not None:
            raise self.iteration_error

    async def aread(self) -> bytes:
        if self.read_error is not None:
            raise self.read_error
        return b"".join(self.chunks)


@dataclass(slots=True)
class ProxyTransportFake:
    """Own fake responses, failures, request capture, and teardown counters per test."""

    response: FakeResponse = field(default_factory=FakeResponse)
    stream_response: FakeStream = field(default_factory=FakeStream)
    request_error: BaseException | None = None
    stream_error: BaseException | None = None
    requests: list[CapturedRequest] = field(default_factory=list)
    client_exit_count: int = field(default=0, init=False)

    @property
    def captured(self) -> CapturedRequest:
        """Return the last request, failing clearly if the transport was not called."""
        if not self.requests:
            raise AssertionError("fake transport captured no request")
        return self.requests[-1]

    def client(self, *_args: object, **_kwargs: object) -> FakeAsyncClient:
        """Build the callable replacement for ``httpx.AsyncClient``."""
        return FakeAsyncClient(self)

    def _capture(self, method: str, url: str, headers: dict[str, str] | None, json: Any) -> None:
        self.requests.append(CapturedRequest(method=method, url=url, headers=headers, json=json))


class FakeAsyncClient:
    """Async-client facade backed by one :class:`ProxyTransportFake` instance."""

    def __init__(self, transport: ProxyTransportFake) -> None:
        self._transport = transport

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        self._transport.client_exit_count += 1
        return False

    async def post(self, url: str, headers: dict[str, str] | None = None, json: Any = None) -> FakeResponse:
        return await self.request("POST", url, headers=headers, json=json)

    async def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json: Any = None,
    ) -> FakeResponse:
        self._transport._capture(method, url, headers, json)
        if self._transport.request_error is not None:
            raise self._transport.request_error
        return self._transport.response

    def stream(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json: Any = None,
    ) -> FakeStream:
        self._transport._capture(method, url, headers, json)
        if self._transport.stream_error is not None:
            raise self._transport.stream_error
        return self._transport.stream_response

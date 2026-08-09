"""Regression for O004: Anthropic passthrough discarded safe upstream response headers."""

from __future__ import annotations

import pytest

from forge.proxy import passthrough

pytestmark = pytest.mark.regression


class _UpstreamResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.content = f'{{"type":"error","status":{status_code}}}'.encode()
        self.headers = {
            "content-type": "application/json",
            "Retry-After": "7",
            "Anthropic-RateLimit-Requests-Remaining": "0",
            "X-Request-ID": "upstream-request-id",
        }

    async def aread(self) -> bytes:
        return self.content


class _StreamContext:
    def __init__(self, response: _UpstreamResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _UpstreamResponse:
        return self._response

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _UpstreamClient:
    status_code = 429

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self._response = _UpstreamResponse(self.status_code)

    async def __aenter__(self) -> _UpstreamClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def post(self, *_args: object, **_kwargs: object) -> _UpstreamResponse:
        return self._response

    def stream(self, *_args: object, **_kwargs: object) -> _StreamContext:
        return _StreamContext(self._response)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [429, 529])
@pytest.mark.parametrize("stream", [False, True])
async def test_bug_o004_anthropic_errors_relay_retry_and_rate_limit_headers(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    stream: bool,
) -> None:
    """Safe control metadata survives alongside the unchanged upstream error response."""

    class _StatusClient(_UpstreamClient):
        pass

    _StatusClient.status_code = status_code
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _StatusClient)

    response = await passthrough.forward(
        raw_body={"model": "claude-opus-4-6", "stream": stream, "messages": []},
        inbound_headers={},
        base_url="https://api.anthropic.test",
        api_key="test-key",
        request_id="forge-request-id",
    )

    assert response.status_code == status_code
    assert bytes(response.body) == f'{{"type":"error","status":{status_code}}}'.encode()
    assert response.headers["retry-after"] == "7"
    assert response.headers["anthropic-ratelimit-requests-remaining"] == "0"
    assert response.headers["x-request-id"] == "forge-request-id"

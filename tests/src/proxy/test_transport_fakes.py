"""Contract tests for the shared proxy HTTP transport fake."""

from __future__ import annotations

import pytest

from tests.fixtures.proxy_transport import FakeResponse, FakeStream, ProxyTransportFake


@pytest.mark.asyncio
async def test_proxy_transport_fake_owns_configuration_and_capture_per_instance() -> None:
    first = ProxyTransportFake(
        response=FakeResponse(status_code=201, content=b"first"),
        stream_response=FakeStream(chunks=(b"first-stream",)),
        request_error=RuntimeError("first-only"),
    )
    second = ProxyTransportFake()

    with pytest.raises(RuntimeError, match="first-only"):
        await first.client().request("POST", "https://first.test", json={"owner": "first"})

    assert first.captured.url == "https://first.test"
    assert first.response.status_code == 201
    assert first.stream_response.chunks == (b"first-stream",)
    assert second.requests == []
    assert second.response.status_code == 200
    assert second.stream_response.chunks == ()
    assert second.request_error is None


@pytest.mark.asyncio
async def test_proxy_transport_fake_configures_stream_failures_and_teardown() -> None:
    read_error = RuntimeError("read failed")
    iteration_error = RuntimeError("stream failed")
    stream = FakeStream(chunks=(b"chunk",), read_error=read_error, iteration_error=iteration_error)
    transport = ProxyTransportFake(stream_response=stream, stream_error=RuntimeError("open failed"))

    async with transport.client() as client:
        with pytest.raises(RuntimeError, match="open failed"):
            client.stream("POST", "https://stream.test")
        transport.stream_error = None

        response = client.stream("POST", "https://stream.test")
        response.enter_error = RuntimeError("enter failed")
        with pytest.raises(RuntimeError, match="enter failed"):
            async with response:
                pass
        response.enter_error = None

        async with response:
            chunks = response.aiter_bytes()
            assert await anext(chunks) == b"chunk"
            with pytest.raises(RuntimeError, match="stream failed"):
                await anext(chunks)

            with pytest.raises(RuntimeError, match="read failed"):
                await response.aread()

    assert response.exit_count == 1
    assert transport.client_exit_count == 1

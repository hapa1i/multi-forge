"""Hermetic Anthropic passthrough response-header integration tests."""

from __future__ import annotations

import httpx
import pytest

from tests.integration.proxy.conftest import FakeAnthropicUpstream

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("stream", [False, True])
def test_anthropic_passthrough_relays_safe_error_metadata(
    proxy_server_fake_anthropic_passthrough: tuple[str, FakeAnthropicUpstream],
    stream: bool,
) -> None:
    proxy_base_url, fake_upstream = proxy_server_fake_anthropic_passthrough
    fake_upstream.requests.clear()

    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{proxy_base_url}/v1/messages",
            json={
                "model": "claude-opus-4-6",
                "max_tokens": 16,
                "stream": stream,
                "messages": [{"role": "user", "content": "Say hello"}],
            },
            headers={"x-api-key": "test"},
        )

    assert response.status_code == 529
    assert response.content == fake_upstream.response_body
    assert response.headers["retry-after"] == "11"
    assert response.headers["anthropic-ratelimit-requests-remaining"] == "0"
    assert response.headers["x-request-id"] != "upstream-request-id"
    assert "openai-organization" not in response.headers
    assert "openai-project" not in response.headers
    assert "set-cookie" not in response.headers

    assert len(fake_upstream.requests) == 1
    upstream_request = fake_upstream.requests[0]
    assert upstream_request["path"] == "/v1/messages"
    assert upstream_request["body"]["stream"] is stream
    upstream_headers = {name.lower(): value for name, value in upstream_request["headers"].items()}
    assert upstream_headers["x-api-key"] == "test-anthropic-key"

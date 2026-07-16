"""Hermetic OpenAI-family proxy routing integration tests."""

from __future__ import annotations

import httpx
import pytest

from tests.integration.proxy.conftest import FakeOpenAIUpstream

pytestmark = pytest.mark.integration


def test_litellm_openai_sonnet_forwards_exact_sol_model(
    proxy_server_fake_litellm_openai: tuple[str, FakeOpenAIUpstream],
) -> None:
    """The bundled remote LiteLLM template forwards sonnet to the exact Sol slug."""
    proxy_base_url, fake_upstream = proxy_server_fake_litellm_openai

    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{proxy_base_url}/v1/messages",
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "Say hello"}],
            },
            headers={"x-api-key": "test"},
        )

    assert response.status_code == 200, response.text[:500]
    assert response.headers.get("X-Resolved-Tier") == "sonnet"
    assert response.headers.get("X-Resolved-Model") == "openai/gpt-5.6-sol"
    assert response.json()["content"][0]["text"] == "FAKE-SOL-OK"

    assert len(fake_upstream.requests) == 1
    upstream_request = fake_upstream.requests[0]
    assert upstream_request["path"] == "/v1/responses"
    assert upstream_request["body"]["input"] == [{"role": "user", "content": "Say hello"}]
    assert upstream_request["body"]["max_output_tokens"] == 16
    assert upstream_request["body"]["model"] == "openai/gpt-5.6-sol"
    assert upstream_request["body"]["reasoning"] == {"effort": "medium"}
    assert upstream_request["body"]["text"] == {"verbosity": "high"}

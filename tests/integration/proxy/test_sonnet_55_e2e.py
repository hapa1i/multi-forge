"""Sonnet 5.5 native controls and both translated provider routes."""

import os

import httpx
import pytest

from tests.integration.proxy.conftest import FakeAnthropicUpstream

pytestmark = pytest.mark.integration


def _native_request(body: dict, path: str = "messages") -> httpx.Response:
    key = os.environ.get("ANTHROPIC_API_KEY")
    assert key, "ANTHROPIC_API_KEY is required for the native Sonnet 5.5 gate"
    with httpx.Client(timeout=90) as client:
        return client.post(
            f"https://api.anthropic.com/v1/{path}",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={
                "model": "claude-sonnet-5-5",
                "messages": [{"role": "user", "content": "Reply OK."}],
                **body,
            },
        )


@pytest.mark.slow
@pytest.mark.parametrize("mode", ["adaptive", "between_tools"])
def test_native_sonnet55_accepts_supported_thinking_modes(mode: str) -> None:
    response = _native_request({"max_tokens": 128, "thinking": {"type": mode}, "output_config": {"effort": "low"}})

    assert response.status_code == 200, response.text[:500]
    assert response.json()["model"] == "claude-sonnet-5-5"
    assert response.json()["usage"]["output_tokens"] > 0


@pytest.mark.slow
@pytest.mark.parametrize(
    "controls",
    [
        {"thinking": {"type": "disabled"}},
        {"thinking": {"type": "enabled", "budget_tokens": 1024}},
        {"thinking": {"type": "between_tools"}, "output_config": {"effort": "xhigh"}},
        {"thinking": {"type": "between_tools", "display": "summarized"}},
    ],
)
def test_native_sonnet55_rejects_invalid_thinking_controls(controls: dict) -> None:
    response = _native_request({"max_tokens": 2048, **controls})

    assert response.status_code == 400, response.text[:500]
    assert response.json()["error"]["type"] == "invalid_request_error"


@pytest.mark.slow
@pytest.mark.parametrize("choice", [{"type": "any"}, {"type": "tool", "name": "ping"}])
def test_native_sonnet55_rejects_forced_tools(choice: dict) -> None:
    response = _native_request(
        {
            "tools": [{"name": "ping", "input_schema": {"type": "object", "properties": {}}}],
            "tool_choice": choice,
        },
        "messages/count_tokens",
    )

    assert response.status_code == 400, response.text[:500]
    assert "tool_choice" in response.json()["error"]["message"]


@pytest.mark.slow
@pytest.mark.parametrize(
    ("fixture", "model"),
    [
        ("proxy_server_local_anthropic", "anthropic/claude-sonnet-5-5"),
        ("proxy_server_openrouter", "anthropic/claude-sonnet-5.5"),
    ],
)
@pytest.mark.parametrize("stream", [False, True])
def test_translated_sonnet55_tools_effort_and_sampling(
    request: pytest.FixtureRequest, fixture: str, model: str, stream: bool
) -> None:
    proxy_url = request.getfixturevalue(fixture)
    with httpx.Client(timeout=90) as client:
        response = client.post(
            f"{proxy_url}/v1/messages",
            headers={"x-api-key": "test"},
            json={
                "model": "claude-sonnet",
                "max_tokens": 128,
                "stream": stream,
                "reasoning_effort": "xhigh",
                "temperature": 0.7,
                "top_p": 0.9,
                "messages": [{"role": "user", "content": "Reply OK; no tool is needed."}],
                "tools": [
                    {"name": "ping", "description": "Ping", "input_schema": {"type": "object", "properties": {}}}
                ],
                "tool_choice": {"type": "auto"},
            },
        )

    assert response.status_code == 200, response.text[:500]
    assert response.headers["X-Resolved-Model"] == model
    assert response.headers["X-Resolved-Tier"] == "sonnet"
    if stream:
        assert "event: message_start" in response.text
        assert "event: message_stop" in response.text
        assert "event: error" not in response.text
    else:
        assert response.json()["type"] == "message"
        assert response.json()["usage"]["input_tokens"] > 0


@pytest.mark.parametrize("thinking", [{"type": "adaptive", "display": "summarized"}, {"type": "between_tools"}])
def test_passthrough_preserves_sonnet55_signed_tool_history(
    proxy_server_fake_anthropic_passthrough: tuple[str, FakeAnthropicUpstream], thinking: dict
) -> None:
    proxy_url, upstream = proxy_server_fake_anthropic_passthrough
    upstream.requests.clear()
    body = {
        "model": "claude-sonnet-5-5",
        "max_tokens": 128,
        "thinking": thinking,
        "output_config": {"effort": "high"},
        "tool_choice": {"type": "auto"},
        "tools": [{"name": "ping", "input_schema": {"type": "object", "properties": {}}}],
        "messages": [
            {"role": "user", "content": "Ping"},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "", "signature": "opaque-sonnet-signature"},
                    {"type": "tool_use", "id": "tool_1", "name": "ping", "input": {}},
                ],
            },
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tool_1", "content": "OK"}]},
        ],
    }
    with httpx.Client(timeout=30) as client:
        response = client.post(f"{proxy_url}/v1/messages", json=body)

    assert response.status_code == 529
    assert len(upstream.requests) == 1
    assert upstream.requests[0]["body"] == body
    assert response.content == upstream.response_body

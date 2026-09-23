"""Opus 5.5 native, translated, and passthrough request contracts."""

from __future__ import annotations

import os

import httpx
import pytest

from tests.integration.proxy.conftest import FakeAnthropicUpstream

pytestmark = pytest.mark.integration


@pytest.mark.slow
@pytest.mark.parametrize("choice", [{"type": "any"}, {"type": "tool", "name": "ping"}])
def test_native_opus_55_rejects_forced_tools_on_token_count(choice: dict[str, str]) -> None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    assert key, "ANTHROPIC_API_KEY is required for the native Opus 5.5 gate"
    with httpx.Client(timeout=30) as client:
        response = client.post(
            "https://api.anthropic.com/v1/messages/count_tokens",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={
                "model": "claude-opus-5-5",
                "messages": [{"role": "user", "content": "Ping"}],
                "tools": [{"name": "ping", "input_schema": {"type": "object"}}],
                "tool_choice": choice,
            },
        )

    assert response.status_code == 400, response.text[:500]
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert "tool_choice" in response.json()["error"]["message"]


@pytest.mark.slow
def test_native_opus_55_accepts_effort_without_a_thinking_parameter() -> None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    assert key, "ANTHROPIC_API_KEY is required for the native Opus 5.5 gate"
    with httpx.Client(timeout=90) as client:
        response = client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={
                "model": "claude-opus-5-5",
                "max_tokens": 128,
                "output_config": {"effort": "low"},
                "messages": [{"role": "user", "content": "Reply OK."}],
            },
        )

    assert response.status_code == 200, response.text[:500]
    data = response.json()
    assert data["model"] == "claude-opus-5-5"
    assert data["usage"]["input_tokens"] > 0
    assert data["usage"]["output_tokens"] > 0


@pytest.mark.slow
@pytest.mark.parametrize("thinking", [{"type": "disabled"}, {"type": "enabled", "budget_tokens": 1024}])
def test_native_opus_55_rejects_legacy_thinking_controls(thinking: dict[str, object]) -> None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    assert key, "ANTHROPIC_API_KEY is required for the native Opus 5.5 gate"
    with httpx.Client(timeout=30) as client:
        response = client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={
                "model": "claude-opus-5-5",
                "max_tokens": 2048,
                "thinking": thinking,
                "messages": [{"role": "user", "content": "Reply OK."}],
            },
        )

    assert response.status_code == 400, response.text[:500]
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert "thinking" in response.json()["error"]["message"]


@pytest.mark.slow
@pytest.mark.parametrize("stream", [False, True])
def test_translated_opus_55_tools_and_reasoning(proxy_server_local_anthropic: str, stream: bool) -> None:
    with httpx.Client(timeout=90) as client:
        response = client.post(
            f"{proxy_server_local_anthropic}/v1/messages",
            headers={"x-api-key": "test"},
            json={
                "model": "claude-opus",
                "max_tokens": 128,
                "stream": stream,
                "reasoning_effort": "medium",
                "messages": [{"role": "user", "content": "Reply OK; no tool is needed."}],
                "tools": [
                    {"name": "ping", "description": "Ping", "input_schema": {"type": "object", "properties": {}}}
                ],
                "tool_choice": {"type": "auto"},
            },
        )

    assert response.status_code == 200, response.text[:500]
    assert response.headers["X-Resolved-Model"] == "anthropic/claude-opus-5-5"
    assert response.headers["X-Resolved-Tier"] == "opus"
    if stream:
        assert "event: message_start" in response.text
        assert "event: message_stop" in response.text
        assert "event: error" not in response.text
    else:
        assert response.json()["type"] == "message"
        assert response.json()["usage"]["input_tokens"] > 0


def test_passthrough_preserves_opus_55_thinking_and_tools(
    proxy_server_fake_anthropic_passthrough: tuple[str, FakeAnthropicUpstream],
) -> None:
    proxy_url, upstream = proxy_server_fake_anthropic_passthrough
    upstream.requests.clear()
    body = {
        "model": "claude-opus-5-5",
        "max_tokens": 128,
        "output_config": {"effort": "medium"},
        "tool_choice": {"type": "auto"},
        "tools": [{"name": "ping", "input_schema": {"type": "object"}}],
        "messages": [
            {"role": "user", "content": "Ping"},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "", "signature": "opaque-opus-signature"},
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

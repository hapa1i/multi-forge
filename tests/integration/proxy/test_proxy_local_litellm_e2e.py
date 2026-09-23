"""Basic proxy → local LiteLLM integration tests.

These tests verify the full flow: Anthropic API request → proxy → core.llm → LiteLLM → response.
"""

from __future__ import annotations

import json

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]


class TestProxyWithLocalLiteLLM:
    """Integration tests for proxy → local LiteLLM flow."""

    def test_health_endpoint(self, proxy_server: str) -> None:
        """GET / returns proxy info."""
        with httpx.Client() as client:
            resp = client.get(f"{proxy_server}/")
            assert resp.status_code == 200
            data = resp.json()
            assert data["is_proxy"] is True
            assert data["template"] == "litellm-gemini-test"

    def test_simple_completion(self, proxy_server: str) -> None:
        """POST /v1/messages returns Anthropic-format response."""
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{proxy_server}/v1/messages",
                json={
                    "model": "claude-3-5-haiku-20241022",
                    "max_tokens": 16,
                    "messages": [{"role": "user", "content": "Say hello"}],
                },
                headers={"x-api-key": "test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "content" in data
            assert data["type"] == "message"

    def test_streaming_completion(self, proxy_server: str) -> None:
        """POST /v1/messages with stream=true returns SSE."""
        with httpx.Client(timeout=60) as client:
            with client.stream(
                "POST",
                f"{proxy_server}/v1/messages",
                json={
                    "model": "claude-3-5-haiku-20241022",
                    "max_tokens": 16,
                    "messages": [{"role": "user", "content": "Count 1 2 3"}],
                    "stream": True,
                },
                headers={"x-api-key": "test"},
            ) as resp:
                assert resp.status_code == 200
                events = []
                for line in resp.iter_lines():
                    if line.startswith("data: "):
                        events.append(line)
                assert len(events) > 0


class TestGeminiFlashLiteLLMGate:
    """The locked LiteLLM must serve current and retained Flash routes with cost data.

    Packaged Gemini 3.8 support is verified in LiteLLM 1.102. This live gate proves the
    full Google AI Studio path on the locked version: routing, thinking usage,
    and the gateway cost header. Cost absence is a hard failure. The offline
    packaged-map expectation is pinned in
    tests/src/proxy/test_litellm_gemini_flash_support.py.
    """

    @pytest.mark.parametrize("model", ["gemini-3.7-flash", "gemini-3.8-flash"])
    def test_flash_completion_thinking_and_cost(self, local_litellm_gemini: str, model: str) -> None:
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                f"{local_litellm_gemini}/chat/completions",
                json={
                    "model": f"gemini/{model}",
                    "max_tokens": 512,
                    "reasoning_effort": "low",
                    "messages": [{"role": "user", "content": "What is 17*23? Reply with just the number."}],
                },
            )

        assert resp.status_code == 200, resp.text[:500]
        data = resp.json()
        message = data["choices"][0]["message"]
        assert (message.get("content") or "").strip()

        usage = data["usage"]
        assert usage["completion_tokens"] > 0
        reasoning_tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
        assert reasoning_tokens > 0, f"thinking not engaged: usage={usage}"

        cost = resp.headers.get("x-litellm-response-cost")
        assert cost is not None and float(cost) > 0, f"cost header missing/zero: {cost!r}"

    # Cache accounting for Gemini Flash remains conservatively disabled in the
    # catalog until this exact local LiteLLM path is probed repeatedly.


class TestOpenAIProxyWithLocalLiteLLM:
    """The local OpenAI template can serve its promoted GPT-6 Astra tier."""

    def test_sonnet_completion_resolves_to_gpt_6_astra(self, proxy_server_local_openai: str) -> None:
        with httpx.Client(timeout=90) as client:
            resp = client.post(
                f"{proxy_server_local_openai}/v1/messages",
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 16,
                    "temperature": 0.7,
                    "top_p": 0.8,
                    "messages": [{"role": "user", "content": "Say hello"}],
                },
                headers={"x-api-key": "test"},
            )

        assert resp.status_code == 200, resp.text[:500]
        assert resp.headers.get("X-Resolved-Tier") == "sonnet"
        assert resp.headers.get("X-Resolved-Model") == "openai/gpt-6-astra"

    @pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-6-sol", "gpt-6-luna"])
    def test_gpt6_responses_cost_without_model_metadata_refresh(self, local_litellm_openai: str, model: str) -> None:
        with httpx.Client(timeout=90) as client:
            resp = client.post(
                f"{local_litellm_openai}/v1/responses",
                json={
                    "model": f"openai/{model}",
                    "input": "Say hello",
                    "max_output_tokens": 16,
                    "reasoning": {"effort": "low"},
                },
            )

        assert resp.status_code == 200, resp.text[:500]
        cost = resp.headers.get("x-litellm-response-cost")
        assert cost is not None and float(cost) > 0, f"{model} cost missing without metadata refresh: {cost!r}"

    @pytest.mark.parametrize("model", ["gpt-6-sol", "gpt-6-luna"])
    @pytest.mark.parametrize("stream", [False, True])
    def test_explicit_gpt6_model_preserves_tool_calls(
        self, proxy_server_local_openai: str, model: str, stream: bool
    ) -> None:
        with httpx.Client(timeout=120) as client:
            response = client.post(
                f"{proxy_server_local_openai}/v1/messages",
                json={
                    "model": f"openai/{model}",
                    "max_tokens": 1024,
                    "temperature": 0.7,
                    "top_p": 0.8,
                    "stream": stream,
                    "messages": [{"role": "user", "content": "Call report with value 391."}],
                    "tools": [
                        {
                            "name": "report",
                            "description": "Report a numeric result.",
                            "input_schema": {
                                "type": "object",
                                "properties": {"value": {"type": "integer"}},
                                "required": ["value"],
                            },
                        }
                    ],
                    "tool_choice": {"type": "any"},
                },
                headers={"x-api-key": "test"},
            )

        assert response.status_code == 200, response.text[:500]
        assert response.headers.get("X-Resolved-Model") == f"openai/{model}"
        if stream:
            events = [
                json.loads(line.removeprefix("data: "))
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
            assert not any(event.get("type") == "error" for event in events), events
            assert any(
                event.get("content_block", {}).get("type") == "tool_use"
                and event["content_block"].get("name") == "report"
                for event in events
            ), events
            assert any(event.get("type") == "message_stop" for event in events)
        else:
            assert response.json()["stop_reason"] == "tool_use"
            assert any(
                block.get("type") == "tool_use" and block.get("name") == "report"
                for block in response.json()["content"]
            )

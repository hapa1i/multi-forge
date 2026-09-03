"""Basic proxy → local LiteLLM integration tests.

These tests verify the full flow: Anthropic API request → proxy → core.llm → LiteLLM → response.
"""

from __future__ import annotations

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


class TestGemini37FlashLiteLLMGate:
    """The locked LiteLLM must serve Gemini 3.7 with thinking and cost data.

    Packaged cost-map support starts in LiteLLM 1.98. This live gate proves the
    full Google AI Studio path on the locked version: routing, thinking usage,
    and the gateway cost header. Cost absence is a hard failure. The offline
    packaged-map expectation is pinned in
    tests/src/proxy/test_litellm_gemini_flash_support.py.
    """

    def test_gemini_37_flash_completion_thinking_and_cost(self, local_litellm_gemini: str) -> None:
        with httpx.Client(timeout=120) as client:
            resp = client.post(
                f"{local_litellm_gemini}/chat/completions",
                json={
                    "model": "gemini/gemini-3.7-flash",
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

    # Cache accounting for Gemini 3.7 remains conservatively disabled in the
    # catalog until this exact local LiteLLM path is probed repeatedly.


class TestOpenAIProxyWithLocalLiteLLM:
    """The local OpenAI template can serve its promoted GPT-5.6 Sol tier."""

    def test_sonnet_completion_resolves_to_gpt_56_sol(self, proxy_server_local_openai: str) -> None:
        with httpx.Client(timeout=90) as client:
            resp = client.post(
                f"{proxy_server_local_openai}/v1/messages",
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 16,
                    "messages": [{"role": "user", "content": "Say hello"}],
                },
                headers={"x-api-key": "test"},
            )

        assert resp.status_code == 200, resp.text[:500]
        assert resp.headers.get("X-Resolved-Tier") == "sonnet"
        assert resp.headers.get("X-Resolved-Model") == "openai/gpt-5.6-sol"

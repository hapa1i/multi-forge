"""Proxy to OpenRouter integration tests.

These tests verify the full flow:
Anthropic API request -> proxy routing/conversion -> core.llm -> OpenRouter -> response.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def _anthropic_response_text(data: dict[str, Any]) -> str:
    content = data.get("content", [])
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(block.get("text", "") for block in content if isinstance(block, dict))


class TestProxyWithOpenRouter:
    """Integration tests for proxy to OpenRouter flow."""

    def test_health_endpoint(self, proxy_server_openrouter_offline: str) -> None:
        """GET / returns OpenRouter proxy runtime truth."""
        with httpx.Client() as client:
            resp = client.get(f"{proxy_server_openrouter_offline}/")

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_proxy"] is True
        assert data["template"] == "openrouter-anthropic"
        assert data["provider"] == "openrouter"
        assert data["runtime"]["tier_mappings"]["haiku"] == "anthropic/claude-haiku-4.5"
        assert data["runtime"]["configured_tier_mappings"] == data["runtime"]["tier_mappings"]
        assert data["runtime"]["model_alternatives"]["opus"]["claude-fable-5-1"] == "anthropic/claude-opus-5"
        assert data["runtime"]["data_policy"] == {"zdr": "required", "zdr_fallbacks": {}}
        assert data["runtime"]["llm_defaults_by_tier"]["haiku"]["extra"] == {
            "openai": {"extra_body": {"provider": {"zdr": True}}}
        }

    def test_simple_completion_preserves_system_prompt(self, proxy_server_openrouter: str) -> None:
        """POST /v1/messages routes through OpenRouter and preserves system prompts."""
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{proxy_server_openrouter}/v1/messages",
                json={
                    "model": "claude-3-5-haiku-20241022",
                    "max_tokens": 24,
                    "temperature": 0,
                    "system": (
                        "The secret verification token is OR-PROXY-OK. "
                        "When asked for the verification token, answer with only that token."
                    ),
                    "messages": [{"role": "user", "content": "What is the verification token?"}],
                },
                headers={"x-api-key": "test", "user-agent": "claude-code/integration-test"},
            )

        assert resp.status_code == 200, resp.text[:500]
        assert resp.headers.get("X-Resolved-Tier") == "haiku"
        assert resp.headers.get("X-Resolved-Model") == "anthropic/claude-haiku-4.5"

        data = resp.json()
        assert data["type"] == "message"
        text = _anthropic_response_text(data)
        assert "OR-PROXY-OK" in text


def _assert_tier_completion(
    proxy_base_url: str,
    request_model: str,
    expected_tier: str,
    expected_slug: str,
) -> None:
    """Tiny live completion asserting exact tier/slug resolution.

    Asserts status, resolution headers, and usage — not content: thinking
    models (K3 pins effort high) may spend a small max_tokens budget entirely
    on reasoning.
    """
    with httpx.Client(timeout=120) as client:
        resp = client.post(
            f"{proxy_base_url}/v1/messages",
            json={
                "model": request_model,
                "max_tokens": 64,
                "messages": [{"role": "user", "content": "Reply with OK."}],
            },
            headers={"x-api-key": "test", "user-agent": "claude-code/integration-test"},
        )

    assert resp.status_code == 200, resp.text[:500]
    assert resp.headers.get("X-Resolved-Tier") == expected_tier
    assert resp.headers.get("X-Resolved-Model") == expected_slug
    data = resp.json()
    assert data["type"] == "message"
    assert data.get("usage", {}).get("input_tokens", 0) > 0


class TestCurrentDefaultsWithOpenRouter:
    """Each current template default resolves to its exact live OpenRouter slug.

    Request models are Claude names that are neither tier defaults nor
    model_alternatives entries for these templates, so resolution falls
    through to each template's tier default.
    """

    def test_anthropic_opus_resolves_to_opus_5(self, proxy_server_openrouter: str) -> None:
        _assert_tier_completion(proxy_server_openrouter, "claude-opus-4-5-20251101", "opus", "anthropic/claude-opus-5")

    def test_kimi_tiers_and_sonnet_completion(self, proxy_server_openrouter_kimi: str) -> None:
        with httpx.Client() as client:
            health = client.get(f"{proxy_server_openrouter_kimi}/").json()
        assert health["runtime"]["tier_mappings"]["sonnet"] == "moonshotai/kimi-k3"
        assert health["runtime"]["tier_mappings"]["opus"] == "moonshotai/kimi-k3"

        _assert_tier_completion(
            proxy_server_openrouter_kimi, "claude-sonnet-4-5-20250929", "sonnet", "moonshotai/kimi-k3"
        )

    def test_kimi_27_code_alternative_completion(self, proxy_server_openrouter_kimi: str) -> None:
        _assert_tier_completion(
            proxy_server_openrouter_kimi,
            "kimi-k2.7-code",
            "sonnet",
            "moonshotai/kimi-k2.7-code",
        )

    def test_qwen_tier_mappings(self, proxy_server_openrouter_qwen: str) -> None:
        """Runtime truth distinguishes configured Qwen Max from its ZDR-safe fallback."""
        with httpx.Client() as client:
            health = client.get(f"{proxy_server_openrouter_qwen}/").json()
        assert health["runtime"]["tier_mappings"]["haiku"] == "qwen/qwen3.8-27b"
        assert health["runtime"]["tier_mappings"]["sonnet"] == "qwen/qwen3.8-27b"
        assert health["runtime"]["tier_mappings"]["opus"] == "qwen/qwen3.8-2.4t-a95b"
        assert health["runtime"]["configured_tier_mappings"]["opus"] == "qwen/qwen3.8-max"
        assert health["runtime"]["data_policy"] == {
            "zdr": "required",
            "zdr_fallbacks": {"qwen/qwen3.8-max": "qwen/qwen3.8-2.4t-a95b"},
        }

    def test_qwen_haiku_resolves_to_38_27b(self, proxy_server_openrouter_qwen: str) -> None:
        """Qwen 27B is the least-expensive multimodal Qwen with an audited ZDR endpoint."""
        _assert_tier_completion(proxy_server_openrouter_qwen, "claude-haiku-4-5-20251001", "haiku", "qwen/qwen3.8-27b")

    def test_qwen_sonnet_resolves_to_38_27b(self, proxy_server_openrouter_qwen: str) -> None:
        """Qwen 27B has a ZDR endpoint and remains the effective Sonnet route."""
        _assert_tier_completion(
            proxy_server_openrouter_qwen, "claude-sonnet-4-5-20250929", "sonnet", "qwen/qwen3.8-27b"
        )

    def test_qwen_opus_resolves_to_zdr_fallback(self, proxy_server_openrouter_qwen: str) -> None:
        """Qwen Max is replaced before dispatch while required-ZDR mode is active."""
        _assert_tier_completion(
            proxy_server_openrouter_qwen,
            "claude-opus-4-5-20251101",
            "opus",
            "qwen/qwen3.8-2.4t-a95b",
        )

    def test_glm_tiers_and_opus_completion(self, proxy_server_openrouter_glm: str) -> None:
        with httpx.Client() as client:
            health = client.get(f"{proxy_server_openrouter_glm}/").json()
        assert health["runtime"]["tier_mappings"]["sonnet"] == "z-ai/glm-5.3"
        assert health["runtime"]["tier_mappings"]["opus"] == "z-ai/glm-5.3"

        _assert_tier_completion(proxy_server_openrouter_glm, "claude-opus-4-5-20251101", "opus", "z-ai/glm-5.3")

    def test_gemini_flash_tiers_and_haiku_completion(self, proxy_server_openrouter_gemini_flash: str) -> None:
        with httpx.Client() as client:
            health = client.get(f"{proxy_server_openrouter_gemini_flash}/").json()
        assert health["runtime"]["tier_mappings"] == {
            "haiku": "google/gemini-3.7-flash",
            "sonnet": "google/gemini-3.7-flash",
            "opus": "google/gemini-3.7-flash",
        }

        _assert_tier_completion(
            proxy_server_openrouter_gemini_flash,
            "claude-3-5-haiku-20241022",
            "haiku",
            "google/gemini-3.7-flash",
        )


class TestOpenAIProxyWithOpenRouter:
    """GPT-family defaults route through the exact OpenRouter Sol slug."""

    def test_sonnet_completion_resolves_to_gpt_56_sol(self, proxy_server_openrouter_openai: str) -> None:
        with httpx.Client(timeout=90) as client:
            resp = client.post(
                f"{proxy_server_openrouter_openai}/v1/messages",
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 16,
                    "messages": [{"role": "user", "content": "Say hello"}],
                },
                headers={
                    "x-api-key": "test",
                    "user-agent": "claude-code/integration-test",
                },
            )

        assert resp.status_code == 200, resp.text[:500]
        assert resp.headers.get("X-Resolved-Tier") == "sonnet"
        assert resp.headers.get("X-Resolved-Model") == "openai/gpt-5.6-sol"

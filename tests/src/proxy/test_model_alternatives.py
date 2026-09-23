"""Tests for model_alternatives proxy routing."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import forge.proxy.server as server
from forge.config import load_config

_UNSET = object()


@pytest.fixture(autouse=True)
def _ensure_runtime(monkeypatch):
    """Stub runtime state so server helpers can run."""
    monkeypatch.setattr(server, "reload", lambda: None)

    class ProviderCfg:
        def __init__(self):
            self.tiers = SimpleNamespace(haiku="h-model", sonnet="s-model", opus="o-model")
            self.allow_non_zdr = False
            self.zdr_fallbacks = {}
            self.model_alternatives = {
                "opus": {
                    "claude-opus-4-8": "anthropic/claude-opus-4.8",
                    "gemini-3.7-flash": "google/gemini-3.7-flash",
                },
            }

    class ProxyCfg:
        default_tier = "sonnet"
        preferred_provider = "openrouter"

        def __init__(self):
            self._provider = ProviderCfg()

        def get_model_for_tier(self, tier: str) -> str:
            return getattr(self._provider.tiers, tier, "s-model")

        def get_provider(self, name=None):
            return self._provider

    monkeypatch.setattr(server.config, "proxy", ProxyCfg())


class TestResolveModelWithAlternatives:
    """Tests for _resolve_model_with_alternatives shared helper."""

    @staticmethod
    def _request(
        model: str,
        *,
        tier: str = "opus",
        original_model_name: str | None | object = _UNSET,
        has_explicit_tier: bool = True,
    ):
        return SimpleNamespace(
            has_explicit_tier=has_explicit_tier,
            tier=tier,
            original_model_name=(model if original_model_name is _UNSET else original_model_name),
            model=model,
        )

    def test_routes_to_alternative_when_matched(self):
        result = server._resolve_model_with_alternatives(self._request("claude-opus-4-8"))
        assert result.model == "anthropic/claude-opus-4.8"
        assert result.tier == "opus"
        assert result.tier_source == "request"

    def test_routes_to_fallback_when_no_match(self):
        result = server._resolve_model_with_alternatives(self._request("claude-opus-4-6"))
        assert result.model == "o-model"

    def test_routes_to_fallback_when_no_original_model(self):
        result = server._resolve_model_with_alternatives(self._request("claude-opus-4-6", original_model_name=None))
        assert result.model == "o-model"

    def test_routes_to_fallback_for_tier_without_alternatives(self):
        result = server._resolve_model_with_alternatives(self._request("claude-sonnet-4-6", tier="sonnet"))
        assert result.model == "s-model"

    def test_projected_tier_precedes_proxy_default_for_non_claude_alternative(self):
        request = self._request("gemini-3.7-flash", tier=None, has_explicit_tier=False)

        result = server._resolve_model_with_alternatives(request, projected_tier="opus")

        assert result.model == "google/gemini-3.7-flash"
        assert result.tier == "opus"
        assert result.tier_source == "forge.model_tier_header"

    def test_explicit_request_tier_precedes_projected_tier(self):
        request = self._request("claude-sonnet-4-6", tier="sonnet")

        result = server._resolve_model_with_alternatives(request, projected_tier="turbo")

        assert result.tier == "sonnet"
        assert result.tier_source == "request"

    def test_invalid_projected_tier_is_rejected(self):
        request = self._request("gemini-3.7-flash", tier=None, has_explicit_tier=False)

        with pytest.raises(HTTPException) as exc_info:
            server._resolve_model_with_alternatives(request, projected_tier="turbo")

        assert exc_info.value.status_code == 400
        assert "X-Forge-Model-Tier must be one of" in exc_info.value.detail["message"]

    def test_strips_1m_suffix_before_lookup(self):
        result = server._resolve_model_with_alternatives(self._request("claude-opus-4-8[1m]"))
        assert result.model == "anthropic/claude-opus-4.8"

    def test_required_zdr_routes_known_non_zdr_model_to_safe_fallback(self):
        proxy_cfg = server.config.proxy
        proxy_cfg._provider.tiers.opus = "qwen/qwen3.8-max"
        proxy_cfg._provider.zdr_fallbacks = {
            "qwen/qwen3.8-max": "qwen/qwen3.8-2.4t-a95b",
        }

        result = server._resolve_model_with_alternatives(self._request("claude-opus"))

        assert result.model == "qwen/qwen3.8-2.4t-a95b"

    @pytest.mark.parametrize(
        ("source", "fallback"),
        [
            ("anthropic/claude-fable-5.1", "anthropic/claude-opus-5.5"),
            ("anthropic/claude-fable-5", "anthropic/claude-opus-5.5"),
            ("qwen/qwen3.6-flash", "qwen/qwen3.8-27b"),
            ("qwen/qwen3.6-plus", "qwen/qwen3.8-27b"),
            ("qwen/qwen3.6-max-preview", "qwen/qwen3.8-2.4t-a95b"),
            ("qwen/qwen3.7-plus", "qwen/qwen3.8-27b"),
            ("qwen/qwen3.7-max", "qwen/qwen3.8-2.4t-a95b"),
            ("qwen/qwen3.8-max", "qwen/qwen3.8-2.4t-a95b"),
            ("qwen/qwen3.8-flash", "qwen/qwen3.8-27b"),
            ("qwen/qwen3.8-max-0902", "qwen/qwen3.8-2.4t-a95b"),
        ],
    )
    def test_builtin_fallbacks_cover_audited_non_zdr_routes(self, source, fallback):
        assert server._model_for_zdr_policy(source) == fallback

    def test_zdr_fallback_target_is_exact_and_drops_client_lookup_suffix(self):
        assert server._model_for_zdr_policy("anthropic/claude-fable-5.1[1m]") == "anthropic/claude-opus-5.5"

    def test_allow_non_zdr_keeps_primary_model(self):
        proxy_cfg = server.config.proxy
        proxy_cfg._provider.tiers.opus = "qwen/qwen3.8-max"
        proxy_cfg._provider.zdr_fallbacks = {
            "qwen/qwen3.8-max": "qwen/qwen3.8-2.4t-a95b",
        }
        proxy_cfg._provider.allow_non_zdr = True

        result = server._resolve_model_with_alternatives(self._request("claude-opus"))

        assert result.model == "qwen/qwen3.8-max"

    def test_configured_zdr_fallback_replaces_builtin_target(self):
        proxy_cfg = server.config.proxy
        proxy_cfg._provider.tiers.opus = "qwen/qwen3.8-max"
        proxy_cfg._provider.zdr_fallbacks = {
            "qwen/qwen3.8-max": "qwen/qwen3.8-27b",
        }

        result = server._resolve_model_with_alternatives(self._request("claude-opus"))

        assert result.model == "qwen/qwen3.8-27b"

    def test_saved_fable_fallback_keeps_its_selected_opus_version(self):
        proxy_cfg = server.config.proxy
        proxy_cfg._provider.zdr_fallbacks = {"anthropic/claude-fable-5.1": "anthropic/claude-opus-5"}

        assert server._model_for_zdr_policy("anthropic/claude-fable-5.1") == "anthropic/claude-opus-5"

    @pytest.mark.parametrize(
        ("template", "request_model", "expected"),
        [
            ("openrouter-anthropic", "claude-opus", "anthropic/claude-opus-5.5"),
            ("openrouter-anthropic", "claude-opus-5", "anthropic/claude-opus-5"),
            ("litellm-anthropic-local", "claude-opus", "anthropic/claude-opus-5-5"),
            ("litellm-anthropic-local", "claude-opus-5", "anthropic/claude-opus-5"),
            (
                "litellm-gemini-flash-local",
                "gemini-3.8-flash",
                "gemini/gemini-3.8-flash",
            ),
            (
                "litellm-gemini-flash-local",
                "gemini-3.7-flash",
                "gemini/gemini-3.7-flash",
            ),
            ("openrouter-openai", "gpt-6-sol", "openai/gpt-6-sol"),
            ("openrouter-openai", "gpt-6-sol-pro", "openai/gpt-6-sol-pro"),
            ("openrouter-openai", "gpt-6-luna", "openai/gpt-6-luna"),
            ("openrouter-openai", "gpt-6-luna-pro", "openai/gpt-6-luna-pro"),
            ("litellm-openai-local", "gpt-6-sol", "openai/gpt-6-sol"),
            ("litellm-openai-local", "gpt-6-luna", "openai/gpt-6-luna"),
            (
                "openrouter-deepseek",
                "deepseek-v4.1-flash",
                "deepseek/deepseek-v4.1-flash",
            ),
            (
                "openrouter-deepseek",
                "deepseek-v4-pro-0813",
                "deepseek/deepseek-v4-pro-0813",
            ),
            ("openrouter-glm", "glm-5.3-flash", "z-ai/glm-5.3-flash"),
            ("openrouter-glm", "glm-5.3-flashx", "z-ai/glm-5.3-flashx"),
        ],
    )
    def test_refreshed_templates_route_explicit_models(self, monkeypatch, template, request_model, expected):
        monkeypatch.setattr(server.config, "proxy", load_config(template=template).proxy)

        result = server._resolve_model_with_alternatives(self._request(request_model))

        assert result.model == expected

    def test_required_zdr_keeps_unknown_model_for_provider_enforcement(self):
        result = server._resolve_model_with_alternatives(self._request("qwen/unknown-zdr-status"))

        assert result.model == "qwen/unknown-zdr-status"

    def test_provider_error_degrades_to_fallback(self, monkeypatch):
        def _broken_provider(name=None):
            raise RuntimeError("config unavailable")

        proxy_cfg = server.config.proxy
        proxy_cfg.preferred_provider = "litellm"
        monkeypatch.setattr(proxy_cfg, "get_provider", _broken_provider)
        monkeypatch.setattr(server, "map_model_name", lambda _: "o-model")
        result = server._resolve_model_with_alternatives(self._request("claude-opus-4-8"))
        assert result.model == "o-model"

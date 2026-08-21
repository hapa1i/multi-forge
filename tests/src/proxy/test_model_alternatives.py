"""Tests for model_alternatives proxy routing."""

from types import SimpleNamespace

import pytest

import forge.proxy.server as server

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
    def _request(model: str, *, tier: str = "opus", original_model_name: str | None | object = _UNSET):
        return SimpleNamespace(
            has_explicit_tier=True,
            tier=tier,
            original_model_name=model if original_model_name is _UNSET else original_model_name,
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

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
        tiers = type("T", (), {"haiku": "h-model", "sonnet": "s-model", "opus": "o-model"})()
        model_alternatives = {
            "opus": {
                "claude-opus-4-8": "anthropic/claude-opus-4.8",
            },
        }

    class ProxyCfg:
        default_tier = "sonnet"
        preferred_provider = "openrouter"
        _provider = ProviderCfg()

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

    def test_provider_error_degrades_to_fallback(self, monkeypatch):
        def _broken_provider(name=None):
            raise RuntimeError("config unavailable")

        proxy_cfg = server.config.proxy
        monkeypatch.setattr(proxy_cfg, "get_provider", _broken_provider)
        monkeypatch.setattr(server, "map_model_name", lambda _: "o-model")
        result = server._resolve_model_with_alternatives(self._request("claude-opus-4-8"))
        assert result.model == "o-model"

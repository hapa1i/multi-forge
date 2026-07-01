"""Tests for proxy request data models (tier detection)."""

import pytest

from forge.proxy.data_models import _detect_tier, map_model_name


class TestMapModelNameFable:
    """map_model_name must treat Fable as the opus tier, not fall through to sonnet."""

    def test_fable_maps_to_openrouter_opus_tier_model(self, monkeypatch):
        # Regression: without fable handling in _anthropic_flavor, a bare
        # "claude-fable-5" fell through to the sonnet default with a misleading
        # "Unknown model" warning instead of mapping to the opus-tier model.
        from forge.config import config as config_mod
        from forge.config.loader import load_config

        loaded = load_config(template="openrouter-anthropic")
        monkeypatch.setattr(config_mod, "proxy", loaded.proxy)

        # Fable rides the opus tier, so this tier mapper resolves it to whatever the
        # opus tier is (now Opus 4.8), never sonnet. Explicit Fable selection is honored
        # separately on the request path via model_alternatives, not this mapper.
        assert map_model_name("claude-fable-5") == loaded.proxy.openrouter.tiers.opus
        # opus-tier siblings keep their own pass-through / tier mapping
        assert map_model_name("anthropic/claude-opus-4.8") == "anthropic/claude-opus-4.8"


class TestDetectTier:
    """Tier inference from the request model name (OpenAI-translated path)."""

    @pytest.mark.parametrize(
        ("model", "tier"),
        [
            ("claude-haiku-4-5", "haiku"),
            ("claude-sonnet-4-6", "sonnet"),
            ("claude-opus-4-6", "opus"),
            ("claude-opus-4-8[1m]", "opus"),
            # Fable carries no tier word of its own; it rides the opus tier.
            ("claude-fable-5", "opus"),
            ("anthropic/claude-fable-5", "opus"),
        ],
    )
    def test_explicit_tier_detected(self, model, tier):
        result = _detect_tier({"model": model})

        assert result["tier"] == tier
        assert result["has_explicit_tier"] is True
        assert result["original_model_name"] == model

    def test_non_claude_model_has_no_explicit_tier(self):
        result = _detect_tier({"model": "gpt-5.5"})

        assert result["tier"] is None
        assert result["has_explicit_tier"] is False

    def test_missing_model_key_is_passthrough(self):
        values = {"max_tokens": 1}
        assert _detect_tier(values) == values

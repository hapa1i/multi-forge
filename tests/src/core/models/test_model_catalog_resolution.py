"""Tests for model ID and alias resolution."""

import pytest

from forge.core.models import (
    ModelCatalogError,
    ModelSpec,
    get_context_window_tokens,
    get_max_output_tokens,
    get_model_spec,
    load_model_catalog,
    model_exists,
    resolve_model_id,
)


class TestResolveModelId:
    """Tests for resolve_model_id function."""

    def test_resolves_canonical_id(self):
        """Canonical model ID resolves to itself."""
        result = resolve_model_id("gpt-5.2")
        assert result == "gpt-5.2"

    def test_resolves_alias_to_canonical(self):
        """Alias resolves to its canonical model ID."""
        result = resolve_model_id("openai/gpt-5.2")
        assert result == "gpt-5.2"

    def test_raises_on_unknown_model(self):
        """Unknown model ID raises ModelCatalogError."""
        with pytest.raises(ModelCatalogError, match="Unknown model or alias"):
            resolve_model_id("totally-fake-model")

    def test_raises_on_unknown_alias(self):
        """Unknown alias raises ModelCatalogError."""
        with pytest.raises(ModelCatalogError, match="Unknown model or alias"):
            resolve_model_id("openai/totally-fake-model")


class TestGetModelSpec:
    """Tests for get_model_spec function."""

    def test_returns_spec_for_canonical_id(self):
        """Returns ModelSpec for canonical model ID."""
        spec = get_model_spec("gpt-5.2")

        assert isinstance(spec, ModelSpec)
        assert spec.friendly_name == "GPT-5.2"
        assert spec.context_window_tokens == 400000

    def test_returns_spec_for_alias(self):
        """Returns same ModelSpec when accessed via alias."""
        spec_canonical = get_model_spec("gpt-5.2")
        spec_alias = get_model_spec("openai/gpt-5.2")

        assert spec_canonical is spec_alias

    def test_raises_on_unknown(self):
        """Unknown model raises ModelCatalogError."""
        with pytest.raises(ModelCatalogError):
            get_model_spec("nonexistent-model")


class TestGPT56Family:
    """Tests for the GPT-5.6 Sol, Terra, and Luna catalog profiles."""

    def test_variants_are_canonical(self):
        catalog = load_model_catalog()

        for model_id in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
            assert model_id in catalog.models
            assert model_id not in catalog.aliases

    @pytest.mark.parametrize(
        ("alias", "canonical"),
        [
            ("gpt-5.6", "gpt-5.6-sol"),
            ("openai/gpt-5.6", "gpt-5.6-sol"),
            ("openai/gpt-5.6-sol", "gpt-5.6-sol"),
            ("openai/gpt-5.6-terra", "gpt-5.6-terra"),
            ("openai/gpt-5.6-luna", "gpt-5.6-luna"),
        ],
    )
    def test_aliases_resolve_to_variants(self, alias, canonical):
        assert resolve_model_id(alias) == canonical

    @pytest.mark.parametrize(
        ("model_id", "friendly_name", "intelligence_score"),
        [
            ("gpt-5.6-sol", "GPT-5.6 Sol", 100),
            ("gpt-5.6-terra", "GPT-5.6 Terra", 98),
            ("gpt-5.6-luna", "GPT-5.6 Luna", 90),
        ],
    )
    def test_shared_capabilities(self, model_id, friendly_name, intelligence_score):
        spec = get_model_spec(model_id)

        assert spec.friendly_name == friendly_name
        assert spec.context_window_tokens == 1_050_000
        assert spec.max_output_tokens == 128_000
        assert spec.max_thinking_tokens is None
        assert spec.supports_thinking is True
        assert spec.supports_images is True
        assert spec.supports_verbosity is True
        assert spec.verbosity_levels == ("low", "medium", "high")
        assert spec.temperature_constraint == "fixed"
        assert spec.temperature.default == 1.0
        assert spec.supports_top_p is False
        assert spec.native_thinking_param == "reasoning_effort"
        assert spec.litellm_reasoning_efforts == (
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
        )
        assert spec.default_reasoning_effort == "medium"
        assert spec.use_responses_api is True
        assert spec.intelligence_score == intelligence_score
        assert spec.system_prompt_addendum == "system_prompt_addendums/openai.md"

    def test_intelligence_scores_use_intentional_peer_tiers(self):
        score = lambda model: get_model_spec(model).intelligence_score  # noqa: E731

        assert score("gpt-5.6-sol") == score("claude-fable-5") == score("gpt-5.5-pro")
        assert score("gpt-5.6-sol") > score("gpt-5.5")
        assert score("gpt-5.6-terra") == score("claude-sonnet-5") == score("claude-opus-4-7")


class TestClaudeFable5:
    """Tests for the claude-fable-5 catalog entry and its aliases."""

    def test_fable_is_canonical(self):
        """claude-fable-5 exists as a canonical model, not an alias."""
        catalog = load_model_catalog()

        assert "claude-fable-5" in catalog.models
        assert "claude-fable-5" not in catalog.aliases

    @pytest.mark.parametrize(
        "alias",
        ["anthropic/claude-fable-5", "claude-fable", "fable", "fable-5"],
    )
    def test_aliases_resolve_to_fable(self, alias):
        """Convenience and provider-prefixed aliases resolve to claude-fable-5."""
        assert resolve_model_id(alias) == "claude-fable-5"

    def test_fable_intrinsic_properties(self):
        """Fable 5 shares the Opus 4.8 request surface: 1M context, adaptive-only."""
        spec = get_model_spec("claude-fable-5")

        assert spec.context_window_tokens == 1_000_000
        assert spec.max_output_tokens == 128_000
        assert spec.supports_1m_context is True
        assert spec.supports_top_p is False  # sampling overrides removed
        assert spec.supports_sampling_overrides is False
        assert spec.native_thinking_param == "output_config.effort"

    def test_fable_is_not_a_catalog_default(self):
        """Catalog opus defaults are Opus 4.8; Fable 5 is opt-in via template/--model."""
        catalog = load_model_catalog()

        for provider in ("anthropic", "openrouter"):
            assert catalog.defaults[provider]["opus"] == "claude-opus-4-8"

    def test_fable_outranks_opus_and_peers_gpt55_pro(self):
        """Fable tops the ladder with gpt-5.5-pro; Opus 4.8 / gpt-5.5 / Gemini 3.1 are one tier below."""
        score = lambda m: get_model_spec(m).intelligence_score  # noqa: E731

        assert score("claude-fable-5") == score("gpt-5.5-pro")
        assert score("claude-fable-5") > score("claude-opus-4-8")
        assert score("gpt-5.5") == score("claude-opus-4-8") == score("gemini-3.1-pro-preview")


class TestClaudeSonnet5:
    """Tests for the claude-sonnet-5 catalog entry, aliases, and default status."""

    def test_sonnet_5_is_canonical(self):
        """claude-sonnet-5 exists as a canonical model, not an alias."""
        catalog = load_model_catalog()

        assert "claude-sonnet-5" in catalog.models
        assert "claude-sonnet-5" not in catalog.aliases

    @pytest.mark.parametrize(
        "alias",
        ["anthropic/claude-sonnet-5", "claude-sonnet", "sonnet", "sonnet-5"],
    )
    def test_aliases_resolve_to_sonnet_5(self, alias):
        """Provider-prefixed and friendly aliases resolve to claude-sonnet-5."""
        assert resolve_model_id(alias) == "claude-sonnet-5"

    def test_sonnet_5_intrinsic_properties(self):
        """Sonnet 5 shares the Opus 4.8 surface: native 1M, adaptive-only, no sampling overrides."""
        spec = get_model_spec("claude-sonnet-5")

        assert spec.context_window_tokens == 1_000_000
        assert spec.max_output_tokens == 128_000
        assert spec.supports_1m_context is True
        assert spec.supports_top_p is False
        assert spec.supports_sampling_overrides is False
        assert spec.native_thinking_param == "output_config.effort"
        assert spec.token_estimate_multiplier == 1.35

    def test_sonnet_5_is_the_sonnet_default_and_opus_is_4_8(self):
        """Sonnet 5 is the catalog sonnet default; Opus 4.8 is the opus default (both layers)."""
        catalog = load_model_catalog()

        for provider in ("anthropic", "openrouter"):
            assert catalog.defaults[provider]["sonnet"] == "claude-sonnet-5"
            assert catalog.defaults[provider]["opus"] == "claude-opus-4-8"


class TestGemini31ProPreviewIsCanonical:
    """Tests ensuring gemini-3.1-pro-preview is a canonical model."""

    def test_gemini_31_pro_preview_is_canonical(self):
        """gemini-3.1-pro-preview exists as a canonical model, not an alias."""
        catalog = load_model_catalog()

        assert "gemini-3.1-pro-preview" in catalog.models
        assert "gemini-3.1-pro-preview" not in catalog.aliases

    def test_gemini_31_pro_preview_has_correct_properties(self):
        """gemini-3.1-pro-preview has expected intrinsic properties."""
        spec = get_model_spec("gemini-3.1-pro-preview")

        assert spec.context_window_tokens == 1048576  # 1M
        assert spec.max_output_tokens == 65536
        assert spec.supports_thinking is True
        assert spec.supports_images is True

    def test_gemini_31_pro_preview_customtools_is_canonical(self):
        """gemini-3.1-pro-preview-customtools exists as a canonical model."""
        catalog = load_model_catalog()

        assert "gemini-3.1-pro-preview-customtools" in catalog.models
        assert "gemini-3.1-pro-preview-customtools" not in catalog.aliases

    def test_customtools_aliases_resolve(self):
        """Provider-prefixed customtools aliases resolve correctly."""
        assert resolve_model_id("vertex_ai/gemini-3.1-pro-preview-customtools") == "gemini-3.1-pro-preview-customtools"
        assert resolve_model_id("gemini/gemini-3.1-pro-preview-customtools") == "gemini-3.1-pro-preview-customtools"

    def test_vertex_ai_alias_resolves_to_gemini_31(self):
        """vertex_ai/gemini-3.1-pro-preview alias resolves correctly."""
        canonical = resolve_model_id("vertex_ai/gemini-3.1-pro-preview")
        assert canonical == "gemini-3.1-pro-preview"

    def test_gemini_alias_resolves_to_gemini_31(self):
        """gemini/gemini-3.1-pro-preview alias resolves correctly."""
        canonical = resolve_model_id("gemini/gemini-3.1-pro-preview")
        assert canonical == "gemini-3.1-pro-preview"


class TestOpenRouterSlugAliases:
    """OpenRouter provider slugs can differ from Forge canonical IDs."""

    def test_dot_slugs_resolve_to_canonical_ids(self):
        assert resolve_model_id("anthropic/claude-opus-4.6") == "claude-opus-4-6-1m"
        assert resolve_model_id("anthropic/claude-sonnet-4.6") == "claude-sonnet-4-6-1m"
        assert resolve_model_id("anthropic/claude-opus-4.8") == "claude-opus-4-8"
        assert resolve_model_id("qwen/qwen3.6-flash") == "qwen3.6-flash"
        assert resolve_model_id("qwen/qwen3.6-plus") == "qwen3.6-plus"
        assert resolve_model_id("minimax/minimax-m2.5") == "minimax-m2.5"
        assert resolve_model_id("minimax/minimax-m2.7") == "minimax-m2.7"
        assert resolve_model_id("minimax/minimax-m3") == "minimax-m3"
        assert resolve_model_id("z-ai/glm-4.7-flash") == "glm-4.7-flash"
        assert resolve_model_id("z-ai/glm-5.1") == "glm-5.1"
        assert resolve_model_id("z-ai/glm-5.2") == "glm-5.2"

    def test_dash_aliases_resolve_to_canonical_ids(self):
        """Dot-to-dash convenience aliases resolve to the canonical dotted IDs."""
        assert resolve_model_id("glm-5-2") == "glm-5.2"
        assert resolve_model_id("glm-5-1") == "glm-5.1"

    def test_metadata_lookups_accept_openrouter_slugs(self):
        assert get_context_window_tokens("anthropic/claude-opus-4.6") == 1000000
        assert get_context_window_tokens("anthropic/claude-sonnet-4.6") == 1000000
        assert get_context_window_tokens("anthropic/claude-opus-4.8") == 1000000
        assert get_context_window_tokens("qwen/qwen3.6-flash") == 1000000
        assert get_context_window_tokens("qwen/qwen3.6-plus") == 1000000
        assert get_context_window_tokens("z-ai/glm-4.7-flash") == 202752
        assert get_context_window_tokens("z-ai/glm-5.1") == 202752
        assert get_context_window_tokens("z-ai/glm-5.2") == 1048576
        assert get_max_output_tokens("minimax/minimax-m2.5") == 196608
        assert get_max_output_tokens("minimax/minimax-m2.7") == 131072
        assert get_max_output_tokens("minimax/minimax-m3") == 512000


class TestConvenienceFunctions:
    """Tests for convenience lookup functions."""

    def test_get_context_window_tokens_canonical(self):
        """get_context_window_tokens works with canonical IDs."""
        assert get_context_window_tokens("gpt-5.2") == 400000
        assert get_context_window_tokens("gemini-2.5-pro") == 1048576
        assert get_context_window_tokens("claude-opus-4-5-20251101") == 200000

    def test_get_context_window_tokens_alias(self):
        """get_context_window_tokens works with aliases."""
        assert get_context_window_tokens("openai/gpt-5.2") == 400000
        assert get_context_window_tokens("vertex_ai/gemini-2.5-pro") == 1048576

    def test_get_max_output_tokens_canonical(self):
        """get_max_output_tokens works with canonical IDs."""
        assert get_max_output_tokens("gpt-5.2") == 128000
        assert get_max_output_tokens("gemini-3.1-pro-preview") == 65536

    def test_get_max_output_tokens_alias(self):
        """get_max_output_tokens works with aliases."""
        assert get_max_output_tokens("openai/gpt-5.2") == 128000

    def test_convenience_functions_raise_on_unknown(self):
        """Convenience functions raise on unknown models."""
        with pytest.raises(ModelCatalogError):
            get_context_window_tokens("fake-model")

        with pytest.raises(ModelCatalogError):
            get_max_output_tokens("fake-model")


class TestModelExists:
    """Tests for model_exists function."""

    def test_returns_true_for_canonical(self):
        """Returns True for canonical model IDs."""
        assert model_exists("gpt-5.2") is True
        assert model_exists("gemini-3.1-pro-preview") is True

    def test_returns_true_for_alias(self):
        """Returns True for aliases."""
        assert model_exists("openai/gpt-5.2") is True
        assert model_exists("vertex_ai/gemini-3.1-pro-preview") is True

    def test_returns_false_for_unknown(self):
        """Returns False for unknown models (doesn't raise)."""
        assert model_exists("totally-fake-model") is False
        assert model_exists("openai/fake-model") is False


class TestCatalogContainment:
    """Tests for __contains__ method on ModelCatalog."""

    def test_in_operator_for_canonical(self):
        """'in' operator works for canonical models."""
        catalog = load_model_catalog()
        assert "gpt-5.2" in catalog
        assert "gemini-3.1-pro-preview" in catalog

    def test_in_operator_for_alias(self):
        """'in' operator works for aliases."""
        catalog = load_model_catalog()
        assert "openai/gpt-5.2" in catalog
        assert "vertex_ai/gemini-3.1-pro-preview" in catalog

    def test_in_operator_for_unknown(self):
        """'in' operator returns False for unknown."""
        catalog = load_model_catalog()
        assert "fake-model" not in catalog


class TestSystemPromptAddendum:
    """Tests for get_system_prompt_addendum resolution."""

    def test_returns_content_for_openai_model(self):
        from forge.core.models import get_system_prompt_addendum

        content = get_system_prompt_addendum("gpt-5.5")
        assert content is not None
        assert "Read" in content
        assert "pages" in content

    def test_returns_content_for_gemini_model(self):
        from forge.core.models import get_system_prompt_addendum

        content = get_system_prompt_addendum("gemini-3.1-pro-preview")
        assert content is not None
        assert "Read" in content

    def test_returns_none_for_claude_model(self):
        from forge.core.models import get_system_prompt_addendum

        assert get_system_prompt_addendum("claude-opus-4-6") is None

    def test_returns_none_for_unknown_model(self):
        from forge.core.models import get_system_prompt_addendum

        assert get_system_prompt_addendum("unknown-custom-model") is None

    def test_strips_provider_prefix(self):
        from forge.core.models import get_system_prompt_addendum

        content = get_system_prompt_addendum("openai/gpt-5.5")
        assert content is not None

    def test_openai_and_gemini_files_loadable(self):
        from importlib import resources

        for name in ("openai.md", "gemini.md"):
            ref = resources.files("forge.core.data").joinpath("system_prompt_addendums", name)
            content = ref.read_text(encoding="utf-8")
            assert len(content) > 100

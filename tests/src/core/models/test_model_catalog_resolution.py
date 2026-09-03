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
        ("model_id", "friendly_name"),
        [
            ("gpt-5.6-sol", "GPT-5.6 Sol"),
            ("gpt-5.6-terra", "GPT-5.6 Terra"),
            ("gpt-5.6-luna", "GPT-5.6 Luna"),
        ],
    )
    def test_shared_capabilities(self, model_id, friendly_name):
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
        assert spec.system_prompt_addendum == "system_prompt_addendums/openai.md"


class TestClaudeFableFamily:
    """Tests for the Claude Fable catalog entries and family-default aliases."""

    def test_fable_versions_are_canonical(self):
        catalog = load_model_catalog()

        for model_id in ("claude-fable-5-1", "claude-fable-5"):
            assert model_id in catalog.models
            assert model_id not in catalog.aliases

    @pytest.mark.parametrize(
        ("alias", "canonical"),
        [
            ("anthropic/claude-fable-5-1", "claude-fable-5-1"),
            ("anthropic/claude-fable-5.1", "claude-fable-5-1"),
            ("claude-fable-5.1", "claude-fable-5-1"),
            ("fable-5-1", "claude-fable-5-1"),
            ("fable-5.1", "claude-fable-5-1"),
            ("claude-fable", "claude-fable-5-1"),
            ("fable", "claude-fable-5-1"),
            ("anthropic/claude-fable-5", "claude-fable-5"),
            ("fable-5", "claude-fable-5"),
        ],
    )
    def test_aliases_resolve_to_the_expected_fable_version(self, alias, canonical):
        assert resolve_model_id(alias) == canonical

    @pytest.mark.parametrize("model_id", ["claude-fable-5-1", "claude-fable-5"])
    def test_fable_intrinsic_properties(self, model_id):
        spec = get_model_spec(model_id)

        assert spec.context_window_tokens == 1_000_000
        assert spec.max_output_tokens == 128_000
        assert spec.supports_1m_context is True
        assert spec.supports_top_p is False  # sampling overrides removed
        assert spec.supports_sampling_overrides is False
        assert spec.native_thinking_param == "output_config.effort"

    def test_fable_5_1_supports_every_documented_effort_level(self):
        spec = get_model_spec("claude-fable-5-1")

        assert spec.litellm_reasoning_efforts == ("low", "medium", "high", "xhigh", "max")
        assert spec.default_reasoning_effort == "high"


class TestClaudeOpus5:
    """Tests for the claude-opus-5 catalog entry, aliases, and default status."""

    def test_opus_5_is_canonical(self):
        """claude-opus-5 exists as a canonical model, not an alias."""
        catalog = load_model_catalog()

        assert "claude-opus-5" in catalog.models
        assert "claude-opus-5" not in catalog.aliases

    @pytest.mark.parametrize(
        "alias",
        ["anthropic/claude-opus-5", "claude-opus", "opus", "opus-5"],
    )
    def test_aliases_resolve_to_opus_5(self, alias):
        """Provider-prefixed and friendly aliases resolve to claude-opus-5."""
        assert resolve_model_id(alias) == "claude-opus-5"

    def test_opus_5_intrinsic_properties(self):
        """Opus 5 shares the Opus 4.8 surface: native 1M, adaptive-only, no sampling overrides."""
        spec = get_model_spec("claude-opus-5")

        assert spec.context_window_tokens == 1_000_000
        assert spec.max_output_tokens == 128_000
        assert spec.supports_1m_context is True
        assert spec.supports_top_p is False
        assert spec.supports_sampling_overrides is False
        assert spec.thinking_modes == ("adaptive",)
        assert spec.native_thinking_param == "output_config.effort"
        assert spec.litellm_reasoning_efforts == ("low", "medium", "high", "xhigh", "max")
        assert spec.token_estimate_multiplier == 1.35


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

    def test_sonnet_5_is_the_sonnet_default_and_opus_is_5(self):
        """Sonnet 5 is the catalog sonnet default; Opus 5 is the opus default (both layers)."""
        catalog = load_model_catalog()

        for provider in ("anthropic", "openrouter"):
            assert catalog.defaults[provider]["sonnet"] == "claude-sonnet-5"
            assert catalog.defaults[provider]["opus"] == "claude-opus-5"


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


class TestGemini36Flash:
    """Tests for the gemini-3.6-flash catalog entry."""

    def test_gemini_36_flash_is_canonical(self):
        catalog = load_model_catalog()

        assert "gemini-3.6-flash" in catalog.models
        assert "gemini-3.6-flash" not in catalog.aliases

    @pytest.mark.parametrize(
        "alias",
        ["vertex_ai/gemini-3.6-flash", "gemini/gemini-3.6-flash", "google/gemini-3.6-flash"],
    )
    def test_prefixed_aliases_resolve(self, alias):
        assert resolve_model_id(alias) == "gemini-3.6-flash"

    def test_gemini_36_flash_intrinsic_properties(self):
        """3.6 is not a 3.5 clone: sampling deprecated, thinking default medium, no none/disable."""
        spec = get_model_spec("gemini-3.6-flash")

        assert spec.context_window_tokens == 1_048_576
        assert spec.max_output_tokens == 65_536
        assert spec.supports_top_p is False
        assert spec.supports_sampling_overrides is False
        assert spec.native_thinking_param == "thinking_level"
        assert spec.thinking_levels == ("minimal", "low", "medium", "high")
        assert spec.default_thinking_level == "medium"
        assert spec.litellm_reasoning_efforts == ("minimal", "low", "medium", "high")
        assert spec.default_reasoning_effort == "medium"
        assert spec.system_prompt_addendum == "system_prompt_addendums/gemini.md"


class TestGemini37Flash:
    """Tests for the Gemini 3.7 Flash catalog entry and family default."""

    def test_gemini_37_flash_is_canonical_and_the_haiku_default(self):
        catalog = load_model_catalog()

        assert "gemini-3.7-flash" in catalog.models
        assert "gemini-3.7-flash" not in catalog.aliases
        assert catalog.defaults["gemini"]["haiku"] == "gemini-3.7-flash"

    @pytest.mark.parametrize(
        "alias",
        ["vertex_ai/gemini-3.7-flash", "gemini/gemini-3.7-flash", "google/gemini-3.7-flash"],
    )
    def test_prefixed_aliases_resolve(self, alias):
        assert resolve_model_id(alias) == "gemini-3.7-flash"

    def test_gemini_37_flash_intrinsic_properties(self):
        spec = get_model_spec("gemini-3.7-flash")

        assert spec.context_window_tokens == 1_048_576
        assert spec.max_output_tokens == 65_536
        assert spec.supports_images is True
        assert spec.supports_top_p is True
        assert spec.native_thinking_param == "thinking_level"
        assert spec.thinking_levels == ("low", "medium", "high")
        assert spec.default_thinking_level == "medium"
        assert spec.litellm_reasoning_efforts == ("low", "medium", "high")
        assert spec.default_reasoning_effort == "medium"


class TestKimiModels:
    """Tests for current Kimi catalog entries and family defaults."""

    def test_kimi_27_code_is_a_canonical_non_default_model(self):
        catalog = load_model_catalog()

        assert "kimi-k2.7-code" in catalog.models
        assert "kimi-k2.7-code" not in catalog.aliases
        assert "kimi-k2.7-code" not in catalog.defaults["kimi"].values()

    @pytest.mark.parametrize("alias", ["moonshotai/kimi-k2.7-code", "kimi-k2-7-code"])
    def test_kimi_27_code_aliases_resolve(self, alias: str):
        assert resolve_model_id(alias) == "kimi-k2.7-code"

    def test_kimi_27_code_intrinsic_properties(self):
        spec = get_model_spec("kimi-k2.7-code")

        assert spec.context_window_tokens == 262_144
        assert spec.max_output_tokens == 262_144
        assert spec.supports_thinking is True
        assert spec.supports_images is True
        assert spec.supports_top_p is True
        assert spec.native_thinking_param is None
        assert spec.litellm_reasoning_efforts is None

    def test_kimi_k3_is_canonical_and_the_kimi_default(self):
        catalog = load_model_catalog()

        assert "kimi-k3" in catalog.models
        assert "kimi-k3" not in catalog.aliases
        assert catalog.defaults["kimi"]["sonnet"] == "kimi-k3"
        assert catalog.defaults["kimi"]["opus"] == "kimi-k3"
        assert catalog.defaults["kimi"]["haiku"] == "gemma-4-31b-it"

    def test_kimi_k3_slug_resolves(self):
        assert resolve_model_id("moonshotai/kimi-k3") == "kimi-k3"

    def test_kimi_k3_intrinsic_properties(self):
        """K3 drops the K2.x range sampling surface and advertises low/high/max efforts."""
        spec = get_model_spec("kimi-k3")

        assert spec.context_window_tokens == 1_048_576
        assert spec.max_output_tokens == 131_072
        assert spec.supports_images is True
        assert spec.supports_top_p is False
        assert spec.supports_sampling_overrides is False
        assert spec.native_thinking_param == "reasoning_effort"
        assert spec.litellm_reasoning_efforts == ("low", "high", "max")
        assert spec.default_reasoning_effort == "max"


class TestQwen37:
    """Tests for the displaced-but-selectable qwen3.7 catalog entries."""

    def test_qwen_37_models_remain_canonical(self):
        catalog = load_model_catalog()

        assert "qwen3.7-plus" in catalog.models
        assert "qwen3.7-max" in catalog.models

    @pytest.mark.parametrize(
        "alias, canonical",
        [
            ("qwen/qwen3.7-plus", "qwen3.7-plus"),
            ("qwen/qwen3.7-max", "qwen3.7-max"),
            ("qwen3-7-plus", "qwen3.7-plus"),
            ("qwen3-7-max", "qwen3.7-max"),
        ],
    )
    def test_qwen_37_aliases_resolve(self, alias, canonical):
        assert resolve_model_id(alias) == canonical

    def test_qwen_37_intrinsic_properties(self):
        """Both 3.7 models publish 1M context / 64k output; only Plus is multimodal."""
        plus = get_model_spec("qwen3.7-plus")
        maxx = get_model_spec("qwen3.7-max")

        for spec in (plus, maxx):
            assert spec.context_window_tokens == 1_000_000
            assert spec.max_output_tokens == 65_536
            assert spec.supports_thinking is True
            assert spec.litellm_reasoning_efforts is None
        assert plus.supports_images is True
        assert maxx.supports_images is False


class TestQwen38:
    """Tests for Qwen3.8 catalog entries and the Qwen family ladder."""

    def test_qwen_38_models_are_canonical_and_family_defaults(self):
        catalog = load_model_catalog()

        assert "qwen3.8-27b" in catalog.models
        assert "qwen3.8-2.4t-a95b" in catalog.models
        assert "qwen3.8-max" in catalog.models
        assert catalog.defaults["qwen"] == {
            "haiku": "qwen3.8-27b",
            "sonnet": "qwen3.8-27b",
            "opus": "qwen3.8-max",
        }

    @pytest.mark.parametrize(
        "alias, canonical",
        [
            ("qwen/qwen3.8-27b", "qwen3.8-27b"),
            ("qwen/qwen3.8-2.4t-a95b", "qwen3.8-2.4t-a95b"),
            ("qwen/qwen3.8-max", "qwen3.8-max"),
            ("qwen3-8-27b", "qwen3.8-27b"),
            ("qwen3-8-2-4t-a95b", "qwen3.8-2.4t-a95b"),
            ("qwen3-8-max", "qwen3.8-max"),
        ],
    )
    def test_qwen_38_aliases_resolve(self, alias, canonical):
        assert resolve_model_id(alias) == canonical

    def test_qwen_38_intrinsic_properties(self):
        balanced = get_model_spec("qwen3.8-27b")
        open_weight = get_model_spec("qwen3.8-2.4t-a95b")
        flagship = get_model_spec("qwen3.8-max")

        for spec in (balanced, flagship):
            assert spec.context_window_tokens == 1_000_000
            assert spec.max_output_tokens == 131_072
            assert spec.supports_thinking is True
            assert spec.supports_images is True
            assert spec.native_thinking_param == "reasoning_effort"
        assert balanced.litellm_reasoning_efforts == ("low", "medium", "xhigh")
        assert open_weight.context_window_tokens == 1_048_576
        assert open_weight.max_output_tokens == 262_144
        assert open_weight.supports_thinking is True
        assert open_weight.supports_images is False
        assert open_weight.litellm_reasoning_efforts is None
        assert flagship.litellm_reasoning_efforts == ("minimal", "low", "medium", "high", "xhigh")


class TestOpenRouterSlugAliases:
    """OpenRouter provider slugs can differ from Forge canonical IDs."""

    def test_dot_slugs_resolve_to_canonical_ids(self):
        assert resolve_model_id("anthropic/claude-opus-4.6") == "claude-opus-4-6-1m"
        assert resolve_model_id("anthropic/claude-sonnet-4.6") == "claude-sonnet-4-6-1m"
        assert resolve_model_id("anthropic/claude-opus-4.8") == "claude-opus-4-8"
        assert resolve_model_id("moonshotai/kimi-k3") == "kimi-k3"
        assert resolve_model_id("moonshotai/kimi-k2.7-code") == "kimi-k2.7-code"
        assert resolve_model_id("qwen/qwen3.6-flash") == "qwen3.6-flash"
        assert resolve_model_id("qwen/qwen3.6-plus") == "qwen3.6-plus"
        assert resolve_model_id("qwen/qwen3.8-27b") == "qwen3.8-27b"
        assert resolve_model_id("qwen/qwen3.8-2.4t-a95b") == "qwen3.8-2.4t-a95b"
        assert resolve_model_id("qwen/qwen3.8-max") == "qwen3.8-max"
        assert resolve_model_id("minimax/minimax-m2.5") == "minimax-m2.5"
        assert resolve_model_id("minimax/minimax-m2.7") == "minimax-m2.7"
        assert resolve_model_id("minimax/minimax-m3") == "minimax-m3"
        assert resolve_model_id("z-ai/glm-4.7-flash") == "glm-4.7-flash"
        assert resolve_model_id("z-ai/glm-5.1") == "glm-5.1"
        assert resolve_model_id("z-ai/glm-5.2") == "glm-5.2"
        assert resolve_model_id("z-ai/glm-5.3") == "glm-5.3"

    def test_dash_aliases_resolve_to_canonical_ids(self):
        """Dot-to-dash convenience aliases resolve to the canonical dotted IDs."""
        assert resolve_model_id("glm-5-2") == "glm-5.2"
        assert resolve_model_id("glm-5-1") == "glm-5.1"
        assert resolve_model_id("glm-5-3") == "glm-5.3"

    def test_metadata_lookups_accept_openrouter_slugs(self):
        assert get_context_window_tokens("anthropic/claude-opus-4.6") == 1000000
        assert get_context_window_tokens("anthropic/claude-sonnet-4.6") == 1000000
        assert get_context_window_tokens("anthropic/claude-opus-4.8") == 1000000
        assert get_context_window_tokens("qwen/qwen3.6-flash") == 1000000
        assert get_context_window_tokens("qwen/qwen3.6-plus") == 1000000
        assert get_context_window_tokens("z-ai/glm-4.7-flash") == 202752
        assert get_context_window_tokens("z-ai/glm-5.1") == 202752
        assert get_context_window_tokens("z-ai/glm-5.2") == 1048576
        assert get_context_window_tokens("z-ai/glm-5.3") == 1048576
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

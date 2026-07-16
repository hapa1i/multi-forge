"""Tests for model catalog loading and schema version validation."""

import pytest

from forge.core.models import (
    ModelCatalog,
    ModelCatalogError,
    get_default_model,
    get_provider_defaults,
    load_model_catalog,
)
from forge.core.models.catalog import (
    SUPPORTED_SCHEMA_VERSIONS,
    _validate_and_build_catalog,
)
from forge.core.models.types import REQUIRED_TIERS


class TestLoadModelCatalog:
    """Tests for the catalog loading function."""

    def test_loads_catalog_successfully(self):
        """Catalog loads without error and returns ModelCatalog."""
        catalog = load_model_catalog()

        assert isinstance(catalog, ModelCatalog)
        assert catalog.schema_version in SUPPORTED_SCHEMA_VERSIONS
        assert len(catalog.models) > 0
        assert len(catalog.aliases) > 0

    def test_catalog_is_cached(self):
        """Subsequent calls return the same cached instance."""
        catalog1 = load_model_catalog()
        catalog2 = load_model_catalog()

        assert catalog1 is catalog2

    def test_force_reload_creates_new_instance(self):
        """force_reload=True creates a fresh catalog instance."""
        catalog1 = load_model_catalog()
        catalog2 = load_model_catalog(force_reload=True)

        # Same content but potentially different object
        assert catalog2.schema_version == catalog1.schema_version
        assert len(catalog2.models) == len(catalog1.models)

    def test_catalog_contains_expected_models(self):
        """Catalog contains known models from MODEL_CONTEXT_WINDOWS."""
        catalog = load_model_catalog()

        # These models were in the old hardcoded list
        expected_models = [
            "gpt-5.2",
            "gpt-5",
            "gpt-4o",
            "gemini-3.1-pro-preview",
            "gemini-2.5-pro",
            "claude-opus-4-5-20251101",
        ]

        for model in expected_models:
            assert model in catalog.models, f"Expected model {model!r} not in catalog"


class TestSchemaVersionValidation:
    """Tests for schema version validation."""

    def test_rejects_missing_schema_version(self):
        """Missing schema_version raises ModelCatalogError."""
        raw = {"models": {}, "aliases": {}}

        with pytest.raises(ModelCatalogError, match="missing required 'schema_version'"):
            _validate_and_build_catalog(raw)

    def test_rejects_unsupported_schema_version(self):
        """Unsupported schema_version raises ModelCatalogError."""
        raw = {"schema_version": 999, "models": {}, "aliases": {}}

        with pytest.raises(ModelCatalogError, match="Unsupported model catalog schema_version: 999"):
            _validate_and_build_catalog(raw)

    def test_accepts_supported_schema_version(self):
        """Supported schema_version is accepted."""
        raw = {
            "schema_version": 1,
            "models": {
                "test-model": {
                    "friendly_name": "Test Model",
                    "context_window_tokens": 100000,
                    "max_output_tokens": 10000,
                    "max_thinking_tokens": None,
                    "supports_thinking": False,
                    "supports_images": False,
                    "temperature_constraint": "range",
                    "temperature": {"min": 0.0, "default": 1.0, "max": 2.0},
                    "intelligence_score": 50,
                    "tags": [],
                }
            },
            "aliases": {},
        }

        catalog = _validate_and_build_catalog(raw)
        assert catalog.schema_version == 1


class TestCatalogStructure:
    """Tests for catalog structure and types."""

    def test_models_have_required_fields(self):
        """Each model in the catalog has all required fields."""
        catalog = load_model_catalog()

        for model_id, spec in catalog.models.items():
            assert spec.friendly_name, f"{model_id} missing friendly_name"
            assert spec.context_window_tokens > 0, f"{model_id} has invalid context_window_tokens"
            assert spec.max_output_tokens > 0, f"{model_id} has invalid max_output_tokens"
            assert spec.temperature is not None, f"{model_id} missing temperature"
            assert 0 <= spec.intelligence_score <= 100, f"{model_id} has invalid intelligence_score"

    def test_aliases_are_strings(self):
        """All aliases map to string canonical IDs."""
        catalog = load_model_catalog()

        for alias, target in catalog.aliases.items():
            assert isinstance(alias, str), f"Alias key {alias!r} is not a string"
            assert isinstance(target, str), f"Alias target for {alias!r} is not a string"
            assert target in catalog.models, f"Alias {alias!r} points to unknown model {target!r}"

    def test_catalog_is_immutable(self):
        """ModelCatalog and ModelSpec are frozen dataclasses."""
        catalog = load_model_catalog()

        # Catalog should be frozen
        with pytest.raises(AttributeError):
            catalog.schema_version = 2  # type: ignore[misc]

        # ModelSpec should be frozen
        spec = list(catalog.models.values())[0]
        with pytest.raises(AttributeError):
            spec.context_window_tokens = 999  # type: ignore[misc]


class TestCatalogDefaults:
    """Tests for the per-provider, per-tier defaults section."""

    def test_defaults_loaded_from_catalog(self):
        catalog = load_model_catalog()
        assert len(catalog.defaults) > 0

    def test_all_providers_have_required_tiers(self):
        catalog = load_model_catalog()
        for provider, tiers in catalog.defaults.items():
            missing = REQUIRED_TIERS - set(tiers.keys())
            assert not missing, f"Provider {provider!r} missing tiers: {missing}"

    def test_all_default_models_exist_in_catalog(self):
        catalog = load_model_catalog()
        for provider, tiers in catalog.defaults.items():
            for tier, model_id in tiers.items():
                assert model_id in catalog.models, (
                    f"defaults.{provider}.{tier} references {model_id!r} " f"which is not in catalog models"
                )

    def test_get_default_model_returns_canonical_id(self):
        model = get_default_model("openai", "opus")
        catalog = load_model_catalog()
        assert model in catalog.models

    def test_openai_default_tiers_use_gpt_5_6_sol(self):
        """Regression: sonnet/opus use Sol while haiku stays on gpt-5.4-mini."""
        assert get_default_model("openai", "sonnet") == "gpt-5.6-sol"
        assert get_default_model("openai", "opus") == "gpt-5.6-sol"
        assert get_default_model("openai", "haiku") == "gpt-5.4-mini"

    def test_get_default_model_unknown_provider(self):
        with pytest.raises(ModelCatalogError, match="No default model"):
            get_default_model("nonexistent", "opus")

    def test_get_default_model_unknown_tier(self):
        with pytest.raises(ModelCatalogError, match="No default model"):
            get_default_model("openai", "nonexistent")

    def test_get_provider_defaults_returns_all(self):
        defaults = get_provider_defaults()
        assert "openai" in defaults
        assert "gemini" in defaults
        assert "anthropic" in defaults

    def test_validation_rejects_unknown_model_in_defaults(self):
        raw = {
            "schema_version": 1,
            "models": {
                "real-model": {
                    "friendly_name": "Real",
                    "context_window_tokens": 100000,
                    "max_output_tokens": 10000,
                    "max_thinking_tokens": None,
                    "supports_thinking": False,
                    "supports_images": False,
                    "temperature_constraint": "range",
                    "temperature": {"min": 0.0, "default": 1.0, "max": 2.0},
                    "intelligence_score": 50,
                    "tags": [],
                }
            },
            "aliases": {},
            "defaults": {
                "test-provider": {
                    "haiku": "real-model",
                    "sonnet": "real-model",
                    "opus": "ghost-model",
                }
            },
        }
        with pytest.raises(ModelCatalogError, match="unknown model 'ghost-model'"):
            _validate_and_build_catalog(raw)

    def test_validation_rejects_missing_tier(self):
        raw = {
            "schema_version": 1,
            "models": {
                "real-model": {
                    "friendly_name": "Real",
                    "context_window_tokens": 100000,
                    "max_output_tokens": 10000,
                    "max_thinking_tokens": None,
                    "supports_thinking": False,
                    "supports_images": False,
                    "temperature_constraint": "range",
                    "temperature": {"min": 0.0, "default": 1.0, "max": 2.0},
                    "intelligence_score": 50,
                    "tags": [],
                }
            },
            "aliases": {},
            "defaults": {
                "test-provider": {
                    "haiku": "real-model",
                    "opus": "real-model",
                    # missing sonnet
                }
            },
        }
        with pytest.raises(ModelCatalogError, match="missing required tiers"):
            _validate_and_build_catalog(raw)

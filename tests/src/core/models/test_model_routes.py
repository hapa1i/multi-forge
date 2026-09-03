"""Tests for the package-owned model route catalog."""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from dataclasses import FrozenInstanceError, dataclass

import pytest
import yaml

from forge.core.models.catalog import load_model_catalog
from forge.core.models.model_routes import (
    ModelRouteCandidate,
    ModelRouteCatalogError,
    _load_route_catalog_yaml,
    _validate_and_build_route_catalog,
    clear_model_route_catalog_cache,
    load_model_route_catalog,
    normalize_model_route_request,
    validate_model_route_catalog_integrations,
)


@pytest.fixture(autouse=True)
def _clear_catalog_cache() -> Iterator[None]:
    clear_model_route_catalog_cache()
    yield
    clear_model_route_catalog_cache()


def _valid_raw() -> dict:
    return deepcopy(_load_route_catalog_yaml())


@dataclass(frozen=True)
class _Source:
    id: str
    template_names: tuple[str, ...]
    provider: str = "openrouter"


class TestPackagedCatalog:
    def test_loads_every_normalized_intrinsic_model(self) -> None:
        catalog = load_model_route_catalog()

        expected = {normalize_model_route_request(model_id).route_key for model_id in load_model_catalog().models}
        assert set(catalog.models) == expected
        assert catalog.schema_version == 1

    def test_loader_is_cached_and_has_explicit_reset(self) -> None:
        first = load_model_route_catalog()
        assert load_model_route_catalog() is first

        clear_model_route_catalog_cache()
        second = load_model_route_catalog()
        assert second is not first
        assert second == first

    def test_candidates_and_mapping_are_immutable(self) -> None:
        catalog = load_model_route_catalog()
        candidate = catalog.models["gpt-5.6-sol"][0]

        with pytest.raises(FrozenInstanceError):
            candidate.kind = "direct"  # type: ignore[misc]
        with pytest.raises(TypeError):
            catalog.models["gpt-5.6-sol"] = ()  # type: ignore[index]

    def test_every_direct_pin_route_starts_direct_and_preserves_ref(self) -> None:
        catalog = load_model_route_catalog()

        for route_key in sorted(model_id for model_id in catalog.models if model_id.startswith("claude-")):
            first = catalog.models[route_key][0]
            assert first == ModelRouteCandidate(
                kind="direct",
                runtime="claude_code",
                model_ref=route_key,
            )

    def test_gemini_37_flash_has_remote_and_local_litellm_routes(self) -> None:
        routes = load_model_route_catalog().models["gemini-3.7-flash"]

        assert (
            ModelRouteCandidate(
                kind="proxy",
                source_id="litellm-remote",
                template="litellm-gemini",
                model_ref="vertex_ai/gemini-3.7-flash",
            )
            in routes
        )
        assert (
            ModelRouteCandidate(
                kind="proxy",
                source_id="litellm-gemini-local",
                template="litellm-gemini-flash-local",
                model_ref="gemini/gemini-3.7-flash",
            )
            in routes
        )

    @pytest.mark.parametrize(
        "model_id",
        [
            "gemini-3.1-pro-preview",
            "gemini-3.1-pro-preview-customtools",
            "gemini-3-flash-preview",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-3.5-flash",
            "gemini-3.6-flash",
            "gemini-3.7-flash",
        ],
    )
    def test_remote_litellm_gemini_routes_use_vertex_ai_refs(self, model_id: str) -> None:
        routes = load_model_route_catalog().models[model_id]
        remote_refs = {route.model_ref for route in routes if route.source_id == "litellm-remote"}

        assert remote_refs == {f"vertex_ai/{model_id}"}

    def test_gemini_38_flash_has_both_openrouter_routes_until_litellm_support_lands(self) -> None:
        routes = load_model_route_catalog().models["gemini-3.8-flash"]

        assert routes == (
            ModelRouteCandidate(
                kind="proxy",
                source_id="openrouter",
                template="openrouter-gemini-flash",
                model_ref="google/gemini-3.8-flash",
            ),
            ModelRouteCandidate(
                kind="proxy",
                source_id="openrouter",
                template="openrouter-gemini",
                model_ref="google/gemini-3.8-flash",
            ),
        )


class TestRequestNormalization:
    def test_normalizes_canonical_alias_and_claude_transport_identity(self) -> None:
        canonical = normalize_model_route_request("gpt-5.6-sol")
        alias = normalize_model_route_request("openai/gpt-5.6-sol")
        bracket = normalize_model_route_request("claude-opus-4-6[1m]")
        variant = normalize_model_route_request("claude-opus-4-6-1m")

        assert canonical == alias
        assert bracket.route_key == "claude-opus-4-6"
        assert bracket.requested_model == "claude-opus-4-6"
        assert bracket.claude_tier == "opus"
        assert bracket.transport_1m is True
        assert variant.route_key == "claude-opus-4-6"
        assert variant.requested_model == "claude-opus-4-6-1m"
        assert variant.transport_1m is True

    def test_preserves_provider_slug_dot_and_hyphen_distinction(self) -> None:
        dotted = normalize_model_route_request("anthropic/claude-opus-4.6")
        hyphenated = normalize_model_route_request("anthropic/claude-opus-4-6")

        assert dotted.route_key == hyphenated.route_key == "claude-opus-4-6"
        assert dotted.transport_1m is True
        assert hyphenated.transport_1m is False

    def test_normalizes_fable_family_alias_to_5_1(self) -> None:
        family_default = normalize_model_route_request("fable")
        openrouter_slug = normalize_model_route_request("anthropic/claude-fable-5.1")

        assert family_default == openrouter_slug
        assert family_default.route_key == "claude-fable-5-1"
        assert family_default.requested_model == "claude-fable-5-1"
        assert family_default.claude_tier == "opus"

    def test_rejects_unknown_empty_and_non_claude_transport_suffix(self) -> None:
        with pytest.raises(ModelRouteCatalogError, match="cannot be empty"):
            normalize_model_route_request("  ")
        with pytest.raises(ModelRouteCatalogError, match="Unknown model or alias"):
            normalize_model_route_request("not-a-model")
        with pytest.raises(ModelRouteCatalogError, match="only supported for Claude"):
            normalize_model_route_request("gpt-5.6-sol[1m]")


class TestSchemaValidation:
    def test_rejects_missing_newer_and_unknown_top_level_fields(self) -> None:
        raw = _valid_raw()
        del raw["schema_version"]
        with pytest.raises(ModelRouteCatalogError, match="missing required fields.*schema_version"):
            _validate_and_build_route_catalog(raw)

        raw = _valid_raw()
        raw["schema_version"] = 2
        with pytest.raises(
            ModelRouteCatalogError,
            match="Unsupported model route catalog schema_version",
        ):
            _validate_and_build_route_catalog(raw)

        raw = _valid_raw()
        raw["extra"] = True
        with pytest.raises(ModelRouteCatalogError, match="unknown fields.*extra"):
            _validate_and_build_route_catalog(raw)

    def test_rejects_malformed_yaml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            yaml,
            "safe_load",
            lambda _: (_ for _ in ()).throw(yaml.YAMLError("bad yaml")),
        )

        with pytest.raises(ModelRouteCatalogError, match="Could not load packaged model route catalog"):
            _load_route_catalog_yaml()

    @pytest.mark.parametrize("schema_version", [True, 1.0, [], {}])
    def test_rejects_non_integer_schema_versions_contextually(self, schema_version: object) -> None:
        raw = _valid_raw()
        raw["schema_version"] = schema_version

        with pytest.raises(ModelRouteCatalogError, match="schema_version must be an integer"):
            _validate_and_build_route_catalog(raw)

    def test_rejects_missing_packaged_resource(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def missing(_: str):
            raise FileNotFoundError("missing model_routes.yaml")

        monkeypatch.setattr("forge.core.models.model_routes.resources.files", missing)
        with pytest.raises(ModelRouteCatalogError, match="missing model_routes.yaml"):
            _load_route_catalog_yaml()

    def test_rejects_unknown_candidate_field_and_duplicate(self) -> None:
        raw = _valid_raw()
        raw["models"]["gpt-5.6-terra"]["routes"][0]["extra"] = True
        with pytest.raises(ModelRouteCatalogError, match="unknown fields.*extra"):
            _validate_and_build_route_catalog(raw)

        raw = _valid_raw()
        routes = raw["models"]["gpt-5.6-terra"]["routes"]
        routes.append(deepcopy(routes[0]))
        with pytest.raises(ModelRouteCatalogError, match="duplicates an earlier candidate"):
            _validate_and_build_route_catalog(raw)

    def test_rejects_unknown_model_key_and_provider_ref_mismatch(self) -> None:
        raw = _valid_raw()
        raw["models"]["ghost-model"] = raw["models"].pop("gpt-5.6-terra")
        with pytest.raises(ModelRouteCatalogError, match="unknown model key 'ghost-model'"):
            _validate_and_build_route_catalog(raw)

        raw = _valid_raw()
        raw["models"]["gpt-5.6-terra"]["routes"][0]["model_ref"] = "openai/gpt-5.6-luna"
        with pytest.raises(ModelRouteCatalogError, match="not model key 'gpt-5.6-terra'"):
            _validate_and_build_route_catalog(raw)

    def test_rejects_missing_model_and_direct_order_violation(self) -> None:
        raw = _valid_raw()
        del raw["models"]["gpt-5.6-terra"]
        with pytest.raises(ModelRouteCatalogError, match="missing canonical model keys.*gpt-5.6-terra"):
            _validate_and_build_route_catalog(raw)

        raw = _valid_raw()
        raw["models"]["claude-opus-5"]["routes"].insert(
            0,
            {
                "kind": "proxy",
                "source_id": "openrouter",
                "template": "openrouter-anthropic",
                "model_ref": "anthropic/claude-opus-5",
            },
        )
        with pytest.raises(ModelRouteCatalogError, match="must start with a direct candidate"):
            _validate_and_build_route_catalog(raw)

    def test_rejects_unsupported_runtime(self) -> None:
        raw = _valid_raw()
        raw["models"]["claude-opus-5"]["routes"][0]["runtime"] = "unknown"
        with pytest.raises(ModelRouteCatalogError, match="runtime is unsupported"):
            _validate_and_build_route_catalog(raw)

    def test_rejects_non_claude_direct_claude_code_candidate(self) -> None:
        raw = _valid_raw()
        raw["models"]["gpt-5.6-sol"]["routes"].insert(
            0,
            {
                "kind": "direct",
                "runtime": "claude_code",
                "model_ref": "gpt-5.6-sol",
            },
        )

        with pytest.raises(ModelRouteCatalogError, match="direct claude_code candidate must resolve to a Claude model"):
            _validate_and_build_route_catalog(raw)


class TestIntegrationValidation:
    def test_accepts_matching_source_template_ownership(self) -> None:
        raw = _valid_raw()
        catalog = _validate_and_build_route_catalog(raw)
        sources: dict[str, set[str]] = {}
        for candidates in catalog.models.values():
            for candidate in candidates:
                if candidate.kind == "proxy":
                    assert candidate.source_id is not None
                    assert candidate.template is not None
                    sources.setdefault(candidate.source_id, set()).add(candidate.template)

        validate_model_route_catalog_integrations(
            catalog,
            tuple(_Source(source_id, tuple(sorted(templates))) for source_id, templates in sources.items()),
        )

    def test_rejects_unknown_source_and_wrong_template_owner(self) -> None:
        raw = _valid_raw()
        catalog = _validate_and_build_route_catalog(raw)

        with pytest.raises(ModelRouteCatalogError, match="unknown source 'openrouter'"):
            validate_model_route_catalog_integrations(catalog, ())

        sources = (
            _Source("openrouter", ("openrouter-anthropic",)),
            _Source("litellm-remote", ("litellm-openai", "litellm-gemini")),
            _Source("codex-responses-local", ("codex-responses-local",)),
            _Source(
                "litellm-openai-local",
                ("litellm-openai-codex-local", "litellm-openai-local"),
            ),
            _Source(
                "litellm-gemini-local",
                ("litellm-gemini-flash-local", "litellm-gemini-local"),
            ),
        )
        with pytest.raises(ModelRouteCatalogError, match="does not belong to source 'openrouter'"):
            validate_model_route_catalog_integrations(catalog, sources)

    def test_rejects_model_ref_that_core_llm_cannot_route_for_litellm_source(self) -> None:
        from forge.backend.sources import list_model_sources

        raw = _valid_raw()
        routes = raw["models"]["gemini-3.7-flash"]["routes"]
        remote = next(route for route in routes if route["source_id"] == "litellm-remote")
        remote["model_ref"] = "google/gemini-3.7-flash"
        catalog = _validate_and_build_route_catalog(raw)

        with pytest.raises(ModelRouteCatalogError, match="cannot be routed by LiteLLM source 'litellm-remote'"):
            validate_model_route_catalog_integrations(catalog, list_model_sources())

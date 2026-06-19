"""Tests for the static model-source catalog."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from forge.backend.registry import (
    BackendInstance,
    BackendRegistry,
    BackendRegistryStore,
)
from forge.backend.sources import (
    LocalBackendLifecycle,
    ModelSource,
    ModelSourceCatalogError,
    ModelSourceKind,
    ModelSourceNotFoundError,
    SourceEndpoint,
    get_model_source,
    list_model_sources,
    model_source_for_template,
    resolve_model_source_id,
    validate_model_sources,
)
from forge.config.loader import list_template_names
from forge.core.provider_types import ProviderType


def test_builtin_catalog_contains_phase_1_sources() -> None:
    """Built-ins cover the v1 local, remote, test, and direct source units."""

    sources = {source.id: source for source in list_model_sources()}

    assert {
        "openrouter",
        "litellm-remote",
        "anthropic-passthrough",
        "anthropic-direct",
        "litellm-gemini-local",
        "litellm-openai-local",
        "litellm-anthropic-local",
        "litellm-gemini-test",
    }.issubset(sources)

    assert sources["openrouter"].provider == "openrouter"
    assert sources["openrouter"].capabilities.provider_trace is True
    assert sources["litellm-remote"].provider == "litellm_remote"
    assert sources["anthropic-direct"].provider == "anthropic"


def test_builtin_catalog_validates() -> None:
    """The shipped catalog passes strict duplicate and shape validation."""

    validate_model_sources(list_model_sources())


def test_all_shipped_templates_resolve_to_a_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every current shipped template has either a canonical source id or alias."""

    monkeypatch.setenv("FORGE_HOME", str(tmp_path))

    templates = list_template_names(include_internal=True)
    resolved = {template: model_source_for_template(template).id for template in templates}

    assert set(resolved) == set(templates)
    assert resolved["openrouter-kimi"] == "openrouter"
    assert resolved["litellm-gemini"] == "litellm-remote"
    assert resolved["litellm-gemini-flash-local"] == "litellm-gemini-local"
    assert resolved["litellm-openai-codex-local"] == "litellm-openai-local"
    assert resolved["litellm-gemini-test"] == "litellm-gemini-test"


def test_local_sources_map_to_lifecycle_without_using_instance_ids() -> None:
    """Local source ids stay disjoint from BackendInstance-style adapter-port ids."""

    local_sources = [source for source in list_model_sources() if source.kind == "local"]
    assert local_sources

    for source in local_sources:
        assert source.local_lifecycle is not None
        assert source.endpoint.kind == "local_backend"

        dependency = source.to_backend_dependency()
        assert dependency.adapter == "litellm"
        assert dependency.required_env_vars == list(source.required_env_vars)
        assert source.id != f"{dependency.adapter}-{dependency.port}"

    test_source = get_model_source("litellm-gemini-test")
    assert test_source.local_lifecycle is not None
    assert test_source.local_lifecycle.default_port == 4001


def test_source_required_env_vars_derive_from_credentials_and_endpoint() -> None:
    """Credential/env requirements come from catalog credentials, not lifecycle copies."""

    assert get_model_source("litellm-gemini-local").required_env_vars == ("GEMINI_API_KEY",)
    assert get_model_source("litellm-openai-local").required_env_vars == ("OPENAI_API_KEY",)
    assert get_model_source("litellm-anthropic-local").required_env_vars == ("ANTHROPIC_API_KEY",)
    assert get_model_source("litellm-remote").required_env_vars == ("LITELLM_API_KEY", "LITELLM_BASE_URL")
    assert get_model_source("openrouter").required_env_vars == ("OPENROUTER_API_KEY",)


def test_remote_sources_do_not_enter_runtime_registry(tmp_path: Path) -> None:
    """The static remote catalog remains separate from the PID/port registry."""

    store = BackendRegistryStore(tmp_path / "backends" / "index.json")
    remote_sources = [source for source in list_model_sources() if source.kind == "remote"]

    assert remote_sources
    assert store.read().backends == {}
    assert all(source.local_lifecycle is None for source in remote_sources)

    store.write(
        BackendRegistry(
            backends={
                "litellm-4000": BackendInstance(
                    backend_id="litellm-4000",
                    adapter_type="litellm",
                    port=4000,
                )
            }
        )
    )

    registry = store.read()
    assert set(registry.backends) == {"litellm-4000"}
    assert not ({source.id for source in remote_sources} & set(registry.backends))


def test_duplicate_source_identifiers_are_rejected() -> None:
    """Source ids and template aliases share one lookup namespace."""

    first = get_model_source("openrouter")
    duplicate = replace(get_model_source("litellm-remote"), id="openrouter")

    with pytest.raises(ModelSourceCatalogError, match="duplicate model-source identifier"):
        validate_model_sources((first, duplicate))


def test_alias_and_source_id_collision_is_rejected() -> None:
    """A template alias cannot collide with another canonical source id."""

    first = get_model_source("openrouter")
    duplicate = replace(get_model_source("litellm-remote"), template_names=("openrouter",))

    with pytest.raises(ModelSourceCatalogError, match="duplicate model-source identifier"):
        validate_model_sources((first, duplicate))


def test_unknown_kind_provider_and_credentials_are_rejected() -> None:
    """Catalog validation fails loudly for unsupported source vocabularies."""

    endpoint = SourceEndpoint.literal_url("https://example.test/v1")

    with pytest.raises(ModelSourceCatalogError, match="invalid model-source kind"):
        ModelSource(
            id="bad-kind",
            kind=cast(ModelSourceKind, "external"),
            provider="openrouter",
            endpoint=endpoint,
            credential_ids=("openrouter",),
        )

    with pytest.raises(ModelSourceCatalogError, match="invalid provider"):
        ModelSource(
            id="bad-provider",
            kind="remote",
            provider=cast(ProviderType, "not-a-provider"),
            endpoint=endpoint,
            credential_ids=("openrouter",),
        )

    with pytest.raises(ModelSourceCatalogError, match="at least one credential"):
        ModelSource(
            id="missing-credential",
            kind="remote",
            provider="openrouter",
            endpoint=endpoint,
            credential_ids=(),
        )

    with pytest.raises(ModelSourceCatalogError, match="unknown credential"):
        ModelSource(
            id="unknown-credential",
            kind="remote",
            provider="openrouter",
            endpoint=endpoint,
            credential_ids=("not-a-credential",),
        )


def test_bad_endpoint_shapes_are_rejected() -> None:
    """Endpoint variants reject mismatched URL/env/local shapes."""

    with pytest.raises(ModelSourceCatalogError, match="literal_url endpoint"):
        SourceEndpoint.literal_url("not-a-url")

    with pytest.raises(ModelSourceCatalogError, match="connection_value endpoint"):
        SourceEndpoint.connection_value("not-loud-enough")

    with pytest.raises(ModelSourceCatalogError, match="default_url"):
        SourceEndpoint.connection_value("OPENROUTER_BASE_URL", default_url="not-a-url")

    with pytest.raises(ModelSourceCatalogError, match="local_backend endpoint"):
        SourceEndpoint(kind="local_backend", value="http://localhost:4000")


def test_lifecycle_is_local_only() -> None:
    """Remote sources cannot fake lifecycle, and local sources must declare it."""

    lifecycle = LocalBackendLifecycle(adapter="litellm", default_port=4000)

    with pytest.raises(ModelSourceCatalogError, match="remote source .* cannot declare local lifecycle"):
        ModelSource(
            id="bad-remote-lifecycle",
            kind="remote",
            provider="litellm_remote",
            endpoint=SourceEndpoint.connection_value("LITELLM_BASE_URL"),
            credential_ids=("litellm-remote",),
            local_lifecycle=lifecycle,
        )

    with pytest.raises(ModelSourceCatalogError, match="local source .* must declare local lifecycle"):
        ModelSource(
            id="bad-local-lifecycle",
            kind="local",
            provider="litellm_local",
            endpoint=SourceEndpoint.local_backend(),
            credential_ids=("gemini-api",),
        )


def test_resolve_model_source_id_accepts_aliases() -> None:
    """Template aliases resolve to canonical source ids."""

    assert resolve_model_source_id("openrouter-openai") == "openrouter"
    assert resolve_model_source_id("litellm-openai") == "litellm-remote"
    assert resolve_model_source_id("litellm-anthropic-local") == "litellm-anthropic-local"

    with pytest.raises(ModelSourceNotFoundError, match="Unknown model source or alias") as exc_info:
        resolve_model_source_id("does-not-exist")

    assert str(exc_info.value) == "Unknown model source or alias: does-not-exist"


def test_model_source_lookup_misses_raise_domain_error_without_keyerror_quotes() -> None:
    """Lookup misses should render cleanly at future CLI boundaries."""

    with pytest.raises(ModelSourceNotFoundError, match="Unknown model source: missing-source") as source_exc:
        get_model_source("missing-source")
    with pytest.raises(ModelSourceNotFoundError, match="Unknown model source or alias") as template_exc:
        model_source_for_template("unknown-template")

    assert str(source_exc.value) == "Unknown model source: missing-source"
    assert str(template_exc.value) == "Unknown model source or alias: unknown-template"

"""Live-read wiring tests for shared per-proxy configuration.

The field registries drive both loader hops and template -> proxy.yaml creation.
These tests pin the live-read path (a schema-only test can pass while runtime
drops a field) and force coverage to grow with each registry.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from forge.config.loader import (
    _proxy_instance_to_forge_config,
    load_proxy_instance_config_from_dict,
)
from forge.config.schema import (
    PROXY_BLOCK_FIELDS,
    PROXY_PROVIDER_DIRECT_FIELDS,
    PROXY_PROVIDER_TRANSFORMED_FIELDS,
    PROXY_SHARED_NON_BLOCK_FIELDS,
    ProviderConfig,
    ProxyConfig,
    ProxyInstanceConfig,
)

_VALID_PROXY: dict[str, Any] = {
    "proxy_format": 1,
    "template": "openrouter-anthropic",
    "template_digest": "sha256:test",
    "provider": "openrouter",
    "proxy_endpoint": "http://localhost:8085",
    "port": 8085,
    "upstream_base_url": "https://openrouter.ai/api/v1",
    "tiers": {
        "haiku": "anthropic/claude-haiku-4-5",
        "sonnet": "anthropic/claude-sonnet-4-6",
        "opus": "anthropic/claude-opus-5",
    },
}

# One non-default marker per shared block. The completeness test below fails when
# a block is added to PROXY_BLOCK_FIELDS without a marker here, so the live-read
# proof grows with the registry instead of silently narrowing.
_BLOCK_MARKERS: dict[str, object] = {
    "costs": {"caps": {"per_day": 12.5}, "on_cap_hit": "warn"},
    "wire_shape": "anthropic_passthrough",
    "intercept": {"mode": "inspect"},
    "audit": {"audit_full_body": True, "retention_days": 3},
    "provider_trace": {"retention_days": 5, "max_total_mb": 77},
    "logging": {"requests": {"enabled": "on", "max_file_mb": 4}},
}

_SHARED_NON_BLOCK_MARKERS: dict[str, object] = {
    "backend": "openrouter",
    "default_tier": "opus",
    "family": "anthropic",
    "tool_prefixes_to_ignore": ["mcp__*"],
}

_PROVIDER_DIRECT_MARKERS: dict[str, object] = {
    "model_alternatives": {"opus": {"claude-opus-4-8": "anthropic/claude-opus-4-8"}},
    "prompt_caching": "auto_inject",
    "auto_cache_min_tokens": 4096,
}


def _assert_markers(proxy_cfg) -> None:
    assert proxy_cfg.costs.caps.per_day == 12.5
    assert proxy_cfg.costs.on_cap_hit == "warn"
    assert proxy_cfg.wire_shape == "anthropic_passthrough"
    assert proxy_cfg.intercept.mode == "inspect"
    assert proxy_cfg.audit.audit_full_body is True
    assert proxy_cfg.audit.retention_days == 3
    assert proxy_cfg.provider_trace.retention_days == 5
    assert proxy_cfg.provider_trace.max_total_mb == 77
    assert proxy_cfg.logging.requests.enabled == "on"
    assert proxy_cfg.logging.requests.max_file_mb == 4


def test_markers_cover_every_registered_block() -> None:
    assert set(_BLOCK_MARKERS) == set(PROXY_BLOCK_FIELDS)


def test_markers_cover_every_direct_field_registry() -> None:
    assert set(_SHARED_NON_BLOCK_MARKERS) == set(PROXY_SHARED_NON_BLOCK_FIELDS)
    assert set(_PROVIDER_DIRECT_MARKERS) == set(PROXY_PROVIDER_DIRECT_FIELDS)


def test_every_block_survives_both_hops_to_forge_config() -> None:
    """The live-read path: dict -> ProxyInstanceConfig -> ForgeConfig.proxy."""
    instance = load_proxy_instance_config_from_dict({**_VALID_PROXY, **_BLOCK_MARKERS})
    _assert_markers(instance)

    forge_config = _proxy_instance_to_forge_config(instance)
    _assert_markers(forge_config.proxy)


def test_every_direct_field_survives_both_hops_to_forge_config() -> None:
    instance = load_proxy_instance_config_from_dict(
        {**_VALID_PROXY, **_SHARED_NON_BLOCK_MARKERS, **_PROVIDER_DIRECT_MARKERS}
    )
    forge_config = _proxy_instance_to_forge_config(instance)
    provider = forge_config.proxy.get_provider()

    for name, marker in _SHARED_NON_BLOCK_MARKERS.items():
        assert getattr(instance, name) == marker
        assert getattr(forge_config.proxy, name) == marker
    for name, marker in _PROVIDER_DIRECT_MARKERS.items():
        assert getattr(instance, name) == marker
        assert getattr(provider, name) == marker


def test_absent_blocks_fall_to_dataclass_defaults() -> None:
    """Defaults have one source: the dataclass fields, not per-hop .get() fallbacks."""
    instance = load_proxy_instance_config_from_dict(dict(_VALID_PROXY))

    defaults = ProxyInstanceConfig(**{**_VALID_PROXY, "tiers": instance.tiers})
    for name in PROXY_BLOCK_FIELDS:
        assert getattr(instance, name) == getattr(defaults, name)


def test_absent_direct_fields_fall_to_dataclass_defaults() -> None:
    instance = load_proxy_instance_config_from_dict(dict(_VALID_PROXY))
    defaults = ProxyInstanceConfig(**{**_VALID_PROXY, "tiers": instance.tiers})

    for name in (*PROXY_SHARED_NON_BLOCK_FIELDS, *PROXY_PROVIDER_DIRECT_FIELDS):
        assert getattr(instance, name) == getattr(defaults, name)


@pytest.mark.parametrize("cls", [ProxyConfig, ProxyInstanceConfig])
def test_registry_names_are_fields_on_both_dataclasses(cls) -> None:
    field_names = {f.name for f in dataclasses.fields(cls)}
    missing = set(PROXY_BLOCK_FIELDS) - field_names
    assert not missing, f"{cls.__name__} lacks registered block field(s): {sorted(missing)}"


def _unregistered_shared_fields(shared: set[str]) -> set[str]:
    return shared - set(PROXY_BLOCK_FIELDS) - PROXY_SHARED_NON_BLOCK_FIELDS


def test_every_shared_field_is_registered_or_explicitly_transported() -> None:
    """Bidirectional drift guard: the dataclass intersection is a closed set.

    The registered->fields check above cannot see a field added to BOTH
    dataclasses but omitted from the registries -- creation and both loader hops
    would silently drop it to its default.
    """
    shared = {f.name for f in dataclasses.fields(ProxyConfig)} & {
        f.name for f in dataclasses.fields(ProxyInstanceConfig)
    }
    unregistered = _unregistered_shared_fields(shared)
    assert not unregistered, (
        f"Shared proxy field(s) {sorted(unregistered)} have no transport: "
        "register a block coercer or an unchanged field in PROXY_SHARED_NON_BLOCK_FIELDS"
    )
    # The exemption set may not go stale (names both dataclasses no longer share)
    # or shadow registry entries (a field must have exactly one transport story).
    assert PROXY_SHARED_NON_BLOCK_FIELDS <= shared
    assert not PROXY_SHARED_NON_BLOCK_FIELDS & set(PROXY_BLOCK_FIELDS)


def test_unregistered_shared_field_is_flagged() -> None:
    """The guard's set logic reports exactly the unaccounted-for member."""
    assert _unregistered_shared_fields({"costs", "backend", "new_block"}) == {"new_block"}


def _unregistered_provider_fields(shared: set[str]) -> set[str]:
    return shared - set(PROXY_PROVIDER_DIRECT_FIELDS) - PROXY_PROVIDER_TRANSFORMED_FIELDS


def test_every_provider_instance_shared_field_has_a_transport_story() -> None:
    shared = {f.name for f in dataclasses.fields(ProviderConfig)} & {
        f.name for f in dataclasses.fields(ProxyInstanceConfig)
    }
    unregistered = _unregistered_provider_fields(shared)
    assert not unregistered, (
        f"Provider/instance field(s) {sorted(unregistered)} have no transport: "
        "copy unchanged via PROXY_PROVIDER_DIRECT_FIELDS or declare an explicit transform"
    )
    assert set(PROXY_PROVIDER_DIRECT_FIELDS) <= shared
    assert PROXY_PROVIDER_TRANSFORMED_FIELDS <= shared
    assert not set(PROXY_PROVIDER_DIRECT_FIELDS) & PROXY_PROVIDER_TRANSFORMED_FIELDS


def test_unregistered_provider_field_is_flagged() -> None:
    assert _unregistered_provider_fields({"tiers", "prompt_caching", "new_provider_field"}) == {"new_provider_field"}


def test_invalid_wire_shape_message_unchanged() -> None:
    """The registry-driven coercer keeps the pre-existing error contract."""
    with pytest.raises(ValueError, match=r"Invalid wire_shape: 'bogus' \(must be one of:"):
        load_proxy_instance_config_from_dict({**_VALID_PROXY, "wire_shape": "bogus"})

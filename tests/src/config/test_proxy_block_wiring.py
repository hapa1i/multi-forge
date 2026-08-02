"""Live-read wiring tests for the shared per-proxy config blocks.

PROXY_BLOCK_FIELDS is the single declaration driving both loader hops, both
dataclasses' coercion, and template -> proxy.yaml creation. These tests pin the
live-read path (a schema-only test passes while the runtime drops the block --
the provider_trace bug class) and force coverage to grow with the registry.
"""

from __future__ import annotations

import dataclasses

import pytest

from forge.config.loader import (
    _proxy_instance_to_forge_config,
    load_proxy_instance_config_from_dict,
)
from forge.config.schema import PROXY_BLOCK_FIELDS, ProxyConfig, ProxyInstanceConfig

_VALID_PROXY = {
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


def test_every_block_survives_both_hops_to_forge_config() -> None:
    """The live-read path: dict -> ProxyInstanceConfig -> ForgeConfig.proxy."""
    instance = load_proxy_instance_config_from_dict({**_VALID_PROXY, **_BLOCK_MARKERS})
    _assert_markers(instance)

    forge_config = _proxy_instance_to_forge_config(instance)
    _assert_markers(forge_config.proxy)


def test_absent_blocks_fall_to_dataclass_defaults() -> None:
    """Defaults have one source: the dataclass fields, not per-hop .get() fallbacks."""
    instance = load_proxy_instance_config_from_dict(dict(_VALID_PROXY))

    defaults = ProxyInstanceConfig(**{**_VALID_PROXY, "tiers": instance.tiers})
    for name in PROXY_BLOCK_FIELDS:
        assert getattr(instance, name) == getattr(defaults, name)


@pytest.mark.parametrize("cls", [ProxyConfig, ProxyInstanceConfig])
def test_registry_names_are_fields_on_both_dataclasses(cls) -> None:
    field_names = {f.name for f in dataclasses.fields(cls)}
    missing = set(PROXY_BLOCK_FIELDS) - field_names
    assert not missing, f"{cls.__name__} lacks registered block field(s): {sorted(missing)}"


def test_invalid_wire_shape_message_unchanged() -> None:
    """The registry-driven coercer keeps the pre-existing error contract."""
    with pytest.raises(ValueError, match=r"Invalid wire_shape: 'bogus' \(must be one of:"):
        load_proxy_instance_config_from_dict({**_VALID_PROXY, "wire_shape": "bogus"})

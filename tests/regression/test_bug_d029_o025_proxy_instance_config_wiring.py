"""Regression: template-owned proxy fields must survive every config hop.

D029: ``tool_prefixes_to_ignore`` lived only on ``ProxyConfig``, so proxy creation
could not persist it and the runtime converter always saw the empty default.

O025: ``create_proxy_file`` did not copy the selected provider's
``prompt_caching`` or ``auto_cache_min_tokens`` values into ``ProxyInstanceConfig``;
created proxies silently used instance defaults instead.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from ruamel.yaml import YAML

import forge.proxy.proxy_orchestrator as orchestrator
from forge.config.loader import (
    _proxy_instance_to_forge_config,
    load_proxy_instance_config_from_dict,
)
from forge.config.schema import CostCaps, CostConfig, ForgeConfig, ProxyInstanceConfig

pytestmark = pytest.mark.regression

_TEMPLATE = "openrouter-anthropic"
_VALID_PROXY: dict[str, Any] = {
    "proxy_format": 1,
    "template": _TEMPLATE,
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


def _create_from_custom_template(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[ForgeConfig], None],
) -> tuple[dict[str, Any], ProxyInstanceConfig, ForgeConfig]:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    template_config = orchestrator.load_config(template=_TEMPLATE)
    mutate(template_config)
    monkeypatch.setattr(orchestrator, "load_config", lambda *_args, **_kwargs: template_config)

    written = orchestrator.create_proxy_file(
        proxy_id="wiring-test",
        template=_TEMPLATE,
        base_url="http://localhost:8085",
        port=8085,
        upstream_base_url="https://openrouter.ai/api/v1",
    )
    loaded_yaml = YAML().load(written.read_text())
    data = dict(loaded_yaml)
    instance = load_proxy_instance_config_from_dict(data)
    return data, instance, _proxy_instance_to_forge_config(instance)


def test_template_tool_prefixes_survive_create_reload_and_runtime(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = ["mcp__*", "plugin__forge__*"]

    def _mutate(config: ForgeConfig) -> None:
        config.proxy.tool_prefixes_to_ignore = expected

    data, instance, runtime = _create_from_custom_template(tmp_path, monkeypatch, _mutate)

    assert data["tool_prefixes_to_ignore"] == expected
    assert instance.tool_prefixes_to_ignore == expected
    assert runtime.proxy.tool_prefixes_to_ignore == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [("prompt_caching", "auto_inject"), ("auto_cache_min_tokens", 4096)],
)
def test_template_prompt_cache_field_survives_create_reload_and_runtime(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    def _mutate(config: ForgeConfig) -> None:
        setattr(config.proxy.get_provider(), field, value)

    data, instance, runtime = _create_from_custom_template(tmp_path, monkeypatch, _mutate)

    assert data[field] == value
    assert getattr(instance, field) == value
    assert getattr(runtime.proxy.get_provider(), field) == value


def test_legacy_instance_without_prompt_cache_fields_keeps_defaults() -> None:
    instance = load_proxy_instance_config_from_dict(dict(_VALID_PROXY))
    runtime = _proxy_instance_to_forge_config(instance)

    assert instance.prompt_caching == "passthrough"
    assert instance.auto_cache_min_tokens == 1024
    assert runtime.proxy.get_provider().prompt_caching == "passthrough"
    assert runtime.proxy.get_provider().auto_cache_min_tokens == 1024


def test_unrelated_shared_block_still_survives_create_and_runtime(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _mutate(config: ForgeConfig) -> None:
        config.proxy.costs = CostConfig(caps=CostCaps(per_day=7.5), on_cap_hit="warn")

    data, instance, runtime = _create_from_custom_template(tmp_path, monkeypatch, _mutate)

    assert data["costs"]["caps"]["per_day"] == 7.5
    assert instance.costs.caps.per_day == 7.5
    assert runtime.proxy.costs.caps.per_day == 7.5

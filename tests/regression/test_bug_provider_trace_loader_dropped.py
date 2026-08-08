"""Regression: a legacy ``proxy.yaml`` ``provider_trace:`` block must survive the loader.

The provider-trace plane's retention bounds (``retention_days`` / ``max_total_mb``) are declared on
``ProxyConfig`` / ``ProxyInstanceConfig`` (schema) and coerced in ``__post_init__``. They are now
deprecated compatibility inputs for the global downstream-retention resolver, but the loader that
bridges YAML -> dataclass must still preserve them at BOTH hops during that compatibility window:

1. ``load_proxy_instance_config_from_dict`` (dict -> ``ProxyInstanceConfig``)
2. ``_proxy_instance_to_forge_config`` (``ProxyInstanceConfig`` -> ``ProxyConfig``)

Because the field has a default (``ProviderTraceConfig()``), the omission was silent: a user's
``provider_trace: {retention_days: 7, ...}`` block loaded as all-defaults. The
``inject_provider_user`` toggle and normative retention policy have since moved to the global
``~/.forge/config.yaml``; new proxy files must not copy these legacy retention keys.

Affected: ``src/forge/config/loader.py`` (both wiring sites).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.regression

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
        "opus": "anthropic/claude-opus-4-8",
    },
}

_PROVIDER_TRACE = {"retention_days": 7, "max_total_mb": 99}


def test_provider_trace_survives_dict_load() -> None:
    """Site 1: the dict loader must carry ``provider_trace`` onto ``ProxyInstanceConfig``."""
    from forge.config.loader import load_proxy_instance_config_from_dict

    instance = load_proxy_instance_config_from_dict({**_VALID_PROXY, "provider_trace": _PROVIDER_TRACE})

    assert instance.provider_trace.retention_days == 7
    assert instance.provider_trace.max_total_mb == 99


def test_provider_trace_survives_to_forge_config() -> None:
    """Site 2: the derived ``ProxyConfig`` must keep the legacy compatibility values."""
    from forge.config.loader import (
        _proxy_instance_to_forge_config,
        load_proxy_instance_config_from_dict,
    )

    instance = load_proxy_instance_config_from_dict({**_VALID_PROXY, "provider_trace": _PROVIDER_TRACE})
    forge_config = _proxy_instance_to_forge_config(instance)

    assert forge_config.proxy.provider_trace.retention_days == 7
    assert forge_config.proxy.provider_trace.max_total_mb == 99


def test_provider_trace_defaults_when_absent() -> None:
    """No legacy block keeps the compatibility object's defaults without manufacturing raw keys."""
    from forge.config.loader import (
        _proxy_instance_to_forge_config,
        load_proxy_instance_config_from_dict,
    )

    forge_config = _proxy_instance_to_forge_config(load_proxy_instance_config_from_dict(dict(_VALID_PROXY)))

    assert forge_config.proxy.provider_trace.retention_days == 14
    assert forge_config.proxy.provider_trace.max_total_mb == 512


def test_template_legacy_retention_is_omitted_but_logging_survives_create(monkeypatch) -> None:
    """New proxy files omit template legacy retention while preserving unrelated shared blocks.

    The loader fix (sites 1-2 above) handled the read path; ``proxy_orchestrator.create_proxy_file``
    is the other ``ProxyInstanceConfig(...)`` builder. It must still carry ``logging`` without
    authoring deprecated ``provider_trace`` retention in a newly generated proxy file.
    """
    from ruamel.yaml import YAML

    import forge.proxy.proxy_orchestrator as orch
    from forge.config.loader import load_proxy_instance_config_from_dict
    from forge.config.schema import LoggingConfig, ProviderTraceConfig, RequestLogConfig

    # A real template config, then stamp non-default blocks onto cfg.proxy (as a custom template would).
    tmpl = orch.load_config(template="openrouter-anthropic")
    tmpl.proxy.provider_trace = ProviderTraceConfig(retention_days=7)
    tmpl.proxy.logging = LoggingConfig(requests=RequestLogConfig(enabled="on", stream_chunks=True))
    monkeypatch.setattr(orch, "load_config", lambda *_a, **_k: tmpl)

    written = orch.create_proxy_file(
        proxy_id="create-blocks-test",
        template="openrouter-anthropic",
        base_url="http://localhost:8085",
        port=8085,
        upstream_base_url="https://openrouter.ai/api/v1",
    )

    data = YAML().load(written.read_text())
    assert "provider_trace" not in data
    instance = load_proxy_instance_config_from_dict(dict(data))
    assert instance.logging.requests.enabled == "on"
    assert instance.logging.requests.stream_chunks is True

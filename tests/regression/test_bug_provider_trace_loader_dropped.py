"""Regression: a ``proxy.yaml`` ``provider_trace:`` block must survive the loader.

The provider-trace plane's retention bounds (``retention_days`` / ``max_total_mb``) are declared on
``ProxyConfig`` / ``ProxyInstanceConfig`` (schema), coerced in ``__post_init__``, and read at
runtime (``server.py`` prunes shards at startup). But the loader that bridges YAML -> dataclass
omitted ``provider_trace`` at BOTH hops:

1. ``load_proxy_instance_config_from_dict`` (dict -> ``ProxyInstanceConfig``)
2. ``_proxy_instance_to_forge_config`` (``ProxyInstanceConfig`` -> ``ProxyConfig``)

Because the field has a default (``ProviderTraceConfig()``), the omission was silent: a user's
``provider_trace: {retention_days: 7, ...}`` block loaded as all-defaults, so custom retention was
ignored. (The ``inject_provider_user`` toggle has since moved to the global ``~/.forge/config.yaml``
and is no longer carried on this proxy-owned block -- see ``runtime_config.py``.)

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
    """Site 2: the derived ``ProxyConfig`` (what the running proxy reads) must carry it.

    ``server.py`` prunes shards from ``config.proxy.provider_trace`` at startup -- off this derived
    ``ProxyConfig``. (The inject toggle is read separately from the global runtime config.)
    """
    from forge.config.loader import (
        _proxy_instance_to_forge_config,
        load_proxy_instance_config_from_dict,
    )

    instance = load_proxy_instance_config_from_dict({**_VALID_PROXY, "provider_trace": _PROVIDER_TRACE})
    forge_config = _proxy_instance_to_forge_config(instance)

    assert forge_config.proxy.provider_trace.retention_days == 7
    assert forge_config.proxy.provider_trace.max_total_mb == 99


def test_provider_trace_defaults_when_absent() -> None:
    """No ``provider_trace:`` block -> documented retention defaults (14d / 512 MB), not corruption."""
    from forge.config.loader import (
        _proxy_instance_to_forge_config,
        load_proxy_instance_config_from_dict,
    )

    forge_config = _proxy_instance_to_forge_config(load_proxy_instance_config_from_dict(dict(_VALID_PROXY)))

    assert forge_config.proxy.provider_trace.retention_days == 14
    assert forge_config.proxy.provider_trace.max_total_mb == 512


def test_template_provider_trace_and_logging_survive_create(monkeypatch) -> None:
    """Third construction site: ``create_proxy_file`` must copy template-defined ``provider_trace``
    AND ``logging`` onto the new ``ProxyInstanceConfig``.

    The loader fix (sites 1-2 above) handled the read path; ``proxy_orchestrator.create_proxy_file``
    is the other ``ProxyInstanceConfig(...)`` builder. It copied wire_shape/intercept/audit but
    dropped both new blocks, so a custom template's opt-ins silently reverted to defaults at
    ``forge proxy create``. Affected: ``src/forge/proxy/proxy_orchestrator.py``.
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
    instance = load_proxy_instance_config_from_dict(dict(data))
    assert instance.provider_trace.retention_days == 7
    assert instance.logging.requests.enabled == "on"
    assert instance.logging.requests.stream_chunks is True

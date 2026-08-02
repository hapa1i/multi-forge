"""Regression: template-declared ``costs`` (spend caps) must survive ``forge proxy create``.

``create_proxy_file`` enumerated the shared blocks by hand and copied
wire_shape/intercept/audit/provider_trace/logging but never ``costs``, so a custom
template's spend caps (``forge proxy template edit`` adding ``costs.caps``) silently
reverted to defaults on the created proxy -- the same silent-drop class previously
fixed for provider_trace/logging at this site. The site now copies every block via
the shared ``PROXY_BLOCK_FIELDS`` declaration.

Affected: ``src/forge/proxy/proxy_orchestrator.py`` (``create_proxy_file``).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.regression


def test_template_costs_survive_create(monkeypatch) -> None:
    from ruamel.yaml import YAML

    import forge.proxy.proxy_orchestrator as orch
    from forge.config.loader import load_proxy_instance_config_from_dict
    from forge.config.schema import CostCaps, CostConfig

    # A real template config, then stamp a costs block onto cfg.proxy (as a custom template would).
    tmpl = orch.load_config(template="openrouter-anthropic")
    tmpl.proxy.costs = CostConfig(caps=CostCaps(per_day=7.5, per_month=42.0), on_cap_hit="warn")
    monkeypatch.setattr(orch, "load_config", lambda *_a, **_k: tmpl)

    written = orch.create_proxy_file(
        proxy_id="create-costs-test",
        template="openrouter-anthropic",
        base_url="http://localhost:8085",
        port=8085,
        upstream_base_url="https://openrouter.ai/api/v1",
    )

    data = YAML().load(written.read_text())
    instance = load_proxy_instance_config_from_dict(dict(data))
    assert instance.costs.caps.per_day == 7.5
    assert instance.costs.caps.per_month == 42.0
    assert instance.costs.on_cap_hit == "warn"

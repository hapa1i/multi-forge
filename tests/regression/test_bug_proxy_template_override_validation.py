"""Regression: proxy template (ProxyConfig) validation parity with running-proxy (ProxyInstanceConfig).

Bug class (audit P2, fail-late): cross-field/value validations lived only on
ProxyInstanceConfig.__post_init__, so the template path (`forge proxy template edit`, validated via
dict_to_dataclass(ForgeConfig, ..., strict=True)) accepted invalid config that then failed late at
`forge proxy create`. Covered here: intercept.mode=override without anthropic_passthrough (#3,
medium); the default_tier allowlist (medium); costs non-mapping coercion (low); per-provider
tier_overrides catalog constraints (low); and the non-blank proxy.family requirement enforced on the
edit command (low -- family="" is a valid dataclass default, so the guard lives in template_edit_cmd).

Fix: shared _validate_wire_shape_intercept()/_validate_default_tier() + ProxyConfig.__post_init__
(coerce costs, validate default_tier/wire_shape, per-provider tier_overrides) in config/schema.py;
proxy.family check in template_edit_cmd (cli/proxy.py).
"""

from __future__ import annotations

import os
import tempfile

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.config.dataclass_utils import dict_to_dataclass
from forge.config.schema import ForgeConfig, InterceptConfig, ProxyConfig

pytestmark = pytest.mark.regression


def test_proxy_config_rejects_override_without_passthrough() -> None:
    # wire_shape defaults to openai_translated, which cannot apply a raw-body override.
    with pytest.raises(ValueError, match="anthropic_passthrough"):
        ProxyConfig(intercept=InterceptConfig(mode="override"))


def test_proxy_config_allows_override_with_passthrough() -> None:
    cfg = ProxyConfig(wire_shape="anthropic_passthrough", intercept=InterceptConfig(mode="override"))
    assert cfg.intercept.mode == "override"


def test_template_edit_path_rejects_override_without_passthrough() -> None:
    """The exact 'forge proxy template edit' path: dict_to_dataclass(ForgeConfig, ..., strict=True)."""
    with pytest.raises(ValueError, match="anthropic_passthrough"):
        dict_to_dataclass(
            ForgeConfig,
            {"proxy": {"family": "anthropic", "intercept": {"mode": "override"}}},
            strict=True,
        )


def test_template_rejects_invalid_default_tier() -> None:
    """default_tier allowlist now enforced on the template path (was instance-only)."""
    with pytest.raises(ValueError, match="default_tier"):
        dict_to_dataclass(
            ForgeConfig,
            {"proxy": {"family": "openai", "default_tier": "BOGUS"}},
            strict=True,
        )


def test_template_rejects_non_mapping_costs() -> None:
    """costs coercion now runs on the template path; a non-mapping is rejected (was left a raw str)."""
    with pytest.raises(ValueError, match="costs"):
        dict_to_dataclass(
            ForgeConfig,
            {"proxy": {"family": "openai", "costs": "not-a-dict"}},
            strict=True,
        )


def test_template_rejects_unsupported_tier_override() -> None:
    """Per-provider tier_overrides catalog constraints now enforced on the template path."""
    with pytest.raises(ValueError, match="reasoning_effort"):
        dict_to_dataclass(
            ForgeConfig,
            {
                "proxy": {
                    "family": "openai",
                    "openai": {
                        "tiers": {"sonnet": "gpt-5.5"},
                        "tier_overrides": {"sonnet": {"reasoning_effort": "ultra-mega-high"}},
                    },
                }
            },
            strict=True,
        )


def test_template_edit_rejects_blank_family(monkeypatch: pytest.MonkeyPatch) -> None:
    """'forge proxy template edit' rejects a blank/missing proxy.family at edit time (was: saved
    cleanly, failed late at create). family="" is a valid dataclass default, so the guard lives in
    the edit command, mirroring _load_template_config (the create path)."""
    script = tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False)
    script.write('#!/bin/sh\nprintf "proxy:\\n  default_tier: sonnet\\n" > "$1"\n')
    script.close()
    os.chmod(script.name, 0o755)
    monkeypatch.setenv("EDITOR", script.name)

    result = CliRunner().invoke(main, ["proxy", "template", "edit", "litellm-openai"])
    assert result.exit_code != 0
    assert "proxy.family is required" in result.output

"""Regression: proxy template validation rejects intercept.mode=override without anthropic_passthrough.

Bug (audit P2 #3, medium): the cross-field rule 'override requires anthropic_passthrough' lived
only in ProxyInstanceConfig.__post_init__. ProxyConfig (the template-validation path used by
'forge proxy template edit' via dict_to_dataclass) had no __post_init__, so an invalid template
saved cleanly and only failed late at 'forge proxy create'.

Fix: shared _validate_wire_shape_intercept() + a ProxyConfig.__post_init__ (config/schema.py).
"""

from __future__ import annotations

import pytest

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

"""Regression: anthropic-passthrough must honor any Claude --model pin.

Bug: the shared --model validator (`_proxy_supports_model_pin`) accepted a pin
only when it equaled the tier default or a configured `model_alternatives` entry.
`anthropic-passthrough` forwards the client model byte-for-byte and configures no
alternatives, so after the default tiers flipped to Sonnet 5 / Opus 4.8, pinning
a displaced model (`claude-fable-5`, `claude-opus-4-6`, `claude-sonnet-4-6`) was
rejected pre-launch even though passthrough would have forwarded it unchanged.

Fix: `_proxy_supports_model_pin` short-circuits to True for
`wire_shape == "anthropic_passthrough"`.

Affected: src/forge/cli/session_model_pin.py
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from forge.cli.session_model_pin import (
    _apply_direct_model_env_if_supported,
    _proxy_supports_model_pin,
    _validate_proxy_model_pin,
)
from forge.config.schema import ProxyInstanceConfig, TierModels
from forge.session.direct_model import resolve_direct_model_pin

pytestmark = pytest.mark.regression

_PROXY_ID = "test-passthrough"

# Models that are NOT the tier default and NOT in model_alternatives, yet must
# stay pinnable on passthrough because the model is forwarded unchanged.
_DISPLACED_PINS = {
    "claude-fable-5": ("opus", "claude-fable-5"),
    "claude-opus-4-6": ("opus", "claude-opus-4-6"),
    "claude-sonnet-4-6": ("sonnet", "claude-sonnet-4-6"),
}


def _passthrough_cfg() -> ProxyInstanceConfig:
    return ProxyInstanceConfig(
        proxy_format=1,
        template="anthropic-passthrough",
        template_digest="abc",
        provider="litellm",
        proxy_endpoint="http://localhost:8096",
        port=8096,
        upstream_base_url="https://api.anthropic.com",
        tiers=TierModels(haiku="claude-haiku-4-5", sonnet="claude-sonnet-5", opus="claude-opus-4-8"),
        model_alternatives={},
        wire_shape="anthropic_passthrough",
    )


@pytest.mark.parametrize("model", sorted(_DISPLACED_PINS))
def test_passthrough_supports_displaced_claude_pins(model: str) -> None:
    cfg = _passthrough_cfg()
    pin = resolve_direct_model_pin(model)

    assert _proxy_supports_model_pin(cfg, pin) is True


@pytest.mark.parametrize("model", sorted(_DISPLACED_PINS))
def test_passthrough_validation_accepts_displaced_pins(model: str) -> None:
    pin = resolve_direct_model_pin(model)

    with patch("forge.config.loader.load_proxy_instance_config", return_value=_passthrough_cfg()):
        assert _validate_proxy_model_pin(_PROXY_ID, pin) is None


@pytest.mark.parametrize("model,expected", sorted(_DISPLACED_PINS.items()))
def test_passthrough_env_application_populates_claude_vars(model: str, expected: tuple[str, str]) -> None:
    tier, env_model = expected
    env_vars: dict[str, str] = {}

    with patch("forge.config.loader.load_proxy_instance_config", return_value=_passthrough_cfg()):
        error = _apply_direct_model_env_if_supported(env_vars, _PROXY_ID, model)

    assert error is None
    assert env_vars == {
        "ANTHROPIC_MODEL": tier,
        f"ANTHROPIC_DEFAULT_{tier.upper()}_MODEL": env_model,
    }

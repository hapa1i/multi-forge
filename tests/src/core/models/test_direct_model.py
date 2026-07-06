"""Tests for direct Claude model pin helpers."""

from __future__ import annotations

import pytest

from forge.core.models.direct_model import (
    apply_direct_model_env,
    apply_proxy_context_model_defaults,
    direct_model_env,
    resolve_direct_model_pin,
)


def test_resolves_opus_48_alias_to_env_pin() -> None:
    pin = resolve_direct_model_pin("opus-4-8")

    assert pin.canonical_model == "claude-opus-4-8"
    assert pin.env_model == "claude-opus-4-8"
    assert pin.tier == "opus"
    assert pin.env() == {
        "ANTHROPIC_MODEL": "opus",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8",
    }


def test_resolves_fable_to_opus_tier_pin() -> None:
    # Fable has no tier word of its own; it rides the opus tier so Claude Code
    # pins ANTHROPIC_DEFAULT_OPUS_MODEL and the proxy routes it as opus.
    pin = resolve_direct_model_pin("claude-fable-5")

    assert pin.canonical_model == "claude-fable-5"
    assert pin.env_model == "claude-fable-5"
    assert pin.tier == "opus"
    assert pin.env() == {
        "ANTHROPIC_MODEL": "opus",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-fable-5",
    }


def test_resolves_fable_alias_to_opus_tier_pin() -> None:
    pin = resolve_direct_model_pin("fable")

    assert pin.canonical_model == "claude-fable-5"
    assert pin.tier == "opus"


def test_preserves_claude_code_1m_suffix() -> None:
    pin = resolve_direct_model_pin("claude-sonnet-4-6[1m]")

    assert pin.canonical_model == "claude-sonnet-4-6"
    assert pin.env_model == "claude-sonnet-4-6[1m]"
    assert pin.env() == {
        "ANTHROPIC_MODEL": "sonnet",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-4-6[1m]",
    }


def test_normalizes_catalog_1m_alias_to_claude_code_suffix() -> None:
    pin = resolve_direct_model_pin("opus-4-6-1m")

    assert pin.canonical_model == "claude-opus-4-6"
    assert pin.env_model == "claude-opus-4-6[1m]"


def test_rejects_unknown_direct_model() -> None:
    with pytest.raises(ValueError, match="Unknown direct Claude model"):
        resolve_direct_model_pin("claude-opus-4.8.1")


def test_rejects_non_claude_model() -> None:
    with pytest.raises(ValueError, match="only supports Claude"):
        direct_model_env("gpt-5.5")


def test_apply_direct_model_env_updates_mapping() -> None:
    env_vars: dict[str, str] = {}

    error = apply_direct_model_env(env_vars, "opus-4-8")

    assert error is None
    assert env_vars == {
        "ANTHROPIC_MODEL": "opus",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8",
    }


def test_apply_direct_model_env_returns_error() -> None:
    env_vars: dict[str, str] = {}

    error = apply_direct_model_env(env_vars, "gpt-5.5")

    assert error is not None
    assert "only supports Claude" in error
    assert env_vars == {}


def test_proxy_context_model_defaults_only_for_large_context() -> None:
    env_vars: dict[str, str] = {}

    apply_proxy_context_model_defaults(env_vars, 200000)
    assert env_vars == {}

    apply_proxy_context_model_defaults(env_vars, 1000000)
    assert env_vars == {
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8[1m]",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-5[1m]",
    }


def test_proxy_context_model_defaults_do_not_force_tier_or_override_explicit_defaults() -> None:
    env_vars = {
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-6",
    }

    apply_proxy_context_model_defaults(env_vars, 1000000)

    assert env_vars == {
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-6",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-5[1m]",
    }
    assert "ANTHROPIC_MODEL" not in env_vars


def test_resolves_sonnet_5_to_env_pin() -> None:
    pin = resolve_direct_model_pin("claude-sonnet-5")

    assert pin.canonical_model == "claude-sonnet-5"
    assert pin.env_model == "claude-sonnet-5"
    assert pin.tier == "sonnet"
    assert pin.env() == {
        "ANTHROPIC_MODEL": "sonnet",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-5",
    }


def test_preserves_1m_suffix_on_native_1m_sonnet_5() -> None:
    # Sonnet 5 is natively 1M (no -1m twin); the [1m] estimator hint still rides through.
    pin = resolve_direct_model_pin("claude-sonnet-5[1m]")

    assert pin.canonical_model == "claude-sonnet-5"
    assert pin.env_model == "claude-sonnet-5[1m]"
    assert pin.tier == "sonnet"

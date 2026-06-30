"""Tests for conservative billing-mode inference (Phase 4c).

``infer_billing_mode`` asserts ``api`` only when a call is provably direct +
key-authenticated; everything ambiguous is ``unknown`` (never guessed).
"""

from __future__ import annotations

from forge.core.usage.billing import infer_billing_mode, resolve_billing_mode


def test_direct_with_key_is_api() -> None:
    assert infer_billing_mode(direct=True, has_api_key=True) == "api"


def test_direct_without_key_is_unknown() -> None:
    assert infer_billing_mode(direct=True, has_api_key=False) == "unknown"


def test_proxied_is_unknown_even_with_key() -> None:
    # A proxied call's upstream billing is opaque from the callsite -- never guess.
    assert infer_billing_mode(direct=False, has_api_key=True) == "unknown"


# --- resolve_billing_mode: the subscription-lane upgrade (epic consumer_lanes, T0) ---


def test_keyless_direct_on_subscription_backend_is_subscription_quota() -> None:
    # claude-max declares billing_posture="subscription_quota"; a keyless direct run on it
    # is the one case the base inference can't see.
    assert resolve_billing_mode(direct=True, has_api_key=False, backend_id="claude-max") == "subscription_quota"


def test_key_and_subscription_backend_coexist_is_api() -> None:
    # Precedence: a resolvable key wins even on a subscription lane (mirrors codex's
    # stored-key-before-tokens). This is the T0 box: a Max login AND an env key.
    assert resolve_billing_mode(direct=True, has_api_key=True, backend_id="claude-max") == "api"


def test_keyless_direct_on_per_token_backend_is_unknown() -> None:
    # anthropic-direct is per_token: keyless + per_token is genuinely unknown (no key to prove api).
    assert resolve_billing_mode(direct=True, has_api_key=False, backend_id="anthropic-direct") == "unknown"


def test_proxied_subscription_backend_is_unknown() -> None:
    # A proxy in the path makes the upstream opaque; the subscription lane can't override that.
    assert resolve_billing_mode(direct=False, has_api_key=False, backend_id="claude-max") == "unknown"


def test_drifted_backend_is_unknown_fail_open() -> None:
    # A binding to a backend that's no longer in the catalog must not raise -- fail open to unknown.
    assert resolve_billing_mode(direct=True, has_api_key=False, backend_id="ghost-renamed") == "unknown"


def test_undeclared_keyless_is_unknown() -> None:
    # No binding (backend_id=None) never earns a subscription label.
    assert resolve_billing_mode(direct=True, has_api_key=False, backend_id=None) == "unknown"


def test_no_backend_matches_base_inference() -> None:
    # With backend_id=None, the resolver is byte-identical to infer_billing_mode.
    for direct in (True, False):
        for has_key in (True, False):
            assert resolve_billing_mode(direct=direct, has_api_key=has_key, backend_id=None) == infer_billing_mode(
                direct=direct, has_api_key=has_key
            )

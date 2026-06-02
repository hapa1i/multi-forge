"""Tests for conservative billing-mode inference (Phase 4c).

``infer_billing_mode`` asserts ``api`` only when a call is provably direct +
key-authenticated; everything ambiguous is ``unknown`` (never guessed).
"""

from __future__ import annotations

from forge.core.usage.billing import infer_billing_mode


def test_direct_with_key_is_api() -> None:
    assert infer_billing_mode(direct=True, has_api_key=True) == "api"


def test_direct_without_key_is_unknown() -> None:
    assert infer_billing_mode(direct=True, has_api_key=False) == "unknown"


def test_proxied_is_unknown_even_with_key() -> None:
    # A proxied call's upstream billing is opaque from the callsite -- never guess.
    assert infer_billing_mode(direct=False, has_api_key=True) == "unknown"

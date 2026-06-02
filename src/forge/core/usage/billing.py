"""Conservative billing-mode inference for usage attribution (Phase 4c).

The ledger records *how* work was billed, but Forge can only assert it where the
signal is unambiguous. This module returns ``"unknown"`` everywhere else -- a
guessed billing mode is worse than an honest "don't know," because downstream
cost reports would silently mis-attribute spend.
"""

from __future__ import annotations

from forge.core.usage.ledger import BillingMode


def infer_billing_mode(*, direct: bool, has_api_key: bool) -> BillingMode:
    """Infer the billing mode of an LLM invocation, conservatively.

    Returns ``"api"`` only when the call is *direct* (no Forge proxy in the path,
    so no unknown upstream) AND a provider API key authenticates it -- the one
    case we can assert per-token API billing. Everything else is ``"unknown"``:
    a proxied call's upstream billing is opaque from the callsite, and a direct
    call with no resolvable key is ambiguous. Never guesses subscription modes.

    Args:
        direct: True when the call bypasses any Forge proxy (hits the provider
            directly). A proxied call is always ``"unknown"`` here.
        has_api_key: True when a provider API key is resolvable for this call.
    """
    return "api" if (direct and has_api_key) else "unknown"

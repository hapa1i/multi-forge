"""Conservative billing-mode inference for usage attribution (Phase 4c).

The ledger records *how* work was billed, but Forge can only assert it where the
signal is unambiguous. This module returns ``"unknown"`` everywhere else -- a
guessed billing mode is worse than an honest "don't know," because downstream
cost reports would silently mis-attribute spend.
"""

from __future__ import annotations

from forge.backend.sources import (
    BillingPosture,
    ModelSourceNotFoundError,
    get_model_source,
)
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


def resolve_billing_mode(*, direct: bool, has_api_key: bool, backend_id: str | None) -> BillingMode:
    """Resolve billing mode, upgrading a keyless direct run on a subscription lane.

    Builds on :func:`infer_billing_mode`: keeps its conservative base (a key-authed
    direct call is ``"api"``; a proxied call stays opaque ``"unknown"``), then upgrades
    the one case it cannot see -- a *direct, keyless* run whose bound consumer-lane
    backend declares a subscription ``billing_posture`` -- to that subscription mode.

    Key presence always wins (mirrors the codex resolver's stored-key-before-tokens
    precedence): a key plus a subscription lane is still ``"api"``. ``backend_id`` is
    the bound lane's backend, or ``None`` when the consumer has no explicit binding (or
    it drifted out of the catalog); ``None`` never earns a subscription label.
    """
    base = infer_billing_mode(direct=direct, has_api_key=has_api_key)
    if base != "unknown":
        return base  # "api" (direct + key) wins; a proxied call is already opaque
    if direct and not has_api_key and backend_id is not None:
        if _backend_billing_posture(backend_id) == "subscription_quota":
            return "subscription_quota"
    return "unknown"


def _backend_billing_posture(backend_id: str) -> BillingPosture | None:
    """Return a backend's declared billing posture, or None if it is not in the catalog.

    Fail-open (design_workflows 1.2): a drifted binding -- a backend renamed out of the
    catalog -- resolves to ``unknown`` billing rather than raising into the telemetry path.
    """
    try:
        return get_model_source(backend_id).billing_posture
    except ModelSourceNotFoundError:
        return None

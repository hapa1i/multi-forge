"""Runtime-neutral normalization for model references used in route evidence."""

from __future__ import annotations

from forge.core.models.catalog import ModelCatalogError, resolve_model_id
from forge.core.models.direct_model import ONE_M_SUFFIX


def strip_transport_model_suffix(value: str) -> str:
    """Remove Claude Code's transport-only 1M suffix for catalog lookup."""
    return value.removesuffix(ONE_M_SUFFIX)


def normalize_model_reference(value: str | None) -> str | None:
    """Resolve a route-model reference without guessing unknown or removed ids.

    Exact catalog ids and aliases win. A single provider prefix is retried only
    after exact lookup fails. This helper deliberately performs no direct-Claude
    tier validation and never raises for an unknown reference.
    """
    if value is None:
        return None
    lookup = strip_transport_model_suffix(value.strip())
    if not lookup:
        return None
    candidates = [lookup]
    if "/" in lookup:
        candidates.append(lookup.split("/", 1)[1])
    for candidate in candidates:
        try:
            return resolve_model_id(candidate)
        except ModelCatalogError:
            continue
    return None

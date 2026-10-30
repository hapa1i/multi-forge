"""Predict only routes supported by live proxy dispatch facts."""

from __future__ import annotations

from dataclasses import dataclass

from forge.core.models.model_reference import strip_transport_model_suffix
from forge.core.models.model_routes import resolve_model_alternative
from forge.core.tiers import detect_tier_word
from forge.core.wire_shapes import ANTHROPIC_PASSTHROUGH
from forge.proxy.runtime_truth import ProxyRuntimeTruth

_TIERS = frozenset({"haiku", "sonnet", "opus"})


@dataclass(frozen=True)
class PredictedRoute:
    tier: str | None
    model: str | None


def predict_route(
    model_id: str | None,
    runtime: ProxyRuntimeTruth | None,
    *,
    authoritative: bool,
    projected_tier: str | None,
) -> PredictedRoute:
    """Apply dispatch precedence without treating configured maps as observed traffic."""
    explicit_tier = detect_tier_word(model_id) if model_id else None
    default_tier = runtime.active_tier if runtime else None
    tier = explicit_tier or (projected_tier if projected_tier in _TIERS else None) or default_tier
    tier = tier if tier in _TIERS else None
    if (
        runtime
        and authoritative
        and runtime.wire_shape == ANTHROPIC_PASSTHROUGH
        and tier is None
        and default_tier is None
    ):
        tier = "sonnet"
    if not runtime or not authoritative or not runtime.wire_shape or not runtime.has_authoritative_route_truth:
        return PredictedRoute(tier, None)
    request_model = strip_transport_model_suffix(model_id) if model_id else None
    if runtime.wire_shape == ANTHROPIC_PASSTHROUGH:
        return PredictedRoute(tier, request_model)
    if not request_model or "/" in request_model or tier is None:
        return PredictedRoute(tier, None)
    alternative = resolve_model_alternative(request_model, runtime.model_alternatives.get(tier, {}))
    return PredictedRoute(tier, alternative or runtime.tier_mappings.get(tier))

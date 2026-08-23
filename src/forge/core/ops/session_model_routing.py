"""Side-effect-free session model-route planning primitives."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

from forge.core.models.model_routes import ModelRouteRequest
from forge.session.models import (
    REQUIRED_MODEL_ROUTE_TIERS,
    LaunchIntent,
    ModelRouteIntent,
    ProxyIntent,
    SessionIntent,
)


class SessionModelRoutingError(ValueError):
    """Raised when a session model-route request cannot form valid intent."""


@dataclass(frozen=True)
class ResolvedModelRoute:
    """Concrete route selection produced before any session mutation."""

    request: ModelRouteRequest
    kind: Literal["direct", "proxy"]
    selected_tier: str
    source_id: str | None = None
    proxy_template: str | None = None
    proxy_base_url: str | None = None

    def __post_init__(self) -> None:
        if self.selected_tier not in REQUIRED_MODEL_ROUTE_TIERS:
            raise SessionModelRoutingError(
                f"selected tier must be one of: {', '.join(sorted(REQUIRED_MODEL_ROUTE_TIERS))}"
            )
        if self.kind == "direct":
            if self.request.claude_tier is None:
                raise SessionModelRoutingError("direct routing only supports Claude model requests")
            if self.selected_tier != self.request.claude_tier:
                raise SessionModelRoutingError(
                    f"direct Claude model {self.request.route_key!r} requires tier {self.request.claude_tier!r}, "
                    f"got {self.selected_tier!r}"
                )
            if self.source_id is not None or self.proxy_template is not None or self.proxy_base_url is not None:
                raise SessionModelRoutingError("direct routing cannot declare proxy source, template, or base URL")
            return
        if self.kind != "proxy":
            raise SessionModelRoutingError(f"unsupported model route kind: {self.kind!r}")
        if not self.proxy_template or not self.proxy_base_url:
            raise SessionModelRoutingError("proxy routing requires a template and base URL")
        if self.source_id is not None and not self.source_id:
            raise SessionModelRoutingError("proxy source_id must be null or non-empty")


@dataclass(frozen=True)
class ModelRouteTransition:
    """Complete session-owned route fields to apply atomically."""

    proxy: ProxyIntent | None
    direct_model: str | None
    model_route: ModelRouteIntent


def plan_model_route_transition(selection: ResolvedModelRoute) -> ModelRouteTransition:
    """Build the complete proxy/direct/neutral intent transition for a selection."""

    proxy = None
    if selection.kind == "proxy":
        assert selection.proxy_template is not None
        assert selection.proxy_base_url is not None
        proxy = ProxyIntent(template=selection.proxy_template, base_url=selection.proxy_base_url)

    direct_model = None
    if selection.request.claude_tier is not None:
        direct_model = selection.request.direct_execution_ref(selection.request.route_key)

    model_route = ModelRouteIntent(
        requested_model=selection.request.requested_model,
        selected_tier=selection.selected_tier,
        kind=selection.kind,
        source_id=selection.source_id,
    )
    return ModelRouteTransition(proxy=proxy, direct_model=direct_model, model_route=model_route)


def apply_model_route_transition(intent: SessionIntent, transition: ModelRouteTransition) -> SessionIntent:
    """Return a copied intent with all model-route-owned fields replaced together."""

    updated = deepcopy(intent)
    updated.proxy = deepcopy(transition.proxy)
    if updated.launch is None:
        updated.launch = LaunchIntent()
    updated.launch.direct_model = transition.direct_model
    updated.launch.model_route = deepcopy(transition.model_route)
    return updated


def clear_model_route_intent(intent: SessionIntent) -> SessionIntent:
    """Return a copied intent with only neutral model-route intent cleared."""

    updated = deepcopy(intent)
    if updated.launch is not None:
        updated.launch.model_route = None
    return updated


__all__ = [
    "ModelRouteTransition",
    "ResolvedModelRoute",
    "SessionModelRoutingError",
    "apply_model_route_transition",
    "clear_model_route_intent",
    "plan_model_route_transition",
]

"""Tests for side-effect-free interactive session model-route planning."""

from __future__ import annotations

from forge.core.models.model_routes import normalize_model_route_request
from forge.core.ops.session_model_routing import (
    ResolvedModelRoute,
    SessionModelRoutingError,
    apply_model_route_transition,
    clear_model_route_intent,
    plan_model_route_transition,
)
from forge.session.models import (
    LaunchIntent,
    ModelRouteIntent,
    ProxyIntent,
    SessionIntent,
)

import pytest


def test_direct_claude_transition_clears_proxy_and_preserves_transport_modifier() -> None:
    selection = ResolvedModelRoute(
        request=normalize_model_route_request("claude-opus-4-6[1m]"),
        kind="direct",
        selected_tier="opus",
    )

    transition = plan_model_route_transition(selection)

    assert transition.proxy is None
    assert transition.direct_model == "claude-opus-4-6[1m]"
    assert transition.model_route == ModelRouteIntent(
        requested_model="claude-opus-4-6",
        selected_tier="opus",
        kind="direct",
        source_id=None,
    )


def test_proxied_claude_transition_keeps_execution_pin() -> None:
    selection = ResolvedModelRoute(
        request=normalize_model_route_request("anthropic/claude-opus-4.6"),
        kind="proxy",
        selected_tier="opus",
        source_id="openrouter",
        proxy_template="openrouter-anthropic",
        proxy_base_url="http://localhost:8095",
    )

    transition = plan_model_route_transition(selection)

    assert transition.proxy == ProxyIntent(
        template="openrouter-anthropic",
        base_url="http://localhost:8095",
    )
    assert transition.direct_model == "claude-opus-4-6[1m]"
    assert transition.model_route.requested_model == "claude-opus-4-6-1m"
    assert transition.model_route.source_id == "openrouter"


def test_proxied_non_claude_transition_clears_stale_direct_pin() -> None:
    intent = SessionIntent(
        proxy=ProxyIntent(template="openrouter-anthropic", base_url="http://localhost:8095"),
        launch=LaunchIntent(direct_model="claude-opus-5"),
    )
    selection = ResolvedModelRoute(
        request=normalize_model_route_request("gpt-5.6-sol"),
        kind="proxy",
        selected_tier="opus",
        source_id="openrouter",
        proxy_template="openrouter-openai",
        proxy_base_url="http://localhost:8096",
    )

    updated = apply_model_route_transition(intent, plan_model_route_transition(selection))

    assert updated is not intent
    assert updated.proxy == ProxyIntent(template="openrouter-openai", base_url="http://localhost:8096")
    assert updated.launch is not None
    assert updated.launch.direct_model is None
    assert updated.launch.model_route == ModelRouteIntent(
        requested_model="gpt-5.6-sol",
        selected_tier="opus",
        kind="proxy",
        source_id="openrouter",
    )
    assert intent.proxy == ProxyIntent(template="openrouter-anthropic", base_url="http://localhost:8095")
    assert intent.launch is not None
    assert intent.launch.direct_model == "claude-opus-5"
    assert intent.launch.model_route is None


def test_apply_transition_preserves_unowned_intent_fields() -> None:
    intent = SessionIntent(agent="custom", subprocess_proxy="worker-proxy", launch=None)
    selection = ResolvedModelRoute(
        request=normalize_model_route_request("claude-sonnet-5"),
        kind="direct",
        selected_tier="sonnet",
    )

    updated = apply_model_route_transition(intent, plan_model_route_transition(selection))

    assert updated.agent == "custom"
    assert updated.subprocess_proxy == "worker-proxy"
    assert updated.launch is not None
    assert updated.launch.runtime == "claude_code"


def test_clear_model_route_preserves_proxy_and_legacy_pin() -> None:
    intent = SessionIntent(
        proxy=ProxyIntent(template="openrouter-anthropic", base_url="http://localhost:8095"),
        launch=LaunchIntent(
            direct_model="claude-opus-5",
            model_route=ModelRouteIntent(
                requested_model="claude-opus-5",
                selected_tier="opus",
                kind="proxy",
                source_id="openrouter",
            ),
        ),
    )

    updated = clear_model_route_intent(intent)

    assert updated.proxy == intent.proxy
    assert updated.launch is not None
    assert updated.launch.direct_model == "claude-opus-5"
    assert updated.launch.model_route is None
    assert intent.launch is not None
    assert intent.launch.model_route is not None


def test_rejects_invalid_direct_and_proxy_selections() -> None:
    with pytest.raises(SessionModelRoutingError, match="direct routing only supports Claude"):
        ResolvedModelRoute(
            request=normalize_model_route_request("gpt-5.6-sol"),
            kind="direct",
            selected_tier="opus",
        )

    with pytest.raises(SessionModelRoutingError, match="requires tier 'sonnet'"):
        ResolvedModelRoute(
            request=normalize_model_route_request("claude-sonnet-5"),
            kind="direct",
            selected_tier="opus",
        )

    with pytest.raises(SessionModelRoutingError, match="requires a template and base URL"):
        ResolvedModelRoute(
            request=normalize_model_route_request("gpt-5.6-sol"),
            kind="proxy",
            selected_tier="opus",
        )

"""Tests for side-effect-free interactive session model-route planning."""

from __future__ import annotations

import pytest

from forge.core.models.model_routes import (
    ModelRouteCandidate,
    get_model_route_candidates,
    normalize_model_route_request,
)
from forge.core.ops.session_model_routing import (
    ProxyRouteSnapshot,
    ResolvedModelRoute,
    SessionModelRoutingError,
    apply_model_route_transition,
    clear_model_route_intent,
    inspect_automatic_candidate,
    plan_model_route_transition,
    plan_session_model_route,
    realize_session_model_route,
    validate_model_tier_option,
)
from forge.session.models import (
    LaunchIntent,
    ModelRouteIntent,
    ProxyIntent,
    SessionIntent,
)


def _proxy_snapshot(
    *,
    template: str = "openrouter-openai",
    base_url: str | None = None,
    proxy_id: str | None = None,
    source_id: str | None = "openrouter",
    default_tier: str | None = "sonnet",
    tiers: dict[str, str] | None = None,
    alternatives: dict[str, dict[str, str]] | None = None,
    ensure_reference: str | None = None,
) -> ProxyRouteSnapshot:
    return ProxyRouteSnapshot(
        template=template,
        base_url=base_url,
        proxy_id=proxy_id,
        source_id=source_id,
        default_tier=default_tier,
        tier_mappings=tiers
        or {
            "sonnet": "openai/gpt-5.6-sol",
            "opus": "openai/gpt-5.6-sol",
        },
        model_alternatives=alternatives or {},
        wire_shape="anthropic_messages",
        ensure_reference=ensure_reference,
    )


class TestSessionModelRoutePlanning:
    def test_explicit_proxy_is_strict_and_wins_before_existing_route(self) -> None:
        explicit = _proxy_snapshot(default_tier="opus")
        existing = _proxy_snapshot(
            template="openrouter-gemini",
            tiers={"sonnet": "google/gemini-3.1-pro-preview"},
        )

        plan = plan_session_model_route(
            "gpt-5.6-sol",
            explicit_proxy=explicit,
            existing_kind="proxy",
            existing_proxy=existing,
        )

        assert plan.proxy is explicit
        assert plan.selected_tier == "opus"

        with pytest.raises(SessionModelRoutingError, match="does not serve model"):
            plan_session_model_route("gemini-3.1-pro-preview", explicit_proxy=explicit)

    def test_no_proxy_is_direct_only_and_validates_intrinsic_tier(self) -> None:
        plan = plan_session_model_route("claude-sonnet-5", no_proxy=True, model_tier="sonnet")

        assert plan.kind == "direct"
        assert plan.selected_tier == "sonnet"

        with pytest.raises(SessionModelRoutingError, match="supports Claude models only"):
            plan_session_model_route("gpt-5.6-sol", no_proxy=True)
        with pytest.raises(SessionModelRoutingError, match="requires --model-tier sonnet"):
            plan_session_model_route("claude-sonnet-5", no_proxy=True, model_tier="opus")

    def test_compatible_existing_route_is_preserved_without_candidate_scan(self) -> None:
        existing = _proxy_snapshot(base_url="http://localhost:8096", proxy_id="existing")

        def unexpected_candidate(_candidate: ModelRouteCandidate) -> ProxyRouteSnapshot | None:
            raise AssertionError("catalog scan must not run for a compatible persisted route")

        plan = plan_session_model_route(
            "gpt-5.6-sol",
            existing_kind="proxy",
            existing_proxy=existing,
            candidate_inspector=unexpected_candidate,
        )

        assert plan.proxy is existing
        assert plan.proxy is not None
        assert plan.proxy.ensure_reference is None

    def test_explicit_incompatible_existing_route_uses_first_admissible_catalog_candidate(self) -> None:
        existing = _proxy_snapshot(
            template="openrouter-gemini",
            tiers={"sonnet": "google/gemini-3.1-pro-preview"},
        )
        inspected: list[str] = []

        def inspect(candidate: ModelRouteCandidate) -> ProxyRouteSnapshot | None:
            template = candidate.template
            assert template is not None
            inspected.append(template)
            if template == "openrouter-openai":
                return _proxy_snapshot(ensure_reference=template)
            return None

        plan = plan_session_model_route(
            "gpt-5.6-sol",
            existing_kind="proxy",
            existing_proxy=existing,
            candidate_inspector=inspect,
        )

        assert inspected == ["openrouter-openai"]
        assert plan.proxy is not None
        assert plan.proxy.ensure_reference == "openrouter-openai"

    def test_bare_stored_route_never_falls_back_when_incompatible(self) -> None:
        existing = _proxy_snapshot(
            template="openrouter-gemini",
            tiers={"sonnet": "google/gemini-3.1-pro-preview"},
        )

        with pytest.raises(SessionModelRoutingError, match="does not serve model"):
            plan_session_model_route(
                "gpt-5.6-sol",
                existing_kind="proxy",
                existing_proxy=existing,
                allow_replacement=False,
            )

    def test_new_claude_request_remains_direct_without_scanning_runtime_state(self) -> None:
        def unexpected_candidate(_candidate: ModelRouteCandidate) -> ProxyRouteSnapshot | None:
            raise AssertionError("Claude direct selection must not scan proxy candidates")

        plan = plan_session_model_route(
            "claude-opus-5",
            candidate_inspector=unexpected_candidate,
        )

        assert plan.kind == "direct"
        assert plan.selected_model == "claude-opus-5"

    def test_tier_resolution_prefers_intrinsic_then_default_then_unique(self) -> None:
        claude = _proxy_snapshot(
            template="openrouter-anthropic",
            default_tier="sonnet",
            tiers={"opus": "anthropic/claude-opus-5", "sonnet": "anthropic/claude-opus-5"},
        )
        assert plan_session_model_route("claude-opus-5", explicit_proxy=claude).selected_tier == "opus"

        non_claude = _proxy_snapshot(default_tier="sonnet")
        assert plan_session_model_route("gpt-5.6-sol", explicit_proxy=non_claude).selected_tier == "sonnet"

        unique = _proxy_snapshot(default_tier="haiku", tiers={"opus": "openai/gpt-5.6-sol"})
        assert plan_session_model_route("gpt-5.6-sol", explicit_proxy=unique).selected_tier == "opus"

    def test_model_alternative_remains_compatible_when_transport_policy_changes_selected_model(self) -> None:
        proxy = _proxy_snapshot(
            template="openrouter-anthropic",
            tiers={"sonnet": "anthropic/claude-sonnet-5"},
            alternatives={"opus": {"claude-fable-5": "anthropic/claude-opus-5"}},
        )

        plan = plan_session_model_route("claude-fable-5", explicit_proxy=proxy)

        assert plan.selected_tier == "opus"
        assert plan.selected_model == "anthropic/claude-opus-5"

    def test_tier_ambiguity_names_choices_and_model_tier_recovery(self) -> None:
        proxy = _proxy_snapshot(default_tier=None)

        with pytest.raises(SessionModelRoutingError, match=r"multiple tiers \(opus, sonnet\).+--model-tier"):
            plan_session_model_route("gpt-5.6-sol", explicit_proxy=proxy)

        plan = plan_session_model_route("gpt-5.6-sol", explicit_proxy=proxy, model_tier="opus")
        assert plan.selected_tier == "opus"

    def test_automatic_tier_ambiguity_does_not_fall_through_after_candidate_selection(self) -> None:
        inspected: list[str] = []

        def inspect(candidate: ModelRouteCandidate) -> ProxyRouteSnapshot | None:
            template = candidate.template
            assert template is not None
            inspected.append(template)
            return _proxy_snapshot(template=template, default_tier=None, ensure_reference=template)

        with pytest.raises(SessionModelRoutingError, match="multiple tiers"):
            plan_session_model_route("gpt-5.6-sol", candidate_inspector=inspect)

        assert inspected == ["openrouter-openai"]

    def test_model_tier_requires_model_and_custom_routes_fail_closed(self) -> None:
        with pytest.raises(SessionModelRoutingError, match="--model-tier requires --model"):
            validate_model_tier_option(None, "opus")
        with pytest.raises(SessionModelRoutingError, match="Unknown model or alias"):
            plan_session_model_route("openai/not-in-the-catalog")

        custom = ProxyRouteSnapshot(
            template=None,
            base_url="https://example.invalid",
            proxy_id=None,
            source_id=None,
            default_tier=None,
            tier_mappings={},
            model_alternatives={},
            wire_shape="unknown",
        )
        with pytest.raises(SessionModelRoutingError, match="custom proxy route"):
            plan_session_model_route("gpt-5.6-sol", explicit_proxy=custom)

    def test_direct_1m_context_uses_transport_variant(self) -> None:
        base = plan_session_model_route("claude-opus-4-6")
        extended = plan_session_model_route("claude-opus-4-6[1m]")

        assert extended.context_limit > base.context_limit


def test_realization_calls_only_selected_proxy_and_never_falls_back() -> None:
    plan = plan_session_model_route(
        "gpt-5.6-sol",
        explicit_proxy=_proxy_snapshot(ensure_reference="openrouter-openai"),
    )
    calls: list[str] = []

    def fail_selected(reference: str) -> tuple[object, bool]:
        calls.append(reference)
        raise RuntimeError("startup failed")

    with pytest.raises(SessionModelRoutingError, match="startup failed"):
        realize_session_model_route(plan, ensure_proxy_fn=fail_selected)

    assert calls == ["openrouter-openai"]


def test_automatic_candidate_admission_uses_backend_source_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    from forge.core.auth import template_secrets

    candidate = get_model_route_candidates("gpt-5.6-sol")[0]
    assert candidate.source_id == "openrouter"
    monkeypatch.setattr(template_secrets, "resolve_env_or_credential", lambda _name: None)
    assert inspect_automatic_candidate(candidate) is None

    monkeypatch.setattr(template_secrets, "resolve_env_or_credential", lambda _name: "configured")
    snapshot = inspect_automatic_candidate(candidate)
    assert snapshot is not None
    assert snapshot.source_id == "openrouter"
    assert snapshot.ensure_reference == "openrouter-openai"


def test_realization_revalidates_the_selected_proxy_without_reselection(monkeypatch: pytest.MonkeyPatch) -> None:
    import forge.core.ops.session_model_routing as routing_module

    snapshot = _proxy_snapshot(ensure_reference="openrouter-openai")
    plan = plan_session_model_route("gpt-5.6-sol", explicit_proxy=snapshot, model_tier="opus")
    entry = type(
        "Entry",
        (),
        {
            "proxy_id": "proxy-1",
            "template": "openrouter-openai",
            "base_url": "http://localhost:8096",
        },
    )()
    healthchecks: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        routing_module,
        "inspect_persisted_proxy_route",
        lambda **_kwargs: _proxy_snapshot(
            base_url="http://localhost:8096",
            proxy_id="proxy-1",
            ensure_reference=None,
        ),
    )

    resolved = realize_session_model_route(
        plan,
        ensure_proxy_fn=lambda _reference: (entry, True),
        healthcheck_fn=lambda base_url, template, proxy_id: healthchecks.append((base_url, template, proxy_id)),
    )

    assert resolved.proxy_id == "proxy-1"
    assert resolved.selected_tier == "opus"
    assert resolved.started_proxy is True
    assert healthchecks == [("http://localhost:8096", "openrouter-openai", "proxy-1")]


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

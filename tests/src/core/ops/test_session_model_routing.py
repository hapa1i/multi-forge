"""Tests for side-effect-free interactive session model-route planning."""

from __future__ import annotations

from types import SimpleNamespace

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
    inspect_automatic_candidate,
    inspect_persisted_proxy_route,
    inspect_proxy_reference,
    plan_model_route_transition,
    plan_session_model_route,
    plan_session_model_route_for_state,
    preserved_model_route_request,
    realize_session_model_route,
    validate_model_tier_option,
)
from forge.session import create_session_state
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
    wire_shape: str = "openai_translated",
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
        wire_shape=wire_shape,
        ensure_reference=ensure_reference,
    )


class TestSessionModelRoutePlanning:
    @pytest.mark.parametrize(
        ("template", "tier"),
        [
            ("openrouter-openai", "sonnet"),
            ("openrouter-openai-codex", "opus"),
            ("litellm-openai", "sonnet"),
            ("litellm-openai-local", "sonnet"),
            ("litellm-openai-codex-local", "opus"),
            ("codex-responses-local", "sonnet"),
        ],
    )
    @pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-5.6-sol"])
    def test_current_gpt_templates_serve_astra_and_retained_sol(self, template: str, tier: str, model: str) -> None:
        snapshot = inspect_proxy_reference(template)

        plan = plan_session_model_route(model, explicit_proxy=snapshot, model_tier=tier)

        assert plan.selected_model == f"openai/{model}"
        assert plan.selected_tier == tier

    @pytest.mark.parametrize("template", ["openrouter-openai", "openrouter-openai-codex"])
    def test_astra_pro_alias_selects_the_openrouter_alternative(self, template: str) -> None:
        snapshot = inspect_proxy_reference(template)

        plan = plan_session_model_route("astra-pro", explicit_proxy=snapshot, model_tier="opus")

        assert plan.request.requested_model == "gpt-6-astra-pro"
        assert plan.selected_model == "openai/gpt-6-astra-pro"

    def test_astra_pro_has_no_native_litellm_route(self) -> None:
        snapshot = inspect_proxy_reference("litellm-openai-local")

        with pytest.raises(SessionModelRoutingError, match="does not serve model"):
            plan_session_model_route("astra-pro", explicit_proxy=snapshot)

    def test_astra_request_does_not_rewrite_an_existing_sol_snapshot(self) -> None:
        snapshot = _proxy_snapshot(proxy_id="existing-sol")

        with pytest.raises(SessionModelRoutingError, match="does not serve model"):
            plan_session_model_route("astra", explicit_proxy=snapshot)

        assert snapshot.tier_mappings == {
            "sonnet": "openai/gpt-5.6-sol",
            "opus": "openai/gpt-5.6-sol",
        }

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

    def test_compatible_existing_route_is_preserved_without_candidate_scan(
        self,
    ) -> None:
        existing = _proxy_snapshot(base_url="http://localhost:8096", proxy_id="existing")

        def unexpected_candidate(
            _candidate: ModelRouteCandidate,
        ) -> ProxyRouteSnapshot | None:
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

    def test_incompatible_existing_proxy_requires_an_explicit_route_boundary(self) -> None:
        existing = _proxy_snapshot(
            template="openrouter-gemini",
            proxy_id="old-gemini",
            tiers={"sonnet": "google/gemini-3.1-pro-preview"},
        )

        def unexpected_candidate(_candidate: ModelRouteCandidate) -> ProxyRouteSnapshot | None:
            raise AssertionError("an incompatible persisted proxy must fail before catalog fallback")

        with pytest.raises(
            SessionModelRoutingError,
            match=r"persisted proxy instance 'old-gemini'.+update or recreate.+--proxy",
        ):
            plan_session_model_route(
                "gpt-5.6-sol",
                existing_kind="proxy",
                existing_proxy=existing,
                candidate_inspector=unexpected_candidate,
            )

    def test_repointed_fable_alias_fails_cleanly_on_an_old_proxy_snapshot(self) -> None:
        existing = _proxy_snapshot(
            template="openrouter-anthropic",
            proxy_id="old-anthropic",
            tiers={"opus": "anthropic/claude-opus-5"},
            alternatives={"opus": {"claude-fable-5": "anthropic/claude-fable-5"}},
        )

        with pytest.raises(
            SessionModelRoutingError,
            match=(
                r"persisted proxy instance 'old-anthropic' \(template 'openrouter-anthropic'\) "
                r"does not serve model 'claude-fable-5-1'.+--proxy.+--no-proxy"
            ),
        ):
            plan_session_model_route("fable", existing_kind="proxy", existing_proxy=existing)

        direct = plan_session_model_route("fable", no_proxy=True)
        assert direct.kind == "direct"
        assert direct.selected_model == "claude-fable-5-1"

        prior = plan_session_model_route("claude-fable-5", existing_kind="proxy", existing_proxy=existing)
        assert prior.proxy is existing
        assert prior.selected_model == "anthropic/claude-fable-5"

    @pytest.mark.parametrize(
        "model_id",
        [
            "gemini-2.5-flash",
            "gemini-3.5-flash",
            "gemini-3.6-flash",
            "gemini-3.7-flash",
            "gemini-3.8-flash",
        ],
    )
    def test_automatic_openrouter_route_serves_current_and_earlier_flash_models(
        self,
        model_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from forge.core.auth import template_secrets

        monkeypatch.setattr(template_secrets, "resolve_env_or_credential", lambda _name: "configured")

        plan = plan_session_model_route(model_id)

        assert plan.kind == "proxy"
        assert plan.source_id == "openrouter"
        assert plan.proxy is not None
        assert plan.proxy.template == "openrouter-gemini-flash"
        assert plan.selected_tier == "sonnet"
        assert plan.selected_model == f"google/{model_id}"

    @pytest.mark.parametrize(
        "model_id",
        ["gemini-2.5-flash", "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash"],
    )
    def test_automatic_remote_litellm_fallback_serves_supported_flash_models(
        self,
        model_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from forge.core.auth import template_secrets

        monkeypatch.setattr(
            template_secrets,
            "resolve_env_or_credential",
            lambda name: None if name == "OPENROUTER_API_KEY" else "configured",
        )

        plan = plan_session_model_route(model_id)

        assert plan.kind == "proxy"
        assert plan.source_id == "litellm-remote"
        assert plan.proxy is not None
        assert plan.proxy.template == "litellm-gemini"
        assert plan.selected_tier == "sonnet"
        assert plan.selected_model == f"vertex_ai/{model_id}"

    def test_bare_stored_route_never_falls_back_when_incompatible(self) -> None:
        existing = _proxy_snapshot(
            template="openrouter-gemini",
            tiers={"sonnet": "google/gemini-3.1-pro-preview"},
        )

        with pytest.raises(SessionModelRoutingError, match="persisted proxy template.+does not serve model"):
            plan_session_model_route(
                "gpt-5.6-sol",
                existing_kind="proxy",
                existing_proxy=existing,
                allow_replacement=False,
            )

    def test_new_claude_request_remains_direct_without_scanning_runtime_state(
        self,
    ) -> None:
        def unexpected_candidate(
            _candidate: ModelRouteCandidate,
        ) -> ProxyRouteSnapshot | None:
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
            tiers={
                "opus": "anthropic/claude-opus-5",
                "sonnet": "anthropic/claude-opus-5",
            },
        )
        assert plan_session_model_route("claude-opus-5", explicit_proxy=claude).selected_tier == "opus"

        non_claude = _proxy_snapshot(default_tier="sonnet")
        assert plan_session_model_route("gpt-5.6-sol", explicit_proxy=non_claude).selected_tier == "sonnet"

        unique = _proxy_snapshot(default_tier="haiku", tiers={"opus": "openai/gpt-5.6-sol"})
        assert plan_session_model_route("gpt-5.6-sol", explicit_proxy=unique).selected_tier == "opus"

    def test_model_alternative_remains_compatible_when_transport_policy_changes_selected_model(
        self,
    ) -> None:
        proxy = _proxy_snapshot(
            template="openrouter-anthropic",
            tiers={"sonnet": "anthropic/claude-sonnet-5"},
            alternatives={"opus": {"claude-fable-5": "anthropic/claude-opus-5"}},
        )

        plan = plan_session_model_route("claude-fable-5", explicit_proxy=proxy)

        assert plan.selected_tier == "opus"
        assert plan.selected_model == "anthropic/claude-opus-5"

    @pytest.mark.parametrize(
        ("model_tier", "default_tier", "tiers"),
        [
            pytest.param("opus", "sonnet", None, id="explicit-tier"),
            pytest.param(None, "opus", None, id="default-tier"),
            pytest.param(None, None, {"haiku": "openai/gpt-5.4"}, id="single-serving-tier"),
        ],
    )
    def test_uncatalogued_selected_provider_model_is_a_contextual_routing_error(
        self,
        model_tier: str | None,
        default_tier: str | None,
        tiers: dict[str, str] | None,
    ) -> None:
        proxy = _proxy_snapshot(
            default_tier=default_tier,
            tiers=tiers,
            alternatives={"opus": {"gpt-5.6-sol": "openai/custom-finetune-x"}},
        )

        with pytest.raises(
            SessionModelRoutingError,
            match=r"selected provider model 'openai/custom-finetune-x'.+context window cannot be determined",
        ):
            plan_session_model_route("gpt-5.6-sol", explicit_proxy=proxy, model_tier=model_tier)

    def test_tier_ambiguity_names_choices_and_model_tier_recovery(self) -> None:
        proxy = _proxy_snapshot(default_tier=None)

        with pytest.raises(
            SessionModelRoutingError,
            match=r"multiple tiers \(opus, sonnet\).+--model-tier",
        ):
            plan_session_model_route("gpt-5.6-sol", explicit_proxy=proxy)

        plan = plan_session_model_route("gpt-5.6-sol", explicit_proxy=proxy, model_tier="opus")
        assert plan.selected_tier == "opus"

    def test_automatic_tier_ambiguity_does_not_fall_through_after_candidate_selection(
        self,
    ) -> None:
        inspected: list[str] = []

        def inspect(candidate: ModelRouteCandidate) -> ProxyRouteSnapshot | None:
            template = candidate.template
            assert template is not None
            inspected.append(template)
            return _proxy_snapshot(template=template, default_tier=None, ensure_reference=template)

        with pytest.raises(SessionModelRoutingError, match="multiple tiers"):
            plan_session_model_route("gpt-5.6-sol", candidate_inspector=inspect)

        assert inspected == ["openrouter-openai"]

    def test_automatic_compatibility_failure_does_not_fall_through_after_admission(
        self,
    ) -> None:
        candidates = tuple(
            candidate for candidate in get_model_route_candidates("gpt-5.6-sol") if candidate.kind == "proxy"
        )
        first, second = candidates[:2]
        inspected: list[str] = []

        def inspect(candidate: ModelRouteCandidate) -> ProxyRouteSnapshot | None:
            template = candidate.template
            assert template is not None
            inspected.append(template)
            if candidate == first:
                return _proxy_snapshot(
                    template=template,
                    tiers={"sonnet": "google/gemini-3.1-pro-preview"},
                    ensure_reference=template,
                )
            return _proxy_snapshot(template=template, ensure_reference=template)

        with pytest.raises(
            SessionModelRoutingError,
            match="pass --proxy <proxy_id-or-template>",
        ):
            plan_session_model_route("gpt-5.6-sol", candidate_inspector=inspect)

        assert inspected == [first.template]

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


def test_automatic_candidate_admission_uses_backend_source_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_explicit_proxy_records_a_proven_backend_source() -> None:
    snapshot = inspect_proxy_reference("openrouter-openai")

    assert snapshot.source_id == "openrouter"


def test_retired_stored_source_fails_when_preserved_route_is_replayed() -> None:
    state = create_session_state("retired-route", worktree_path="/tmp", runtime="claude_code")
    assert state.intent.launch is not None
    state.intent.launch.model_route = ModelRouteIntent(
        requested_model="gpt-5.6-sol",
        selected_tier="sonnet",
        kind="proxy",
        source_id="retired-source",
    )

    with pytest.raises(
        SessionModelRoutingError,
        match="stored proxy source 'retired-source'.+select a replacement",
    ):
        plan_session_model_route_for_state(
            "gpt-5.6-sol",
            state=state,
            allow_replacement=False,
        )


def test_persisted_route_rejects_same_url_registry_template_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from forge.config import loader
    from forge.proxy import proxies

    replacement = SimpleNamespace(proxy_id="replacement-id", template="replacement-template")
    monkeypatch.setattr(proxies.ProxyRegistryStore, "read", lambda _self: {})
    monkeypatch.setattr(proxies, "lookup_proxy_by_base_url", lambda _registry, _url: replacement)
    monkeypatch.setattr(loader, "load_config", lambda **_kwargs: SimpleNamespace(proxy=object()))

    with pytest.raises(SessionModelRoutingError, match="changed template identity"):
        inspect_persisted_proxy_route(
            template="stored-template",
            base_url="http://localhost:8096",
            proxy_id=None,
        )


def test_preserved_route_rejects_blank_template_before_same_url_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import forge.core.ops.session_model_routing as routing_module

    state = create_session_state("blank-template", worktree_path="/tmp", runtime="claude_code")
    assert state.intent.launch is not None
    state.intent.proxy = ProxyIntent(template="", base_url="http://localhost:8096")
    state.intent.launch.model_route = ModelRouteIntent(
        requested_model="gpt-5.6-sol",
        selected_tier="sonnet",
        kind="proxy",
        source_id=None,
    )

    def unexpected_inspection(**_kwargs: object) -> ProxyRouteSnapshot:
        raise AssertionError("blank stored template must fail before same-URL registry inference")

    monkeypatch.setattr(routing_module, "inspect_persisted_proxy_route", unexpected_inspection)

    with pytest.raises(SessionModelRoutingError, match="missing template identity"):
        plan_session_model_route_for_state(
            "gpt-5.6-sol",
            state=state,
            allow_replacement=False,
        )


def test_explicit_proxy_replacement_bypasses_blank_stored_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import forge.core.ops.session_model_routing as routing_module

    state = create_session_state("blank-template", worktree_path="/tmp", runtime="claude_code")
    assert state.intent.launch is not None
    state.intent.proxy = ProxyIntent(template="", base_url="http://localhost:8096")
    state.intent.launch.model_route = ModelRouteIntent(
        requested_model="gpt-5.6-sol",
        selected_tier="sonnet",
        kind="proxy",
        source_id=None,
    )
    replacement = _proxy_snapshot(base_url="http://localhost:8097", proxy_id="replacement")
    monkeypatch.setattr(routing_module, "inspect_proxy_reference", lambda _reference: replacement)

    def unexpected_inspection(**_kwargs: object) -> ProxyRouteSnapshot:
        raise AssertionError("explicit replacement must bypass malformed stored routing")

    monkeypatch.setattr(routing_module, "inspect_persisted_proxy_route", unexpected_inspection)

    plan = plan_session_model_route_for_state(
        "gpt-5.6-sol",
        proxy_name="replacement",
        state=state,
    )

    assert plan.proxy is replacement


def test_preserved_route_rejects_proven_source_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    import forge.core.ops.session_model_routing as routing_module

    state = create_session_state("source-drift", worktree_path="/tmp", runtime="claude_code")
    assert state.intent.launch is not None
    state.intent.proxy = ProxyIntent(template="openrouter-openai", base_url="http://localhost:8096")
    state.intent.launch.model_route = ModelRouteIntent(
        requested_model="gpt-5.6-sol",
        selected_tier="sonnet",
        kind="proxy",
        source_id="openrouter",
    )
    drifted = _proxy_snapshot(source_id=None, base_url="http://localhost:8096", proxy_id="proxy-1")
    monkeypatch.setattr(routing_module, "inspect_persisted_proxy_route", lambda **_kwargs: drifted)

    with pytest.raises(SessionModelRoutingError, match="no longer proves stored source 'openrouter'"):
        plan_session_model_route_for_state(
            "gpt-5.6-sol",
            model_tier="sonnet",
            state=state,
            allow_replacement=False,
        )


def test_preserved_route_does_not_enrich_unproven_source(monkeypatch: pytest.MonkeyPatch) -> None:
    import forge.core.ops.session_model_routing as routing_module

    state = create_session_state("unproven-source", worktree_path="/tmp", runtime="claude_code")
    assert state.intent.launch is not None
    state.intent.proxy = ProxyIntent(template="openrouter-openai", base_url="http://localhost:8096")
    state.intent.launch.model_route = ModelRouteIntent(
        requested_model="gpt-5.6-sol",
        selected_tier="sonnet",
        kind="proxy",
        source_id=None,
    )
    proven_now = _proxy_snapshot(source_id="openrouter", base_url="http://localhost:8096", proxy_id="proxy-1")
    monkeypatch.setattr(routing_module, "inspect_persisted_proxy_route", lambda **_kwargs: proven_now)

    plan = plan_session_model_route_for_state(
        "gpt-5.6-sol",
        model_tier="sonnet",
        state=state,
        allow_replacement=False,
    )

    assert plan.source_id is None


def test_preserved_model_route_request_restores_matching_1m_projection() -> None:
    state = create_session_state("one-m", worktree_path="/tmp", runtime="claude_code")
    assert state.intent.launch is not None
    state.intent.launch.direct_model = "claude-opus-4-6[1m]"
    state.intent.launch.model_route = ModelRouteIntent(
        requested_model="claude-opus-4-6",
        selected_tier="opus",
        kind="direct",
        source_id=None,
    )

    request = preserved_model_route_request(state)
    plan = plan_session_model_route_for_state(
        request,
        model_tier="opus",
        state=state,
        allow_replacement=False,
    )
    resolved = realize_session_model_route(plan)

    assert request == "claude-opus-4-6[1m]"
    assert plan.context_limit == 1_000_000
    assert plan_model_route_transition(resolved).direct_model == "claude-opus-4-6[1m]"


def test_preserved_model_route_request_rejects_mismatched_1m_projection() -> None:
    state = create_session_state("bad-one-m", worktree_path="/tmp", runtime="claude_code")
    assert state.intent.launch is not None
    state.intent.launch.direct_model = "claude-sonnet-4-6[1m]"
    state.intent.launch.model_route = ModelRouteIntent(
        requested_model="claude-opus-4-6",
        selected_tier="opus",
        kind="direct",
        source_id=None,
    )

    with pytest.raises(SessionModelRoutingError, match="does not match stored model route"):
        preserved_model_route_request(state)


def test_codex_responses_template_is_deliberately_dual_ingress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from forge.core.auth import template_secrets
    from forge.core.wire_shapes import OPENAI_RESPONSES_PASSTHROUGH

    candidate = next(
        candidate
        for candidate in get_model_route_candidates("gpt-5.6-sol")
        if candidate.template == "codex-responses-local"
    )
    monkeypatch.setattr(template_secrets, "resolve_env_or_credential", lambda _name: "configured")
    snapshot = inspect_automatic_candidate(candidate)

    assert snapshot is not None
    assert snapshot.wire_shape == OPENAI_RESPONSES_PASSTHROUGH
    plan = plan_session_model_route(
        "gpt-5.6-sol",
        candidate_inspector=lambda inspected: (snapshot if inspected == candidate else None),
    )
    assert plan.candidate == candidate
    assert plan.selected_model == "openai/gpt-5.6-sol"


def test_realization_revalidates_the_selected_proxy_without_reselection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_realization_rejects_selected_source_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    import forge.core.ops.session_model_routing as routing_module

    snapshot = _proxy_snapshot(ensure_reference="openrouter-openai")
    plan = plan_session_model_route("gpt-5.6-sol", explicit_proxy=snapshot, model_tier="opus")
    entry = SimpleNamespace(
        proxy_id="proxy-1",
        template="openrouter-openai",
        base_url="http://localhost:8096",
    )
    monkeypatch.setattr(
        routing_module,
        "inspect_persisted_proxy_route",
        lambda **_kwargs: _proxy_snapshot(
            source_id=None,
            base_url="http://localhost:8096",
            proxy_id="proxy-1",
        ),
    )

    with pytest.raises(SessionModelRoutingError, match="no longer proves source 'openrouter'"):
        realize_session_model_route(plan, ensure_proxy_fn=lambda _reference: (entry, False))


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

    with pytest.raises(SessionModelRoutingError, match="no longer in the backend-source catalog"):
        plan_model_route_transition(
            ResolvedModelRoute(
                request=normalize_model_route_request("gpt-5.6-sol"),
                kind="proxy",
                selected_tier="opus",
                source_id="retired-source",
                proxy_template="retired-template",
                proxy_base_url="http://localhost:8096",
            )
        )

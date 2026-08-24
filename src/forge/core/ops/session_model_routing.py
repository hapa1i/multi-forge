"""Side-effect-free session model-route planning primitives."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Literal

from forge.core.models.direct_model import ONE_M_SUFFIX
from forge.core.models.model_routes import (
    ModelRouteCandidate,
    ModelRouteCatalogError,
    ModelRouteRequest,
    get_model_route_candidates,
    normalize_model_route_request,
)
from forge.session.models import (
    REQUIRED_MODEL_ROUTE_TIERS,
    LaunchIntent,
    ModelRouteIntent,
    ProxyIntent,
    SessionIntent,
    SessionState,
)


class SessionModelRoutingError(ValueError):
    """Raised when a session model-route request cannot form valid intent."""


@dataclass(frozen=True)
class ProxyRouteSnapshot:
    """Read-only proxy/template facts used during route selection."""

    template: str | None
    base_url: str | None
    proxy_id: str | None
    source_id: str | None
    default_tier: str | None
    tier_mappings: Mapping[str, str]
    model_alternatives: Mapping[str, Mapping[str, str]]
    wire_shape: str
    ensure_reference: str | None = None

    def __post_init__(self) -> None:
        tiers = MappingProxyType(dict(self.tier_mappings))
        alternatives = MappingProxyType(
            {tier: MappingProxyType(dict(models)) for tier, models in self.model_alternatives.items()}
        )
        object.__setattr__(self, "tier_mappings", tiers)
        object.__setattr__(self, "model_alternatives", alternatives)


@dataclass(frozen=True)
class SessionModelRoutePlan:
    """Selected route before proxy realization or session mutation."""

    request: ModelRouteRequest
    kind: Literal["direct", "proxy"]
    selected_tier: str
    selected_model: str
    context_limit: int
    source_id: str | None = None
    proxy: ProxyRouteSnapshot | None = None
    candidate: ModelRouteCandidate | None = None

    def __post_init__(self) -> None:
        if self.kind == "direct":
            if self.proxy is not None or self.source_id is not None:
                raise SessionModelRoutingError("direct route plan cannot declare proxy or source identity")
            return
        if self.kind != "proxy" or self.proxy is None:
            raise SessionModelRoutingError("proxy route plan requires inspected proxy facts")


@dataclass(frozen=True)
class ResolvedModelRoute:
    """Concrete route selection produced before any session mutation."""

    request: ModelRouteRequest
    kind: Literal["direct", "proxy"]
    selected_tier: str
    source_id: str | None = None
    proxy_template: str | None = None
    proxy_base_url: str | None = None
    proxy_id: str | None = None
    selected_model: str | None = None
    context_limit: int | None = None
    started_proxy: bool = False

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
            if (
                self.source_id is not None
                or self.proxy_template is not None
                or self.proxy_base_url is not None
                or self.proxy_id is not None
                or self.started_proxy
            ):
                raise SessionModelRoutingError("direct routing cannot declare proxy source, template, or base URL")
            return
        if self.kind != "proxy":
            raise SessionModelRoutingError(f"unsupported model route kind: {self.kind!r}")
        if not self.proxy_template or not self.proxy_base_url:
            raise SessionModelRoutingError("proxy routing requires a template and base URL")
        if self.source_id is not None and not self.source_id:
            raise SessionModelRoutingError("proxy source_id must be null or non-empty")


CandidateInspector = Callable[[ModelRouteCandidate], ProxyRouteSnapshot | None]
ProxyEnsurer = Callable[[str], tuple[object, bool]]
ProxyHealthcheck = Callable[[str, str, str], None]


def validate_model_tier_option(model: str | None, model_tier: str | None) -> None:
    """Validate the CLI relationship shared by all interactive leaves."""

    if model_tier is not None and model is None:
        raise SessionModelRoutingError("--model-tier requires --model")
    if model_tier is not None and model_tier not in REQUIRED_MODEL_ROUTE_TIERS:
        raise SessionModelRoutingError(f"--model-tier must be one of: {', '.join(sorted(REQUIRED_MODEL_ROUTE_TIERS))}")


def plan_session_model_route(
    model: str,
    *,
    model_tier: str | None = None,
    explicit_proxy: ProxyRouteSnapshot | None = None,
    no_proxy: bool = False,
    existing_kind: Literal["direct", "proxy", "custom"] | None = None,
    existing_proxy: ProxyRouteSnapshot | None = None,
    allow_replacement: bool = True,
    candidate_inspector: CandidateInspector | None = None,
) -> SessionModelRoutePlan:
    """Select one route without starting a proxy or mutating session state."""

    validate_model_tier_option(model, model_tier)
    if explicit_proxy is not None and no_proxy:
        raise SessionModelRoutingError("--proxy and --no-proxy are mutually exclusive")
    try:
        request = normalize_model_route_request(model)
    except ModelRouteCatalogError as exc:
        raise SessionModelRoutingError(str(exc)) from exc

    if explicit_proxy is not None:
        return _plan_proxy_route(request, explicit_proxy, model_tier=model_tier)
    if no_proxy:
        return _plan_direct_route(request, model_tier=model_tier)

    if existing_kind is not None:
        if existing_kind == "direct":
            if request.claude_tier is not None:
                return _plan_direct_route(request, model_tier=model_tier)
            if not allow_replacement:
                raise SessionModelRoutingError(
                    f"stored direct route cannot serve non-Claude model {request.requested_model!r}"
                )
        elif existing_kind == "custom":
            raise SessionModelRoutingError(
                "--model cannot validate a custom proxy route without template and tier-map identity; "
                "pass --proxy <proxy_id-or-template> or --no-proxy"
            )
        elif existing_kind == "proxy":
            if existing_proxy is None:
                raise SessionModelRoutingError("persisted proxy route is missing inspectable template/config identity")
            serving = _serving_proxy_tiers(request, existing_proxy, candidate=None)
            compatible = bool(serving) and (model_tier is None or model_tier in serving)
            if compatible or not allow_replacement:
                return _plan_proxy_route(request, existing_proxy, model_tier=model_tier)
        else:
            raise SessionModelRoutingError(f"unsupported existing route kind: {existing_kind!r}")

    if request.claude_tier is not None:
        return _plan_direct_route(request, model_tier=model_tier)

    inspect_candidate = candidate_inspector or inspect_automatic_candidate
    for candidate in get_model_route_candidates(model):
        if candidate.kind != "proxy":
            continue
        proxy = inspect_candidate(candidate)
        if proxy is None:
            continue
        return _plan_proxy_route(request, proxy, model_tier=model_tier, candidate=candidate)
    raise SessionModelRoutingError(
        f"no admissible model route can serve {request.requested_model!r}; "
        "configure credentials for a compatible catalog route or pass --proxy explicitly"
    )


def plan_session_model_route_for_state(
    model: str,
    *,
    model_tier: str | None = None,
    proxy_name: str | None = None,
    no_proxy: bool = False,
    state: SessionState | None = None,
    allow_replacement: bool = True,
    candidate_inspector: CandidateInspector | None = None,
) -> SessionModelRoutePlan:
    """Build a route plan from CLI constraints and optional durable session state."""

    explicit_proxy = inspect_proxy_reference(proxy_name) if proxy_name is not None else None
    existing_kind: Literal["direct", "proxy", "custom"] | None = None
    existing_proxy: ProxyRouteSnapshot | None = None
    if state is not None and explicit_proxy is None and not no_proxy:
        if not allow_replacement:
            _validate_preserved_route_source(state)
        existing_kind, existing_proxy = _inspect_state_route(state)
        if existing_proxy is not None:
            existing_proxy = _validate_preserved_route_identity(state, existing_proxy)
    return plan_session_model_route(
        model,
        model_tier=model_tier,
        explicit_proxy=explicit_proxy,
        no_proxy=no_proxy,
        existing_kind=existing_kind,
        existing_proxy=existing_proxy,
        allow_replacement=allow_replacement,
        candidate_inspector=candidate_inspector,
    )


def inspect_proxy_reference(reference: str) -> ProxyRouteSnapshot:
    """Inspect an explicit proxy id/template without startup or health checks."""

    from forge.config.loader import load_config, template_exists
    from forge.proxy.proxies import (
        ProxyNotFoundError,
        ProxyRegistryStore,
        ProxyResolutionError,
        resolve_proxy,
    )

    try:
        entry = resolve_proxy(ProxyRegistryStore().read(), reference)
    except ProxyNotFoundError:
        try:
            if not template_exists(reference):
                raise SessionModelRoutingError(f"no proxy or template found matching {reference!r}")
            config = load_config(template=reference)
        except SessionModelRoutingError:
            raise
        except (FileNotFoundError, TypeError, ValueError) as exc:
            raise SessionModelRoutingError(f"could not inspect proxy template {reference!r}: {exc}") from exc
        return _snapshot_from_config(
            config.proxy,
            template=reference,
            base_url=None,
            proxy_id=None,
            ensure_reference=reference,
        )
    except ProxyResolutionError as exc:
        raise SessionModelRoutingError(str(exc)) from exc

    try:
        config = load_config(proxy_id=entry.proxy_id)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise SessionModelRoutingError(f"could not inspect proxy {entry.proxy_id!r}: {exc}") from exc
    return _snapshot_from_config(
        config.proxy,
        template=entry.template,
        base_url=entry.base_url,
        proxy_id=entry.proxy_id,
        ensure_reference=reference,
    )


def inspect_persisted_proxy_route(
    *,
    template: str | None,
    base_url: str,
    proxy_id: str | None,
) -> ProxyRouteSnapshot:
    """Inspect a persisted route without authorizing replacement or startup."""

    if proxy_id is None:
        from forge.proxy.proxies import ProxyRegistryStore, lookup_proxy_by_base_url

        entry = lookup_proxy_by_base_url(ProxyRegistryStore().read(), base_url)
        if entry is not None:
            if template is not None and entry.template != template:
                raise SessionModelRoutingError(
                    f"stored proxy route changed template identity at {base_url!r}: "
                    f"expected {template!r}, found {entry.template!r}; "
                    "pass --model with --proxy <proxy_id-or-template> to select a replacement"
                )
            proxy_id = entry.proxy_id
            if template is None:
                template = entry.template

    if template is None:
        return ProxyRouteSnapshot(
            template=None,
            base_url=base_url,
            proxy_id=proxy_id,
            source_id=None,
            default_tier=None,
            tier_mappings={},
            model_alternatives={},
            wire_shape="unknown",
        )

    from forge.config.loader import load_config

    try:
        config = load_config(proxy_id=proxy_id) if proxy_id is not None else load_config(template=template)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise SessionModelRoutingError(f"could not inspect persisted proxy route {template!r}: {exc}") from exc
    return _snapshot_from_config(
        config.proxy,
        template=template,
        base_url=base_url,
        proxy_id=proxy_id,
        ensure_reference=None,
    )


def inspect_automatic_candidate(
    candidate: ModelRouteCandidate,
) -> ProxyRouteSnapshot | None:
    """Return side-effect-free facts for one admissible automatic candidate."""

    if candidate.kind != "proxy" or candidate.source_id is None or candidate.template is None:
        return None

    from forge.backend.sources import get_model_source
    from forge.config.loader import load_config, template_exists
    from forge.core.auth.template_secrets import resolve_env_or_credential

    source = get_model_source(candidate.source_id)
    if any(resolve_env_or_credential(name) is None for name in source.required_env_vars):
        return None
    try:
        if not template_exists(candidate.template):
            return None
        config = load_config(template=candidate.template)
    except (FileNotFoundError, TypeError, ValueError):
        return None
    return _snapshot_from_config(
        config.proxy,
        template=candidate.template,
        base_url=None,
        proxy_id=None,
        source_id=candidate.source_id,
        ensure_reference=candidate.template,
    )


def realize_session_model_route(
    plan: SessionModelRoutePlan,
    *,
    ensure_proxy_fn: ProxyEnsurer | None = None,
    healthcheck_fn: ProxyHealthcheck | None = None,
) -> ResolvedModelRoute:
    """Realize one selected plan without reopening catalog fallback."""

    if plan.kind == "direct":
        return ResolvedModelRoute(
            request=plan.request,
            kind="direct",
            selected_tier=plan.selected_tier,
            selected_model=plan.selected_model,
            context_limit=plan.context_limit,
        )

    assert plan.proxy is not None
    proxy = plan.proxy
    started = False
    proxy_id: str | None
    template: str | None
    base_url: str | None
    if proxy.ensure_reference is not None:
        if ensure_proxy_fn is None:
            from forge.proxy.proxy_orchestrator import ensure_proxy

            ensure_proxy_fn = ensure_proxy
        try:
            entry, started = ensure_proxy_fn(proxy.ensure_reference)
            proxy_id = _required_string_attr(entry, "proxy_id")
            template = _required_string_attr(entry, "template")
            base_url = _required_string_attr(entry, "base_url")
        except Exception as exc:
            raise SessionModelRoutingError(
                f"selected proxy route {proxy.ensure_reference!r} could not be realized: {exc}"
            ) from exc
        if proxy.template is not None and template != proxy.template:
            raise SessionModelRoutingError(
                f"selected proxy route changed template identity: expected {proxy.template!r}, got {template!r}"
            )
    else:
        proxy_id = proxy.proxy_id
        template = proxy.template
        base_url = proxy.base_url
        if template is None or base_url is None:
            raise SessionModelRoutingError("selected persisted proxy route is unavailable or lacks template identity")

    if healthcheck_fn is not None:
        if proxy_id is None:
            raise SessionModelRoutingError(
                "selected persisted proxy route cannot be identity-checked without a proxy id; "
                "pass --proxy <proxy_id-or-template> to select it explicitly"
            )
        try:
            healthcheck_fn(base_url, template, proxy_id)
        except Exception as exc:
            raise SessionModelRoutingError(f"selected proxy route failed identity/health validation: {exc}") from exc

    concrete = inspect_persisted_proxy_route(template=template, base_url=base_url, proxy_id=proxy_id)
    if plan.source_id is not None and concrete.source_id != plan.source_id:
        raise SessionModelRoutingError(
            f"selected proxy route no longer proves source {plan.source_id!r}; "
            "pass --model with --proxy <proxy_id-or-template> to select a replacement"
        )
    confirmed = _plan_proxy_route(
        plan.request,
        concrete,
        model_tier=plan.selected_tier,
        candidate=plan.candidate,
    )
    return ResolvedModelRoute(
        request=plan.request,
        kind="proxy",
        selected_tier=confirmed.selected_tier,
        source_id=plan.source_id,
        proxy_template=template,
        proxy_base_url=base_url,
        proxy_id=proxy_id,
        selected_model=confirmed.selected_model,
        context_limit=confirmed.context_limit,
        started_proxy=started,
    )


def resolve_proxy_selected_model(
    requested_model: str,
    selected_tier: str,
    *,
    tier_mappings: Mapping[str, str],
    model_alternatives: Mapping[str, Mapping[str, str]],
    wire_shape: str,
) -> str:
    """Resolve one persisted proxy tier through the planner's compatibility rules."""

    try:
        request = normalize_model_route_request(requested_model)
    except ModelRouteCatalogError as exc:
        raise SessionModelRoutingError(str(exc)) from exc
    proxy = ProxyRouteSnapshot(
        template="<persisted-route>",
        base_url=None,
        proxy_id=None,
        source_id=None,
        default_tier=None,
        tier_mappings=tier_mappings,
        model_alternatives=model_alternatives,
        wire_shape=wire_shape,
    )
    serving = _serving_proxy_tiers(request, proxy, candidate=None)
    selected_model = serving.get(selected_tier)
    if selected_model is None:
        raise SessionModelRoutingError(
            f"persisted proxy route no longer serves {request.requested_model!r} at tier {selected_tier!r}"
        )
    return selected_model


def _plan_direct_route(request: ModelRouteRequest, *, model_tier: str | None) -> SessionModelRoutePlan:
    if request.claude_tier is None:
        raise SessionModelRoutingError(
            f"--no-proxy supports Claude models only; {request.requested_model!r} requires a proxy route"
        )
    if model_tier is not None and model_tier != request.claude_tier:
        raise SessionModelRoutingError(
            f"direct Claude model {request.requested_model!r} requires --model-tier {request.claude_tier}"
        )
    selected_model = request.direct_execution_ref(request.route_key)
    return SessionModelRoutePlan(
        request=request,
        kind="direct",
        selected_tier=request.claude_tier,
        selected_model=selected_model,
        context_limit=_selected_context_limit(request, selected_model),
    )


def _plan_proxy_route(
    request: ModelRouteRequest,
    proxy: ProxyRouteSnapshot,
    *,
    model_tier: str | None,
    candidate: ModelRouteCandidate | None = None,
) -> SessionModelRoutePlan:
    if proxy.template is None:
        raise SessionModelRoutingError(
            "--model cannot validate a custom proxy route without template and tier-map identity"
        )
    serving = _serving_proxy_tiers(request, proxy, candidate=candidate)
    if not serving:
        raise SessionModelRoutingError(
            f"proxy template {proxy.template!r} does not serve model {request.requested_model!r}"
        )
    selected_tier = _select_proxy_tier(request, proxy, serving, model_tier=model_tier)
    selected_model = serving[selected_tier]
    return SessionModelRoutePlan(
        request=request,
        kind="proxy",
        selected_tier=selected_tier,
        selected_model=selected_model,
        context_limit=_selected_context_limit(request, selected_model),
        source_id=proxy.source_id,
        proxy=proxy,
        candidate=candidate,
    )


def _serving_proxy_tiers(
    request: ModelRouteRequest,
    proxy: ProxyRouteSnapshot,
    *,
    candidate: ModelRouteCandidate | None,
) -> dict[str, str]:
    from forge.core.wire_shapes import ANTHROPIC_PASSTHROUGH

    if candidate is not None and _route_key(candidate.model_ref) != request.route_key:
        return {}
    if proxy.wire_shape == ANTHROPIC_PASSTHROUGH and request.claude_tier is not None:
        return {request.claude_tier: request.direct_execution_ref(request.route_key)}

    serving: dict[str, str] = {}
    for tier in sorted(REQUIRED_MODEL_ROUTE_TIERS):
        alternative = _matching_alternative(request, proxy.model_alternatives.get(tier, {}))
        selected_model = alternative or proxy.tier_mappings.get(tier)
        if selected_model is None:
            continue
        if alternative is None and _route_key(selected_model) != request.route_key:
            continue
        serving[tier] = selected_model
    return serving


def _matching_alternative(request: ModelRouteRequest, alternatives: Mapping[str, str]) -> str | None:
    for requested_model, selected_model in alternatives.items():
        if _route_key(requested_model) == request.route_key:
            return selected_model
    return None


def _select_proxy_tier(
    request: ModelRouteRequest,
    proxy: ProxyRouteSnapshot,
    serving: Mapping[str, str],
    *,
    model_tier: str | None,
) -> str:
    if model_tier is not None:
        if model_tier not in serving:
            available = ", ".join(sorted(serving))
            raise SessionModelRoutingError(
                f"proxy template {proxy.template!r} does not serve {request.requested_model!r} at "
                f"--model-tier {model_tier}; serving tiers: {available}"
            )
        return model_tier
    if request.claude_tier is not None and request.claude_tier in serving:
        return request.claude_tier
    if proxy.default_tier is not None and proxy.default_tier in serving:
        return proxy.default_tier
    if len(serving) == 1:
        return next(iter(serving))
    choices = ", ".join(sorted(serving))
    raise SessionModelRoutingError(
        f"model {request.requested_model!r} is available through multiple tiers ({choices}); "
        "choose one with --model-tier <haiku|sonnet|opus>"
    )


def _selected_context_limit(request: ModelRouteRequest, selected_model: str) -> int:
    from forge.core.models.catalog import (
        ModelCatalogError,
        get_context_window_tokens,
        model_exists,
        resolve_model_id,
    )

    if request.transport_1m and request.claude_tier is not None:
        one_m_model = f"{request.route_key}-1m"
        if model_exists(one_m_model):
            return get_context_window_tokens(one_m_model)
    try:
        return get_context_window_tokens(resolve_model_id(selected_model.removesuffix(ONE_M_SUFFIX)))
    except ModelCatalogError as exc:
        raise SessionModelRoutingError(
            f"selected provider model {selected_model!r} for {request.requested_model!r} is not in the Forge model "
            "catalog, so its context window cannot be determined; update the proxy tier mapping or "
            "model_alternatives to use a catalog model"
        ) from exc


def _route_key(model_ref: str) -> str:
    try:
        return normalize_model_route_request(model_ref).route_key
    except ValueError:
        return ""


def _snapshot_from_config(
    proxy_config: object,
    *,
    template: str,
    base_url: str | None,
    proxy_id: str | None,
    ensure_reference: str | None,
    source_id: str | None = None,
) -> ProxyRouteSnapshot:
    from forge.backend.sources import ModelSourceNotFoundError, get_model_source
    from forge.proxy.model_routes import effective_proxy_model_maps

    tiers, alternatives = effective_proxy_model_maps(proxy_config)
    proven_source = source_id
    if proven_source is None:
        backend = getattr(proxy_config, "backend", None)
        if isinstance(backend, str) and backend:
            try:
                source = get_model_source(backend)
            except ModelSourceNotFoundError:
                pass
            else:
                if template in source.template_names:
                    proven_source = source.id
    return ProxyRouteSnapshot(
        template=template,
        base_url=base_url,
        proxy_id=proxy_id,
        source_id=proven_source,
        default_tier=getattr(proxy_config, "default_tier", None),
        tier_mappings=tiers,
        model_alternatives=alternatives,
        wire_shape=str(getattr(proxy_config, "wire_shape", "unknown")),
        ensure_reference=ensure_reference,
    )


def _inspect_state_route(
    state: SessionState,
) -> tuple[Literal["direct", "proxy", "custom"], ProxyRouteSnapshot | None]:
    launch = state.intent.launch
    neutral = launch.model_route if launch is not None else None
    if neutral is not None and neutral.kind == "direct":
        return "direct", None

    if neutral is not None and neutral.kind == "proxy":
        if state.intent.proxy is None:
            raise SessionModelRoutingError(
                f"stored proxy model route for {neutral.requested_model!r} is missing intent.proxy; "
                f"pass --model {neutral.requested_model} with --proxy <proxy_id-or-template> to select a replacement"
            )
        template = state.intent.proxy.template or None
        base_url = state.intent.proxy.base_url
        snapshot = inspect_persisted_proxy_route(template=template, base_url=base_url, proxy_id=None)
        return ("proxy" if snapshot.template is not None else "custom"), snapshot

    confirmed = state.confirmed.started_with_proxy
    if confirmed is not None:
        snapshot = inspect_persisted_proxy_route(
            template=confirmed.template,
            base_url=confirmed.base_url,
            proxy_id=confirmed.proxy_id,
        )
        return ("proxy" if snapshot.template is not None else "custom"), snapshot
    if state.intent.proxy is not None:
        template = state.intent.proxy.template or None
        snapshot = inspect_persisted_proxy_route(
            template=template,
            base_url=state.intent.proxy.base_url,
            proxy_id=None,
        )
        return ("proxy" if snapshot.template is not None else "custom"), snapshot
    return "direct", None


def _validate_preserved_route_source(state: SessionState) -> None:
    """Revalidate mutable source membership only when replaying stored intent."""

    launch = state.intent.launch
    neutral = launch.model_route if launch is not None else None
    if neutral is None or neutral.source_id is None:
        return

    from forge.backend.sources import ModelSourceNotFoundError, get_model_source

    try:
        get_model_source(neutral.source_id)
    except ModelSourceNotFoundError as exc:
        raise SessionModelRoutingError(
            f"stored proxy source {neutral.source_id!r} for {neutral.requested_model!r} is no longer in the "
            "backend-source catalog; pass --model with --proxy <proxy_id-or-template> to select a replacement"
        ) from exc


def _validate_preserved_route_identity(
    state: SessionState,
    snapshot: ProxyRouteSnapshot,
) -> ProxyRouteSnapshot:
    """Keep replay bound to the template and source identity stored by the session."""

    launch = state.intent.launch
    neutral = launch.model_route if launch is not None else None
    if neutral is None or neutral.kind != "proxy":
        return snapshot

    stored_proxy = state.intent.proxy
    stored_template = (stored_proxy.template or None) if stored_proxy is not None else None
    if stored_template is not None and snapshot.template != stored_template:
        raise SessionModelRoutingError(
            f"stored proxy route changed template identity: expected {stored_template!r}, got {snapshot.template!r}; "
            f"pass --model {neutral.requested_model} with --proxy <proxy_id-or-template> to select a replacement"
        )

    if neutral.source_id is not None and snapshot.source_id != neutral.source_id:
        raise SessionModelRoutingError(
            f"stored proxy route for {neutral.requested_model!r} no longer proves stored source "
            f"{neutral.source_id!r}; pass --model {neutral.requested_model} with "
            "--proxy <proxy_id-or-template> to select a replacement"
        )
    if neutral.source_id is None and snapshot.source_id is not None:
        return replace(snapshot, source_id=None)
    return snapshot


def preserved_model_route_request(state: SessionState) -> str:
    """Restore a validated execution-only ``[1m]`` projection for route replay."""

    launch = state.intent.launch
    neutral = launch.model_route if launch is not None else None
    if neutral is None:
        raise SessionModelRoutingError("session has no stored model route to replay")
    assert launch is not None

    direct_model = launch.direct_model
    if direct_model is None or not direct_model.endswith(ONE_M_SUFFIX):
        return neutral.requested_model

    try:
        neutral_request = normalize_model_route_request(neutral.requested_model)
        direct_request = normalize_model_route_request(direct_model)
    except ModelRouteCatalogError as exc:
        raise SessionModelRoutingError(f"stored direct model projection is invalid: {exc}") from exc
    if direct_request.route_key != neutral_request.route_key:
        raise SessionModelRoutingError(
            f"stored direct model projection {direct_model!r} does not match stored model route "
            f"{neutral.requested_model!r}; pass --model with --proxy or --no-proxy to select a replacement"
        )
    if neutral_request.transport_1m:
        return neutral.requested_model
    return f"{neutral_request.route_key}{ONE_M_SUFFIX}"


def _required_string_attr(value: object, name: str) -> str:
    result = getattr(value, name, None)
    if not isinstance(result, str) or not result:
        raise SessionModelRoutingError(f"realized proxy is missing {name}")
    return result


@dataclass(frozen=True)
class ModelRouteTransition:
    """Complete session-owned route fields to apply atomically."""

    proxy: ProxyIntent | None
    direct_model: str | None
    model_route: ModelRouteIntent


def plan_model_route_transition(selection: ResolvedModelRoute) -> ModelRouteTransition:
    """Build the complete proxy/direct/neutral intent transition for a selection."""

    if selection.source_id is not None:
        from forge.backend.sources import ModelSourceNotFoundError, get_model_source

        try:
            get_model_source(selection.source_id)
        except ModelSourceNotFoundError as exc:
            raise SessionModelRoutingError(
                f"resolved proxy source {selection.source_id!r} is no longer in the backend-source catalog"
            ) from exc

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


__all__ = [
    "ModelRouteTransition",
    "ProxyRouteSnapshot",
    "ResolvedModelRoute",
    "SessionModelRoutePlan",
    "SessionModelRoutingError",
    "apply_model_route_transition",
    "inspect_automatic_candidate",
    "inspect_persisted_proxy_route",
    "inspect_proxy_reference",
    "plan_model_route_transition",
    "plan_session_model_route",
    "plan_session_model_route_for_state",
    "preserved_model_route_request",
    "realize_session_model_route",
    "resolve_proxy_selected_model",
    "validate_model_tier_option",
]

"""Workflow-specific routing types and functions.

Builds on the shared primitives in ``forge.core.reactive.routing``
to add workflow-specific types (``WorkerRoutingPlan``) and functions
(``derive_model_routes``, ``resolve_invocation_routing``,
``resolve_model_flag``).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from forge.core.reactive.routing import ModelRoute, RoutingResult
from forge.core.runtime.codex_preflight import CodexPreflight


@runtime_checkable
class RoutableSpec(Protocol):
    """Structural protocol for model specs that can be routed.

    Decouples routing from the concrete ``ModelSpec`` dataclass so
    Concrete ``ModelSpec`` instances satisfy this protocol implicitly.
    """

    @property
    def name(self) -> str: ...
    @property
    def model_id(self) -> str: ...
    @property
    def family(self) -> str: ...
    @property
    def runtime(self) -> str: ...


_log = logging.getLogger(__name__)

# Direct workers run claude -p --bare which needs ANTHROPIC_API_KEY
_DIRECT_CREDENTIAL = "anthropic-api"


class WorkflowRoutingError(RuntimeError):
    """Workflow routing failure with structured CLI recovery guidance."""

    def __init__(
        self,
        message: str,
        *,
        tip_lines: Sequence[str] = (),
        commands: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.tip_lines = tuple(tip_lines)
        self.commands = tuple(commands)


@dataclass(frozen=True)
class WorkerRoutingPlan:
    """Pre-resolved routing for all workers in a workflow invocation.

    Created once at invocation start. Frozen and passed to each worker.
    ``routes`` is indexed by worker position (same order as spec list). A
    runtime-native entry intentionally has ``source="runtime_native"`` and
    ``route=None``; every other workflow-plan entry requires a concrete route.
    """

    routes: tuple[RoutingResult, ...]
    resolved_at: str
    via_override: str | None
    codex_preflight: CodexPreflight | None = None


def resolve_model_flag(route: ModelRoute) -> str | None:
    """Return the ``--model`` flag for a routed workflow worker.

    Direct workers use Claude Code env pins instead of ``--model``.
    Proxied workers always send an explicit model ref so ``--models``
    means the same thing regardless of which compatible proxy was selected.
    """
    if route.provider == "direct":
        return None
    return route.model_ref


# ── Template metadata cache ──────────────────────────────────────


@dataclass(frozen=True)
class _TemplateMeta:
    """Cached static metadata for one proxy template."""

    name: str
    family: str
    preferred_provider: str
    credentials: tuple[str, ...]


_template_cache: dict[str, _TemplateMeta] = {}


def _get_template_meta(template_name: str) -> _TemplateMeta | None:
    """Load and cache template metadata (family, provider, credentials)."""
    if template_name in _template_cache:
        return _template_cache[template_name]

    try:
        import yaml

        from forge.config.loader import read_template

        content = read_template(template_name)
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            return None

        proxy_block = data.get("proxy", {})
        if not isinstance(proxy_block, dict):
            return None

        family = proxy_block.get("family", "")
        provider = proxy_block.get("preferred_provider", "")
        if not family or not provider:
            return None

        from forge.core.auth.capabilities import credentials_for_template

        creds = credentials_for_template(template_name)
        cred_names = tuple(c.name for c in creds)

        meta = _TemplateMeta(
            name=template_name,
            family=family,
            preferred_provider=provider,
            credentials=cred_names,
        )
        _template_cache[template_name] = meta
        return meta
    except Exception:
        _log.debug("Could not load metadata for template '%s'", template_name, exc_info=True)
        return None


def clear_template_cache() -> None:
    """Clear the template metadata cache (for testing)."""
    _template_cache.clear()


# ── Route derivation ─────────────────────────────────────────────


def derive_model_routes(spec: RoutableSpec) -> tuple[ModelRoute, ...]:
    """Materialize the shared route catalog for one workflow worker.

    Candidate order is already authoritative in ``model_routes.yaml``. Template
    metadata contributes family/provider/credential facts without consulting the
    runtime proxy registry or re-ranking candidates.
    """

    from forge.core.models.model_routes import (
        get_model_route_candidates,
        normalize_model_route_request,
    )

    request = normalize_model_route_request(spec.model_id)
    candidates = get_model_route_candidates(spec.model_id)
    routes: list[ModelRoute] = []
    for candidate in candidates:
        if candidate.kind == "direct":
            routes.append(
                ModelRoute(
                    provider="direct",
                    credential=_DIRECT_CREDENTIAL,
                    family=spec.family,
                    template_id=None,
                    template_family=None,
                    model_ref=request.direct_execution_ref(candidate.model_ref),
                )
            )
            continue

        assert candidate.template is not None
        meta = _get_template_meta(candidate.template)
        if meta is None:
            raise WorkflowRoutingError(
                f"Route catalog template {candidate.template!r} for model {spec.name!r} could not be loaded."
            )
        credential = meta.credentials[0] if meta.credentials else meta.preferred_provider
        routes.append(
            ModelRoute(
                provider=meta.preferred_provider,
                credential=credential,
                family=spec.family,
                template_id=candidate.template,
                template_family=meta.family,
                model_ref=candidate.model_ref,
            )
        )
    return tuple(routes)


def preferred_proxy_for_routes(routes: Sequence[ModelRoute]) -> str | None:
    """Return the catalog-leading proxy template, if the worker is proxied."""

    for route in routes:
        if route.provider != "direct" and route.template_id is not None:
            return route.template_id
    return None


# ── Invocation routing ───────────────────────────────────────────


def resolve_invocation_routing(
    specs: Sequence[Any],
    via: str | None = None,
) -> WorkerRoutingPlan:
    """Resolve routing for all workers at invocation start.

    Called once by the workflow CLI command. Fail-closed: raises if any
    non-runtime-native worker has no concrete route. Runtime-native workers
    carry their frozen readiness snapshot on the returned plan.
    """
    from forge.core.reactive.routing import resolve_subprocess_routing
    from forge.core.state import now_iso

    results: list[RoutingResult] = []
    codex_preflight = None
    if any(spec.runtime == "codex" for spec in specs):
        from forge.core.runtime.codex_preflight_cache import read_fresh_codex_preflight

        codex_preflight = read_fresh_codex_preflight()

    for spec in specs:
        routes: tuple[ModelRoute, ...]
        if spec.runtime == "codex":
            routes = ()
            result = _resolve_runtime_native_spec(spec, via)
        else:
            routes = derive_model_routes(spec)

            direct_only = bool(routes) and all(r.provider == "direct" for r in routes)
            if direct_only:
                result = _resolve_direct_spec(spec, routes, via)
            else:
                result = resolve_subprocess_routing(
                    explicit_proxy=via,
                    preferred_proxy=preferred_proxy_for_routes(routes),
                    routes=routes,
                    require_route=True,
                    advisory_check=True,
                )

        if result.source != "runtime_native" and result.route is None:
            _raise_no_route_error(spec, routes)

        _log_routing_decision(spec, result)
        results.append(result)

    return WorkerRoutingPlan(
        routes=tuple(results),
        resolved_at=now_iso(),
        via_override=via,
        codex_preflight=codex_preflight,
    )


def _log_routing_decision(spec: RoutableSpec, result: RoutingResult) -> None:
    """Emit one consolidated line for workflow routing observability."""
    route = result.route
    model_ref = route.model_ref if route else "(none)"
    template = result.template or (route.template_id if route else None) or "(direct)"
    proxy = result.proxy_id or "(direct)"
    _log.info(
        "Routing decision: model=%s source=%s proxy=%s template=%s model_ref=%s",
        spec.name,
        result.source,
        proxy,
        template,
        model_ref,
    )


def _resolve_direct_spec(
    spec: RoutableSpec,
    routes: tuple[ModelRoute, ...],
    via: str | None,
) -> RoutingResult:
    """Build a RoutingResult for a direct-only spec, bypassing the resolver."""
    direct_route = next((r for r in routes if r.provider == "direct"), None)
    if direct_route is None:
        _raise_no_route_error(spec, routes)

    warning = None
    if via:
        warning = f"Worker '{spec.name}' uses direct Anthropic routing; --proxy ignored."

    return RoutingResult(
        base_url=None,
        proxy_id=None,
        template=None,
        source="direct",
        route=direct_route,
        credential=_DIRECT_CREDENTIAL,
        warning=warning,
    )


def _resolve_runtime_native_spec(spec: RoutableSpec, via: str | None) -> RoutingResult:
    """Build the route-null success used by a runtime-owned Codex worker."""
    warning = None
    if via:
        warning = f"Worker '{spec.name}' uses direct routing; --proxy ignored."

    return RoutingResult(
        base_url=None,
        proxy_id=None,
        template=None,
        source="runtime_native",
        route=None,
        credential=None,
        warning=warning,
    )


def _raise_no_route_error(spec: RoutableSpec, routes: tuple[ModelRoute, ...]) -> None:
    """Raise an actionable error when no route resolves for a workflow worker.

    Distinguishes "missing credential" from "credential configured but no
    proxy running" to avoid sending the user to forge auth login when they
    need forge proxy create/start instead.
    """
    try:
        from forge.core.auth.capabilities import (
            CREDENTIALS,
            format_missing_credential_error,
        )
        from forge.core.auth.template_secrets import resolve_env_or_credential

        if not routes:
            raise WorkflowRoutingError(
                f"No routes derived for model '{spec.name}' (family={spec.family}).",
                tip_lines=(
                    "Run 'forge proxy create <template>' for a compatible proxy,",
                    "or 'forge auth login' to configure credentials.",
                ),
            )

        cred_name = routes[0].credential
        cred = CREDENTIALS.get(cred_name)

        if cred:
            missing_vars = [ev.name for ev in cred.env_vars if ev.required and not resolve_env_or_credential(ev.name)]
            if missing_vars:
                raise RuntimeError(
                    format_missing_credential_error(
                        cred,
                        missing_vars=missing_vars,
                        context=f"Workflow model '{spec.name}'",
                    )
                )

        template_ids = [r.template_id for r in routes if r.template_id]
        if template_ids:
            templates_str = ", ".join(template_ids[:3])
            message = f"No running proxy found for model '{spec.name}'.\n  Compatible templates: {templates_str}"
            raise WorkflowRoutingError(
                message,
                tip_lines=(
                    f"Run 'forge proxy create {template_ids[0]}' to create one,",
                    "or 'forge proxy start <id>' if one exists.",
                ),
            )

        raise RuntimeError(f"No route found for model '{spec.name}' (family={spec.family}).")
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError(f"No route found for model '{spec.name}' (family={spec.family}).")

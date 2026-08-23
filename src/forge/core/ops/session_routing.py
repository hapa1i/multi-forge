"""Launch-route preparation, required journal commit, and manifest projection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from forge.config.loader import load_config
from forge.core.models.direct_model import DirectModelPin, resolve_direct_model_pin
from forge.core.models.model_practices import (
    load_model_practices,
    resolve_model_practice,
)
from forge.core.models.model_reference import normalize_model_reference
from forge.core.reactive.env import RunIdentity
from forge.core.wire_shapes import ANTHROPIC_PASSTHROUGH, DEFAULT_WIRE_SHAPE
from forge.proxy.model_routes import effective_proxy_model_maps
from forge.session.models import RouteCommitConfirmed, SessionState
from forge.session.routing import (
    ROUTING_ABORT_EVENT,
    ROUTING_COMMIT_EVENT,
    append_routing_event,
    custom_route_fingerprint,
    new_routing_event,
)
from forge.session.store import SessionStore

from .session import ForgeOpError
from .session_authority_launch import AuthorityLaunchAttempt


def build_runtime_native_routing_payload() -> dict[str, Any]:
    """Build the exact runtime-native payload used by managed Codex launches."""
    load_model_practices()
    return {
        "route": {
            "kind": "runtime_native",
            "backend_id": None,
            "proxy_id": None,
            "template": None,
            "custom_route_fingerprint": None,
            "wire_shape": None,
        },
        "requested_model": None,
        "selected_tier": None,
        "selected_model": None,
        "default_tier": None,
        "direct_model": None,
        "tier_mappings": {},
        "model_alternatives": {},
        "billing_mode": "unknown",
        "route_scope_tags": ["route:runtime_native", "runtime:codex"],
        "marking_snapshots": [],
    }


def build_claude_routing_payload(
    state: SessionState,
    *,
    effective_template: str | None,
    runtime_base_url: str | None,
    proxy_id: str | None,
    applied_direct_model: DirectModelPin | None = None,
) -> dict[str, Any]:
    """Build one immutable Claude route snapshot after argv and env preparation."""
    catalog = load_model_practices()
    requested = state.intent.launch.direct_model if state.intent.launch is not None else None
    requested_pin = resolve_direct_model_pin(requested) if requested else None
    requested_model = requested_pin.canonical_model if requested_pin is not None else None

    if runtime_base_url is None:
        direct_model = applied_direct_model.canonical_model if applied_direct_model is not None else None
        selected_pin = applied_direct_model if requested_pin is not None else None
        scope = ["route:direct", "runtime:claude_code"]
        snapshots = (
            [_marking_snapshot("direct", None, None, direct_model, scope, catalog)] if direct_model is not None else []
        )
        return _payload(
            kind="direct",
            requested_model=requested_model,
            selected_tier=selected_pin.tier if selected_pin is not None else None,
            selected_model=selected_pin.canonical_model if selected_pin is not None else None,
            direct_model=direct_model,
            route_scope_tags=scope,
            marking_snapshots=snapshots,
        )

    if proxy_id is None and not effective_template:
        return _payload(
            kind="custom",
            custom_route_fingerprint=custom_route_fingerprint(runtime_base_url),
            requested_model=requested_model,
            selected_tier=None,
            route_scope_tags=["route:custom", "runtime:claude_code"],
        )

    try:
        config = load_config(proxy_id=proxy_id) if proxy_id is not None else load_config(template=effective_template)
    except ValueError as exc:
        config_label = (
            f"proxy.yaml for proxy {proxy_id!r}" if proxy_id is not None else f"proxy template {effective_template!r}"
        )
        raise ForgeOpError(f"{config_label} is invalid: {exc}") from exc
    tier_mappings, model_alternatives = effective_proxy_model_maps(config.proxy)
    default_tier = config.proxy.default_tier
    template = effective_template or config.proxy.active_template
    if not template:
        raise ForgeOpError("proxy route has no template identity")
    backend = config.proxy.backend
    backend_id = backend if isinstance(backend, str) and backend else None
    scope = ["route:proxy", "runtime:claude_code"]
    if backend_id is not None:
        scope.append(f"backend:{backend_id}")
    scope.sort()
    wire_shape = getattr(config.proxy, "wire_shape", DEFAULT_WIRE_SHAPE)
    snapshots = [
        _marking_snapshot("tier_default", tier, None, model, scope, catalog) for tier, model in tier_mappings.items()
    ]
    snapshots.extend(
        _marking_snapshot("model_alternative", tier, request_model, route_model, scope, catalog)
        for tier, alternatives in model_alternatives.items()
        for request_model, route_model in alternatives.items()
    )
    selected_model = None
    if applied_direct_model is not None:
        if wire_shape == ANTHROPIC_PASSTHROUGH:
            selected_model = applied_direct_model.canonical_model
        else:
            selected_model = model_alternatives.get(applied_direct_model.tier, {}).get(
                applied_direct_model.canonical_model
            )
            selected_model = selected_model or tier_mappings.get(applied_direct_model.tier)
    return _payload(
        kind="proxy",
        backend_id=backend_id,
        proxy_id=proxy_id,
        template=template,
        wire_shape=wire_shape,
        requested_model=requested_model,
        selected_tier=applied_direct_model.tier if applied_direct_model is not None else None,
        selected_model=selected_model,
        default_tier=default_tier,
        tier_mappings=tier_mappings,
        model_alternatives=model_alternatives,
        route_scope_tags=scope,
        marking_snapshots=snapshots,
    )


def commit_launch_routing(
    *,
    store: SessionStore,
    state: SessionState,
    root: RunIdentity,
    operation: str,
    payload: dict[str, Any],
    authority_attempt: AuthorityLaunchAttempt | None,
) -> RouteCommitConfirmed:
    """Commit routing and its pointer before a managed child can be invoked."""
    try:
        immutable_payload = deepcopy(payload)
        commit = new_routing_event(
            state,
            event_type=ROUTING_COMMIT_EVENT,
            run_id=root.run_id,
            operation=operation,
            payload=immutable_payload,
        )
    except Exception as primary:
        authority_errors = _compensate_authority(authority_attempt, "routing_commit_failed")
        raise _routing_failure("routing commit validation", primary, authority_errors) from primary
    try:
        append_routing_event(store.forge_root, commit)
    except Exception as primary:
        authority_errors = _compensate_authority(authority_attempt, "routing_commit_failed")
        raise _routing_failure("required routing commit append", primary, authority_errors) from primary

    projection = RouteCommitConfirmed(event_id=commit.event_id, run_id=root.run_id)
    try:
        store.update(
            timeout_s=5.0,
            mutate=lambda manifest: setattr(manifest.confirmed, "route_commit", projection),
        )
    except Exception as primary:
        compensation_errors: list[str] = []
        try:
            abort = new_routing_event(
                state,
                event_type=ROUTING_ABORT_EVENT,
                run_id=root.run_id,
                operation=operation,
                payload=immutable_payload,
            )
            append_routing_event(store.forge_root, abort)
        except Exception as compensation:
            compensation_errors.append(f"routing abort failed: {compensation}")
        compensation_errors.extend(_compensate_authority(authority_attempt, "route_projection_failed"))
        raise _routing_failure("route projection", primary, compensation_errors) from primary
    return projection


def _compensate_authority(attempt: AuthorityLaunchAttempt | None, reason_code: str) -> list[str]:
    if attempt is None:
        return []
    try:
        attempt.abort_before_child(reason_code=reason_code)
    except Exception as exc:
        return [f"authority abort failed: {exc}"]
    return []


def _routing_failure(label: str, primary: Exception, compensation_errors: list[str]) -> ForgeOpError:
    suffix = f"; compensation errors: {'; '.join(compensation_errors)}" if compensation_errors else ""
    return ForgeOpError(f"launch {label} failed: {primary}{suffix}")


def _marking_snapshot(
    slot: str,
    tier: str | None,
    request_model: str | None,
    route_model: str,
    scope: list[str],
    catalog: Any,
) -> dict[str, Any]:
    canonical = normalize_model_reference(route_model)
    return {
        "slot": slot,
        "tier": tier,
        "request_model": request_model,
        "route_model": route_model,
        "canonical_model": canonical,
        "declaration": resolve_model_practice(canonical, scope, catalog=catalog),
    }


def _payload(
    *,
    kind: str,
    backend_id: str | None = None,
    proxy_id: str | None = None,
    template: str | None = None,
    custom_route_fingerprint: str | None = None,
    wire_shape: str | None = None,
    requested_model: str | None = None,
    selected_tier: str | None = None,
    selected_model: str | None = None,
    default_tier: str | None = None,
    direct_model: str | None = None,
    tier_mappings: dict[str, str] | None = None,
    model_alternatives: dict[str, dict[str, str]] | None = None,
    route_scope_tags: list[str],
    marking_snapshots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "route": {
            "kind": kind,
            "backend_id": backend_id,
            "proxy_id": proxy_id,
            "template": template,
            "custom_route_fingerprint": custom_route_fingerprint,
            "wire_shape": wire_shape,
        },
        "requested_model": requested_model,
        "selected_tier": selected_tier,
        "selected_model": selected_model,
        "default_tier": default_tier,
        "direct_model": direct_model,
        "tier_mappings": tier_mappings or {},
        "model_alternatives": model_alternatives or {},
        "billing_mode": "unknown",
        "route_scope_tags": route_scope_tags,
        "marking_snapshots": marking_snapshots or [],
    }

"""Read-only session model-route provenance reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

from forge.config.loader import load_config
from forge.core.models.model_practices import (
    ModelPracticesCatalog,
    load_model_practices,
    resolve_model_practice,
)
from forge.core.models.model_reference import normalize_model_reference
from forge.proxy.model_routes import effective_proxy_model_maps
from forge.proxy.runtime_truth import ProxyRuntimeTruth
from forge.session.models import SessionState, session_runtime
from forge.session.routing import (
    RoutingHistory,
    custom_route_fingerprint,
    derive_routing_history,
)

from .context import ExecutionContext
from .session import resolve_session
from .session_active import read_active_session_strict

MODEL_REPORT_LIMITATIONS = (
    "route commitment only",
    "no per-request or authorship attestation",
)


@dataclass(frozen=True)
class SessionModelReport:
    """Stable schema-v1 model-route read payload."""

    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.payload


@dataclass(frozen=True)
class SessionModelHistoryReport:
    """Stable schema-v1 routing-history read payload."""

    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.payload


def get_session_model_report(*, ctx: ExecutionContext, session_name: str | None = None) -> SessionModelReport:
    """Resolve one session and render its intent, durable route, and live proxy facts."""
    resolved = resolve_session(ctx=ctx, session_name=session_name)
    state = resolved.state
    catalog = load_model_practices()
    active = read_active_session_strict(resolved.store) is not None
    history = derive_routing_history(resolved.store.forge_root, state)
    intent = _route_intent(state)
    route_commit = _route_commit(state, history)
    live_proxy = _live_proxy(state, intent, route_commit)
    marking = _marking(route_commit, live_proxy, history, catalog)
    return SessionModelReport(
        {
            "schema_version": 1,
            "session": state.name,
            "runtime": session_runtime(state),
            "active": active,
            "route_intent": intent,
            "route_commit": route_commit,
            "live_proxy": live_proxy,
            "current_request_tier": None,
            "current_request_source": "unavailable",
            "history_status": history.status,
            "marking": marking,
            "limitations": list(MODEL_REPORT_LIMITATIONS),
        }
    )


def get_session_model_history_report(
    *, ctx: ExecutionContext, session_name: str | None = None
) -> SessionModelHistoryReport:
    """Return every validated routing event in append order."""
    resolved = resolve_session(ctx=ctx, session_name=session_name)
    history = derive_routing_history(resolved.store.forge_root, resolved.state)
    return SessionModelHistoryReport(
        {
            "schema_version": 1,
            "session": resolved.state.name,
            "history_status": history.status,
            "events": [asdict(event) for event in history.events],
        }
    )


def _route_intent(state: SessionState) -> dict[str, Any]:
    runtime = session_runtime(state)
    launch = state.intent.launch
    requested = None
    if launch is not None:
        requested = launch.model_route.requested_model if launch.model_route is not None else launch.direct_model
    if runtime == "codex":
        return {
            "kind": "runtime_native",
            "template": None,
            "proxy_id": None,
            "custom_route_fingerprint": None,
            "requested_model": None,
        }
    proxy = state.intent.proxy
    if proxy is None:
        return {
            "kind": "direct",
            "template": None,
            "proxy_id": None,
            "custom_route_fingerprint": None,
            "requested_model": normalize_model_reference(requested),
        }
    if proxy.template:
        return {
            "kind": "proxy",
            "template": proxy.template,
            "proxy_id": None,
            "custom_route_fingerprint": None,
            "requested_model": normalize_model_reference(requested),
        }
    return {
        "kind": "custom",
        "template": None,
        "proxy_id": None,
        "custom_route_fingerprint": custom_route_fingerprint(proxy.base_url),
        "requested_model": normalize_model_reference(requested),
    }


def _route_commit(state: SessionState, history: RoutingHistory) -> dict[str, Any] | None:
    projection = state.confirmed.route_commit
    if projection is not None:
        if history.status == "supported" and history.effective_commit is not None:
            return _commit_from_payload(
                event_id=projection.event_id,
                run_id=projection.run_id,
                evidence_source="route_commit",
                payload=history.effective_commit.payload,
            )
        return _empty_commit(
            event_id=projection.event_id,
            run_id=projection.run_id,
            evidence_source="unproven_projection",
        )

    legacy = state.confirmed.launch
    if legacy is None:
        return None
    kind = {"custom_base_url": "custom"}.get(legacy.routing_mode or "", legacy.routing_mode)
    commit = _empty_commit(event_id=None, run_id=None, evidence_source="legacy_confirmed_launch")
    commit.update(
        {
            "kind": kind if kind in {"direct", "proxy", "custom"} else None,
            "proxy_id": legacy.proxy_id,
            "template": (state.intent.proxy.template if state.intent.proxy is not None else None),
            "custom_route_fingerprint": (
                custom_route_fingerprint(legacy.base_url) if kind == "custom" and legacy.base_url is not None else None
            ),
            "requested_model": normalize_model_reference(
                state.intent.launch.direct_model if state.intent.launch is not None else None
            ),
        }
    )
    return commit


def _commit_from_payload(
    *,
    event_id: str | None,
    run_id: str | None,
    evidence_source: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    route = payload["route"]
    return {
        "run_id": run_id,
        "event_id": event_id,
        "evidence_source": evidence_source,
        "kind": route["kind"],
        "backend_id": route["backend_id"],
        "proxy_id": route["proxy_id"],
        "template": route["template"],
        "custom_route_fingerprint": route["custom_route_fingerprint"],
        "requested_model": payload["requested_model"],
        "selected_tier": payload["selected_tier"],
        "selected_model": payload["selected_model"],
        "default_tier": payload["default_tier"],
        "direct_model": payload["direct_model"],
        "tier_mappings": payload["tier_mappings"],
        "model_alternatives": payload["model_alternatives"],
        "billing_mode": payload["billing_mode"],
        "route_scope_tags": payload["route_scope_tags"],
    }


def _empty_commit(*, event_id: str | None, run_id: str | None, evidence_source: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "event_id": event_id,
        "evidence_source": evidence_source,
        "kind": None,
        "backend_id": None,
        "proxy_id": None,
        "template": None,
        "custom_route_fingerprint": None,
        "requested_model": None,
        "selected_tier": None,
        "selected_model": None,
        "default_tier": None,
        "direct_model": None,
        "tier_mappings": {},
        "model_alternatives": {},
        "billing_mode": None,
        "route_scope_tags": [],
    }


def _live_proxy(
    state: SessionState,
    intent: dict[str, Any],
    route_commit: dict[str, Any] | None,
) -> dict[str, Any]:
    route_kind = route_commit.get("kind") if route_commit and route_commit.get("kind") else intent["kind"]
    if route_kind != "proxy":
        return _empty_live_proxy("not_applicable")

    proxy_id = _first_string(
        route_commit.get("proxy_id") if route_commit else None,
        state.confirmed.launch.proxy_id if state.confirmed.launch is not None else None,
        (state.confirmed.started_with_proxy.proxy_id if state.confirmed.started_with_proxy is not None else None),
    )
    template = _first_string(
        route_commit.get("template") if route_commit else None,
        intent.get("template"),
        (state.confirmed.started_with_proxy.template if state.confirmed.started_with_proxy is not None else None),
    )
    base_url = _first_string(
        state.confirmed.launch.base_url if state.confirmed.launch is not None else None,
        (state.confirmed.started_with_proxy.base_url if state.confirmed.started_with_proxy is not None else None),
        state.intent.proxy.base_url if state.intent.proxy is not None else None,
    )

    runtime = _probe_proxy_runtime(base_url, expected_proxy_id=proxy_id, expected_template=template)
    runtime_reachable = runtime is not None
    if runtime is not None and _runtime_has_route_truth(runtime):
        return {
            "reachable": True,
            "evidence_source": "runtime",
            "proxy_id": runtime.proxy_id,
            "template": runtime.template if runtime.template != "unknown" else None,
            "backend_id": runtime.backend_id,
            "default_tier": runtime.active_tier,
            "tier_mappings": runtime.tier_mappings,
            "model_alternatives": runtime.model_alternatives,
        }

    if proxy_id is not None or template is not None:
        try:
            config = load_config(proxy_id=proxy_id) if proxy_id is not None else load_config(template=template)
            tier_mappings, alternatives = effective_proxy_model_maps(config.proxy)
            return {
                "reachable": runtime_reachable,
                "evidence_source": "proxy_config",
                "proxy_id": proxy_id,
                "template": config.proxy.active_template or template,
                "backend_id": config.proxy.backend or None,
                "default_tier": config.proxy.default_tier,
                "tier_mappings": tier_mappings,
                "model_alternatives": alternatives,
            }
        except Exception:
            pass

    if route_commit is not None and route_commit.get("evidence_source") == "route_commit":
        return {
            "reachable": runtime_reachable,
            "evidence_source": "route_commit",
            "proxy_id": route_commit["proxy_id"],
            "template": route_commit["template"],
            "backend_id": route_commit["backend_id"],
            "default_tier": route_commit["default_tier"],
            "tier_mappings": route_commit["tier_mappings"],
            "model_alternatives": route_commit["model_alternatives"],
        }
    unavailable = _empty_live_proxy("unavailable")
    unavailable.update({"reachable": runtime_reachable, "proxy_id": proxy_id, "template": template})
    return unavailable


def _empty_live_proxy(evidence_source: str) -> dict[str, Any]:
    return {
        "reachable": False,
        "evidence_source": evidence_source,
        "proxy_id": None,
        "template": None,
        "backend_id": None,
        "default_tier": None,
        "tier_mappings": {},
        "model_alternatives": {},
    }


def _probe_proxy_runtime(
    base_url: str | None,
    *,
    expected_proxy_id: str | None,
    expected_template: str | None,
) -> ProxyRuntimeTruth | None:
    if base_url is None:
        return None
    try:
        import httpx

        parsed = urlsplit(base_url if "://" in base_url else f"http://{base_url}")
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        port = f":{parsed.port}" if parsed.port is not None else ""
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        query_url = f"{parsed.scheme}://{host}{port}/"
        with httpx.Client(timeout=httpx.Timeout(0.5)) as client:
            response = client.get(query_url)
        if response.status_code != 200:
            return None
        raw = response.json()
        if not isinstance(raw, dict) or raw.get("is_proxy") is not True:
            return None
        runtime = ProxyRuntimeTruth(raw)
        if expected_proxy_id is not None and runtime.proxy_id != expected_proxy_id:
            return None
        if expected_template is not None and runtime.template != expected_template:
            return None
        return runtime
    except Exception:
        return None


def _runtime_has_route_truth(runtime: ProxyRuntimeTruth) -> bool:
    return runtime.has_authoritative_route_truth


def _marking(
    route_commit: dict[str, Any] | None,
    live_proxy: dict[str, Any],
    history: RoutingHistory,
    catalog: ModelPracticesCatalog,
) -> dict[str, Any]:
    launch_entries: list[dict[str, Any]] = []
    if (
        route_commit is not None
        and route_commit.get("evidence_source") == "route_commit"
        and history.effective_commit is not None
    ):
        scope = route_commit["route_scope_tags"]
        for snapshot in history.effective_commit.payload["marking_snapshots"]:
            current = resolve_model_practice(snapshot["canonical_model"], scope, catalog=catalog)
            launch_entries.append(
                {
                    "slot": snapshot["slot"],
                    "tier": snapshot["tier"],
                    "request_model": snapshot["request_model"],
                    "route_model": snapshot["route_model"],
                    "canonical_model": snapshot["canonical_model"],
                    "launch_snapshot": snapshot["declaration"],
                    "current_declaration": current,
                    "changed_since_launch": current != snapshot["declaration"],
                }
            )

    live_entries: list[dict[str, Any]] = []
    if live_proxy["evidence_source"] == "runtime":
        scope = ["route:proxy", "runtime:claude_code"]
        live_backend = live_proxy["backend_id"]
        if isinstance(live_backend, str) and live_backend:
            scope.append(f"backend:{live_backend}")
        scope.sort()
        for tier, model in live_proxy["tier_mappings"].items():
            live_entries.append(_live_marking_entry("tier_default", tier, None, model, scope, catalog))
        for tier, alternatives in live_proxy["model_alternatives"].items():
            if not isinstance(alternatives, dict):
                continue
            for request_model, route_model in alternatives.items():
                live_entries.append(
                    _live_marking_entry(
                        "model_alternative",
                        tier,
                        request_model,
                        route_model,
                        scope,
                        catalog,
                    )
                )
    return {
        "scope": "text",
        # This labels the semantics of every status, including unknown. It is not
        # a claim that a declaration exists for at least one displayed model.
        "provider_declared": True,
        "launch_entries": launch_entries,
        "live_proxy_entries": live_entries,
    }


def _live_marking_entry(
    slot: str,
    tier: str,
    request_model: str | None,
    route_model: object,
    scope: list[str],
    catalog: ModelPracticesCatalog,
) -> dict[str, Any]:
    model = route_model if isinstance(route_model, str) else ""
    canonical = normalize_model_reference(model)
    return {
        "slot": slot,
        "tier": tier,
        "request_model": request_model,
        "route_model": model,
        "canonical_model": canonical,
        "evidence_source": "runtime",
        "declaration": resolve_model_practice(canonical, scope, catalog=catalog),
    }


def _first_string(*values: object) -> str | None:
    return next((value for value in values if isinstance(value, str) and value), None)

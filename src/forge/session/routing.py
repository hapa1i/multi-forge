"""Strict session launch-routing journal, projection, and payload contracts."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from forge.core.models.model_practices import (
    ModelPracticesError,
    validate_model_practice_snapshot,
    validate_route_scope_tags,
)
from forge.core.models.model_reference import normalize_model_reference
from forge.core.wire_shapes import ANTHROPIC_PASSTHROUGH, VALID_WIRE_SHAPES

from .events import (
    SessionEvent,
    SessionEventValidationError,
    append_session_event,
    get_session_event_journal_path,
    new_session_event,
    read_session_events,
)
from .models import RouteCommitConfirmed, SessionState, session_runtime

ROUTING_JOURNAL_DOMAIN = "routing"
ROUTING_COMMIT_EVENT = "launch_routing_committed"
ROUTING_ABORT_EVENT = "launch_aborted"
ROUTING_EVENT_TYPES = frozenset({ROUTING_COMMIT_EVENT, ROUTING_ABORT_EVENT})
ROUTE_KINDS = frozenset({"direct", "proxy", "custom", "runtime_native"})
ROUTING_LAUNCH_OPERATIONS = frozenset({"start", "resume", "fork", "incognito"})
ROUTING_ABORT_REASON = "route_projection_failed"
ROUTING_PAYLOAD_FIELDS = frozenset(
    {
        "route",
        "requested_model",
        "selected_tier",
        "selected_model",
        "default_tier",
        "direct_model",
        "tier_mappings",
        "model_alternatives",
        "billing_mode",
        "route_scope_tags",
        "marking_snapshots",
    }
)
ROUTE_FIELDS = frozenset({"kind", "backend_id", "proxy_id", "template", "custom_route_fingerprint", "wire_shape"})
LEGACY_ROUTE_FIELDS = ROUTE_FIELDS - {"wire_shape"}
MARKING_SNAPSHOT_FIELDS = frozenset({"slot", "tier", "request_model", "route_model", "canonical_model", "declaration"})
BILLING_MODES = frozenset(
    {
        "api",
        "subscription_interactive",
        "subscription_headless_credit",
        "subscription_quota",
        "unknown",
    }
)
_CUSTOM_ROUTE_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

RoutingHistoryStatus = Literal["supported", "unproven"]


@dataclass(frozen=True)
class RoutingHistory:
    """Validated routing events plus their projection-continuity result."""

    status: RoutingHistoryStatus | None
    events: tuple[SessionEvent, ...]
    effective_commit: SessionEvent | None
    journal_exists: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "history_status": self.status,
            "events": [asdict(event) for event in self.events],
        }


def new_routing_event(
    state: SessionState,
    *,
    event_type: str,
    run_id: str,
    operation: str,
    payload: dict[str, Any],
) -> SessionEvent:
    """Construct one validated routing commit or compensating abort event."""
    return new_session_event(
        session=state.name,
        runtime=session_runtime(state),
        event_type=event_type,
        run_id=run_id,
        origin_surface="launcher",
        operation=operation,
        outcome="success" if event_type == ROUTING_COMMIT_EVENT else "error",
        reason_code=(None if event_type == ROUTING_COMMIT_EVENT else ROUTING_ABORT_REASON),
        payload=deepcopy(payload),
        payload_validator=validate_routing_payload,
        event_validator=validate_routing_event,
    )


def append_routing_event(forge_root: str | Path, event: SessionEvent) -> Path:
    """Durably append one routing event through the shared neutral journal."""
    return append_session_event(
        forge_root,
        ROUTING_JOURNAL_DOMAIN,
        event,
        payload_validator=validate_routing_payload,
        event_validator=validate_routing_event,
    )


def read_routing_events(forge_root: str | Path, state: SessionState) -> list[SessionEvent]:
    """Read a routing journal and validate its whole append-order state machine."""
    events = read_session_events(
        forge_root,
        state.name,
        ROUTING_JOURNAL_DOMAIN,
        payload_validator=_validate_historical_routing_payload,
        event_validator=_validate_historical_routing_event,
    )
    expected_runtime = session_runtime(state)
    for index, event in enumerate(events, start=1):
        if event.runtime != expected_runtime:
            raise SessionEventValidationError(
                f"runtime {event.runtime!r} does not match manifest runtime {expected_runtime!r}",
                record=index,
                field="runtime",
            )
    _validate_routing_continuity(events)
    return events


def derive_routing_history(forge_root: str | Path, state: SessionState) -> RoutingHistory:
    """Derive supported/unproven/null exactly from journal and route projection."""
    journal = get_session_event_journal_path(forge_root, state.name, ROUTING_JOURNAL_DOMAIN)
    journal_exists = journal.exists()
    events = read_routing_events(forge_root, state)
    aborted_runs = {event.run_id for event in events if event.event_type == ROUTING_ABORT_EVENT}
    effective = [
        event for event in events if event.event_type == ROUTING_COMMIT_EVENT and event.run_id not in aborted_runs
    ]
    latest = effective[-1] if effective else None
    projection = state.confirmed.route_commit

    if projection is None:
        if not journal_exists:
            status: RoutingHistoryStatus | None = None
        elif not events:
            status = "unproven"
        elif latest is None:
            status = "supported"
        else:
            status = "unproven"
        return RoutingHistory(
            status=status,
            events=tuple(events),
            effective_commit=latest,
            journal_exists=journal_exists,
        )

    target = _projection_target(events, projection)
    status = "supported" if target is not None and target is latest else "unproven"
    return RoutingHistory(
        status=status,
        events=tuple(events),
        effective_commit=latest,
        journal_exists=journal_exists,
    )


def validate_routing_payload(event_type: str, payload: dict[str, Any]) -> None:
    """Validate the exact route payload shared unchanged by commit and abort."""
    _validate_routing_payload(
        event_type,
        payload,
        verify_catalog_normalization=True,
        allow_legacy_wire_shape=False,
    )


def _validate_historical_routing_payload(event_type: str, payload: dict[str, Any]) -> None:
    """Validate immutable payload structure without reinterpreting the launch catalog."""
    _validate_routing_payload(
        event_type,
        payload,
        verify_catalog_normalization=False,
        allow_legacy_wire_shape=True,
    )


def _validate_routing_payload(
    event_type: str,
    payload: dict[str, Any],
    *,
    verify_catalog_normalization: bool,
    allow_legacy_wire_shape: bool,
) -> None:
    if event_type not in ROUTING_EVENT_TYPES:
        raise ValueError(f"unknown routing event type {event_type!r}")
    _require_exact_fields(payload, ROUTING_PAYLOAD_FIELDS, "routing payload")
    route = payload["route"]
    if not isinstance(route, dict):
        raise ValueError("route must be an object")
    if not (allow_legacy_wire_shape and set(route) == LEGACY_ROUTE_FIELDS):
        _require_exact_fields(route, ROUTE_FIELDS, "route")
    kind = route["kind"]
    if kind not in ROUTE_KINDS:
        raise ValueError(f"route.kind must be one of {sorted(ROUTE_KINDS)}")

    for field in ("backend_id", "proxy_id", "template", "custom_route_fingerprint"):
        _optional_string(route[field], f"route.{field}")
    wire_shape = route.get("wire_shape")
    if wire_shape is not None and wire_shape not in VALID_WIRE_SHAPES:
        raise ValueError(f"route.wire_shape must be null or one of {sorted(VALID_WIRE_SHAPES)}")
    for field in ("requested_model", "selected_model", "default_tier", "direct_model"):
        _optional_string(payload[field], field)
    selected_tier = payload["selected_tier"]
    if selected_tier is not None and selected_tier not in {"haiku", "sonnet", "opus"}:
        raise ValueError("selected_tier must be null, haiku, sonnet, or opus")
    default_tier = payload["default_tier"]
    if default_tier is not None and default_tier not in {"haiku", "sonnet", "opus"}:
        raise ValueError("default_tier must be null, haiku, sonnet, or opus")
    _string_map(payload["tier_mappings"], "tier_mappings", tier_keys=True)
    _alternative_map(payload["model_alternatives"])
    if payload["billing_mode"] not in BILLING_MODES:
        raise ValueError(f"billing_mode must be one of {sorted(BILLING_MODES)}")
    try:
        scope_tags = validate_route_scope_tags(payload["route_scope_tags"])
    except ModelPracticesError as exc:
        raise ValueError(str(exc)) from exc
    snapshots = payload["marking_snapshots"]
    if not isinstance(snapshots, list):
        raise ValueError("marking_snapshots must be a list")
    for index, snapshot in enumerate(snapshots):
        _validate_marking_snapshot(
            snapshot,
            index,
            scope_tags,
            verify_catalog_normalization=verify_catalog_normalization,
        )


def validate_routing_event(event: SessionEvent) -> None:
    """Validate routing-specific envelope and route-kind/runtime invariants."""
    _validate_routing_event(
        event,
        verify_catalog_normalization=True,
        allow_legacy_wire_shape=False,
    )


def _validate_historical_routing_event(event: SessionEvent) -> None:
    """Validate historical invariants without applying the current model catalog."""
    _validate_routing_event(
        event,
        verify_catalog_normalization=False,
        allow_legacy_wire_shape=True,
    )


def _validate_routing_event(
    event: SessionEvent,
    *,
    verify_catalog_normalization: bool,
    allow_legacy_wire_shape: bool,
) -> None:
    if event.event_type not in ROUTING_EVENT_TYPES:
        raise SessionEventValidationError(f"unknown routing event type {event.event_type!r}", field="event_type")
    if event.origin_surface != "launcher":
        raise SessionEventValidationError("must be launcher", field="origin_surface")
    if event.operation not in ROUTING_LAUNCH_OPERATIONS:
        raise SessionEventValidationError("must be a launch operation", field="operation")
    if event.run_id is None:
        raise SessionEventValidationError("is required for routing events", field="run_id")
    if event.event_type == ROUTING_COMMIT_EVENT:
        if event.outcome != "success" or event.reason_code is not None:
            raise SessionEventValidationError("commit requires success and null reason_code")
    elif event.outcome != "error" or event.reason_code != ROUTING_ABORT_REASON:
        raise SessionEventValidationError(f"abort requires error and {ROUTING_ABORT_REASON!r}")

    route = event.payload["route"]
    kind = route["kind"]
    if kind == "runtime_native":
        _require_runtime_native(event)
    elif event.runtime != "claude_code":
        raise SessionEventValidationError(f"route kind {kind!r} requires claude_code runtime", field="runtime")
    elif kind == "direct":
        _require_direct(event, verify_catalog_normalization=verify_catalog_normalization)
    elif kind == "proxy":
        _require_proxy(
            event,
            verify_catalog_normalization=verify_catalog_normalization,
            allow_legacy_wire_shape=allow_legacy_wire_shape,
        )
    else:
        _require_custom(event, verify_catalog_normalization=verify_catalog_normalization)


def custom_route_fingerprint(base_url: str) -> str:
    """Hash only a canonical credential-free HTTP(S) origin."""
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("custom route URL has an invalid port") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("custom route must be an HTTP(S) URL with a host")
    scheme = parsed.scheme.lower()
    host_raw = parsed.hostname.lower()
    try:
        address = ipaddress.ip_address(host_raw)
    except ValueError:
        try:
            host = host_raw.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("custom route host cannot be canonicalized") from exc
    else:
        host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    default_port = 80 if scheme == "http" else 443
    authority = host if port is None or port == default_port else f"{host}:{port}"
    origin = f"{scheme}://{authority}"
    return f"sha256:{hashlib.sha256(origin.encode('ascii')).hexdigest()}"


def _projection_target(events: list[SessionEvent], projection: RouteCommitConfirmed) -> SessionEvent | None:
    for event in events:
        if (
            event.event_type == ROUTING_COMMIT_EVENT
            and event.event_id == projection.event_id
            and event.run_id == projection.run_id
        ):
            return event
    return None


def _validate_routing_continuity(events: list[SessionEvent]) -> None:
    commits: dict[str, SessionEvent] = {}
    aborts: set[str] = set()
    for index, event in enumerate(events, start=1):
        assert event.run_id is not None
        if event.event_type == ROUTING_COMMIT_EVENT:
            if event.run_id in commits:
                raise SessionEventValidationError("duplicate routing commit for run", record=index, field="run_id")
            commits[event.run_id] = event
            continue
        commit = commits.get(event.run_id)
        if commit is None:
            raise SessionEventValidationError(
                "routing abort has no prior same-run commit",
                record=index,
                field="run_id",
            )
        if event.run_id in aborts:
            raise SessionEventValidationError("duplicate routing abort for run", record=index, field="run_id")
        if event.operation != commit.operation:
            raise SessionEventValidationError(
                "routing abort operation does not match its commit",
                record=index,
                field="operation",
            )
        if event.payload != commit.payload:
            raise SessionEventValidationError(
                "routing abort payload does not match its commit",
                record=index,
                field="payload",
            )
        aborts.add(event.run_id)


def _require_direct(event: SessionEvent, *, verify_catalog_normalization: bool) -> None:
    payload = event.payload
    route = payload["route"]
    _all_none(route, ("backend_id", "proxy_id", "template", "custom_route_fingerprint"))
    if route.get("wire_shape") is not None:
        raise SessionEventValidationError("direct route wire_shape must be null", field="payload")
    if payload["tier_mappings"] or payload["model_alternatives"]:
        raise SessionEventValidationError("direct route maps must be empty", field="payload")
    if payload["default_tier"] is not None:
        raise SessionEventValidationError("direct default_tier must be null", field="payload")
    if payload["billing_mode"] != "unknown":
        raise SessionEventValidationError("direct billing_mode must be unknown", field="payload")
    _require_route_scope_tags(event)
    expected = []
    if payload["direct_model"] is not None:
        expected.append(("direct", None, None, payload["direct_model"]))
    _require_snapshot_slots(payload, expected)
    _require_canonical_field(payload, "requested_model", verify=verify_catalog_normalization)
    _require_canonical_field(payload, "direct_model", verify=verify_catalog_normalization)
    requested = payload["requested_model"]
    if requested is None:
        if payload["selected_tier"] is not None or payload["selected_model"] is not None:
            raise SessionEventValidationError("direct selection requires requested_model", field="payload")
    elif (
        payload["selected_tier"] is None
        or payload["selected_model"] != requested
        or payload["direct_model"] != requested
    ):
        raise SessionEventValidationError(
            "direct selected model must match the requested effective model",
            field="payload",
        )


def _require_proxy(
    event: SessionEvent,
    *,
    verify_catalog_normalization: bool,
    allow_legacy_wire_shape: bool,
) -> None:
    payload = event.payload
    route = payload["route"]
    wire_shape = route.get("wire_shape")
    if wire_shape is None and ("wire_shape" in route or not allow_legacy_wire_shape):
        raise SessionEventValidationError("proxy route requires wire_shape", field="payload")
    if not route["template"] or not payload["default_tier"] or not payload["tier_mappings"]:
        raise SessionEventValidationError(
            "proxy route requires template, default tier, and tier mappings",
            field="payload",
        )
    if payload["default_tier"] not in payload["tier_mappings"]:
        raise SessionEventValidationError("proxy default_tier requires an effective tier mapping", field="payload")
    if route["custom_route_fingerprint"] is not None or payload["direct_model"] is not None:
        raise SessionEventValidationError("proxy route carries forbidden direct/custom fields", field="payload")
    _require_route_scope_tags(event)
    expected_slots = [("tier_default", tier, None, model) for tier, model in payload["tier_mappings"].items()]
    expected_slots.extend(
        ("model_alternative", tier, request_model, route_model)
        for tier, alternatives in payload["model_alternatives"].items()
        for request_model, route_model in alternatives.items()
    )
    _require_snapshot_slots(payload, expected_slots)
    _require_canonical_field(payload, "requested_model", verify=verify_catalog_normalization)
    requested = payload["requested_model"]
    selected_tier = payload["selected_tier"]
    if requested is None:
        if selected_tier is not None or payload["selected_model"] is not None:
            raise SessionEventValidationError("proxy selection requires requested_model", field="payload")
    elif selected_tier is None:
        if payload["selected_model"] is not None:
            raise SessionEventValidationError(
                "ignored proxy request must not select a model",
                field="payload",
            )
    else:
        if wire_shape == ANTHROPIC_PASSTHROUGH:
            expected_model = requested
        else:
            alternatives = payload["model_alternatives"].get(selected_tier, {})
            # The launch payload materializes any catalog-alias match under the
            # exact persisted request spelling. Do not reinterpret historical
            # route facts through the current catalog here.
            expected_model = alternatives.get(requested)
            if expected_model is None:
                expected_model = payload["tier_mappings"].get(selected_tier)
        if expected_model is None or payload["selected_model"] != expected_model:
            raise SessionEventValidationError(
                "proxy selected_model does not match the effective route",
                field="payload",
            )


def _require_custom(event: SessionEvent, *, verify_catalog_normalization: bool) -> None:
    payload = event.payload
    route = payload["route"]
    if (
        not route["custom_route_fingerprint"]
        or _CUSTOM_ROUTE_FINGERPRINT_RE.fullmatch(route["custom_route_fingerprint"]) is None
    ):
        raise SessionEventValidationError("custom route requires a fingerprint", field="payload")
    _all_none(route, ("backend_id", "proxy_id", "template"))
    if route.get("wire_shape") is not None:
        raise SessionEventValidationError("custom route wire_shape must be null", field="payload")
    if (
        payload["default_tier"] is not None
        or payload["direct_model"] is not None
        or payload["tier_mappings"]
        or payload["model_alternatives"]
    ):
        raise SessionEventValidationError("custom route carries forbidden model/proxy fields", field="payload")
    if payload["billing_mode"] != "unknown":
        raise SessionEventValidationError("custom billing_mode must be unknown", field="payload")
    _require_route_scope_tags(event)
    _require_snapshot_slots(payload, [])
    _require_canonical_field(payload, "requested_model", verify=verify_catalog_normalization)
    if payload["selected_model"] is not None:
        raise SessionEventValidationError("custom selected_model must be null", field="payload")
    if payload["selected_tier"] is not None:
        raise SessionEventValidationError("custom selected_tier must be null", field="payload")


def _require_runtime_native(event: SessionEvent) -> None:
    payload = event.payload
    route = payload["route"]
    if event.runtime != "codex":
        raise SessionEventValidationError("runtime_native route requires codex runtime", field="runtime")
    _all_none(route, ("backend_id", "proxy_id", "template", "custom_route_fingerprint"))
    if route.get("wire_shape") is not None:
        raise SessionEventValidationError("runtime_native wire_shape must be null", field="payload")
    for field in (
        "requested_model",
        "selected_tier",
        "selected_model",
        "default_tier",
        "direct_model",
    ):
        if payload[field] is not None:
            raise SessionEventValidationError(f"runtime_native {field} must be null", field="payload")
    if payload["tier_mappings"] or payload["model_alternatives"] or payload["marking_snapshots"]:
        raise SessionEventValidationError("runtime_native maps and marking snapshots must be empty", field="payload")
    if payload["billing_mode"] != "unknown":
        raise SessionEventValidationError("runtime_native billing_mode must be unknown", field="payload")
    _require_route_scope_tags(event)


def _require_route_scope_tags(event: SessionEvent) -> None:
    """Require scope tags to be derived only from proven facts stored in this event."""
    payload = event.payload
    route = payload["route"]
    expected = {f"route:{route['kind']}", f"runtime:{event.runtime}"}
    if route["backend_id"]:
        expected.add(f"backend:{route['backend_id']}")
    if payload["billing_mode"] != "unknown":
        expected.add(f"billing:{payload['billing_mode']}")
    if payload["route_scope_tags"] != sorted(expected):
        raise SessionEventValidationError("route_scope_tags do not match proven route facts", field="payload")


def _validate_marking_snapshot(
    raw: object,
    index: int,
    route_scope_tags: tuple[str, ...],
    *,
    verify_catalog_normalization: bool,
) -> None:
    if not isinstance(raw, dict):
        raise ValueError(f"marking_snapshots[{index}] must be an object")
    _require_exact_fields(raw, MARKING_SNAPSHOT_FIELDS, f"marking_snapshots[{index}]")
    if raw["slot"] not in {"direct", "tier_default", "model_alternative"}:
        raise ValueError(f"marking_snapshots[{index}].slot is invalid")
    _optional_string(raw["tier"], f"marking_snapshots[{index}].tier")
    _optional_string(raw["request_model"], f"marking_snapshots[{index}].request_model")
    _optional_string(raw["route_model"], f"marking_snapshots[{index}].route_model")
    _optional_string(raw["canonical_model"], f"marking_snapshots[{index}].canonical_model")
    normalized = normalize_model_reference(raw["route_model"])
    canonical = raw["canonical_model"]
    if verify_catalog_normalization:
        canonical_matches = canonical == normalized
    else:
        # A null launch value stays unknown if a later catalog adds the route
        # model. A nonnull launch value stays valid if that model is later
        # removed, while current-catalog mismatches still expose corruption.
        canonical_matches = canonical is None or normalized is None or canonical == normalized
    if not canonical_matches:
        raise ValueError(f"marking_snapshots[{index}].canonical_model does not match route_model")
    try:
        validate_model_practice_snapshot(raw["declaration"])
    except ModelPracticesError as exc:
        raise ValueError(str(exc)) from exc
    declaration = raw["declaration"]
    if declaration["status"] != "unknown":
        if raw["canonical_model"] is None:
            raise ValueError(f"marking_snapshots[{index}] cannot declare an unknown canonical model")
        if not set(declaration["route_scope"]).issubset(route_scope_tags):
            raise ValueError(f"marking_snapshots[{index}].declaration route_scope exceeds the launch scope")


def _require_snapshot_slots(payload: dict[str, Any], expected: Sequence[tuple[object, ...]]) -> None:
    actual = [
        (
            snapshot["slot"],
            snapshot["tier"],
            snapshot["request_model"],
            snapshot["route_model"],
        )
        for snapshot in payload["marking_snapshots"]
    ]
    if sorted(actual, key=repr) != sorted(expected, key=repr):
        raise SessionEventValidationError(
            "marking snapshots do not match the effective model slots",
            field="payload.marking_snapshots",
        )


def _require_canonical_field(payload: dict[str, Any], field: str, *, verify: bool) -> None:
    value = payload[field]
    normalized = normalize_model_reference(value) if value is not None else None
    if value is not None and (verify or normalized is not None) and normalized != value:
        raise SessionEventValidationError(f"{field} must be a canonical model id", field=f"payload.{field}")


def _require_exact_fields(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        unknown = sorted(set(value) - expected)
        raise ValueError(f"{label} field set is invalid (missing={missing}, unknown={unknown})")


def _optional_string(value: object, field: str) -> None:
    if value is not None and (not isinstance(value, str) or not value):
        raise ValueError(f"{field} must be null or a nonempty string")


def _string_map(value: object, field: str, *, tier_keys: bool = False) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    if tier_keys and not set(value).issubset({"haiku", "sonnet", "opus"}):
        raise ValueError(f"{field} contains an invalid tier")
    if any(not isinstance(key, str) or not key or not isinstance(item, str) or not item for key, item in value.items()):
        raise ValueError(f"{field} must map strings to nonempty strings")


def _alternative_map(value: object) -> None:
    if not isinstance(value, dict) or not set(value).issubset({"haiku", "sonnet", "opus"}):
        raise ValueError("model_alternatives must be a tier-keyed object")
    for tier, alternatives in value.items():
        _string_map(alternatives, f"model_alternatives.{tier}")


def _all_none(route: dict[str, Any], fields: tuple[str, ...]) -> None:
    if any(route[field] is not None for field in fields):
        raise SessionEventValidationError(f"route fields must be null: {', '.join(fields)}", field="payload")

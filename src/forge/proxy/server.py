"""
Unified LLM Proxy Server - Anthropic-compatible API for multiple providers.

This FastAPI server provides an Anthropic Messages API-compatible interface for
LLM providers via LiteLLM.

The server routes provider-specific behavior through ``CoreLLMClientAdapter``,
which exposes the completion, streaming, and token-count operations consumed
by the request handlers.

Key endpoints:
- POST /v1/messages - Main chat completion endpoint (streaming/non-streaming)
- POST /v1/messages/count_tokens - Token counting endpoint
- GET / - Health check and service information

For detailed API documentation, architecture overview, and configuration options,
see README.md in the project root.
"""

import asyncio
import logging
import os
import socket
import sys
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, NoReturn

import click
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from forge.backend.sources import ModelSourceNotFoundError, get_model_source
from forge.config import TierOverride, config, init_config, reload
from forge.config.schema import RequestLogConfig
from forge.core.llm.detection import LITELLM_PROVIDER_PREFIXES
from forge.core.llm.errors import AuthenticationError
from forge.core.logging import (
    configure_console_logging,
    configure_debug_logging,
    get_effective_log_level,
)
from forge.core.run_id import (
    FORGE_COMMAND_HEADER,
    FORGE_ROOT_RUN_ID_HEADER,
    FORGE_RUN_ID_HEADER,
    FORGE_SESSION_HEADER,
    derive_provider_session_id,
    is_valid_label,
    is_valid_provider_session_id,
    is_valid_run_id,
)
from forge.core.telemetry.downstream import mint_downstream_event_id
from forge.core.tiers import detect_tier_word
from forge.core.usage.vocabulary import Confidence, Reporter
from forge.core.wire_shapes import ANTHROPIC_PASSTHROUGH, DEFAULT_WIRE_SHAPE
from forge.proxy.base_client import ProxyStreamError
from forge.proxy.client_factory import ModelProvider, TierClientFactory
from forge.proxy.converters import (
    RequestConversionError,
    convert_anthropic_to_openai,
    convert_openai_to_anthropic,
    convert_openai_to_anthropic_sse,
)
from forge.proxy.cost_logger import log_request_cost
from forge.proxy.cost_tracker import CostTracker
from forge.proxy.data_models import (
    MessagesRequest,
    TokenCountRequest,
    TokenCountResponse,
    map_model_name,
)
from forge.proxy.error_hints import enrich_error_content
from forge.proxy.metrics import proxy_metrics
from forge.proxy.passthrough_ingress import handle_anthropic_passthrough
from forge.proxy.ports import (
    NoAvailablePortError,
)
from forge.proxy.ports import (
    find_available_loopback_port as _find_available_loopback_port,
)
from forge.proxy.provider_trace_logger import record_provider_trace
from forge.proxy.reasoning import resolve_reasoning_effort
from forge.proxy.request_id import is_valid_request_id
from forge.proxy.responses_ingress import (
    advertise_responses_ingress,
    build_intercept_capability_section,
    register_responses_routes,
)
from forge.proxy.utils import (
    ToolEventMetadata,
    bounded_tool_event_identifier,
    log_request_beautifully,
    log_request_response,
    log_tool_event,
    log_tool_failure,
    tool_event_value_shape,
)

logger = logging.getLogger(__name__)

logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

client_factory = TierClientFactory()

PREFERRED_PROVIDER = None

# When a proxy is started under a proxy id, its config should be stable for the
# lifetime of the process (no hot reload).
PROXY_ID: str | None = os.environ.get("FORGE_PROXY_ID")

cost_tracker: CostTracker | None = None


_warned_unknown_backend_instances: set[str] = set()
_warned_absent_backend_instance: bool = False


def _backend_instance_id() -> str | None:
    global _warned_absent_backend_instance
    backend = getattr(config.proxy, "backend", "") or None
    if not backend:
        # No backend -> no backend_id, so downstream attribution, provider-trace, and provider-user
        # grouping are all disabled for this proxy (they gate on a backend-capable backend_id).
        # Surface it once; absent backend has no value to key on, so use a dedicated latch rather
        # than the value-keyed _warned_unknown_backend_instances set (best-effort log, never silent).
        if not _warned_absent_backend_instance:
            _warned_absent_backend_instance = True
            logger.info(
                "proxy.yaml has no 'backend:'; downstream attribution, provider-trace, and "
                "provider-user grouping are disabled for this proxy. Recreate it to refresh proxy.yaml."
            )
        return None
    backend = str(backend)
    # proxy.yaml is user-owned config (a system boundary): an unrecognized backend is a
    # misconfiguration, not durable-state corruption to reject. Degrade to the raw value
    # but warn once so the silent telemetry-attribution gap is visible -- best-effort
    # degradation must log, never be silent (coding-standards section 5).
    if backend not in _warned_unknown_backend_instances:
        try:
            get_model_source(backend)
        except ModelSourceNotFoundError:
            _warned_unknown_backend_instances.add(backend)
            logger.warning(
                "proxy.backend %r is not a known backend instance; downstream telemetry for this "
                "proxy will carry an unrecognized backend_id. Recreate the proxy to refresh proxy.yaml.",
                backend,
            )
    return backend


def _inject_provider_user_enabled() -> bool:
    # The global toggle in ~/.forge/config.yaml governs BOTH the proxied and the direct OpenRouter
    # routes; the per-proxy proxy.yaml key is deprecated (see config/schema.py). Same runtime-config
    # read the proxy already uses for auth_ignore_env. Singleton-cached: a running proxy reads it
    # once (restart to change), matching the prior proxy.yaml-at-startup behavior.
    from forge.runtime_config import get_runtime_config

    return bool(get_runtime_config().provider_trace.inject_provider_user)


def _sidecar_mode_active() -> bool:
    """True when running inside a Forge sidecar container (FORGE_SIDECAR set by container.py).

    Sidecar proxies skip host-registry startup validation: the host proxy registry
    is not mounted into the container and the port is fixed (8085), so the
    registry/port cross-check cannot hold there. The proxy.yaml overlay is mounted
    explicitly and is the in-container source of truth.
    """
    return bool(os.environ.get("FORGE_SIDECAR"))


def _initialize_cost_tracker_from_config() -> CostTracker:
    """Initialize request cost tracking in the module serving FastAPI traffic.

    ``python -m forge.proxy.server`` executes this file as ``__main__``, while
    uvicorn imports ``forge.proxy.server:app`` for request handling. Module
    globals therefore need to be initialized in the imported app module too.
    """
    global cost_tracker
    if cost_tracker is not None:
        return cost_tracker

    from forge.config.schema import CostConfig

    cost_cfg = getattr(config.proxy, "costs", None) or CostConfig()
    if cost_cfg.caps.per_day is not None or cost_cfg.caps.per_month is not None:
        from forge.core.paths import get_forge_home

        cost_tracker = CostTracker(
            daily_cap_usd=cost_cfg.caps.per_day,
            monthly_cap_usd=cost_cfg.caps.per_month,
            on_cap_hit=cost_cfg.on_cap_hit,
        )
        cost_tracker.bootstrap_from_logs(
            get_forge_home() / "telemetry" / "downstream",
            proxy_id=PROXY_ID,
        )
    else:
        cost_tracker = CostTracker()
    return cost_tracker


def _attach_cap_summary(metrics: dict[str, Any], tracker: CostTracker | None) -> None:
    """Nest spend-cap proximity under ``metrics.costs.caps`` when caps are configured.

    ``cap_summary()`` returns per-window ``current_usd``/``limit_usd``/``percent``;
    the ``caps`` key is omitted entirely when no caps exist, so a consumer (the
    ``spend_cap`` status-line segment) can treat its presence as "caps are active".
    Mutates ``metrics`` in place.
    """
    if tracker is None or not tracker.has_caps:
        return
    caps = tracker.cap_summary()
    costs = metrics.get("costs")
    if caps and isinstance(costs, dict):
        costs["caps"] = caps


_downstream_pruned = False
_request_logs_pruned = False
_downstream_retention_resolution: Any | None = None
_downstream_prune_error: str | None = None
_DOWNSTREAM_RETENTION_RESOLUTION_ERROR = "retention policy resolution failed; inspect proxy logs"
_DOWNSTREAM_RETENTION_ENFORCEMENT_ERROR = "downstream retention enforcement failed; inspect proxy logs"


def _maybe_prune_downstream_records() -> None:
    """Resolve and enforce the one downstream retention policy once per process."""
    global _downstream_pruned, _downstream_prune_error, _downstream_retention_resolution
    if _downstream_pruned:
        return
    _downstream_pruned = True

    from forge.core.paths import get_forge_home
    from forge.core.telemetry.downstream_retention import resolve_downstream_retention

    try:
        resolution = resolve_downstream_retention()
    except Exception as e:
        _downstream_prune_error = _DOWNSTREAM_RETENTION_RESOLUTION_ERROR
        logger.warning(
            "Downstream retention could not resolve a policy; automatic pruning was skipped for %s: %s",
            get_forge_home() / "telemetry" / "downstream",
            e,
        )
        return
    _downstream_retention_resolution = resolution

    if resolution.deprecated_keys:
        rendered = ", ".join(
            f"{item.proxy_id}:{item.key}->{item.replacement}" for item in resolution.deprecated_keys[:8]
        )
        suffix = f" (+{len(resolution.deprecated_keys) - 8} more)" if len(resolution.deprecated_keys) > 8 else ""
        logger.warning(
            "Deprecated proxy-local downstream retention keys detected: %s%s. "
            "Run 'forge config migrate-retention' to preview the global migration.",
            rendered,
            suffix,
        )

    for error in resolution.errors:
        logger.warning(
            "Downstream retention input could not be inspected at %s: %s",
            error.path,
            error.detail,
        )

    if not resolution.pruning_enabled or resolution.effective is None:
        proxy_ids = sorted(
            {proxy_id for conflict in resolution.conflicts for item in conflict.values for proxy_id in item.proxy_ids}
        )
        conflict_detail = f" Conflicting proxy IDs: {', '.join(proxy_ids)}." if proxy_ids else ""
        if resolution.errors:
            recovery = "Repair the named global or proxy file, then retry migration."
        else:
            recovery = (
                "Set telemetry.downstream.retention_days and telemetry.downstream.max_total_mb, "
                "then run 'forge config migrate-retention'."
            )
        logger.warning(
            "Downstream retention is degraded; automatic pruning was skipped.%s %s",
            conflict_detail,
            recovery,
        )
        return

    policy = resolution.effective
    downstream_dir = get_forge_home() / "telemetry" / "downstream"
    try:
        from forge.core.telemetry.downstream import prune_downstream_records

        result = prune_downstream_records(
            retention_days=policy.retention_days,
            max_total_mb=policy.max_total_mb,
        )
        if result is not None and result.errors:
            prune_detail = "; ".join(result.errors)
            _downstream_prune_error = _DOWNSTREAM_RETENTION_ENFORCEMENT_ERROR
            logger.warning(
                "Downstream retention was only partially enforced for %s with retention_days=%s, max_total_mb=%s: %s",
                downstream_dir,
                policy.retention_days,
                policy.max_total_mb,
                prune_detail,
            )
    except Exception as e:
        _downstream_prune_error = _DOWNSTREAM_RETENTION_ENFORCEMENT_ERROR
        logger.warning(
            "Downstream retention could not be enforced for %s with retention_days=%s, max_total_mb=%s: %s",
            downstream_dir,
            policy.retention_days,
            policy.max_total_mb,
            e,
        )


def _downstream_retention_status_section() -> tuple[dict[str, Any], bool]:
    """Return the root-status payload and whether retention enforcement is degraded."""
    section = (
        _downstream_retention_resolution.to_dict()
        if _downstream_retention_resolution is not None
        else {
            "configured": None,
            "effective": None,
            "source": None,
            "pruning_enabled": False,
            "degraded": True,
            "deprecated_keys": [],
            "conflicts": [],
            "errors": [],
        }
    )
    section["prune_error"] = _downstream_prune_error
    degraded = not section["pruning_enabled"] or _downstream_prune_error is not None
    section["degraded"] = degraded
    return section, degraded


def _maybe_prune_request_logs() -> None:
    """Enforce request-log retention once per process (best-effort) once config is loaded."""
    global _request_logs_pruned
    if _request_logs_pruned:
        return
    _request_logs_pruned = True
    requests_cfg = getattr(getattr(config.proxy, "logging", None), "requests", None)
    if requests_cfg is None:
        return
    try:
        from forge.proxy.utils import prune_request_logs

        prune_request_logs(
            retention_days=requests_cfg.retention_days,
            max_total_mb=requests_cfg.max_total_mb,
        )
    except Exception as e:
        logger.debug("request log prune skipped: %s", e)


def _request_log_config() -> RequestLogConfig:
    """Return the per-proxy request-diagnostics config, tolerant of a partial ``config.proxy``.

    Request logging is best-effort telemetry that must never break a response, and ``config.proxy``
    telemetry fields are already read defensively here (see ``_maybe_prune_*``). Fall back to
    defaults when the ``logging.requests`` block is absent (e.g. a partial config); the defaults
    preserve today's auto/debug-gated, metadata-only behavior.
    """
    requests = getattr(getattr(config.proxy, "logging", None), "requests", None)
    if requests is None:
        return RequestLogConfig()
    return requests


def _ensure_runtime_state() -> None:
    """Ensure the imported app module has proxy config and runtime trackers."""
    if PROXY_ID is None:
        reload()
    elif not config.proxy.active_template:
        reload(proxy_id=PROXY_ID)

    _initialize_cost_tracker_from_config()
    _maybe_prune_downstream_records()
    _maybe_prune_request_logs()


def _reported_cost_provenance() -> tuple[Reporter | None, Confidence]:
    """Map the proxy's resolved provider to (reporter, confidence) for a reported cost.

    OpenRouter returns actual spend in the response body (``usage.cost``) → a
    directly *reported* figure. A LiteLLM gateway computes spend and returns it in
    the ``x-litellm-response-cost`` header → *gateway_calculated*. Used only when a
    reported cost is present; the provider value is otherwise irrelevant.
    """
    provider = getattr(config.proxy, "preferred_provider", "") or ""
    if provider == "openrouter":
        return "openrouter", "reported"
    if provider.startswith("litellm"):
        return "litellm", "gateway_calculated"
    return None, "reported"  # a number is present but the provider is unrecognized


def _valid_run_header(value: str | None) -> str | None:
    """Return a validated Forge run id from an inbound header, else None (Slice 4g)."""
    return value if is_valid_run_id(value) else None


def _valid_session_header(value: str | None) -> str | None:
    """Return a validated provider grouping id from ``X-Forge-Session``, else None (Phase 1)."""
    return value if is_valid_provider_session_id(value) else None


def _valid_command_header(value: str | None) -> str | None:
    """Return a validated command role from ``X-Forge-Command``, else None (Phase 1)."""
    return value if is_valid_label(value) else None


def _canonicalize_request_id_header(request: Request, request_id: str) -> None:
    """Replace supplied request-ID headers with the validated correlation value.

    The middleware calls this before constructing a ``Request.headers`` view. Make
    the ASGI iterable concrete defensively, then mutate the shared scope list so
    passthrough and fresh downstream requests cannot observe rejected raw values.
    """
    raw_headers = request.scope["headers"]
    if not isinstance(raw_headers, list):
        raw_headers = request.scope["headers"] = list(raw_headers)
    raw_headers[:] = [(name, value) for name, value in raw_headers if name.lower() != b"x-request-id"]
    raw_headers.append((b"x-request-id", request_id.encode("ascii")))


def _forge_run_ids(request: Request) -> tuple[str | None, str | None]:
    """The validated ``(forge_run_id, forge_root_run_id)`` the middleware stored."""
    state = request.state
    return getattr(state, "forge_run_id", None), getattr(state, "forge_root_run_id", None)


def _forge_session_command(request: Request) -> tuple[str | None, str | None]:
    """The validated ``(forge_session, forge_command)`` the middleware stored (Phase 1)."""
    state = request.state
    return getattr(state, "forge_session", None), getattr(state, "forge_command", None)


def _provider_user_value(
    *,
    backend_id: str | None = None,
    inject: bool,
    forge_session: str | None,
    forge_root_run_id: str | None,
    forge_command: str | None,
) -> str | None:
    """The provider ``user`` grouping id to inject, or None.

    Opt-in and backend-capability gated: the resolved ``backend_id`` must declare
    ``provider_user_grouping`` (no provider-name fallback). Prefers the already-derived, validated
    ``X-Forge-Session`` id; falls back to ``forge_run_<hash>`` when only run identity exists;
    returns None when there is nothing to group by (or the flag/route does not apply).
    """
    if not inject:
        return None
    if not backend_id:
        return None
    try:
        if not get_model_source(backend_id).capabilities.provider_user_grouping:
            return None
    except ModelSourceNotFoundError:
        logger.debug("unknown backend instance for provider-user grouping: %s", backend_id)
        return None
    if forge_session:
        return forge_session
    if forge_root_run_id:
        return derive_provider_session_id(None, forge_root_run_id, forge_command)
    return None


def _calc_and_log_cost(
    *,
    model: str,
    tier: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
    latency_ms: float,
    failed: bool,
    request_id: str,
    reported_cost_micros: int | None = None,
    forge_run_id: str | None = None,
    forge_root_run_id: str | None = None,
    downstream_event_id: str | None = None,
) -> int | None:
    """Log a request's cost (microdollars) and return it, or ``None`` if unavailable.

    Forge records what the route reported, nothing more. When the route reported a
    cost (``reported_cost_micros``), it is logged with the real reporter and
    ``reported``/``gateway_calculated`` confidence. Otherwise cost is ``None`` /
    ``confidence="unavailable"`` — tokens are still logged, but no dollar figure is
    invented from a local price table. Best-effort: never raises; cost tracking must
    not break the request path.
    """
    try:
        if reported_cost_micros is not None:
            cost_micros: int | None = reported_cost_micros
            reporter, confidence = _reported_cost_provenance()
        else:
            cost_micros, reporter, confidence = None, None, "unavailable"

        log_request_cost(
            proxy_id=PROXY_ID or "unknown",
            backend_id=_backend_instance_id(),
            model=model,
            tier=tier,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cost_micros=cost_micros,
            latency_ms=latency_ms,
            failed=failed,
            request_id=request_id,
            reporter=reporter,
            confidence=confidence,
            forge_run_id=forge_run_id,
            forge_root_run_id=forge_root_run_id,
            downstream_event_id=downstream_event_id,
        )

        # Spend caps account for reported costs only; an unavailable cost advances nothing.
        if cost_tracker is not None and cost_micros is not None:
            cost_tracker.record(cost_micros)

        return cost_micros
    except Exception as e:
        logger.warning("Cost calculation failed for model=%s (non-fatal): %s", model, e)
        return None


def _request_cost_header(cost_micros: int | None) -> dict[str, str]:
    """``X-Request-Cost`` only when this request reported a cost.

    A ``None`` cost is "unavailable" — omit the header rather than emit a
    misleading ``0.000000`` (and ``None / 1_000_000`` would raise).
    """
    if cost_micros is None:
        return {}
    return {"X-Request-Cost": f"{cost_micros / 1_000_000:.6f}"}


def _cumulative_cost_header() -> dict[str, str]:
    """``X-Cumulative-Cost`` only once at least one request has reported a cost.

    A cumulative ``0.000000`` on a proxy that has only ever seen cost-unavailable
    routes (e.g. Anthropic passthrough) is the same "unknown-as-zero" bug in header
    form — omit it until there is real reported-cost evidence.
    """
    if proxy_metrics.cost_reported_requests <= 0:
        return {}
    return {"X-Cumulative-Cost": f"{proxy_metrics.total_cost_micros / 1_000_000:.6f}"}


_CAP_CONFIG_KEY = {"daily": "per_day", "monthly": "per_month"}


def _cap_result_message(cap_result) -> str:
    """Format a spend cap result for HTTP headers and errors."""
    cap_type = cap_result.cap_type or "configured"
    config_key = _CAP_CONFIG_KEY.get(cap_type, f"per_{cap_type}")
    return (
        f"{cap_type} spend cap reached: "
        f"${cap_result.current_micros / 1_000_000:.2f} / "
        f"${cap_result.limit_micros / 1_000_000:.2f}. "
        f"Adjust with: forge proxy set <id> costs.caps.{config_key}=<amount>"
    )


def _with_spend_warning(headers: dict[str, str], warning: str | None) -> dict[str, str]:
    """Attach the optional spend warning header to a response header dict."""
    if warning:
        headers["X-Spend-Warning"] = warning
    return headers


def _get_tier_override(tier: str) -> TierOverride | None:
    """Get tier override from the active provider config.

    Returns the TierOverride for the specified tier, or None if not configured.
    Tier overrides allow per-tier hyperparameter customization (e.g., different
    reasoning_effort for opus vs sonnet when both map to the same model).
    """
    try:
        provider_cfg = config.proxy.get_provider()
        return provider_cfg.tier_overrides.get(tier)
    except Exception:
        return None


@dataclass(frozen=True)
class _ResolvedModelRoute:
    tier: str
    tier_source: str
    model: str
    explicit_backend: bool


def _is_explicit_backend_model(original_model_name: str | None) -> bool:
    """Whether a client model string should be preserved as an explicit backend id."""
    if original_model_name is None or "/" not in original_model_name:
        return False
    if config.proxy.preferred_provider == "openrouter":
        # OpenRouter accepts arbitrary provider/model slugs.
        return True
    return any(original_model_name.startswith(prefix) for prefix in LITELLM_PROVIDER_PREFIXES)


def _model_alternative_or_default(tier: str, original_model_name: str | None, fallback_model: str) -> str:
    """Check per-tier alternatives before falling back to the configured tier model."""
    try:
        provider_cfg = config.proxy.get_provider()
        alt_models = provider_cfg.model_alternatives.get(tier, {})
        if original_model_name and alt_models:
            lookup = original_model_name.removesuffix("[1m]")
            if lookup in alt_models:
                return alt_models[lookup]
    except Exception:
        # Best-effort: degrade to fallback_model if provider config is unavailable
        logger.debug("model_alternatives lookup failed, using tier default", exc_info=True)
    return fallback_model


def _resolve_model_with_alternatives(
    request_data: MessagesRequest | TokenCountRequest,
) -> _ResolvedModelRoute:
    """Resolve request tier and backend model for message and token-count routes."""
    if request_data.has_explicit_tier and request_data.tier:
        resolved_tier: str = request_data.tier
        resolved_tier_source = "request"
    elif config.proxy.default_tier:
        resolved_tier = config.proxy.default_tier
        resolved_tier_source = "proxy.default_tier"
    else:
        raise HTTPException(
            status_code=500,
            detail={
                "type": "configuration_error",
                "message": "config.proxy.default_tier is required for ambiguous requests under proxy-only routing",
            },
        )

    request_data.tier = resolved_tier
    original_model_name = request_data.original_model_name
    mapped_model = map_model_name(request_data.model)
    is_explicit_backend = _is_explicit_backend_model(original_model_name)
    if is_explicit_backend:
        actual_model_id = mapped_model
    else:
        tier_default = config.proxy.get_model_for_tier(resolved_tier)
        actual_model_id = _model_alternative_or_default(resolved_tier, original_model_name, tier_default)

    return _ResolvedModelRoute(
        tier=resolved_tier,
        tier_source=resolved_tier_source,
        model=actual_model_id,
        explicit_backend=is_explicit_backend,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    logger.info("Server started...")
    try:
        yield
    finally:
        if cost_tracker is not None:
            cost_tracker.flush_cap_state()
        logger.info("Server is shutting down... Cleaning up resources")


app = FastAPI(title="Unified LLM Proxy", lifespan=lifespan)


def _thinking_summary(thinking: object) -> dict[str, object] | None:
    if not isinstance(thinking, dict):
        return None
    return {
        "type": thinking.get("type"),
        "budget_tokens": thinking.get("budget_tokens"),
    }


def _inspect_route() -> dict[str, Any]:
    return {
        "template": getattr(config.proxy, "active_template", ""),
        "provider": getattr(config.proxy, "preferred_provider", ""),
        "backend": _backend_instance_id() or "",
        "wire_shape": getattr(config.proxy, "wire_shape", DEFAULT_WIRE_SHAPE),
    }


def _persist_request_side(
    *,
    body: dict[str, Any],
    request_id: str,
    proxy_id: str,
    route: dict[str, Any],
    mode: str,
    headers: dict[str, str] | None,
    sys_hash: str | None,
    tool_hash: str | None,
    backend_id: str | None,
    counts: dict[str, int],
    thinking: dict[str, Any] | None,
    full_body: bool,
    redact_headers: set[str],
    defer_full_body: bool,
) -> None:
    """Request-side audit persistence (drift + record). Runs in a worker thread.

    Writes a metadata record (metadata mode) or a request-only full-body record
    (full-body mode). When full-body capture is deferred (passthrough), the record
    is written response-side instead so the redacted response is included here.
    Best-effort — never raises into the request path.
    """
    from forge.proxy import audit_logger

    try:
        audit_logger.check_and_record_drift(
            proxy_id=proxy_id,
            dimension="system_prompt",
            current_hash=sys_hash,
            request_id=request_id,
            route=route,
            backend_id=backend_id,
        )
        audit_logger.check_and_record_drift(
            proxy_id=proxy_id,
            dimension="tool_surface",
            current_hash=tool_hash,
            request_id=request_id,
            route=route,
            backend_id=backend_id,
        )
        if not full_body:
            audit_logger.write_metadata_record(
                request_id=request_id,
                proxy_id=proxy_id,
                mode=mode,
                route=route,
                system_prompt_hash=sys_hash,
                tool_surface_hash=tool_hash,
                thinking=thinking,
                counts=counts,
                backend_id=backend_id,
            )
        elif not defer_full_body:
            # Request-only full body (the translated path has no response capture yet);
            # hashes/counts are included so the record is complete on the request side.
            audit_logger.write_full_body_record(
                request_id=request_id,
                proxy_id=proxy_id,
                mode=mode,
                route=route,
                request_headers=headers,
                request_body=body,
                redact_header_names=redact_headers,
                system_prompt_hash=sys_hash,
                tool_surface_hash=tool_hash,
                counts=counts,
                thinking=thinking,
                backend_id=backend_id,
            )
    except Exception as e:
        logger.debug("[%s] inspect persist skipped: %s", request_id, e)


async def _observe_request_side(
    body: dict[str, Any],
    request_id: str,
    *,
    headers: dict[str, str] | None = None,
    defer_full_body: bool = False,
) -> dict[str, Any] | None:
    """Inspect-mode observation: hash system/tools, detect drift, write a record.

    Hashing is cheap and runs inline; the drift/JSONL I/O is offloaded to a thread
    so the event loop is never blocked. Returns the computed context (hashes,
    counts, mode, route) so a response-side caller can complete a deferred
    full-body record, or None in passthrough mode / when there is no intercept config.
    """
    intercept = getattr(config.proxy, "intercept", None)
    if intercept is None or intercept.mode == "passthrough":
        return None
    try:
        from forge.proxy import audit_logger

        audit = getattr(config.proxy, "audit", None)
        full_body = bool(audit is not None and getattr(audit, "audit_full_body", False))
        redact_headers = audit.effective_redact_headers() if audit is not None else set()
        ctx: dict[str, Any] = {
            "proxy_id": PROXY_ID or "unknown",
            "backend_id": _backend_instance_id(),
            "route": _inspect_route(),
            "mode": intercept.mode,
            "sys_hash": audit_logger.hash_system_prompt(body.get("system")),
            "tool_hash": audit_logger.hash_tool_surface(body.get("tools")),
            "counts": {
                "num_messages": len(body.get("messages") or []),
                "num_tools": len(body.get("tools") or []),
            },
            "thinking": _thinking_summary(body.get("thinking")),
            "full_body": full_body,
            "redact_headers": redact_headers,
        }
    except Exception as e:
        logger.debug("[%s] inspect observation skipped: %s", request_id, e)
        return None

    try:
        await asyncio.to_thread(
            _persist_request_side,
            body=body,
            request_id=request_id,
            proxy_id=ctx["proxy_id"],
            route=ctx["route"],
            mode=ctx["mode"],
            headers=headers,
            sys_hash=ctx["sys_hash"],
            tool_hash=ctx["tool_hash"],
            backend_id=ctx["backend_id"],
            counts=ctx["counts"],
            thinking=ctx["thinking"],
            full_body=full_body,
            redact_headers=redact_headers,
            defer_full_body=defer_full_body,
        )
    except Exception as e:
        logger.debug("[%s] inspect persist dispatch failed: %s", request_id, e)
    return ctx


def _tier_from_model_name(model: str) -> str | None:
    """Infer haiku/sonnet/opus tier from a raw Anthropic model name (passthrough path).

    Mirrors data_models._detect_tier without constructing a MessagesRequest, so an
    explicit `claude-opus-*` request resolves tier_overrides.opus on passthrough.
    """
    return detect_tier_word(model or "")


# Anthropic-facing passthrough ingress (anthropic_passthrough). The handler and
# its override applier live in passthrough_ingress.py, the structural peer of
# responses_ingress.py, to keep this module's size bounded. Bound to the private
# name so the messages route/middleware dispatch (and its test seam) is unchanged.
_handle_anthropic_passthrough = handle_anthropic_passthrough


# Codex-facing OpenAI Responses ingress (openai_responses_passthrough). The handler
# and capability advert live in responses_ingress.py to keep this module's size
# bounded; create-before-catch-all registration order is owned there.
register_responses_routes(app)


_RESPONSE_CONVERSION_ERROR_TYPE = "api_error"
_RESPONSE_CONVERSION_ERROR_MESSAGE = "Failed to convert response"


def _coerce_usage_count(value: Any) -> int:
    """Return one external usage count as a non-negative int, or zero when malformed."""
    if isinstance(value, bool):
        return 0
    try:
        count = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return count if count >= 0 else 0


@app.post("/v1/messages", response_model=None)
async def create_message(request_data: MessagesRequest, raw_request: Request):
    """
    Process chat completion requests using unified client architecture.

    This endpoint handles both streaming and non-streaming responses,
    automatically routing to the appropriate provider based on model name.
    """
    request_id = raw_request.state.request_id
    downstream_event_id = getattr(raw_request.state, "downstream_event_id", None)
    forge_run_id, forge_root_run_id = _forge_run_ids(raw_request)  # Slice 4g run-tree correlation
    forge_session, forge_command = _forge_session_command(raw_request)  # Phase 3 provider-trace join keys
    start_time = time.time()

    _ensure_runtime_state()

    # Passthrough (wire_shape='anthropic_passthrough') is handled entirely in
    # log_requests_middleware, before this route binds MessagesRequest — so
    # create_message only ever runs the openai_translated path below.

    # Inspect/override observation on the openai_translated path (lossy: thinking
    # blocks are stripped downstream). Guarded so the default passthrough mode does
    # no model_dump() on the hot path.
    _intercept = getattr(config.proxy, "intercept", None)
    if _intercept is not None and _intercept.mode != "passthrough":
        await _observe_request_side(request_data.model_dump(), request_id, headers=dict(raw_request.headers))

    spend_warning: str | None = None
    provider_attempt_started = False
    provider_response_received = False
    _trace_ctx: dict[str, Any] = {}

    resolved_route = _resolve_model_with_alternatives(request_data)
    resolved_tier = resolved_route.tier
    resolved_tier_source = resolved_route.tier_source
    actual_model_id = resolved_route.model
    original_model_name = request_data.original_model_name

    logger.debug(f"[{request_id}] Resolved tier: {resolved_tier} (source={resolved_tier_source})")

    if resolved_route.explicit_backend:
        logger.debug(
            f"[{request_id}] Explicit backend model '{original_model_name}' - preserving as '{actual_model_id}'"
        )
    else:
        logger.debug(f"[{request_id}] Tier-resolved model: tier={resolved_tier} -> '{actual_model_id}'")

    # Spend cap check — post-event enforcement from accumulated spend.
    if cost_tracker is not None and cost_tracker.has_caps:
        cap_result = cost_tracker.check_cap()
        if cap_result.exceeded:
            spend_warning = _cap_result_message(cap_result)
            if cost_tracker.on_cap_hit == "reject":
                return JSONResponse(
                    status_code=429,
                    content={
                        "type": "error",
                        "error": {
                            "type": "spend_cap_exceeded",
                            "message": spend_warning,
                        },
                    },
                    headers={"X-Request-ID": request_id},
                )
            logger.warning("[%s] %s", request_id, spend_warning)

    num_messages = 0
    num_tools = 0
    tool_names: list[str] = []
    has_system = False

    try:
        num_messages = len(request_data.messages) if request_data.messages else 0
        num_tools = len(request_data.tools) if request_data.tools else 0
        tool_names = [tool.name for tool in request_data.tools] if request_data.tools else []
        has_system = bool(request_data.system)

        await _check_client_tool_failures(request_data, request_id, actual_model_id)

        # Detect provider BEFORE conversion to enable provider-specific schema handling
        detected_provider = client_factory.detect_provider_for_model(actual_model_id)
        provider_name = detected_provider.value  # Convert enum to string

        logger.debug(
            f"[{request_id}] Processing '/v1/messages': "
            f"original='{original_model_name}', target='{actual_model_id}', provider='{provider_name}', "
            f"messages={num_messages}, tools={num_tools}, stream={request_data.stream}"
        )

        try:
            openai_request_dict = convert_anthropic_to_openai(request_data, provider=provider_name)
        except RequestConversionError as exc:
            logger.info("[%s] Invalid translated request: %s", request_id, exc)
            raise HTTPException(
                status_code=400,
                detail={"type": "invalid_request_error", "message": str(exc)},
            ) from exc

        openai_request_dict["model"] = actual_model_id

        # Forward User-Agent from incoming request (Claude Code identity).
        # Upstream LLM gateways may filter traffic by User-Agent; without this,
        # the proxy's OpenAI SDK default header could cause requests to be blocked.
        # The factory deliberately collapses local/remote LiteLLM into one routing enum;
        # backend-instance provider strings are a different vocabulary.
        if detected_provider in (ModelProvider.LITELLM, ModelProvider.OPENROUTER):
            incoming_user_agent = raw_request.headers.get("user-agent")
            if incoming_user_agent:
                openai_request_dict["_user_agent"] = incoming_user_agent
                logger.debug(f"[{request_id}] Forwarding User-Agent: {incoming_user_agent[:120]!r}")

        # Opt-in (default off): record the Forge session grouping id in the provider's `user` field
        # so a session/fork is retrievable from the provider's account-side record. Backend-capability
        # gated (the backend_id must declare provider-user grouping); metadata-only, already hashed.
        forge_user = _provider_user_value(
            backend_id=_backend_instance_id(),
            # Read the flag lazily: source capability decides whether this route uses it.
            inject=_inject_provider_user_enabled(),
            forge_session=forge_session,
            forge_root_run_id=forge_root_run_id,
            forge_command=forge_command,
        )
        if forge_user:
            openai_request_dict["_forge_user"] = forge_user

        # Priority: request explicit > tier_override > model default (in catalog)
        tier_override = _get_tier_override(resolved_tier)
        if tier_override:
            logger.debug(f"[{request_id}] Tier override for '{resolved_tier}': {tier_override}")

        if request_data.temperature is not None:
            openai_request_dict["temperature"] = request_data.temperature
        elif tier_override and tier_override.temperature is not None:
            openai_request_dict["temperature"] = tier_override.temperature

        if request_data.max_tokens is not None:
            openai_request_dict["max_tokens"] = request_data.max_tokens
        if request_data.top_p is not None:
            openai_request_dict["top_p"] = request_data.top_p

        # Optional reasoning/thinking overrides.
        # Priority: request explicit > thinking-derived > tier_override > model default
        # tier_override acts as a FLOOR (never go below the user's tier config);
        # the result is normalized against the catalog's effort levels for the
        # mapped model (explicit unsupported values reject, derived ones clamp).
        openai_request_dict["reasoning_effort"] = resolve_reasoning_effort(
            request_data,
            tier_override=tier_override,
            model_id=actual_model_id,
            request_id=request_id,
        )

        # Note: the raw `thinking` dict is NOT forwarded — it's Anthropic-specific.
        # Litellm controls thinking via reasoning_effort (mapped above).

        verbosity = getattr(request_data, "verbosity", None)
        if verbosity is not None:
            openai_request_dict["verbosity"] = verbosity
        elif tier_override and tier_override.verbosity is not None:
            openai_request_dict["verbosity"] = tier_override.verbosity

        if request_data.stop_sequences:
            openai_request_dict["stop"] = request_data.stop_sequences

        # Get unified client for this model (pass tier for tier-specific hyperparameters)
        try:
            client = await client_factory.get_client(actual_model_id, tier=resolved_tier)
            logger.debug(f"[{request_id}] Got client for {actual_model_id} (tier={resolved_tier})")
        except AuthenticationError as e:
            logger.error(f"[{request_id}] Authentication failed: {e}")
            raise HTTPException(
                status_code=401,
                detail={
                    "type": "authentication_error",
                    "message": f"Authentication failed [{request_id}]",
                },
            )

        # Shared run-tree context for every provider-trace record on this request.
        # Reusing one dict at each real-call path prevents the per-path context drift
        # that caused the auth-retry gap (Defect B).
        # Capability gating lives inside ``record_provider_trace``; callers stay unconditional.
        _trace_ctx = {
            "backend_id": _backend_instance_id(),
            "proxy_id": PROXY_ID or "unknown",
            "mapped_model": actual_model_id,
            "request_id": request_id,
            "forge_run_id": forge_run_id,
            "forge_root_run_id": forge_root_run_id,
            "provider_session_id": forge_session,
            "provider_command": forge_command,
        }

        def _fail_non_streaming_conversion(openai_response: dict[str, Any], duration_ms: float) -> NoReturn:
            """Record a completed provider attempt whose response cannot reach the client."""
            raw_usage = openai_response.get("usage")
            usage = raw_usage if isinstance(raw_usage, dict) else {}
            input_tokens = _coerce_usage_count(usage.get("prompt_tokens"))
            output_tokens = _coerce_usage_count(usage.get("completion_tokens"))
            cached_tokens = _coerce_usage_count(usage.get("cached_tokens"))
            reported_cost_micros = openai_response.get("_reported_cost_micros")

            cost = _calc_and_log_cost(
                model=actual_model_id,
                tier=resolved_tier,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
                latency_ms=duration_ms,
                failed=True,
                request_id=request_id,
                reported_cost_micros=reported_cost_micros,
                forge_run_id=forge_run_id,
                forge_root_run_id=forge_root_run_id,
                downstream_event_id=downstream_event_id,
            )
            proxy_metrics.record_request(
                tier=resolved_tier,
                model=actual_model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_tokens=cached_tokens,
                latency_ms=duration_ms,
                streaming=False,
                failed=True,
                error_type=_RESPONSE_CONVERSION_ERROR_TYPE,
                cost_micros=cost,
            )
            # The provider call completed even though Forge could not represent its
            # response. Retain that attempt's metadata and reported cost without
            # relabelling it as an upstream transport failure.
            record_provider_trace(
                **_trace_ctx,
                request_mode="non_streaming",
                provider_meta=openai_response.get("_provider_meta"),
                stream_started=True,
                first_chunk_seen=True,
                final_usage_seen=True,
                client_disconnected=False,
                reported_cost_micros=reported_cost_micros,
                latency_ms=duration_ms,
                downstream_event_id=downstream_event_id,
            )
            asyncio.create_task(
                log_request_response(
                    request_id=request_id,
                    original_model=original_model_name or "",
                    mapped_model=actual_model_id,
                    request_body=request_data.model_dump(),
                    response_body=None,
                    request_log=_request_log_config(),
                    status_code=500,
                    duration_ms=duration_ms,
                    error=_RESPONSE_CONVERSION_ERROR_MESSAGE,
                    num_messages=num_messages,
                    num_tools=num_tools,
                    tool_names=tool_names,
                    has_system=has_system,
                    temperature=request_data.temperature,
                    max_tokens=request_data.max_tokens,
                    streaming=False,
                )
            )
            log_request_beautifully(
                method="POST",
                path="/v1/messages",
                original_model=original_model_name or "",
                mapped_model=actual_model_id,
                num_messages=num_messages,
                num_tools=num_tools,
                status_code=500,
            )
            raise HTTPException(
                status_code=500,
                detail={
                    "type": _RESPONSE_CONVERSION_ERROR_TYPE,
                    "message": _RESPONSE_CONVERSION_ERROR_MESSAGE,
                },
            )

        if request_data.stream:
            # Streaming response
            async def stream_generator():
                try:
                    async for chunk in client.create_streaming_completion(openai_request_dict, request_id):
                        yield chunk
                except ProxyStreamError as e:
                    logger.error(f"[{request_id}] ProxyStreamError ({e.error_type}): {e}")
                    yield {
                        "error": {
                            "type": e.error_type,
                            "message": f"Streaming request failed [{request_id}]",
                            "status_code": e.status_code,
                        }
                    }

            headers = {
                "X-Request-ID": request_id,
                "X-Resolved-Tier": resolved_tier,
                "X-Resolved-Model": actual_model_id,
                **_cumulative_cost_header(),
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
            headers = _with_spend_warning(headers, spend_warning)

            # Log streaming request (no response body available)
            duration_ms = (time.time() - start_time) * 1000
            asyncio.create_task(
                log_request_response(
                    request_id=request_id,
                    original_model=original_model_name or "",
                    mapped_model=actual_model_id,
                    request_body=request_data.model_dump(),
                    response_body=None,  # Streaming has no response body
                    status_code=200,
                    duration_ms=duration_ms,
                    num_messages=num_messages,
                    num_tools=num_tools,
                    tool_names=tool_names,
                    has_system=has_system,
                    temperature=request_data.temperature,
                    max_tokens=request_data.max_tokens,
                    streaming=True,
                    request_log=_request_log_config(),
                )
            )

            log_request_beautifully(
                method="POST",
                path="/v1/messages (streaming)",
                original_model=original_model_name or "",
                mapped_model=actual_model_id,
                num_messages=num_messages,
                num_tools=num_tools,
                status_code=200,
            )

            def _on_stream_complete(usage: dict[str, Any], failed: bool, error_type: str | None) -> None:
                elapsed = (time.time() - start_time) * 1000
                in_tok = usage.get("input_tokens", 0)
                out_tok = usage.get("output_tokens", 0)
                cache_tok = usage.get("cached_tokens", 0)
                cost = _calc_and_log_cost(
                    model=actual_model_id,
                    tier=resolved_tier,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cached_tokens=cache_tok,
                    latency_ms=elapsed,
                    failed=failed,
                    request_id=request_id,
                    # final_usage carries the route-reported cost the SSE converter parked there.
                    reported_cost_micros=usage.get("reported_cost_micros"),
                    forge_run_id=forge_run_id,
                    forge_root_run_id=forge_root_run_id,
                    downstream_event_id=downstream_event_id,
                )
                proxy_metrics.record_request(
                    tier=resolved_tier,
                    model=actual_model_id,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cached_tokens=cache_tok,
                    latency_ms=elapsed,
                    streaming=True,
                    failed=failed,
                    error_type=error_type,
                    cost_micros=cost,
                )
                # The converter parked provider_meta + stream lifecycle under usage["_provider_trace"];
                # a stream cancelled before the final usage chunk still carries the generation id here.
                _trace = usage.get("_provider_trace") or {}
                _lc = _trace.get("lifecycle", {})
                record_provider_trace(
                    **_trace_ctx,
                    request_mode="streaming",
                    provider_meta=_trace.get("provider_meta"),
                    stream_started=_lc.get("stream_started", False),
                    first_chunk_seen=_lc.get("first_chunk_seen", False),
                    final_usage_seen=_lc.get("final_usage_seen", False),
                    client_disconnected=_lc.get("client_disconnected", False),
                    reported_cost_micros=usage.get("reported_cost_micros"),
                    latency_ms=elapsed,
                    downstream_event_id=downstream_event_id,
                )

            _stream_log_cfg = _request_log_config()
            return StreamingResponse(
                convert_openai_to_anthropic_sse(
                    stream_generator(),
                    request_data,
                    request_id,
                    on_complete=_on_stream_complete,
                    stream_chunks=_stream_log_cfg.stream_chunks,
                    stream_chunk_max_bytes=_stream_log_cfg.stream_chunk_max_bytes,
                ),
                media_type="text/event-stream",
                headers=headers,
            )
        else:
            try:
                provider_attempt_started = True
                openai_response = await client.create_completion(openai_request_dict, request_id)
                provider_response_received = True
                anthropic_response = convert_openai_to_anthropic(openai_response, original_model_name)

                if anthropic_response is None:
                    duration_ms = (time.time() - start_time) * 1000
                    _fail_non_streaming_conversion(openai_response, duration_ms)

                response_dict = anthropic_response.model_dump()
                response_dict["_request_id"] = request_id

                duration_ms = (time.time() - start_time) * 1000

                _usage = openai_response.get("usage", {})
                _in = _usage.get("prompt_tokens", 0)
                _out = _usage.get("completion_tokens", 0)
                _cached = _usage.get("cached_tokens", 0)
                _cost = _calc_and_log_cost(
                    model=actual_model_id,
                    tier=resolved_tier,
                    input_tokens=_in,
                    output_tokens=_out,
                    cached_tokens=_cached,
                    latency_ms=duration_ms,
                    failed=False,
                    request_id=request_id,
                    reported_cost_micros=openai_response.get("_reported_cost_micros"),
                    forge_run_id=forge_run_id,
                    forge_root_run_id=forge_root_run_id,
                    downstream_event_id=downstream_event_id,
                )
                proxy_metrics.record_request(
                    tier=resolved_tier,
                    model=actual_model_id,
                    input_tokens=_in,
                    output_tokens=_out,
                    cached_tokens=_cached,
                    latency_ms=duration_ms,
                    streaming=False,
                    failed=False,
                    error_type=None,
                    cost_micros=_cost,
                )
                # Non-streaming: the full body arrived, so the lifecycle is trivially
                # complete; provider_meta rides the top-level carrier key.
                record_provider_trace(
                    **_trace_ctx,
                    request_mode="non_streaming",
                    provider_meta=openai_response.get("_provider_meta"),
                    stream_started=True,
                    first_chunk_seen=True,
                    final_usage_seen=True,
                    client_disconnected=False,
                    reported_cost_micros=openai_response.get("_reported_cost_micros"),
                    latency_ms=duration_ms,
                    downstream_event_id=downstream_event_id,
                )

                asyncio.create_task(
                    log_request_response(
                        request_id=request_id,
                        original_model=original_model_name or "",
                        mapped_model=actual_model_id,
                        request_body=request_data.model_dump(),
                        response_body=response_dict,
                        request_log=_request_log_config(),
                        status_code=200,
                        duration_ms=duration_ms,
                        num_messages=num_messages,
                        num_tools=num_tools,
                        tool_names=tool_names,
                        has_system=has_system,
                        temperature=request_data.temperature,
                        max_tokens=request_data.max_tokens,
                        streaming=False,
                    )
                )

                log_request_beautifully(
                    method="POST",
                    path="/v1/messages",
                    original_model=original_model_name or "",
                    mapped_model=actual_model_id,
                    num_messages=num_messages,
                    num_tools=num_tools,
                    status_code=200,
                )
                return JSONResponse(
                    content=response_dict,
                    headers=_with_spend_warning(
                        {
                            "X-Request-ID": request_id,
                            "X-Resolved-Tier": resolved_tier,
                            "X-Resolved-Model": actual_model_id,
                            **_request_cost_header(_cost),
                            **_cumulative_cost_header(),
                        },
                        spend_warning,
                    ),
                )

            except AuthenticationError:
                # Try refreshing credentials once
                logger.warning(f"[{request_id}] Auth failed, refreshing credentials")
                client = await client_factory.invalidate_and_retry(actual_model_id, tier=resolved_tier)
                provider_attempt_started = True
                provider_response_received = False
                openai_response = await client.create_completion(openai_request_dict, request_id)
                provider_response_received = True
                anthropic_response = convert_openai_to_anthropic(openai_response, original_model_name)

                if anthropic_response is None:
                    retry_duration_ms = (time.time() - start_time) * 1000
                    _fail_non_streaming_conversion(openai_response, retry_duration_ms)

                retry_duration_ms = (time.time() - start_time) * 1000
                _retry_usage = openai_response.get("usage", {})
                _ri = _retry_usage.get("prompt_tokens", 0)
                _ro = _retry_usage.get("completion_tokens", 0)
                _rc = _retry_usage.get("cached_tokens", 0)
                _rcost = _calc_and_log_cost(
                    model=actual_model_id,
                    tier=resolved_tier,
                    input_tokens=_ri,
                    output_tokens=_ro,
                    cached_tokens=_rc,
                    latency_ms=retry_duration_ms,
                    failed=False,
                    request_id=request_id,
                    reported_cost_micros=openai_response.get("_reported_cost_micros"),
                    forge_run_id=forge_run_id,
                    forge_root_run_id=forge_root_run_id,
                    downstream_event_id=downstream_event_id,
                )
                proxy_metrics.record_request(
                    tier=resolved_tier,
                    model=actual_model_id,
                    input_tokens=_ri,
                    output_tokens=_ro,
                    cached_tokens=_rc,
                    latency_ms=retry_duration_ms,
                    streaming=False,
                    failed=False,
                    error_type=None,
                    cost_micros=_rcost,
                )
                # The auth-retry success path is a real provider call too; without this a
                # 401 -> refresh -> 200 logged cost/metrics with no provider-trace record.
                record_provider_trace(
                    **_trace_ctx,
                    request_mode="non_streaming",
                    provider_meta=openai_response.get("_provider_meta"),
                    stream_started=True,
                    first_chunk_seen=True,
                    final_usage_seen=True,
                    client_disconnected=False,
                    reported_cost_micros=openai_response.get("_reported_cost_micros"),
                    latency_ms=retry_duration_ms,
                    downstream_event_id=downstream_event_id,
                )

                response_dict = anthropic_response.model_dump()
                response_dict["_request_id"] = request_id
                return JSONResponse(
                    content=response_dict,
                    headers=_with_spend_warning(
                        {
                            "X-Request-ID": request_id,
                            "X-Resolved-Tier": resolved_tier,
                            "X-Resolved-Model": actual_model_id,
                            **_request_cost_header(_rcost),
                            **_cumulative_cost_header(),
                        },
                        spend_warning,
                    ),
                )

    except HTTPException:
        raise
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        error_msg = f"Internal error [{request_id}]"

        _err_cost = _calc_and_log_cost(
            model=actual_model_id,
            tier=resolved_tier,
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            latency_ms=duration_ms,
            failed=True,
            request_id=request_id,
            forge_run_id=forge_run_id,
            forge_root_run_id=forge_root_run_id,
            downstream_event_id=downstream_event_id,
        )
        proxy_metrics.record_request(
            tier=resolved_tier,
            model=actual_model_id,
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            latency_ms=duration_ms,
            streaming=request_data.stream or False,
            failed=True,
            error_type="api_error",
            cost_micros=_err_cost,
        )
        if provider_attempt_started and not provider_response_received and _trace_ctx:
            # The provider call began but yielded no usable response. Keep local
            # validation/conversion/client-construction failures trace-free, and do not
            # duplicate a lifecycle after a response reached Forge. The context guard
            # also keeps this error handler safe if dispatch ordering changes later.
            record_provider_trace(
                **_trace_ctx,
                request_mode="non_streaming",
                provider_meta=None,
                stream_started=False,
                first_chunk_seen=False,
                final_usage_seen=False,
                client_disconnected=False,
                reported_cost_micros=None,
                latency_ms=duration_ms,
                downstream_event_id=downstream_event_id,
            )

        asyncio.create_task(
            log_request_response(
                request_id=request_id,
                original_model=original_model_name or "",
                mapped_model=actual_model_id,
                request_body=request_data.model_dump(),
                response_body=None,
                status_code=500,
                duration_ms=duration_ms,
                error=error_msg,
                num_messages=num_messages,
                num_tools=num_tools,
                tool_names=tool_names,
                has_system=has_system,
                temperature=request_data.temperature,
                max_tokens=request_data.max_tokens,
                streaming=request_data.stream or False,
                request_log=_request_log_config(),
            )
        )

        log_request_beautifully(
            method="POST",
            path="/v1/messages",
            original_model=original_model_name or "",
            mapped_model=actual_model_id,
            num_messages=num_messages,
            num_tools=num_tools,
            status_code=500,
        )

        logger.error(f"[{request_id}] Unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"type": "api_error", "message": error_msg})


@app.post("/v1/messages/count_tokens", response_model=TokenCountResponse)
async def count_tokens(request_data: TokenCountRequest, raw_request: Request):
    """Count tokens using the appropriate client's token counter."""
    request_id = raw_request.state.request_id

    _ensure_runtime_state()

    # Passthrough count_tokens is handled in log_requests_middleware (pre-routing);
    # this handler only runs the openai_translated path.

    try:
        original_model_name = request_data.original_model_name
        resolved_route = _resolve_model_with_alternatives(request_data)
        resolved_tier = resolved_route.tier
        resolved_tier_source = resolved_route.tier_source
        actual_model_id = resolved_route.model

        logger.info(f"[{request_id}] Token counting: original='{original_model_name}', target='{actual_model_id}'")
        logger.debug(f"[{request_id}] Token count resolved tier: {resolved_tier} (source={resolved_tier_source})")

        detected_provider = client_factory.detect_provider_for_model(actual_model_id)
        provider_name = detected_provider.value

        simulated_request = MessagesRequest(
            model=actual_model_id,
            messages=request_data.messages,
            system=request_data.system,
            max_tokens=1,
        )
        openai_dict = convert_anthropic_to_openai(simulated_request, provider=provider_name)
        messages = openai_dict.get("messages", [])

        client = await client_factory.get_client(actual_model_id, tier=resolved_tier)
        token_count = await client.count_tokens(messages)

        response = TokenCountResponse(input_tokens=token_count)
        return JSONResponse(content=response.model_dump(), headers={"X-Request-ID": request_id})

    except Exception as e:
        logger.error(f"[{request_id}] Token counting failed: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "type": "api_error",
                "message": f"Token counting failed [{request_id}]",
            },
        )


DEFAULT_CONTEXT_WINDOW = 200000


def get_context_window(model_name: str) -> int:
    """Get context window size for a model from the central catalog.

    Falls back to a safe default for models not in the catalog (e.g.,
    OpenRouter models outside Forge's known set).

    Args:
        model_name: Model ID (canonical or alias like 'openai/gpt-5.5')

    Returns:
        Context window size in tokens.
    """
    from forge.core.models import get_context_window_tokens, model_exists

    if not model_exists(model_name):
        logger.debug(f"Model {model_name!r} not in catalog, using default context window")
        return DEFAULT_CONTEXT_WINDOW

    return get_context_window_tokens(model_name)


@app.get("/", include_in_schema=False)
async def root(request: Request):
    """Service health and runtime truth for status line scripts.

    Returns proxy runtime status including:
    - is_proxy: True (indicates this is a proxy, not direct Anthropic API)
    - template: Active configuration template name
    - provider: Underlying provider (litellm, openai, gemini)
    - tiers: Mapping of Claude tiers to actual models with context windows
    - proxy: First-class proxy identity (proxy_id, template, port, base_url)
    - runtime: Actual resolved tier → model mappings, context windows, llm defaults
    - downstream_retention: Effective global policy plus migration/degraded status

    Note: Session state is no longer returned by proxy. Consumers should read
    session state locally via FORGE_SESSION env var or CWD manifest.

    This endpoint reflects what the proxy is **actually doing**, not just
    echoed configuration. It serves as the source of runtime truth.
    """
    # A freshly-imported uvicorn app has only import-time default config and a
    # None cost_tracker until the first POST runs _ensure_runtime_state(). As the
    # documented source of runtime truth (polled by the status line before any
    # request flows), root() must self-initialize too — otherwise it reports
    # default template/tiers and omits metrics.costs.caps. Idempotent + cheap on
    # a warm process (reload() no-ops once config is loaded; tracker init returns).
    _ensure_runtime_state()

    import os

    from forge.proxy.proxy_identity import get_proxy_identity

    active_template = os.environ.get("ACTIVE_TEMPLATE", "unknown")
    preferred_provider = os.environ.get("PREFERRED_PROVIDER", "unknown")

    # Extract request host/port for proxy identity (accurate even with --auto-port)
    request_host = request.url.hostname or "localhost"
    request_port = request.url.port

    # Fallback to env var if request port unavailable
    env_port_str = os.environ.get("ACTIVE_PORT")
    env_port = int(env_port_str) if env_port_str else None

    # Discover proxy identity (2-tier: registry > derived)
    proxy_identity = get_proxy_identity(
        active_template=active_template,
        request_host=request_host,
        request_port=request_port,
        env_port=env_port,
        process_proxy_id=os.environ.get("FORGE_PROXY_ID"),
    )

    # Tier mappings exposed via GET / for status line and session context
    tiers = {}
    provider_config = config.proxy.get_provider(preferred_provider)
    tier_models = {
        "haiku": provider_config.tiers.haiku,
        "sonnet": provider_config.tiers.sonnet,
        "opus": provider_config.tiers.opus,
    }

    for tier, model in tier_models.items():
        tiers[tier] = {
            "model": model,
            "context_window": get_context_window(model),
        }

    # Compute runtime LLM defaults (post-merge) from the credential manager.
    # This reflects the actual baseline hyperparameters used by proxy clients,
    # including env/tier overrides and caps.
    llm_defaults_by_tier: dict[str, dict[str, object]] = {}
    for tier in ("haiku", "sonnet", "opus"):
        try:
            model_name = tier_models.get(tier)
            if not model_name:
                raise ValueError(f"No model configured for tier {tier!r}")
            hp = client_factory.get_default_hyperparams_for_tier(
                provider=preferred_provider, tier=tier, model_name=model_name
            )
            llm_defaults_by_tier[tier] = hp.model_dump(exclude_unset=True)
        except Exception as e:
            llm_defaults_by_tier[tier] = {"error": f"failed to compute defaults: {e}"}

    if config.proxy.default_tier:
        default_tier = config.proxy.default_tier
        default_tier_source = "proxy.default_tier"
    else:
        default_tier = None
        default_tier_source = "missing"

    runtime_active_model = tier_models.get(default_tier or "sonnet") or tier_models.get("sonnet")

    routing_section = {
        "default_tier": default_tier,
        "default_tier_source": default_tier_source,
        "note": "Routing defaults are proxy-owned. Session state is not authoritative for routing defaults.",
    }

    if default_tier is None:
        routing_section["note"] = (
            "Proxy is missing config.proxy.default_tier; ambiguous requests will fail until configured."
        )

    runtime_section = {
        "template": active_template,
        "provider": preferred_provider,
        "tier_mappings": tier_models,
        "context_windows": {tier: get_context_window(model) for tier, model in tier_models.items()},
        "active_tier": default_tier,
        "active_context_window": get_context_window(runtime_active_model) if runtime_active_model else None,
        # Proxy-owned hyperparameter defaults actually used by proxy clients (post-merge)
        "llm_defaults_by_tier": llm_defaults_by_tier,
    }

    # Build proxy identity section (B2.1.5)
    proxy_section = {
        "proxy_id": proxy_identity.proxy_id,
        "template": proxy_identity.template,
        "port": proxy_identity.port,
        "base_url": proxy_identity.base_url,
        "source": proxy_identity.source,
        "status": proxy_identity.status,
    }

    # Intercept preflight: report mode + what Forge can inspect for this route so a
    # launcher can say "inspect active (signature-safe)" vs "inspect active (lossy)".
    _wire_shape = getattr(config.proxy, "wire_shape", DEFAULT_WIRE_SHAPE)
    _intercept_cfg = getattr(config.proxy, "intercept", None)
    _intercept_mode = _intercept_cfg.mode if _intercept_cfg is not None else "passthrough"
    _audit_cfg = getattr(config.proxy, "audit", None)
    intercept_section = build_intercept_capability_section(
        _wire_shape,
        _intercept_mode,
        bool(getattr(_audit_cfg, "audit_full_body", False)),
    )
    # Advertised Responses-ingress capability for the Phase 4 launcher health-check.
    _responses_ingress = advertise_responses_ingress(_wire_shape, getattr(config.proxy, "backend", "") or "")

    # Per-proxy metrics (request counts, token usage, latency); spend-cap
    # proximity is attached under metrics.costs.caps when caps are configured.
    metrics_snapshot = proxy_metrics.snapshot()
    _attach_cap_summary(metrics_snapshot, cost_tracker)

    retention_section, retention_degraded = _downstream_retention_status_section()

    response = {
        "is_proxy": True,
        "template": active_template,
        "provider": preferred_provider,
        # Wire shape is the authoritative wire truth; provider may be a config slot
        # (e.g. anthropic-passthrough uses provider=litellm). See Phase 2 audit proxy.
        "wire_shape": _wire_shape,
        "intercept_mode": _intercept_mode,
        "intercept": intercept_section,
        "capabilities": {"responses_ingress": _responses_ingress},
        "tiers": tiers,
        "status": "degraded" if retention_degraded else "running",
        "routing": routing_section,
        # Proxy identity (B2.1.5): first-class proxy identity
        "proxy": proxy_section,
        # Runtime truth: tier mappings, context windows, hyperparameter defaults
        "runtime": runtime_section,
        "downstream_retention": retention_section,
        "metrics": metrics_snapshot,
    }

    return response


# A successful, fast completion on a non-verbose endpoint (GET /, health/runtime-truth
# polls) is logged at DEBUG, not INFO -- the status line polls GET / frequently and an
# INFO line per poll turns the proxy log into an access-log stream (proxy_log_hygiene).
# A slow poll above this threshold, or any non-2xx, still logs once at INFO so genuine
# stalls and failures stay visible.
_SLOW_POLL_LOG_S = 1.0


@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    """Request logging middleware."""
    start_time = time.time()

    path = request.url.path
    prefix = "req_"
    if "/count_tokens" in path:
        prefix = "tok_"
    elif "/" == path:
        prefix = "inf_"

    raw_headers = request.scope["headers"]
    if not isinstance(raw_headers, list):
        raw_headers = request.scope["headers"] = list(raw_headers)
    client_request_ids = [value.decode("latin-1") for name, value in raw_headers if name.lower() == b"x-request-id"]
    client_request_id = client_request_ids[0] if len(client_request_ids) == 1 else None
    request_id = client_request_id if is_valid_request_id(client_request_id) else f"{prefix}{uuid.uuid4().hex[:12]}"
    if client_request_ids:
        _canonicalize_request_id_header(request, request_id)
    request.state.request_id = request_id
    request.state.downstream_event_id = mint_downstream_event_id(event_key=f"proxy:{request_id}:{uuid.uuid4().hex}")

    # Slice 4g: run-tree correlation. Read + VALIDATE the Forge run-id headers a
    # proxy-routed `claude -p` subprocess stamps, so each cost record can join to the
    # run tree. Validation drops a malformed/spoofed value (stored None, never trusted
    # into the cost log). Set before BOTH the passthrough branch and call_next so both
    # wire shapes see them on request.state.
    request.state.forge_run_id = _valid_run_header(request.headers.get(FORGE_RUN_ID_HEADER))
    request.state.forge_root_run_id = _valid_run_header(request.headers.get(FORGE_ROOT_RUN_ID_HEADER))
    # Phase 1: provider-trace correlation. The opaque session grouping id + command role
    # the subprocess stamped, validated the same way (spoofed/over-long -> None). These are
    # internal Forge<->proxy headers; the proxy consumes them and never forwards upstream.
    request.state.forge_session = _valid_session_header(request.headers.get(FORGE_SESSION_HEADER))
    request.state.forge_command = _valid_command_header(request.headers.get(FORGE_COMMAND_HEADER))

    # Transparent Anthropic passthrough is intercepted HERE, before the route's
    # MessagesRequest binding runs — FastAPI validates the body against a closed
    # content-block union, so an unknown/future block type would 422 before any
    # in-handler wire_shape check. Middleware forwards the raw bytes instead.
    if request.method == "POST" and path in (
        "/v1/messages",
        "/v1/messages/count_tokens",
    ):
        try:
            _ensure_runtime_state()
            is_passthrough = getattr(config.proxy, "wire_shape", DEFAULT_WIRE_SHAPE) == ANTHROPIC_PASSTHROUGH
        except Exception as e:
            logger.error("[%s] passthrough preflight failed: %s", request_id, e)
            is_passthrough = False
        if is_passthrough:
            try:
                response = await _handle_anthropic_passthrough(request, request_id, path=path)
            except Exception as e:
                logger.error("[%s] passthrough error: %s", request_id, e, exc_info=True)
                return JSONResponse(
                    status_code=500,
                    content={
                        "type": "error",
                        "error": {
                            "type": "api_error",
                            "message": f"Passthrough error [{request_id}]",
                        },
                    },
                    headers={"X-Request-ID": request_id},
                )
            if "X-Request-ID" not in response.headers:
                response.headers["X-Request-ID"] = request_id
            logger.info(f"{path} [{request_id}] passthrough completed in {time.time() - start_time:.3f}s")
            return response

    # Endpoints that have their own detailed logging
    verbose_endpoints = ("/messages", "/event_logging")
    has_own_logging = any(ep in path for ep in verbose_endpoints)

    logger.debug(f"{path} [{request_id}] {request.method}")

    try:
        response = await call_next(request)
        elapsed = time.time() - start_time

        if has_own_logging:
            logger.debug(f"{path} [{request_id}] Middleware: {elapsed:.3f}s")
        else:
            status = response.status_code
            # Quiet successful, fast polls (GET / etc.) to DEBUG; keep INFO for failures
            # and slow responses so they stay visible without an access-log per poll.
            level = logging.INFO if (status >= 400 or elapsed > _SLOW_POLL_LOG_S) else logging.DEBUG
            logger.log(level, f"{path} [{request_id}] Completed in {elapsed:.3f}s ({status})")

        if "X-Request-ID" not in response.headers:
            response.headers["X-Request-ID"] = request_id

        return response
    except Exception as e:
        logger.error(f"[{request_id}] Middleware error: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "type": "api_error",
                    "message": f"Internal error [{request_id}]",
                }
            },
            headers={"X-Request-ID": request_id},
        )


async def _check_client_tool_failures(request_data: MessagesRequest, request_id: str, mapped_model: str):
    """Check for client-side tool execution failures in the request.

    Only scans the most recent user message. Older tool_result blocks were
    already inspected on prior requests; re-scanning them produces duplicate
    log entries and skews telemetry.
    """
    latest_user_msg = next(
        (m for m in reversed(request_data.messages) if m.role == "user" and isinstance(m.content, list)),
        None,
    )
    if latest_user_msg is None:
        return

    for msg in (latest_user_msg,):
        if msg.role == "user" and isinstance(msg.content, list):
            for block in msg.content:
                if hasattr(block, "type") and block.type == "tool_result":
                    tool_use_id = getattr(block, "tool_use_id", None)
                    is_error = False
                    error_content = None

                    # 1. Most reliable: Check explicit is_error field
                    if hasattr(block, "is_error") and block.is_error:
                        is_error = True
                        if hasattr(block, "content"):
                            error_content = block.content

                    if hasattr(block, "content") and not is_error:
                        # 2. Check for dict with error keys (structured errors)
                        if isinstance(block.content, dict) and any(k in block.content for k in ["error", "exception"]):
                            is_error = True
                            error_content = block.content
                        # 3. For string content, only check for explicit error patterns at the start
                        # Don't scan the entire content as it causes false positives with documentation
                        elif isinstance(block.content, str):
                            content_start = block.content[:200] if len(block.content) > 200 else block.content
                            # Be specific to avoid false positives
                            error_patterns = [
                                "Error:",
                                "ERROR:",
                                "Exception:",
                                "EXCEPTION:",
                                "Failed:",
                                "FAILED:",
                                "Tool execution failed",
                                "Command failed",
                                "File not found",
                                "Permission denied",
                                "Invalid tool",  # More specific than just "Invalid"
                                "Invalid arguments",
                                "Invalid input",
                                "Traceback (most recent call last)",
                            ]
                            if any(content_start.startswith(pattern) for pattern in error_patterns):
                                is_error = True
                                error_content = block.content
                            else:
                                error_content = None
                        else:
                            error_content = block.content

                    if is_error and tool_use_id:
                        tool_name, tool_input = _find_tool_use_info(request_data.messages, msg, tool_use_id)
                        safe_request_id = bounded_tool_event_identifier(request_id) or "unknown"
                        safe_tool_name = bounded_tool_event_identifier(tool_name) or "unknown"
                        safe_tool_use_id = bounded_tool_event_identifier(tool_use_id) or "unknown"
                        content_type, content_length = tool_event_value_shape(error_content)

                        # Check if this is a stale cleared tool result (not actionable)
                        is_cleared_content = (
                            isinstance(error_content, str) and "Old tool result content cleared" in error_content
                        )

                        # Only log as warning if we have actual error content (not cleared)
                        if error_content and not is_cleared_content:
                            logger.warning(
                                "[%s] Client tool failure: tool=%s id=%s content_type=%s content_length=%s",
                                safe_request_id,
                                safe_tool_name,
                                safe_tool_use_id,
                                content_type,
                                content_length,
                            )
                        elif is_cleared_content:
                            logger.debug(
                                "[%s] Stale tool failure (content cleared): tool=%s id=%s",
                                safe_request_id,
                                safe_tool_name,
                                safe_tool_use_id,
                            )
                        else:
                            # Debug log for investigation when is_error but no content
                            logger.debug(
                                "[%s] Tool marked as error but no error content: tool=%s id=%s is_error=%s",
                                safe_request_id,
                                safe_tool_name,
                                safe_tool_use_id,
                                getattr(block, "is_error", None),
                            )

                        enriched_content = error_content
                        if error_content and not is_cleared_content and isinstance(error_content, str):
                            provider_cfg = config.proxy.get_provider()
                            if provider_cfg.error_hints:
                                enriched_content = enrich_error_content(tool_name, error_content)
                                if enriched_content != error_content:
                                    block.content = enriched_content
                                    logger.debug(
                                        "[%s] Enriched error hint for tool %s",
                                        safe_request_id,
                                        safe_tool_name,
                                    )

                        # Only log as failure if we have actual error content (not cleared)
                        if error_content and not is_cleared_content:
                            asyncio.create_task(
                                log_tool_failure(
                                    request_id=request_id,
                                    mapped_model=mapped_model,
                                    tool_name=tool_name,
                                    tool_use_id=tool_use_id,
                                    tool_input=tool_input,
                                    error_content=error_content,
                                )
                            )
                            asyncio.create_task(
                                log_tool_event(
                                    request_id=request_id,
                                    tool_name=tool_name,
                                    status="failure",
                                    stage="client_execution_report",
                                    metadata=ToolEventMetadata(
                                        event="client_tool_failure",
                                        tool_id=tool_use_id,
                                        content_type=content_type,
                                        content_length=content_length,
                                        tool_name_found=bool(tool_name),
                                    ),
                                )
                            )


def _find_tool_use_info(messages, current_msg, tool_use_id) -> tuple[str | None, dict[str, Any] | None]:
    """Find tool name and input parameters from message history."""
    current_idx = messages.index(current_msg)

    for i in range(current_idx - 1, -1, -1):
        prev_msg = messages[i]
        if prev_msg.role == "assistant" and isinstance(prev_msg.content, list):
            for block in prev_msg.content:
                if (
                    hasattr(block, "type")
                    and block.type == "tool_use"
                    and hasattr(block, "id")
                    and block.id == tool_use_id
                ):
                    return (
                        getattr(block, "name", None),
                        getattr(block, "input", None),
                    )
    return None, None


def find_available_port(start_port: int, max_attempts: int = 10) -> int:
    """Find an available port starting from start_port."""
    try:
        return _find_available_loopback_port(start_port, max_attempts)
    except NoAvailablePortError:
        raise RuntimeError(f"Could not find available port in range {start_port}-{start_port + max_attempts}") from None


@click.command()
@click.option(
    "--template",
    type=str,
    required=True,
    help="Configuration template to use (e.g., openrouter-gemini, openrouter-openai, openrouter-anthropic)",
)
@click.option("--port", type=int, default=8082, help="Port to run the server on (default: 8082)")
@click.option(
    "--host",
    default="127.0.0.1",
    help="Host to bind the server to (default: 127.0.0.1)",
)
@click.option("--reload", is_flag=True, help="Enable auto-reload on code changes")
@click.option(
    "--auto-port",
    is_flag=True,
    help="Automatically find an available port if the specified port is in use",
)
@click.option(
    "--proxy-id",
    type=str,
    required=False,
    help="Explicit proxy id (enables proxy-scoped overrides + strict startup validation).",
)
def main(
    template: str,
    port: int,
    host: str,
    reload: bool,
    auto_port: bool,
    proxy_id: str | None,
):
    """Start the Unified LLM Proxy server with template-based configuration.

    Template configurations are defined in YAML files under config/defaults/templates/.
    Each template specifies:
    - Provider (gemini, openai, litellm)
    - Model tier mappings (haiku, sonnet, opus)
    - Provider-specific settings (reasoning effort, cache TTL, etc.)
    """
    import os

    from forge.config.loader import template_exists

    # When a proxy id is supplied, proxy.yaml is authoritative (init_config ignores the
    # template), so don't hard-gate on template existence — a proxy created from a user
    # template that isn't shipped in this environment (e.g. a sidecar) must still start.
    if proxy_id is None and not template_exists(template):
        click.echo(f"Unknown template '{template}'")
        click.echo("Run 'forge proxy template list' to see available templates.")
        sys.exit(1)

    level = get_effective_log_level()
    if level != "off":
        configure_debug_logging(component="proxy", subdirectory="proxy")
        configure_console_logging()

    effective_proxy_id = proxy_id

    try:
        cfg = init_config(template=template, proxy_id=effective_proxy_id)
        provider = cfg.proxy.preferred_provider
        default_port = cfg.proxy.default_port

        if not provider:
            click.echo(f"✘ Template '{template}' missing 'preferred_provider' field")
            sys.exit(1)

    except Exception as e:
        click.echo(f"✘ Failed to load template '{template}': {e}")
        sys.exit(1)

    if default_port and default_port != port:
        click.echo(
            f"⚠︎  Warning: Template '{template}' typically uses port {default_port}, but starting on port {port}"
        )
        click.echo(f" Recommended: python -m forge.proxy.server --template {template} --port {default_port}")

    actual_port = port
    if auto_port:
        if effective_proxy_id is not None:
            click.echo("✘ --auto-port cannot be used when starting under a proxy id")
            sys.exit(1)

        actual_port = find_available_port(port)
        if actual_port != port:
            click.echo(f"⚠︎  Port {port} is in use, using port {actual_port} instead")
    else:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
                sock.close()
            except OSError:
                click.echo(f"✘ Port {port} is already in use!")
                click.echo(" Use --auto-port to automatically find an available port")
                sys.exit(1)

    # Strict proxy startup validation (B2.1.3). Skipped in sidecar mode — see
    # _sidecar_mode_active(): the host registry isn't in the container and the port
    # is fixed, so the registry/port cross-check can't hold; proxy.yaml is mounted.
    if effective_proxy_id is not None and not _sidecar_mode_active():
        from forge.proxy.proxy_startup import (
            ProxyStartupContext,
            ProxyStartupValidationError,
            validate_proxy_startup,
        )

        try:
            validate_proxy_startup(
                ctx=ProxyStartupContext(proxy_id=effective_proxy_id, template=template, port=actual_port)
            )

        except ProxyStartupValidationError as e:
            click.echo(f"✘ {e}")
            sys.exit(1)
        except Exception as e:
            click.echo(f"✘ Failed to validate proxy startup: {e}")
            sys.exit(1)

    # Track which template is active (for runtime introspection)
    # Set ACTIVE_PORT to actual_port (not port) to handle --auto-port correctly
    os.environ["ACTIVE_TEMPLATE"] = template
    os.environ["ACTIVE_PORT"] = str(actual_port)
    os.environ["PREFERRED_PROVIDER"] = provider

    # Freeze proxy id for request handlers. Set in env so the uvicorn worker
    # (which reimports the module when app is passed as a string) picks it up.
    global PROXY_ID
    PROXY_ID = effective_proxy_id
    if effective_proxy_id is not None:
        os.environ["FORGE_PROXY_ID"] = effective_proxy_id

    # Initialize in this module for direct/app-object runs; the imported
    # uvicorn app module initializes itself lazily via _ensure_runtime_state().
    _initialize_cost_tracker_from_config()

    provider_cfg = cfg.proxy.get_provider(provider)
    tier_models = {
        "haiku": provider_cfg.tiers.haiku,
        "sonnet": provider_cfg.tiers.sonnet,
        "opus": provider_cfg.tiers.opus,
    }

    click.echo("")
    click.echo("╔══════════════════════════════════════╗")
    click.echo("║     Unified LLM Proxy Server         ║")
    click.echo("╚══════════════════════════════════════╝")
    click.echo("")
    click.echo(f"🌐 Server:    http://{host}:{actual_port}")
    click.echo(f" Template:  {template}")
    click.echo(f"📡 Provider:  {provider}")
    click.echo(f" Log Level: {level}")
    click.echo(f"🔄 Reload:    {'enabled' if reload else 'disabled'}")
    click.echo("")
    click.echo(" Model Tier Mappings:")
    for tier, model in tier_models.items():
        if model:
            click.echo(f"   {tier.capitalize():6} → {model}")
    click.echo("")

    click.echo("  Provider Settings:")
    click.echo(f"   cache_ttl: {provider_cfg.cache_ttl}")
    if provider_cfg.base_url:
        click.echo(f"   base_url: {provider_cfg.base_url}")
    click.echo("")

    if effective_proxy_id is not None:
        click.echo(f" Proxy: ~/.forge/proxies/{effective_proxy_id}/proxy.yaml")
    else:
        click.echo(f" Template: defaults/templates/{template}.yaml")
    click.echo("")
    click.echo("Press CTRL+C to stop the server")
    click.echo("")

    uvicorn_level = {
        "off": "warning",
        "debug": "debug",
        "info": "info",
        "warning": "warning",
    }.get(level, "warning")

    uvicorn.run(
        "forge.proxy.server:app",
        host=host,
        port=actual_port,
        log_level=uvicorn_level,
        reload=reload,
    )


if __name__ == "__main__":
    main()

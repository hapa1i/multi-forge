"""
Unified LLM Proxy Server - Anthropic-compatible API for multiple providers.

This FastAPI server provides an Anthropic Messages API-compatible interface for
LLM providers via LiteLLM.

The server uses a unified client architecture where provider-specific logic is
encapsulated in client implementations that inherit from AbstractLLMClient.
This design ensures consistent behavior across providers while keeping the
server code clean and maintainable.

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
from json import JSONDecodeError
from typing import Any

import click
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from forge.config import TierOverride, config, init_config, reload
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
    is_valid_label,
    is_valid_provider_session_id,
    is_valid_run_id,
)
from forge.core.usage.vocabulary import Confidence, Reporter
from forge.proxy.base_client import ProxyStreamError, ToolCallError
from forge.proxy.client_factory import TierClientFactory
from forge.proxy.converters import (
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
from forge.proxy.utils import (
    log_request_beautifully,
    log_request_response,
    log_tool_event,
    log_tool_failure,
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
        cost_tracker.bootstrap_from_logs(get_forge_home() / "costs" / "requests", proxy_id=PROXY_ID)
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


_audit_pruned = False


def _maybe_prune_audit_logs() -> None:
    """Enforce audit retention once per process (best-effort) once config is loaded."""
    global _audit_pruned
    if _audit_pruned:
        return
    _audit_pruned = True
    audit = getattr(config.proxy, "audit", None)
    if audit is None:
        return
    try:
        from forge.proxy.audit_logger import prune_audit_logs

        prune_audit_logs(retention_days=audit.retention_days, max_total_mb=audit.max_total_mb)
    except Exception as e:
        logger.debug("audit prune skipped: %s", e)


def _ensure_runtime_state() -> None:
    """Ensure the imported app module has proxy config and runtime trackers."""
    if PROXY_ID is None:
        reload()
    elif not config.proxy.active_template:
        reload(proxy_id=PROXY_ID)

    _initialize_cost_tracker_from_config()
    _maybe_prune_audit_logs()


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


def _forge_run_ids(request: Request) -> tuple[str | None, str | None]:
    """The validated ``(forge_run_id, forge_root_run_id)`` the middleware stored."""
    state = request.state
    return getattr(state, "forge_run_id", None), getattr(state, "forge_root_run_id", None)


def _forge_session_command(request: Request) -> tuple[str | None, str | None]:
    """The validated ``(forge_session, forge_command)`` the middleware stored (Phase 1)."""
    state = request.state
    return getattr(state, "forge_session", None), getattr(state, "forge_command", None)


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


def _resolve_model_with_alternatives(tier: str, original_model_name: str | None, fallback_model: str) -> str:
    """Resolve backend model, checking per-tier alternatives before the tier default.

    Used by both message routing and token counting so model resolution is
    consistent across both paths.  Strips ``[1m]`` context-window suffix before
    lookup since it is a Claude Code hint, not a routing decision.
    """
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    logger.info("Server started...")
    yield
    logger.info("Server is shutting down... Cleaning up resources")


app = FastAPI(title="Unified LLM Proxy", lifespan=lifespan)


# --- Thinking → reasoning_effort translation ---
# Claude Code sends Anthropic-specific `thinking` config; litellm uses
# `reasoning_effort` which it translates per provider (Gemini 3: thinking_level,
# Gemini 2.5: thinkingBudget). These helpers map between the two.

# Ordered from lowest to highest so we can compare with max().
_EFFORT_RANK: dict[str | None, int] = {
    None: -1,
    "none": 0,
    "disable": 0,
    "minimal": 1,
    "low": 2,
    "medium": 3,
    "high": 4,
    "xhigh": 5,
}

# Budget thresholds for ceil-to-tier mapping (never downgrade).
# Checked top-down; first match wins.  LiteLLM internal budgets for
# reference: low ~ 1,024, medium ~ 8,192, high ~ 24,576.
_BUDGET_THRESHOLDS: list[tuple[int, str]] = [
    (25_000, "xhigh"),  # >=25k tokens -> xhigh (above litellm high)
    (10_000, "high"),  # >=10k tokens -> high
    (2_000, "medium"),  # >=2k tokens  -> medium
    (500, "low"),  # >=500 tokens -> low
    (1, "minimal"),  # >=1 token    -> minimal
]

# Type-based fallback when budget_tokens is absent.
_TYPE_TO_EFFORT: dict[str, str] = {
    "enabled": "high",
    "adaptive": "medium",
    "disabled": "none",
}


def _derive_reasoning_effort(thinking: dict[str, object] | object | None) -> str | None:
    """Derive reasoning_effort from Claude Code's thinking config.

    Priority: budget_tokens (numeric, precise) > type (semantic label).
    Unknown types default to "medium" (safe — never results in no reasoning).
    """
    if not isinstance(thinking, dict):
        return None

    # 1) Use budget_tokens if present — data-driven, not label-driven.
    budget = thinking.get("budget_tokens")
    if isinstance(budget, (int, float)) and budget > 0:
        for threshold, effort in _BUDGET_THRESHOLDS:
            if budget >= threshold:
                return effort
        return "minimal"  # budget_tokens in (0, 1) — fractional edge case

    # 2) Fall back to type-based mapping.
    thinking_type = thinking.get("type")
    if isinstance(thinking_type, str):
        mapped: str | None = _TYPE_TO_EFFORT.get(thinking_type)
        if mapped is not None:
            return mapped
        # Unknown type — default to medium (safe), log warning.
        logger.warning(
            "Unknown thinking type '%s', defaulting to reasoning_effort='medium'",
            thinking_type,
        )
        return "medium"

    return None


def _max_effort(a: str | None, b: str | None) -> str | None:
    """Return the higher of two reasoning_effort levels, treating None as unset."""
    if a is None:
        return b
    if b is None:
        return a
    return a if _EFFORT_RANK.get(a, 3) >= _EFFORT_RANK.get(b, 3) else b


def _thinking_summary(thinking: object) -> dict[str, object] | None:
    if not isinstance(thinking, dict):
        return None
    return {"type": thinking.get("type"), "budget_tokens": thinking.get("budget_tokens")}


def _inspect_route() -> dict[str, Any]:
    return {
        "template": getattr(config.proxy, "active_template", ""),
        "provider": getattr(config.proxy, "preferred_provider", ""),
        "wire_shape": getattr(config.proxy, "wire_shape", "openai_translated"),
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
            proxy_id=proxy_id, dimension="system_prompt", current_hash=sys_hash, request_id=request_id, route=route
        )
        audit_logger.check_and_record_drift(
            proxy_id=proxy_id, dimension="tool_surface", current_hash=tool_hash, request_id=request_id, route=route
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
            )
    except Exception as e:
        logger.debug("[%s] inspect persist skipped: %s", request_id, e)


async def _observe_request_side(
    body: dict[str, Any], request_id: str, *, headers: dict[str, str] | None = None, defer_full_body: bool = False
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
            "route": _inspect_route(),
            "mode": intercept.mode,
            "sys_hash": audit_logger.hash_system_prompt(body.get("system")),
            "tool_hash": audit_logger.hash_tool_surface(body.get("tools")),
            "counts": {"num_messages": len(body.get("messages") or []), "num_tools": len(body.get("tools") or [])},
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
    name = (model or "").lower()
    for tier in ("haiku", "sonnet", "opus"):
        if tier in name:
            return tier
    # Fable carries no tier word of its own; it rides the opus tier.
    if "fable" in name:
        return "opus"
    return None


async def _apply_passthrough_override(
    raw_body: dict[str, Any], request_id: str, resolved_tier: str, ctx: dict[str, Any] | None
) -> JSONResponse | None:
    """Apply override mutations to the raw body and write a mutation record.

    Returns a 403 JSONResponse when a guard blocks the request (caller returns it),
    else None (continue forwarding the possibly-mutated body). The mutation-safety
    RuntimeError is intentionally NOT caught — it must fail closed (no forward).
    """
    from forge.proxy import audit_logger, intercept

    intercept_cfg = config.proxy.intercept
    override_cfg = getattr(intercept_cfg, "override", None)
    tier_override = _get_tier_override(resolved_tier)
    reasoning_floor = getattr(tier_override, "reasoning_effort", None) if tier_override else None
    route = (ctx or {}).get("route") or _inspect_route()
    proxy_id = PROXY_ID or "unknown"

    result = intercept.apply_override(
        raw_body,
        system_prompt_augment=getattr(override_cfg, "system_prompt_augment", "") if override_cfg else "",
        system_prompt_guards=getattr(override_cfg, "system_prompt_guards", []) if override_cfg else [],
        reasoning_floor_effort=reasoning_floor,
    )
    for warning in result.warnings:
        logger.warning("[%s] override: %s", request_id, warning)
    if result.mutation_record is not None:
        try:
            # Offload the JSONL write off the event loop (parity with inspect persistence).
            await asyncio.to_thread(
                audit_logger.write_mutation_record,
                request_id=request_id,
                proxy_id=proxy_id,
                route=route,
                mutation=result.mutation_record,
            )
        except Exception as e:
            logger.debug("[%s] mutation record skipped: %s", request_id, e)
    if result.blocked:
        return JSONResponse(
            status_code=403,
            content={"type": "error", "error": {"type": "intercept_guard_blocked", "message": result.blocked_reason}},
            headers={"X-Request-ID": request_id},
        )
    return None


async def _handle_anthropic_passthrough(raw_request: Request, request_id: str, *, path: str = "/v1/messages"):
    """Forward a raw Anthropic request upstream without the OpenAI translation.

    Used when the proxy's wire_shape is 'anthropic_passthrough'. Reads the raw
    body (not the parsed MessagesRequest, which drops unknown fields) so thinking
    blocks and unknown/future fields survive byte-for-byte. Spend caps, cost
    logging, metrics, and audit all run here so a passthrough proxy is a
    first-class accounted path rather than an unmetered side door.
    """
    from forge.core.auth.template_secrets import resolve_env_or_credential
    from forge.proxy.passthrough import forward

    start_time = time.time()
    forge_run_id, forge_root_run_id = _forge_run_ids(raw_request)  # Slice 4g run-tree correlation

    base_url = config.proxy.get_provider().base_url
    if not base_url:
        return JSONResponse(
            status_code=500,
            content={
                "type": "error",
                "error": {"type": "configuration_error", "message": "passthrough upstream base_url is not configured"},
            },
            headers={"X-Request-ID": request_id},
        )

    api_key = resolve_env_or_credential("ANTHROPIC_API_KEY")
    if not api_key:
        return JSONResponse(
            status_code=401,
            content={
                "type": "error",
                "error": {
                    "type": "authentication_error",
                    "message": "ANTHROPIC_API_KEY is not configured for passthrough",
                },
            },
            headers={"X-Request-ID": request_id},
        )

    try:
        raw_body = await raw_request.json()
    except (JSONDecodeError, ValueError):
        return JSONResponse(
            status_code=400,
            content={
                "type": "error",
                "error": {"type": "invalid_request_error", "message": "Request body must be valid JSON"},
            },
            headers={"X-Request-ID": request_id},
        )

    if not isinstance(raw_body, dict):
        return JSONResponse(
            status_code=422,
            content={
                "type": "error",
                "error": {"type": "invalid_request_error", "message": "Request body must be a JSON object"},
            },
            headers={"X-Request-ID": request_id},
        )

    # count_tokens carries no generation/usage: forward only (no caps/cost/audit, and
    # intentionally no override — the preflight estimate omits augment/reasoning-pin
    # deltas; the real /v1/messages call applies them).
    if path != "/v1/messages":
        return await forward(
            raw_body=raw_body,
            inbound_headers=raw_request.headers,
            base_url=base_url,
            api_key=api_key,
            request_id=request_id,
            path=path,
        )

    model = str(raw_body.get("model") or "unknown")
    # Prefer the request's explicit tier (from the model name) over the proxy default,
    # so tier_overrides.<tier> (e.g. reasoning_effort) match an explicit opus request.
    resolved_tier = _tier_from_model_name(model) or getattr(config.proxy, "default_tier", None) or "sonnet"
    req_headers = dict(raw_request.headers)

    # Spend-cap check — same cross-request accumulation as the translated path, so caps
    # configured on a passthrough proxy are enforced, not silently ignored.
    spend_warning: str | None = None
    if cost_tracker is not None and cost_tracker.has_caps:
        cap_result = cost_tracker.check_cap()
        if cap_result.exceeded:
            spend_warning = _cap_result_message(cap_result)
            if cost_tracker.on_cap_hit == "reject":
                return JSONResponse(
                    status_code=429,
                    content={"type": "error", "error": {"type": "spend_cap_exceeded", "message": spend_warning}},
                    headers=_with_spend_warning({"X-Request-ID": request_id}, spend_warning),
                )
            logger.warning("[%s] %s", request_id, spend_warning)

    # Request-side observation; full-body capture is deferred to on_complete so the
    # record can include the redacted response rather than overclaiming request-only.
    ctx = await _observe_request_side(raw_body, request_id, headers=req_headers, defer_full_body=True)

    # Override mode: mutate current-request control surfaces (system prompt + thinking)
    # AFTER the inspect record, BEFORE forwarding. Signature-safe — historical messages
    # are never touched. A guard block short-circuits with a 403.
    _intercept = getattr(config.proxy, "intercept", None)
    if _intercept is not None and getattr(_intercept, "mode", "passthrough") == "override":
        blocked_response = await _apply_passthrough_override(raw_body, request_id, resolved_tier, ctx)
        if blocked_response is not None:
            return blocked_response

    streaming = bool(raw_body.get("stream"))

    def _on_complete(usage: dict[str, int], response_body: dict[str, Any] | None, failed: bool) -> None:
        elapsed = (time.time() - start_time) * 1000
        in_tok, out_tok, cache_tok = (
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
            usage.get("cached_tokens", 0),
        )
        cost = _calc_and_log_cost(
            model=model,
            tier=resolved_tier,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cached_tokens=cache_tok,
            latency_ms=elapsed,
            failed=failed,
            request_id=request_id,
            forge_run_id=forge_run_id,
            forge_root_run_id=forge_root_run_id,
        )
        proxy_metrics.record_request(
            tier=resolved_tier,
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cached_tokens=cache_tok,
            latency_ms=elapsed,
            streaming=streaming,
            failed=failed,
            error_type=None,
            cost_micros=cost,
        )
        if ctx is not None and ctx.get("full_body"):
            try:
                from forge.proxy import audit_logger

                # Recompute hashes from the body being logged: under override the
                # forwarded body is mutated, so ctx's pre-mutation hashes would make
                # the row internally inconsistent (mutated body, stale hash).
                audit_logger.write_full_body_record(
                    request_id=request_id,
                    proxy_id=ctx["proxy_id"],
                    mode=ctx["mode"],
                    route=ctx["route"],
                    request_headers=req_headers,
                    request_body=raw_body,
                    response_headers=None,
                    response_body=response_body,
                    redact_header_names=ctx["redact_headers"],
                    system_prompt_hash=audit_logger.hash_system_prompt(raw_body.get("system")),
                    tool_surface_hash=audit_logger.hash_tool_surface(raw_body.get("tools")),
                    counts=ctx["counts"],
                    thinking=_thinking_summary(raw_body.get("thinking")),
                )
            except Exception as e:
                logger.debug("[%s] passthrough full-body audit skipped: %s", request_id, e)

    extra_headers = _with_spend_warning(
        {
            "X-Resolved-Model": model,
            "X-Resolved-Tier": resolved_tier,
            **_cumulative_cost_header(),
        },
        spend_warning,
    )

    return await forward(
        raw_body=raw_body,
        inbound_headers=raw_request.headers,
        base_url=base_url,
        api_key=api_key,
        request_id=request_id,
        path=path,
        on_complete=_on_complete,
        extra_headers=extra_headers,
    )


@app.post("/v1/messages", response_model=None)
async def create_message(request_data: MessagesRequest, raw_request: Request):
    """
    Process chat completion requests using unified client architecture.

    This endpoint handles both streaming and non-streaming responses,
    automatically routing to the appropriate provider based on model name.
    """
    request_id = raw_request.state.request_id
    forge_run_id, forge_root_run_id = _forge_run_ids(raw_request)  # Slice 4g run-tree correlation
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

    # Resolve effective tier (routing invariants):
    # Precedence: request explicit tier > config.proxy.default_tier
    # If neither is available, fail fast (misconfiguration).
    if request_data.has_explicit_tier and request_data.tier:
        # Request explicitly specified a tier (haiku/sonnet/opus in model name)
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

    logger.debug(f"[{request_id}] Resolved tier: {resolved_tier} (source={resolved_tier_source})")

    request_data.tier = resolved_tier

    # Determine if this is an explicit backend model or needs tier-based resolution
    # Only re-resolve model based on tier if:
    #   1. Model was mapped from Anthropic-style (contains haiku/sonnet/opus), OR
    #   2. Model is truly ambiguous (no provider prefix and not a known backend model)
    # Do NOT override explicit backend models like "openai/gpt-5.5" or "vertex_ai/gemini-3.1-pro"
    original_model_name = request_data.original_model_name
    mapped_model = map_model_name(request_data.model)  # Map AFTER reload() for fresh config

    # Check if original model is an explicit backend model (has provider prefix)
    # These should be passed through, not tier-resolved
    if config.proxy.preferred_provider == "openrouter":
        # OpenRouter: any provider/model format is explicit (google/, meta-llama/, etc.)
        is_explicit_backend = original_model_name is not None and "/" in original_model_name
    else:
        is_explicit_backend = (
            original_model_name is not None
            and "/" in original_model_name
            and any(
                original_model_name.startswith(prefix)
                for prefix in [
                    "openai/",
                    "anthropic/",
                    "vertex_ai/",
                    "bedrock/",
                    "gemini/",
                    "together_ai/",
                    "replicate/",
                ]
            )
        )

    # Only use tier-resolved model for Anthropic-style or ambiguous requests
    # For explicit backend models, use what map_model_name() returned (usually pass-through)
    if is_explicit_backend:
        # Explicit backend model - preserve it (map_model_name already handled it)
        actual_model_id = mapped_model
        logger.debug(
            f"[{request_id}] Explicit backend model '{original_model_name}' - preserving as '{actual_model_id}'"
        )
    else:
        # Anthropic-style or ambiguous — check alternatives, then fall back to tier default
        tier_default = config.proxy.get_model_for_tier(resolved_tier)
        actual_model_id = _resolve_model_with_alternatives(resolved_tier, original_model_name, tier_default)
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

        openai_request_dict = convert_anthropic_to_openai(request_data, provider=provider_name)

        openai_request_dict["model"] = actual_model_id

        # Forward User-Agent from incoming request (Claude Code identity).
        # Upstream LLM gateways may filter traffic by User-Agent; without this,
        # the proxy's OpenAI SDK default header could cause requests to be blocked.
        # Only inject for LiteLLM providers (other clients don't need it).
        if provider_name in ("litellm_remote", "litellm_local", "openrouter"):
            incoming_user_agent = raw_request.headers.get("user-agent")
            if incoming_user_agent:
                openai_request_dict["_user_agent"] = incoming_user_agent
                logger.debug(f"[{request_id}] Forwarding User-Agent: {incoming_user_agent[:120]!r}")

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
        # tier_override acts as a FLOOR (never go below the user's tier config).
        # Use getattr() for test stubs that don't include new fields.
        reasoning_effort = getattr(request_data, "reasoning_effort", None)
        if reasoning_effort is not None:
            openai_request_dict["reasoning_effort"] = reasoning_effort
        else:
            # Claude Code sends `thinking` (Anthropic-specific) instead of
            # `reasoning_effort`. Translate to reasoning_effort so litellm can
            # map it to each provider's native parameter.
            thinking = getattr(request_data, "thinking", None)
            derived = _derive_reasoning_effort(thinking)

            # Apply tier_override as a floor: max(derived, tier_override).
            tier_effort = tier_override.reasoning_effort if tier_override else None
            openai_request_dict["reasoning_effort"] = _max_effort(derived, tier_effort)

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
            client = await client_factory.get_client(actual_model_id, tier=request_data.tier)
            logger.debug(f"[{request_id}] Got client for {actual_model_id} (tier={request_data.tier})")
        except AuthenticationError as e:
            logger.error(f"[{request_id}] Authentication failed: {e}")
            raise HTTPException(
                status_code=401,
                detail={
                    "type": "authentication_error",
                    "message": f"Authentication failed [{request_id}]",
                },
            )

        if request_data.stream:
            # Streaming response
            async def stream_generator():
                try:
                    async for chunk in client.create_streaming_completion(openai_request_dict, request_id):
                        yield chunk
                except ToolCallError as e:
                    logger.error(f"[{request_id}] ToolCallError: {e}")
                    yield {
                        "error": {
                            "type": e.error_type,
                            "message": f"Tool call error [{request_id}]",
                        }
                    }
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

            def _on_stream_complete(usage: dict[str, int], failed: bool, error_type: str | None) -> None:
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

            return StreamingResponse(
                convert_openai_to_anthropic_sse(
                    stream_generator(),
                    request_data,
                    request_id,
                    on_complete=_on_stream_complete,
                ),
                media_type="text/event-stream",
                headers=headers,
            )
        else:
            try:
                openai_response = await client.create_completion(openai_request_dict, request_id)
                anthropic_response = convert_openai_to_anthropic(openai_response, original_model_name)

                if not anthropic_response:
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "type": "api_error",
                            "message": "Failed to convert response",
                        },
                    )

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

                asyncio.create_task(
                    log_request_response(
                        request_id=request_id,
                        original_model=original_model_name or "",
                        mapped_model=actual_model_id,
                        request_body=request_data.model_dump(),
                        response_body=response_dict,
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

            except ToolCallError as e:
                duration_ms = (time.time() - start_time) * 1000
                error_msg = str(e)

                _tc_cost = _calc_and_log_cost(
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
                )
                proxy_metrics.record_request(
                    tier=resolved_tier,
                    model=actual_model_id,
                    input_tokens=0,
                    output_tokens=0,
                    cached_tokens=0,
                    latency_ms=duration_ms,
                    streaming=False,
                    failed=True,
                    error_type="tool_call_error",
                    cost_micros=_tc_cost,
                )

                asyncio.create_task(
                    log_request_response(
                        request_id=request_id,
                        original_model=original_model_name or "",
                        mapped_model=actual_model_id,
                        request_body=request_data.model_dump(),
                        response_body=None,
                        status_code=400,
                        duration_ms=duration_ms,
                        error=error_msg,
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
                    status_code=400,
                )

                logger.error(f"[{request_id}] Tool call error: {e}")
                raise HTTPException(
                    status_code=400,
                    detail={"type": "invalid_request_error", "message": error_msg},
                )
            except AuthenticationError:
                # Try refreshing credentials once
                logger.warning(f"[{request_id}] Auth failed, refreshing credentials")
                client = await client_factory.invalidate_and_retry(actual_model_id)
                openai_response = await client.create_completion(openai_request_dict, request_id)
                anthropic_response = convert_openai_to_anthropic(openai_response, original_model_name)

                if not anthropic_response:
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "type": "api_error",
                            "message": "Failed to convert response after retry",
                        },
                    )

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

        # Resolve tier FIRST (same precedence as message routing)
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

        # Match the /v1/messages model resolution: explicit backend models are
        # preserved; Anthropic-style or ambiguous models go through tier + alternatives.
        mapped_model = map_model_name(request_data.model)

        if config.proxy.preferred_provider == "openrouter":
            is_explicit_backend = original_model_name is not None and "/" in original_model_name
        else:
            is_explicit_backend = (
                original_model_name is not None
                and "/" in original_model_name
                and any(
                    original_model_name.startswith(p)
                    for p in [
                        "openai/",
                        "anthropic/",
                        "vertex_ai/",
                        "bedrock/",
                        "gemini/",
                        "together_ai/",
                        "replicate/",
                    ]
                )
            )

        if is_explicit_backend:
            actual_model_id = mapped_model
        else:
            tier_default = config.proxy.get_model_for_tier(resolved_tier)
            actual_model_id = _resolve_model_with_alternatives(resolved_tier, original_model_name, tier_default)

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
            detail={"type": "api_error", "message": f"Token counting failed [{request_id}]"},
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
    _wire_shape = getattr(config.proxy, "wire_shape", "openai_translated")
    _intercept_cfg = getattr(config.proxy, "intercept", None)
    _intercept_mode = _intercept_cfg.mode if _intercept_cfg is not None else "passthrough"
    _audit_cfg = getattr(config.proxy, "audit", None)
    intercept_section = {
        "mode": _intercept_mode,
        "wire_shape": _wire_shape,
        "thinking_blocks_preserved": _wire_shape == "anthropic_passthrough",
        "can_inspect": {
            "system_prompt": _intercept_mode in ("inspect", "override"),
            "drift_detection": _intercept_mode in ("inspect", "override"),
            "override": _intercept_mode == "override",
            "full_body_audit": bool(getattr(_audit_cfg, "audit_full_body", False)),
        },
    }

    # Per-proxy metrics (request counts, token usage, latency); spend-cap
    # proximity is attached under metrics.costs.caps when caps are configured.
    metrics_snapshot = proxy_metrics.snapshot()
    _attach_cap_summary(metrics_snapshot, cost_tracker)

    response = {
        "is_proxy": True,
        "template": active_template,
        "provider": preferred_provider,
        # Wire shape is the authoritative wire truth; provider may be a config slot
        # (e.g. anthropic-passthrough uses provider=litellm). See Phase 2 audit proxy.
        "wire_shape": _wire_shape,
        "intercept_mode": _intercept_mode,
        "intercept": intercept_section,
        "tiers": tiers,
        "status": "running",
        "routing": routing_section,
        # Proxy identity (B2.1.5): first-class proxy identity
        "proxy": proxy_section,
        # Runtime truth: tier mappings, context windows, hyperparameter defaults
        "runtime": runtime_section,
        "metrics": metrics_snapshot,
    }

    return response


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

    request_id = request.headers.get("X-Request-ID") or f"{prefix}{uuid.uuid4().hex[:12]}"
    request.state.request_id = request_id

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
    if request.method == "POST" and path in ("/v1/messages", "/v1/messages/count_tokens"):
        try:
            _ensure_runtime_state()
            is_passthrough = getattr(config.proxy, "wire_shape", "openai_translated") == "anthropic_passthrough"
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
                        "error": {"type": "api_error", "message": f"Passthrough error [{request_id}]"},
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
            logger.info(f"{path} [{request_id}] Completed in {elapsed:.3f}s ({status})")

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

                        # Check if this is a stale cleared tool result (not actionable)
                        is_cleared_content = (
                            isinstance(error_content, str) and "Old tool result content cleared" in error_content
                        )

                        # Only log as warning if we have actual error content (not cleared)
                        if error_content and not is_cleared_content:
                            logger.warning(
                                f"[{request_id}] Client tool failure: "
                                f"tool='{tool_name or 'unknown'}', id='{tool_use_id}', "
                                f"error={str(error_content)[:100]}"
                            )
                        elif is_cleared_content:
                            logger.debug(
                                f"[{request_id}] Stale tool failure (content cleared): "
                                f"tool='{tool_name or 'unknown'}', id='{tool_use_id}'"
                            )
                        else:
                            # Debug log for investigation when is_error but no content
                            logger.debug(
                                f"[{request_id}] Tool marked as error but no error content: "
                                f"tool='{tool_name or 'unknown'}', id='{tool_use_id}', "
                                f"is_error={getattr(block, 'is_error', None)}"
                            )

                        enriched_content = error_content
                        if error_content and not is_cleared_content and isinstance(error_content, str):
                            provider_cfg = config.proxy.get_provider()
                            if provider_cfg.error_hints:
                                enriched_content = enrich_error_content(tool_name, error_content)
                                if enriched_content != error_content:
                                    block.content = enriched_content
                                    logger.debug(f"[{request_id}] Enriched error hint for tool '{tool_name}'")

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
                                    details={
                                        "tool_use_id": tool_use_id,
                                        "error_content": enriched_content,
                                        "tool_name_found": bool(tool_name),
                                    },
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
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                # Probe loopback only; proxies bind 127.0.0.1 by default.
                sock.bind(("127.0.0.1", port))
                sock.close()
                return port
            except OSError:
                continue
    raise RuntimeError(f"Could not find available port in range {start_port}-{start_port + max_attempts}")


@click.command()
@click.option(
    "--template",
    type=str,
    required=True,
    help="Configuration template to use (e.g., openrouter-gemini, openrouter-openai, openrouter-anthropic)",
)
@click.option("--port", type=int, default=8082, help="Port to run the server on (default: 8082)")
@click.option("--host", default="127.0.0.1", help="Host to bind the server to (default: 127.0.0.1)")
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

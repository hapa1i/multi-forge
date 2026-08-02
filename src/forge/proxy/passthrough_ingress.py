"""Anthropic-facing passthrough ingress: raw /v1/messages forwarding + accounting.

Server glue for the ``anthropic_passthrough`` wire shape -- the structural peer of
``responses_ingress.py``. It sits above the pure transport (``passthrough.py``) and
below the proxy's messages route/middleware, which dispatches here when the wire
shape is passthrough. It owns body validation, upstream-credential resolution, the
spend-cap + cost/metrics/audit accounting, override mutation, and provider-trace
forward-wiring. Handlers reach back into ``server`` for proxy runtime state
(config, cost tracker, metrics, run-id helpers) via a lazy import -- that read of
live singletons is exactly what the proxy needs, and the lazy import also avoids a
server<->ingress import cycle (server imports this module at load to bind the
handler name).
"""

from __future__ import annotations

import asyncio
import logging
import time
from json import JSONDecodeError
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


async def _apply_passthrough_override(
    raw_body: dict[str, Any],
    request_id: str,
    resolved_tier: str,
    ctx: dict[str, Any] | None,
) -> JSONResponse | None:
    """Apply override mutations to the raw body and write a mutation record.

    Returns a 403 JSONResponse when a guard blocks the request (caller returns it),
    else None (continue forwarding the possibly-mutated body). The mutation-safety
    RuntimeError is intentionally NOT caught — it must fail closed (no forward).
    """
    import forge.proxy.server as server
    from forge.proxy import audit_logger, intercept

    intercept_cfg = server.config.proxy.intercept
    override_cfg = getattr(intercept_cfg, "override", None)
    tier_override = server._get_tier_override(resolved_tier)
    reasoning_floor = getattr(tier_override, "reasoning_effort", None) if tier_override else None
    route = (ctx or {}).get("route") or server._inspect_route()
    proxy_id = server.PROXY_ID or "unknown"

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
                backend_id=server._backend_instance_id(),
            )
        except Exception as e:
            logger.debug("[%s] mutation record skipped: %s", request_id, e)
    if result.blocked:
        return JSONResponse(
            status_code=403,
            content={
                "type": "error",
                "error": {
                    "type": "intercept_guard_blocked",
                    "message": result.blocked_reason,
                },
            },
            headers={"X-Request-ID": request_id},
        )
    return None


async def handle_anthropic_passthrough(raw_request: Request, request_id: str, *, path: str = "/v1/messages"):
    """Forward a raw Anthropic request upstream without the OpenAI translation.

    Used when the proxy's wire_shape is 'anthropic_passthrough'. Reads the raw
    body (not the parsed MessagesRequest, which drops unknown fields) so thinking
    blocks and unknown/future fields survive byte-for-byte. Spend caps, cost
    logging, metrics, and audit all run here so a passthrough proxy is a
    first-class accounted path rather than an unmetered side door.
    """
    import forge.proxy.server as server
    from forge.core.auth.template_secrets import resolve_env_or_credential
    from forge.proxy.passthrough import forward

    start_time = time.time()
    downstream_event_id = getattr(raw_request.state, "downstream_event_id", None)
    forge_run_id, forge_root_run_id = server._forge_run_ids(raw_request)  # Slice 4g run-tree correlation
    forge_session, forge_command = server._forge_session_command(raw_request)  # Phase 3 provider-trace join keys

    base_url = server.config.proxy.get_provider().base_url
    if not base_url:
        return JSONResponse(
            status_code=500,
            content={
                "type": "error",
                "error": {
                    "type": "configuration_error",
                    "message": "passthrough upstream base_url is not configured",
                },
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
                "error": {
                    "type": "invalid_request_error",
                    "message": "Request body must be valid JSON",
                },
            },
            headers={"X-Request-ID": request_id},
        )

    if not isinstance(raw_body, dict):
        return JSONResponse(
            status_code=422,
            content={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "Request body must be a JSON object",
                },
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
    resolved_tier = (
        server._tier_from_model_name(model) or getattr(server.config.proxy, "default_tier", None) or "sonnet"
    )
    req_headers = dict(raw_request.headers)

    # Spend-cap check — same cross-request accumulation as the translated path, so caps
    # configured on a passthrough proxy are enforced, not silently ignored.
    spend_warning: str | None = None
    if server.cost_tracker is not None and server.cost_tracker.has_caps:
        cap_result = server.cost_tracker.check_cap()
        if cap_result.exceeded:
            spend_warning = server._cap_result_message(cap_result)
            if server.cost_tracker.on_cap_hit == "reject":
                return JSONResponse(
                    status_code=429,
                    content={
                        "type": "error",
                        "error": {
                            "type": "spend_cap_exceeded",
                            "message": spend_warning,
                        },
                    },
                    headers=server._with_spend_warning({"X-Request-ID": request_id}, spend_warning),
                )
            logger.warning("[%s] %s", request_id, spend_warning)

    # Request-side observation; full-body capture is deferred to on_complete so the
    # record can include the redacted response rather than overclaiming request-only.
    ctx = await server._observe_request_side(raw_body, request_id, headers=req_headers, defer_full_body=True)

    # Override mode: mutate current-request control surfaces (system prompt + thinking)
    # AFTER the inspect record, BEFORE forwarding. Signature-safe — historical messages
    # are never touched. A guard block short-circuits with a 403.
    _intercept = getattr(server.config.proxy, "intercept", None)
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
        cost = server._calc_and_log_cost(
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
            downstream_event_id=downstream_event_id,
        )
        server.proxy_metrics.record_request(
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
                    thinking=server._thinking_summary(raw_body.get("thinking")),
                    backend_id=ctx.get("backend_id"),
                )
            except Exception as e:
                logger.debug("[%s] passthrough full-body audit skipped: %s", request_id, e)

    extra_headers = server._with_spend_warning(
        {
            "X-Resolved-Model": model,
            "X-Resolved-Tier": resolved_tier,
            **server._cumulative_cost_header(),
        },
        spend_warning,
    )

    # Provider-trace forward-wiring: the passthrough relay mirrors stream lifecycle
    # into the same backend-capability-gated record_provider_trace helper.
    provider_trace_ctx = {
        "backend_id": server._backend_instance_id(),
        "proxy_id": server.PROXY_ID or "unknown",
        "mapped_model": model,
        "request_id": request_id,
        "forge_run_id": forge_run_id,
        "forge_root_run_id": forge_root_run_id,
        "provider_session_id": forge_session,
        "provider_command": forge_command,
        "downstream_event_id": downstream_event_id,
    }

    return await forward(
        raw_body=raw_body,
        inbound_headers=raw_request.headers,
        base_url=base_url,
        api_key=api_key,
        request_id=request_id,
        path=path,
        on_complete=_on_complete,
        extra_headers=extra_headers,
        provider_trace_ctx=provider_trace_ctx,
    )

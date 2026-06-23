"""Codex-facing OpenAI Responses ingress: FastAPI<->transport glue + capability advert.

Server glue for the ``openai_responses_passthrough`` wire shape. It sits above the
pure transport (``responses_passthrough.py``) and below the proxy routes: it owns the
capability gate, upstream-credential resolution, the spend-cap + accounting wiring
(generation endpoint only), the route registration, and the GET / advertisement
helpers. ``handle_responses_passthrough`` reaches back into ``server`` for proxy runtime
state (config, cost tracker, metrics, run-id helpers) via a lazy import -- that read of
live singletons is exactly what the proxy needs, and the lazy import also avoids a
server<->ingress import cycle (server imports this module at load to register routes).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from json import JSONDecodeError
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


def build_intercept_capability_section(wire_shape: str, intercept_mode: str, audit_full_body: bool) -> dict[str, Any]:
    """Compute GET /'s intercept truth table for one wire shape.

    Both passthrough shapes preserve signed reasoning byte-for-byte (Anthropic
    thinking blocks / Responses reasoning items). A byte-faithful Responses
    passthrough cannot inspect or override bodies, so its can_inspect is uniformly
    false even when intercept.mode is inspect/override.
    """
    is_responses_pt = wire_shape == "openai_responses_passthrough"
    return {
        "mode": intercept_mode,
        "wire_shape": wire_shape,
        "thinking_blocks_preserved": wire_shape in ("anthropic_passthrough", "openai_responses_passthrough"),
        "can_inspect": {
            "system_prompt": (not is_responses_pt) and intercept_mode in ("inspect", "override"),
            "drift_detection": (not is_responses_pt) and intercept_mode in ("inspect", "override"),
            "override": (not is_responses_pt) and intercept_mode == "override",
            "full_body_audit": (not is_responses_pt) and bool(audit_full_body),
        },
    }


def advertise_responses_ingress(wire_shape: str, source_id: str) -> bool:
    """Whether GET / advertises responses_ingress (Phase 4 launcher health-check).

    True only for the Responses passthrough wire shape backed by a source that
    declares the capability -- the same conjunction the /v1/responses route
    enforces, so the advertisement cannot promise an ingress the route then 501s.
    """
    if wire_shape != "openai_responses_passthrough" or not source_id:
        return False
    from forge.backend.sources import ModelSourceNotFoundError, get_model_source

    try:
        return get_model_source(source_id).capabilities.responses_ingress
    except ModelSourceNotFoundError:
        return False


async def handle_responses_passthrough(raw_request: Request, *, method: str, url_path: str) -> Response:
    """Forward a raw OpenAI Responses request to the Responses-capable upstream.

    Codex-facing ingress for ``forge codex start --proxy``. Gated on
    ``wire_shape == openai_responses_passthrough`` AND the source's
    ``responses_ingress`` capability -- the same conjunction the codex preflight
    mirrors, so a green preflight cannot 501 here. Reasoning items survive
    byte-for-byte (passthrough); body audit is structurally unavailable. The body
    is read only for POST -- bodyless GET/DELETE never call ``.json()``.
    """
    import forge.proxy.server as server
    from forge.backend.sources import (
        ModelSourceNotFoundError,
        get_model_source,
        source_bearer_auth_env_var,
    )
    from forge.core.auth.template_secrets import resolve_env_or_credential
    from forge.proxy.responses_passthrough import forward

    server._ensure_runtime_state()
    request_id = getattr(raw_request.state, "request_id", None) or uuid.uuid4().hex
    start_time = time.time()
    config = server.config  # proxy runtime config singleton

    def _error(status: int, etype: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={"type": "error", "error": {"type": etype, "message": message}},
            headers={"X-Request-ID": request_id},
        )

    # Capability gate = the runtime guard the codex preflight mirrors.
    wire_shape = getattr(config.proxy, "wire_shape", "openai_translated")
    source_id = getattr(config.proxy, "source", "") or ""
    source = None
    if wire_shape == "openai_responses_passthrough" and source_id:
        try:
            source = get_model_source(source_id)
        except ModelSourceNotFoundError:
            source = None
    if source is None or not source.capabilities.responses_ingress:
        return _error(
            501,
            "not_implemented",
            "This proxy is not Responses-capable (needs wire_shape=openai_responses_passthrough "
            "and a responses_ingress source). Run native 'codex' directly.",
        )

    base_url = config.proxy.get_provider().base_url
    if not base_url:
        return _error(500, "configuration_error", "responses passthrough upstream base_url is not configured")

    try:
        bearer_env = source_bearer_auth_env_var(source)
    except ValueError as e:  # ModelSourceCatalogError: ambiguous/missing bearer secret
        # Log the catalog detail (source id, env var names) server-side only; return a
        # generic message so the Codex client can't read internal config (CWE-209).
        logger.warning("[%s] responses passthrough bearer-secret resolution failed: %s", request_id, e)
        return _error(500, "configuration_error", "responses passthrough upstream credential is misconfigured")
    api_key = resolve_env_or_credential(bearer_env)
    if not api_key:
        return _error(401, "authentication_error", f"{bearer_env} is not configured for responses passthrough")

    # Body: POST only, parsed from raw bytes so bodyless GET/DELETE never read.
    body: dict[str, Any] | None = None
    if method == "POST":
        raw = await raw_request.body()
        if raw:
            try:
                parsed = json.loads(raw)
            except (JSONDecodeError, ValueError):
                return _error(400, "invalid_request_error", "Request body must be valid JSON")
            body = parsed if isinstance(parsed, dict) else None

    model = str(body.get("model")) if body and body.get("model") else "unknown"
    resolved_tier = getattr(config.proxy, "default_tier", None) or "sonnet"
    streaming = body is not None and bool(body.get("stream"))
    forge_run_id, forge_root_run_id = server._forge_run_ids(raw_request)
    forge_session, forge_command = server._forge_session_command(raw_request)
    downstream_event_id = getattr(raw_request.state, "downstream_event_id", None)

    # Account only for the billable generation endpoint — POST /v1/responses (create).
    # Retrieve/cancel/delete/input_items/compact either echo a prior response's usage
    # (so accounting double-counts tokens) or carry none (logging zero-token attempts);
    # the spend cap likewise governs new generations, not management of an existing run
    # (you must be able to cancel a run to STOP spending even while over cap).
    is_generation = method == "POST" and url_path == "/v1/responses"

    # Spend-cap check — same cross-request accumulation as the other accounted
    # paths, so caps configured on a Responses proxy reject rather than silently pass.
    tracker = server.cost_tracker
    spend_warning: str | None = None
    if is_generation and tracker is not None and tracker.has_caps:
        cap_result = tracker.check_cap()
        if cap_result.exceeded:
            spend_warning = server._cap_result_message(cap_result)
            if tracker.on_cap_hit == "reject":
                return JSONResponse(
                    status_code=429,
                    content={"type": "error", "error": {"type": "spend_cap_exceeded", "message": spend_warning}},
                    headers=server._with_spend_warning({"X-Request-ID": request_id}, spend_warning),
                )
            logger.warning("[%s] %s", request_id, spend_warning)

    def _on_complete(
        usage: dict[str, int], reported_cost_micros: int | None, failed: bool, error_type: str | None
    ) -> None:
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
            reported_cost_micros=reported_cost_micros,
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
            error_type=error_type,
            cost_micros=cost,
        )

    provider_trace_ctx = (
        {
            "backend_id": server._backend_source_id(),
            "proxy_id": server.PROXY_ID or "unknown",
            "mapped_model": model,
            "request_id": request_id,
            "forge_run_id": forge_run_id,
            "forge_root_run_id": forge_root_run_id,
            "provider_session_id": forge_session,
            "provider_command": forge_command,
            "downstream_event_id": downstream_event_id,
        }
        if is_generation
        else None
    )

    # Warn-mode caps forward the request but must still surface the cap message on the
    # response (design.md: warn mode returns it in X-Spend-Warning). reject mode already
    # returned 429 above, so a non-None spend_warning here is always warn mode.
    return await forward(
        method=method,
        url_path=url_path,
        body=body,
        query_string=raw_request.url.query,
        inbound_headers=raw_request.headers,
        base_url=base_url,
        api_key=api_key,
        request_id=request_id,
        on_complete=_on_complete if is_generation else None,
        provider_trace_ctx=provider_trace_ctx,
        extra_response_headers=server._with_spend_warning({}, spend_warning) or None,
    )


def register_responses_routes(app: FastAPI) -> None:
    """Register the Codex Responses routes: the exact create path before the catch-all.

    Registration order is load-bearing: ``POST /v1/responses`` (create) must precede the
    ``/v1/responses/{rest:path}`` catch-all so the create path always wins.
    """

    async def create_response(raw_request: Request) -> Response:
        """Codex-facing OpenAI Responses create (passthrough; streamed when stream=true)."""
        return await handle_responses_passthrough(raw_request, method="POST", url_path="/v1/responses")

    async def responses_subresource(rest: str, raw_request: Request) -> Response:
        """Codex Responses sub-surface: retrieve/cancel/input_items/delete/compact/input_tokens."""
        return await handle_responses_passthrough(
            raw_request, method=raw_request.method, url_path=f"/v1/responses/{rest}"
        )

    app.add_api_route("/v1/responses", create_response, methods=["POST"], response_model=None)
    app.add_api_route(
        "/v1/responses/{rest:path}",
        responses_subresource,
        methods=["GET", "POST", "DELETE"],
        response_model=None,
    )

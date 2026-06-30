"""Usage-ledger emission helpers (Phase 4c).

Thin adapters from Forge's existing cost/run signals to a :class:`UsageEvent`.
Two shapes:

- :func:`emit_usage_for_session_result` -- a ``claude -p`` verb (memory-writer,
  supervisor, curation, a workflow fan-out). Run identity comes from the
  ``SessionResult`` (stamped by ``build_claude_env`` in the child env), cost from
  the ``track_verb_cost`` holder. ``source_refs`` is null: the child originates
  its own proxy requests, so Forge can't know the proxy ``request_id`` (4g).
- :func:`emit_direct_llm_usage` -- a direct ``core.llm`` call (the tagger). Run
  identity is ambient (the spawner's env); tokens come from the provider's
  in-band ``usage``.

Both are best-effort and **depth-agnostic**: they never raise and are never gated
by ``FORGE_DEPTH`` (attribution must not depend on the recursion guard). When no
run identity is available there is nothing to attribute, so they no-op.

4d will route the review fan-out through ``HeadlessInvoker``; it reuses these same
helpers, so per-callsite wiring here does not become throwaway.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from forge.core.reactive.cost_tracking import VerbCostResult
from forge.core.reactive.env import get_run_identity
from forge.core.reactive.session_runner import SessionResult
from forge.core.telemetry.downstream import (
    DownstreamRecord,
    mint_downstream_event_id,
    write_downstream_record,
)
from forge.core.usage.billing import resolve_billing_mode
from forge.core.usage.ledger import (
    BillingMode,
    SourceRefs,
    UsageEvent,
    log_usage_event,
)
from forge.core.usage.measurement import (
    resolve_claude_p_measurement,
    resolve_codex_measurement,
    resolve_direct_llm_measurement,
)
from forge.core.usage.vocabulary import Confidence, Reporter

logger = logging.getLogger(__name__)


def _backend_id_for_direct_usage(*, provider: str | None, reporter: Reporter | None) -> str | None:
    if reporter == "claude_code":
        return "anthropic-direct"
    if provider == "anthropic":
        return "anthropic-direct"
    if provider == "openrouter":
        return "openrouter"
    return None


def _session_status(result: SessionResult) -> tuple[str, str | None]:
    """Map a SessionResult to (status, failure_type).

    A runtime-reported error (envelope ``is_error`` with exit 0) reads as
    ``error`` -- the run did not succeed even though the process exited cleanly.
    ``runtime_is_error`` is already is-error-reliable-gated upstream (Phase 5).
    """
    if result.success:
        if result.runtime_is_error:
            return "error", "runtime_reported_error"
        return "success", None
    if result.timed_out:
        return "timeout", "timeout"
    if result.error:
        return "error", "subprocess_error"
    return "error", f"exit_{result.returncode}"


def emit_usage_for_session_result(
    result: SessionResult,
    *,
    command: str,
    cost: VerbCostResult | None = None,
    session: str | None = None,
    workflow: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    direct: bool = False,
    backend_id: str | None = None,
    runtime: str = "claude_code",
) -> None:
    """Emit one verb-level UsageEvent for a completed ``run_claude_session`` call.

    No-ops when the result carries no run identity (nothing to attribute).
    ``cost`` is the ``track_verb_cost`` holder; an unmeasured holder (no proxy in
    the path) yields ``measurement_source="unattributed"`` with null cost rather
    than a fabricated $0. ``backend_id`` is the run's bound consumer-lane backend
    (or None): a keyless direct run on a subscription-posture backend is billed as
    that subscription mode (see ``resolve_billing_mode``).
    """
    try:
        if not result.run_id:
            return
        status, failure_type = _session_status(result)

        # Cost-provenance precedence (Phase 5). EXACTLY ONE reporter attributes cost
        # per run: forge_proxy (proxied) XOR claude_code (direct self-report) XOR none.
        proxied = bool(base_url)
        # #1: a parsed envelope can carry tokens with NO cost (direct OAuth) -> gate the
        # self-reported cost on envelope_parsed, not on cost presence.
        self_cost = result.cost_micro_usd if result.envelope_parsed else None
        measurement = resolve_claude_p_measurement(
            caller="verb",
            proxied=proxied,
            cost=cost,
            self_cost=self_cost,
            envelope_parsed=result.envelope_parsed,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cached_tokens=result.cached_tokens,
        )

        # "Direct" for billing only when no proxy is in the path; a proxied call's
        # upstream billing is opaque from here, so it stays "unknown".
        effective_direct = direct and not base_url
        event = UsageEvent(
            run_id=result.run_id,
            parent_run_id=result.parent_run_id,
            root_run_id=result.root_run_id or result.run_id,
            runtime=runtime,
            command=command,
            status=status,
            failure_type=failure_type,
            session=session,
            workflow=workflow,
            model=model,
            billing_mode=resolve_billing_mode(
                direct=effective_direct,
                has_api_key=_anthropic_key_present(),
                backend_id=backend_id,
            ),
            measurement_source=measurement.measurement_source,
            attribution_granularity="verb",
            route="claude_p",
            reporter=measurement.reporter,
            confidence=measurement.confidence,
            input_tokens=measurement.input_tokens,
            output_tokens=measurement.output_tokens,
            cached_tokens=measurement.cached_tokens,
            cost_micro_usd=measurement.cost_micro_usd,
            latency_ms=round(cost.duration_ms, 1) if (cost and cost.duration_ms) else None,
            source_refs=None,  # claude -p: proxy request_id unknown to Forge (4g)
        )
        if measurement.write_downstream:
            write_downstream_record(
                DownstreamRecord(
                    kind="attempt",
                    downstream_event_id=mint_downstream_event_id(event_key=f"claude_p:{result.run_id}:{command}"),
                    forge_run_id=result.run_id,
                    forge_root_run_id=result.root_run_id or result.run_id,
                    provider=None,
                    source_id=measurement.reporter,
                    source_kind="provider" if measurement.reporter else None,
                    backend_id=_backend_id_for_direct_usage(provider=None, reporter=measurement.reporter),
                    model=model,
                    input_tokens=measurement.input_tokens,
                    output_tokens=measurement.output_tokens,
                    cached_tokens=measurement.cached_tokens,
                    cost_micros=measurement.cost_micro_usd,
                    reporter=measurement.reporter,
                    confidence=measurement.confidence,
                    latency_ms=round(cost.duration_ms, 1) if (cost and cost.duration_ms) else None,
                    failed=status != "success",
                )
            )
        log_usage_event(event)
    except Exception as e:  # best-effort: telemetry must not break the verb
        logger.debug("emit_usage_for_session_result(%s) failed: %s", command, e)


def emit_verb_usage(
    *,
    command: str,
    cost: VerbCostResult | None = None,
    status: str = "success",
    workflow: str | None = None,
    session: str | None = None,
    runtime: str = "claude_code",
) -> None:
    """Emit a verb-level aggregate UsageEvent attributed to the ambient run.

    For workflow fan-outs (panel/analyze/debate/consensus): ``track_verb_cost``
    gives an *estimated aggregate* across N proxied workers, attributed to the
    ambient run (the session that launched the workflow), granularity ``"verb"``.
    Per-worker events are out of scope -- ``ReviewResult`` carries no per-worker
    cost (those land in 4d behind the invoker). No-ops without a run identity.
    """
    try:
        identity = get_run_identity()
        if identity is None:
            return
        measured_cost = cost if (cost is not None and cost.measured) else None
        # Cost is real evidence only when the window had a reported-cost request; a
        # tokens-only passthrough aggregate reports cost-unavailable, never a fake $0.
        cost_evident = cost is not None and cost.cost_measured
        # Aggregate over heterogeneous workers -> no single route (None). Reported cost
        # makes it "reported" (proxy total sums route-reported costs only); else no cost
        # reporter -> "unavailable".
        reporter: Reporter | None = "forge_proxy" if cost_evident else None
        confidence: Confidence = "reported" if cost_evident else "unavailable"
        event = UsageEvent(
            run_id=identity.run_id,
            parent_run_id=identity.parent_run_id,
            root_run_id=identity.root_run_id,
            runtime=runtime,
            command=command,
            status=status,
            session=session,
            workflow=workflow,
            route=None,
            reporter=reporter,
            confidence=confidence,
            measurement_source="verb_snapshot_estimated" if measured_cost else "unattributed",
            attribution_granularity="verb",
            input_tokens=measured_cost.input_tokens if measured_cost else None,
            output_tokens=measured_cost.output_tokens if measured_cost else None,
            cached_tokens=measured_cost.cached_tokens if measured_cost else None,
            cost_micro_usd=cost.total_cost_micros if (cost is not None and cost.cost_measured) else None,
            latency_ms=round(cost.duration_ms, 1) if (cost and cost.duration_ms) else None,
            source_refs=None,  # claude -p workers: proxy request_id unknown (4g)
        )
        log_usage_event(event)
    except Exception as e:
        logger.debug("emit_verb_usage(%s) failed: %s", command, e)


def emit_worker_usage(
    *,
    run_id: str,
    command: str,
    status: str,
    parent_run_id: str | None = None,
    root_run_id: str | None = None,
    workflow: str | None = None,
    session: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    proxy_id: str | None = None,
    latency_ms: float | None = None,
    runtime: str = "claude_code",
    base_url: str | None = None,
    cost_micro_usd: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cached_tokens: int | None = None,
    envelope_parsed: bool = False,
) -> None:
    """Emit a per-worker UsageEvent: one run-tree leaf of a fan-out.

    Cost precedence (Phase 5), mirroring the verb path:

    - **Direct** worker (no proxy) that self-reported cost -> ``claude_code`` /
      ``reported`` / ``runtime_native`` with its exact in-band tokens.
    - **Direct** worker, tokens-only (e.g. OAuth, cost absent) ->
      ``provider_usage_exact`` / ``unavailable`` with exact tokens.
    - **Proxied** worker -> cost ``None`` / ``unavailable``, tokens null: the
      per-worker proxy cost is not isolatable here; the verb aggregate
      (:func:`emit_verb_usage`) holds the estimated total, so attributing cost
      here would double-count.

    Best-effort; no-ops without a ``run_id`` (nothing to attribute).
    """
    try:
        if not run_id:
            return
        proxied = bool(base_url)
        self_cost = cost_micro_usd if envelope_parsed else None
        measurement = resolve_claude_p_measurement(
            caller="worker",
            proxied=proxied,
            self_cost=self_cost,
            envelope_parsed=envelope_parsed,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
        )

        event = UsageEvent(
            run_id=run_id,
            parent_run_id=parent_run_id,
            root_run_id=root_run_id or run_id,
            runtime=runtime,
            command=command,
            status=status,
            session=session,
            workflow=workflow,
            provider=provider,
            model=model,
            proxy_id=proxy_id,
            route="claude_p",
            reporter=measurement.reporter,
            confidence=measurement.confidence,
            measurement_source=measurement.measurement_source,
            attribution_granularity="worker",
            input_tokens=measurement.input_tokens,
            output_tokens=measurement.output_tokens,
            cached_tokens=measurement.cached_tokens,
            cost_micro_usd=measurement.cost_micro_usd,
            latency_ms=round(latency_ms, 1) if latency_ms is not None else None,
            source_refs=None,
        )
        if measurement.write_downstream:
            write_downstream_record(
                DownstreamRecord(
                    kind="attempt",
                    downstream_event_id=mint_downstream_event_id(event_key=f"claude_worker:{run_id}:{command}"),
                    forge_run_id=run_id,
                    forge_root_run_id=root_run_id or run_id,
                    provider=provider,
                    source_id=provider,
                    source_kind="provider" if provider else None,
                    backend_id=_backend_id_for_direct_usage(provider=provider, reporter=measurement.reporter),
                    model=model,
                    input_tokens=measurement.input_tokens,
                    output_tokens=measurement.output_tokens,
                    cached_tokens=measurement.cached_tokens,
                    cost_micros=measurement.cost_micro_usd,
                    reporter=measurement.reporter,
                    confidence=measurement.confidence,
                    latency_ms=round(latency_ms, 1) if latency_ms is not None else None,
                    failed=status != "success",
                )
            )
        log_usage_event(event)
    except Exception as e:  # best-effort: telemetry must not break the fan-out
        logger.debug("emit_worker_usage(%s) failed: %s", command, e)


def emit_codex_usage(
    *,
    run_id: str,
    command: str,
    status: str,
    parent_run_id: str | None = None,
    root_run_id: str | None = None,
    workflow: str | None = None,
    session: str | None = None,
    model: str | None = None,
    provider: str | None = "openai",
    billing_mode: BillingMode | None = None,
    latency_ms: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cached_tokens: int | None = None,
    runtime: str = "codex",
) -> None:
    """Emit a per-run UsageEvent for a native ``codex exec --json`` run.

    Codex runs DIRECT to OpenAI -- there is no Forge proxy in the path, so there is no
    proxy cost record to join (``source_refs=None``) and no dollar figure
    (``cost_micro_usd=None``). The JSONL stream still reports exact tokens, so:

    - ``reporter="codex_jsonl"`` / ``measurement_source="runtime_native"`` with the
      stream's exact tokens (the *tokens* are attributed);
    - ``confidence="unavailable"`` -- the ledger's ``confidence`` is a **cost** signal,
      and Codex reports no cost (mirrors the tokens-only direct branch in
      ``direct_cost_provenance``. Honest absence, never a fabricated $0.

    ``billing_mode`` is the resolved Codex posture (from ``CodexPreflight``); the
    invoker can't infer it. Best-effort; no-ops without a ``run_id``.
    """
    try:
        if not run_id:
            return
        measurement = resolve_codex_measurement(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
        )
        write_downstream_record(
            DownstreamRecord(
                kind="attempt",
                downstream_event_id=mint_downstream_event_id(event_key=f"codex:{run_id}:{command}"),
                forge_run_id=run_id,
                forge_root_run_id=root_run_id or run_id,
                provider=provider,
                source_id=provider,
                source_kind="provider",
                backend_id=_backend_id_for_direct_usage(provider=provider, reporter=measurement.reporter),
                model=model,
                input_tokens=measurement.input_tokens,
                output_tokens=measurement.output_tokens,
                cached_tokens=measurement.cached_tokens,
                cost_micros=measurement.cost_micro_usd,
                reporter=measurement.reporter,
                confidence=measurement.confidence,
                latency_ms=round(latency_ms, 1) if latency_ms is not None else None,
                failed=status != "success",
            )
        )
        event = UsageEvent(
            run_id=run_id,
            parent_run_id=parent_run_id,
            root_run_id=root_run_id or run_id,
            runtime=runtime,
            command=command,
            status=status,
            session=session,
            workflow=workflow,
            provider=provider,
            model=model,
            billing_mode=billing_mode or "unknown",
            route="codex_exec",
            reporter=measurement.reporter,
            confidence=measurement.confidence,
            measurement_source=measurement.measurement_source,
            attribution_granularity="worker",
            input_tokens=measurement.input_tokens,
            output_tokens=measurement.output_tokens,
            cached_tokens=measurement.cached_tokens,
            cost_micro_usd=measurement.cost_micro_usd,  # native runtime: no $ figure (no proxy record to join)
            latency_ms=round(latency_ms, 1) if latency_ms is not None else None,
            source_refs=None,  # direct to OpenAI: no Forge proxy request_id exists
        )
        log_usage_event(event)
    except Exception as e:  # best-effort: telemetry must not break the run
        logger.debug("emit_codex_usage(%s) failed: %s", command, e)


def emit_direct_llm_usage(
    *,
    command: str,
    model: str | None = None,
    provider: str | None = None,
    usage: dict[str, int] | None = None,
    status: str = "success",
    failure_type: str | None = None,
    cost_request_id: str | None = None,
    billing_mode: BillingMode = "unknown",
    latency_ms: float | None = None,
    workflow: str | None = None,
    session: str | None = None,
    runtime: str = "claude_code",
    provider_meta: object | None = None,
) -> None:
    """Emit a UsageEvent for a direct ``core.llm`` call (Forge is the HTTP client).

    Attribution comes from the ambient run identity (``os.environ``). Tokens come
    from the provider's in-band ``usage`` (exact), so ``measurement_source`` is
    ``provider_usage_exact``; ``cost_micro_usd`` stays null (no $ figure is computed
    here -- when ``cost_request_id`` is set, the exact $ lives in the joined proxy
    cost record). ``cost_request_id`` is set only by callers that proved a Forge
    proxy target (else null -- a dangling ref is worse than null). ``billing_mode``
    defaults to ``unknown``: a direct caller rarely proves direct + real-credential
    billing (e.g. the tagger routes via local LiteLLM with a dummy key), and a
    guessed mode is worse than honest uncertainty.
    """
    try:
        identity = get_run_identity()
        if identity is None:
            return
        measurement = resolve_direct_llm_measurement(usage=usage)
        # Direct core.llm call: tokens are provider-reported in-band when present. This
        # helper never computes a $ figure, so cost confidence is always unavailable; a
        # joined source_refs cost ref does not change event-local confidence.
        pm: dict[str, Any] = {}
        if provider_meta is not None:
            model_dump = getattr(provider_meta, "model_dump", None)
            if callable(model_dump):
                dumped = model_dump(exclude_none=True)
                if isinstance(dumped, dict):
                    pm = dumped
            elif isinstance(provider_meta, dict):
                pm = provider_meta
        pm_provider = pm.get("provider") if isinstance(pm.get("provider"), str) else None
        pm_selected_provider = pm.get("selected_provider") if isinstance(pm.get("selected_provider"), str) else None
        pm_response_id = pm.get("provider_response_id") if isinstance(pm.get("provider_response_id"), str) else None
        pm_generation_id = (
            pm.get("provider_generation_id") if isinstance(pm.get("provider_generation_id"), str) else None
        )
        pm_request_id = pm.get("provider_request_id") if isinstance(pm.get("provider_request_id"), str) else None
        pm_session_id = pm.get("provider_session_id") if isinstance(pm.get("provider_session_id"), str) else None
        pm_headers = pm.get("headers")
        provider_headers: dict[str, str] | None = None
        if isinstance(pm_headers, dict):
            from forge.core.llm.clients.openai_compat import provider_trace_headers

            provider_headers = provider_trace_headers(pm_headers)
        if cost_request_id is None:
            write_downstream_record(
                DownstreamRecord(
                    kind="attempt",
                    downstream_event_id=mint_downstream_event_id(
                        event_key=f"core_llm:{identity.run_id}:{command}:{uuid.uuid4().hex}"
                    ),
                    source_id=provider,
                    source_kind="provider",
                    backend_id=_backend_id_for_direct_usage(
                        provider=provider or pm_provider,
                        reporter=measurement.reporter,
                    ),
                    forge_run_id=identity.run_id,
                    forge_root_run_id=identity.root_run_id,
                    provider=provider or pm_provider,
                    selected_provider=pm_selected_provider,
                    model=model,
                    input_tokens=measurement.input_tokens,
                    output_tokens=measurement.output_tokens,
                    cached_tokens=measurement.cached_tokens,
                    cost_micros=measurement.cost_micro_usd,
                    reporter=measurement.reporter,
                    confidence=measurement.confidence,
                    latency_ms=round(latency_ms, 1) if latency_ms is not None else None,
                    failed=status != "success",
                    provider_response_id=pm_response_id,
                    provider_generation_id=pm_generation_id,
                    provider_request_id=pm_request_id,
                    provider_session_id=pm_session_id,
                    provider_headers=provider_headers,
                    local_usage_status="unavailable",
                )
            )
        event = UsageEvent(
            run_id=identity.run_id,
            parent_run_id=identity.parent_run_id,
            root_run_id=identity.root_run_id,
            runtime=runtime,
            command=command,
            status=status,
            failure_type=failure_type,
            session=session,
            workflow=workflow,
            provider=provider,
            model=model,
            billing_mode=billing_mode,
            measurement_source=measurement.measurement_source,
            attribution_granularity="verb",
            route="core_llm",
            reporter=measurement.reporter,
            confidence=measurement.confidence,
            input_tokens=measurement.input_tokens,
            output_tokens=measurement.output_tokens,
            cached_tokens=measurement.cached_tokens,
            cost_micro_usd=measurement.cost_micro_usd,
            latency_ms=round(latency_ms, 1) if latency_ms is not None else None,
            source_refs=SourceRefs(cost_request_id=cost_request_id) if cost_request_id else None,
        )
        log_usage_event(event)
    except Exception as e:
        logger.debug("emit_direct_llm_usage(%s) failed: %s", command, e)


def _anthropic_key_present() -> bool:
    """True if an ANTHROPIC_API_KEY is resolvable (env or credential file)."""
    try:
        from forge.core.auth.template_secrets import resolve_env_or_credential

        return bool(resolve_env_or_credential("ANTHROPIC_API_KEY"))
    except Exception:
        return False

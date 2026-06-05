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

from forge.core.reactive.cost_tracking import VerbCostResult
from forge.core.reactive.env import get_run_identity
from forge.core.reactive.session_runner import SessionResult
from forge.core.usage.billing import infer_billing_mode
from forge.core.usage.ledger import BillingMode, SourceRefs, UsageEvent, log_usage_event
from forge.core.usage.vocabulary import Confidence, Reporter

logger = logging.getLogger(__name__)


def _session_status(result: SessionResult) -> tuple[str, str | None]:
    """Map a SessionResult to (status, failure_type)."""
    if result.success:
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
    runtime: str = "claude_code",
) -> None:
    """Emit one verb-level UsageEvent for a completed ``run_claude_session`` call.

    No-ops when the result carries no run identity (nothing to attribute).
    ``cost`` is the ``track_verb_cost`` holder; an unmeasured holder (no proxy in
    the path) yields ``measurement_source="unattributed"`` with null cost rather
    than a fabricated $0.
    """
    try:
        if not result.run_id:
            return
        status, failure_type = _session_status(result)
        # Narrow to a measured holder (None when no proxy delta was captured) so a
        # direct/no-proxy verb reports null tokens, not fabricated zeros.
        measured_cost = cost if (cost is not None and cost.measured) else None
        # Cost is real evidence only when the proxy window had a reported-cost request.
        # A passthrough verb is measured (tokens) yet cost-unavailable (no $ evidence) —
        # so its cost is null, never a fabricated measured $0.
        cost_evident = cost is not None and cost.cost_measured
        # "Direct" for billing only when no proxy is in the path; a proxied call's
        # upstream billing is opaque from here, so it stays "unknown".
        effective_direct = direct and not base_url
        # A claude -p verb is always route="claude_p"; reported cost makes it "reported"
        # (the proxy total now sums route-reported costs only). No reported-cost evidence
        # -> no reporter -> "unavailable".
        reporter: Reporter | None = "forge_proxy" if cost_evident else None
        confidence: Confidence = "reported" if cost_evident else "unavailable"
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
            billing_mode=infer_billing_mode(direct=effective_direct, has_api_key=_anthropic_key_present()),
            measurement_source="verb_snapshot_estimated" if measured_cost else "unattributed",
            attribution_granularity="verb",
            route="claude_p",
            reporter=reporter,
            confidence=confidence,
            input_tokens=measured_cost.input_tokens if measured_cost else None,
            output_tokens=measured_cost.output_tokens if measured_cost else None,
            cached_tokens=measured_cost.cached_tokens if measured_cost else None,
            cost_micro_usd=cost.total_cost_micros if (cost is not None and cost.cost_measured) else None,
            latency_ms=round(cost.duration_ms, 1) if (cost and cost.duration_ms) else None,
            source_refs=None,  # claude -p: proxy request_id unknown to Forge (4g)
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
) -> None:
    """Emit a per-worker UsageEvent: one run-tree leaf of a fan-out.

    Each worker is a ``claude -p`` subprocess whose *per-worker* cost is unknown
    (``ReviewResult`` carries none; the verb aggregate from :func:`emit_verb_usage`
    holds the estimated total). So cost/tokens stay null and
    ``measurement_source="unattributed"`` -- the event captures the tree shape
    (run/parent/root + model + status + latency), never a fabricated cost.
    Best-effort; no-ops without a ``run_id`` (nothing to attribute).
    """
    try:
        if not run_id:
            return
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
            reporter=None,
            confidence="unavailable",
            measurement_source="unattributed",
            attribution_granularity="worker",
            latency_ms=round(latency_ms, 1) if latency_ms is not None else None,
            source_refs=None,
        )
        log_usage_event(event)
    except Exception as e:  # best-effort: telemetry must not break the fan-out
        logger.debug("emit_worker_usage(%s) failed: %s", command, e)


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
        measured = usage is not None
        # Direct core.llm call: tokens are provider-reported in-band when present, so
        # reporter="provider"; this helper never computes a $ figure (cost_micro_usd stays
        # None), so cost confidence is always "unavailable" -- not a contradiction with the
        # provider-reported tokens, and a joined source_refs cost ref does not change it.
        reporter: Reporter | None = "provider" if measured else None
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
            measurement_source="provider_usage_exact" if measured else "unattributed",
            attribution_granularity="verb",
            route="core_llm",
            reporter=reporter,
            confidence="unavailable",
            input_tokens=usage.get("prompt_tokens") if usage else None,
            output_tokens=usage.get("completion_tokens") if usage else None,
            cached_tokens=usage.get("cached_tokens") if usage else None,
            cost_micro_usd=None,
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

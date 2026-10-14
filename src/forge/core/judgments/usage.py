"""Map Decisions attempts into the existing downstream and attribution schemas."""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal

from forge.core.reactive.env import RunIdentity
from forge.core.telemetry.downstream import DownstreamRecord, write_downstream_record
from forge.core.telemetry.vocabulary import Confidence
from forge.core.usage.ledger import UsageEvent, log_usage_event

from .types import JudgmentAttempt

logger = logging.getLogger(__name__)


def emit_attempt(
    attempt: JudgmentAttempt,
    *,
    identity: RunIdentity | None,
    session: str | None,
    grouping: str | None,
    command: str,
    direct: bool,
) -> None:
    """Emit once per physical attempt; telemetry failures cannot invalidate a judgment."""
    try:
        usage = attempt.usage
        cost = (
            int((Decimal(str(usage.cost)) * 1_000_000).to_integral_value(rounding=ROUND_HALF_UP))
            if usage is not None and usage.cost is not None
            else None
        )
        confidence: Confidence = "reported" if cost is not None else "unavailable"
        inputs = usage.input_tokens if usage else None
        outputs = usage.output_tokens if usage else None
        timed_out = attempt.failure == "ambiguous_timeout"
        write_downstream_record(
            DownstreamRecord(
                kind="attempt",
                downstream_event_id=attempt.downstream_event_id,
                request_id=attempt.request_id,
                source_id="openrouter",
                source_kind="provider",
                backend_id="openrouter",
                forge_run_id=identity.run_id if identity else None,
                forge_root_run_id=identity.root_run_id if identity else None,
                provider_session_id=grouping,
                provider_command=command,
                provider="openrouter",
                selected_provider=attempt.provider,
                model=attempt.requested_model,
                mapped_model=attempt.model,
                input_tokens=inputs,
                output_tokens=outputs,
                cost_micros=cost,
                reporter="openrouter",
                confidence=confidence,
                latency_ms=attempt.latency_ms,
                failed=attempt.failure is not None,
                provider_response_id=attempt.provider_response_id,
                request_mode="non_streaming",
                final_usage_seen=inputs is not None and outputs is not None,
                client_disconnected=attempt.failure == "cancelled",
                local_usage_status="available" if usage else "unavailable",
                timeout_seen=timed_out,
                reported_cost_micros=cost,
            )
        )
        if identity is None:
            return
        log_usage_event(
            UsageEvent(
                run_id=identity.run_id,
                root_run_id=identity.root_run_id,
                parent_run_id=identity.parent_run_id,
                event_id=f"evt_{attempt.downstream_event_id}",
                runtime="forge",
                command=command,
                status="timeout" if timed_out else "error" if attempt.failure else "success",
                failure_type=attempt.failure,
                session=session,
                provider="openrouter",
                model=attempt.model or attempt.requested_model,
                billing_mode="api" if direct else "unknown",
                measurement_source="provider_usage_exact" if usage else "unattributed",
                route="core_llm",
                reporter="openrouter",
                confidence=confidence,
                input_tokens=inputs,
                output_tokens=outputs,
                cost_micro_usd=cost,
                latency_ms=attempt.latency_ms,
            )
        )
    except Exception:
        # Do not include provider content or credentials in best-effort diagnostics.
        logger.debug("Could not emit judgment attempt %s", attempt.request_id)

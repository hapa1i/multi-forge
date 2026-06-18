"""Shared usage measurement resolution.

The emitters own run identity and persistence; this module owns the cost/token
precedence rules so verb, worker, Codex, and direct ``core.llm`` paths do not
drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NamedTuple

from forge.core.reactive.cost_tracking import VerbCostResult
from forge.core.usage.ledger import MeasurementSource
from forge.core.usage.vocabulary import Confidence, Reporter

MeasurementCaller = Literal["verb", "worker"]


@dataclass(frozen=True)
class UsageMeasurement:
    cost_micro_usd: int | None
    reporter: Reporter | None
    confidence: Confidence
    measurement_source: MeasurementSource
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    write_downstream: bool = False


class DirectCostProvenance(NamedTuple):
    """Cost/token provenance for a direct (non-proxied) ``claude -p`` run."""

    cost_micro_usd: int | None
    reporter: Reporter | None
    confidence: Confidence
    measurement_source: MeasurementSource
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None


def direct_cost_provenance(
    self_cost: int | None,
    envelope_parsed: bool,
    input_tokens: int | None,
    output_tokens: int | None,
    cached_tokens: int | None,
) -> DirectCostProvenance:
    """One-reporter cost precedence for a direct ``claude -p`` run."""
    if self_cost is not None:
        return DirectCostProvenance(
            self_cost, "claude_code", "reported", "runtime_native", input_tokens, output_tokens, cached_tokens
        )
    if envelope_parsed and input_tokens is not None:
        return DirectCostProvenance(
            None, None, "unavailable", "provider_usage_exact", input_tokens, output_tokens, cached_tokens
        )
    return DirectCostProvenance(None, None, "unavailable", "unattributed", None, None, None)


def resolve_claude_p_measurement(
    *,
    caller: MeasurementCaller,
    proxied: bool,
    cost: VerbCostResult | None = None,
    self_cost: int | None = None,
    envelope_parsed: bool = False,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cached_tokens: int | None = None,
) -> UsageMeasurement:
    """Resolve measurement for a ``claude -p`` verb or worker event."""
    if proxied and caller == "worker":
        return UsageMeasurement(None, None, "unavailable", "unattributed")

    if proxied:
        cost_evident = cost is not None and cost.cost_measured
        cost_micro_usd: int | None
        reporter: Reporter | None
        confidence: Confidence
        if cost_evident and cost is not None:
            cost_micro_usd, reporter, confidence = cost.total_cost_micros, "forge_proxy", "reported"
        else:
            cost_micro_usd, reporter, confidence = None, None, "unavailable"
        if cost is not None and cost.measured:
            return UsageMeasurement(
                cost_micro_usd,
                reporter,
                confidence,
                "verb_snapshot_estimated",
                cost.input_tokens,
                cost.output_tokens,
                cost.cached_tokens,
                write_downstream=False,
            )
        return UsageMeasurement(cost_micro_usd, reporter, confidence, "unattributed", write_downstream=False)

    prov = direct_cost_provenance(self_cost, envelope_parsed, input_tokens, output_tokens, cached_tokens)
    return UsageMeasurement(
        prov.cost_micro_usd,
        prov.reporter,
        prov.confidence,
        prov.measurement_source,
        prov.input_tokens,
        prov.output_tokens,
        prov.cached_tokens,
        write_downstream=True,
    )


def resolve_codex_measurement(
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cached_tokens: int | None = None,
) -> UsageMeasurement:
    """Resolve measurement for native Codex JSONL token reporting."""
    return UsageMeasurement(
        None,
        "codex_jsonl",
        "unavailable",
        "runtime_native",
        input_tokens,
        output_tokens,
        cached_tokens,
        write_downstream=True,
    )


def resolve_direct_llm_measurement(*, usage: dict[str, int] | None) -> UsageMeasurement:
    """Resolve measurement for direct ``core.llm`` calls."""
    measured = usage is not None
    return UsageMeasurement(
        None,
        "provider" if measured else None,
        "unavailable",
        "provider_usage_exact" if measured else "unattributed",
        usage.get("prompt_tokens") if usage else None,
        usage.get("completion_tokens") if usage else None,
        usage.get("cached_tokens") if usage else None,
        write_downstream=True,
    )

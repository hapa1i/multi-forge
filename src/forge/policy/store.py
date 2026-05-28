"""Helpers for reading/writing policy state to the session manifest.

Policy state is persisted to confirmed.policy in the session manifest.
This enables stateful policies (like TDD) to track state across hook
invocations, since hooks are short-lived processes.
"""

from __future__ import annotations

import logging
from typing import Any

from forge.core.state import now_iso
from forge.policy.types import CompositeDecision, PolicyDecision, Violation

_log = logging.getLogger(__name__)

# Maximum number of decisions to keep in the log
MAX_DECISION_LOG = 100


def serialize_decision(decision: PolicyDecision) -> dict[str, Any]:
    """Serialize a PolicyDecision for persistence.

    Args:
        decision: The decision to serialize

    Returns:
        Dict suitable for JSON serialization
    """
    return {
        "decision": decision.decision,
        "policy_id": decision.policy_id,
        "violations": [_serialize_violation(v) for v in decision.violations],
        "warnings": decision.warnings,
        "cached": decision.cached,
        "evaluated_at": decision.evaluated_at,
    }


def _serialize_violation(violation: Violation) -> dict[str, Any]:
    """Serialize a Violation for persistence."""
    return {
        "rule_id": violation.rule_id,
        "message": violation.message,
        "severity": violation.severity,
        "evidence": violation.evidence,
        "suggested_fix": violation.suggested_fix,
        "citations": violation.citations,
    }


def serialize_composite_decision(
    composite: CompositeDecision,
    context_summary: str | None = None,
) -> dict[str, Any]:
    """Serialize a CompositeDecision for the decision log.

    Args:
        composite: The composite decision to serialize
        context_summary: Optional summary of the action context

    Returns:
        Dict suitable for JSON serialization
    """
    return {
        "final_decision": composite.final_decision,
        "context_summary": context_summary,
        "blocking_violations": [_serialize_violation(v) for v in composite.blocking_violations],
        "warnings": composite.all_warnings,
        "evaluated_at": now_iso(),
        "decisions": [serialize_decision(d) for d in composite.decisions],
    }


def build_policy_state_update(
    result: CompositeDecision,
    engine_state: dict[str, dict[str, Any]],
    existing_state: dict[str, Any] | None,
    *,
    forge_version: str | None = None,
    bundles: list[str] | None = None,
    rules_active: list[str] | None = None,
    context_summary: str | None = None,
) -> dict[str, Any]:
    """Build the policy state update for the session manifest.

    Appends to the decision log and merges the engine's collected policy states
    into existing states. Policies that weren't evaluated (applies_to() returned
    False) retain their prior state — only policies that ran get updated.

    Args:
        result: The composite decision from evaluation
        engine_state: Collected state from evaluated stateful policies (keyed by policy_id)
        existing_state: Current confirmed.policy state (may be None)
        forge_version: Forge version for provenance
        bundles: Active bundle names for provenance
        rules_active: Active rule IDs for provenance
        context_summary: Summary of the action for logging

    Returns:
        Dict to write to confirmed.policy
    """
    existing = existing_state or {}

    # Append to decision log (with bounded size)
    decisions_log = list(existing.get("decisions", []))
    decisions_log.append(serialize_composite_decision(result, context_summary))
    if len(decisions_log) > MAX_DECISION_LOG:
        decisions_log = decisions_log[-MAX_DECISION_LOG:]

    # Merge engine state into existing policy_states.
    # Policies that weren't evaluated (applies_to() returned False) retain
    # their prior state. Only policies that ran get their state updated.
    merged_states = dict(existing.get("policy_states", {}))
    merged_states.update(engine_state)

    return {
        "forge_version": forge_version or existing.get("forge_version"),
        "bundles": bundles or existing.get("bundles", []),
        "rules_active": rules_active or existing.get("rules_active", []),
        "decisions": decisions_log,
        "policy_states": merged_states,
    }

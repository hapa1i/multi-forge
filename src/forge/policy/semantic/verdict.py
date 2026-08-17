"""Supervisor verdict parsing and conversion.

Parses structured JSON responses from the semantic supervisor and
converts them to PolicyDecision objects.
"""

from __future__ import annotations

import logging
import math
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from forge.core.reactive.structured_output import extract_json_from_response
from forge.policy.types import PolicyDecision, Severity, Violation

_log = logging.getLogger(__name__)

# Confidence threshold for blocking (require high confidence + citations)
CONFIDENCE_THRESHOLD = 0.8


@dataclass
class SupervisorVerdict:
    """Parsed verdict from the semantic supervisor.

    Attributes:
        verdict: "aligned" (action matches plan) or "divergent" (action deviates)
        confidence: 0.0-1.0 confidence in the verdict
        violations: List of violation details for divergent verdicts
    """

    verdict: Literal["aligned", "divergent"]
    confidence: float = 1.0
    violations: list[dict[str, Any]] = field(default_factory=list)


def meets_block_bar(confidence: float, has_citations: bool) -> bool:
    """Return whether a divergent verdict has enough support to block."""
    return confidence >= CONFIDENCE_THRESHOLD and has_citations


def _warn_verdict(evidence: str, suggested_fix: str) -> SupervisorVerdict:
    """Create a divergent verdict with 0.0 confidence (maps to warn, not deny)."""
    return SupervisorVerdict(
        verdict="divergent",
        confidence=0.0,
        violations=[
            {
                "severity": "low",
                "evidence": evidence,
                "suggested_fix": suggested_fix,
                "citations": [],
            }
        ],
    )


def parse_supervisor_verdict_with_status(response: str) -> tuple[SupervisorVerdict, bool]:
    """Parse a supervisor response, returning ``(verdict, parsed)``.

    ``parsed`` is False when the response was empty or unparseable -- the returned
    verdict is then the divergent-0.0 fallback warn. Callers that *audit* the
    supervisor (shadow sampling) need this flag to distinguish a real
    low-confidence divergence (``parsed=True``) from a failed/unparseable run
    (``parsed=False``), which the bare verdict cannot.
    """
    if not response:
        _log.warning("Empty supervisor response, failing open with warning")
        return (
            _warn_verdict(
                "Supervisor response was empty — check supervisor session health",
                "Verify supervisor resume_id and proxy connectivity",
            ),
            False,
        )

    data = extract_json_from_response(response)
    if data is None:
        _log.warning("Could not parse supervisor verdict, failing open with warning")
        return (
            _warn_verdict(
                "Supervisor verdict could not be parsed — check supervisor response format",
                "Verify supervisor session responds with valid JSON verdict",
            ),
            False,
        )

    verdict = _parse_verdict_data(data)
    if verdict is None:
        return (
            _warn_verdict(
                "Supervisor verdict was missing or invalid — expected exact 'aligned' or 'divergent'",
                "Verify supervisor session returns the documented verdict schema",
            ),
            False,
        )
    return verdict, True


def parse_supervisor_verdict(response: str) -> SupervisorVerdict:
    """Extract a JSON verdict from a supervisor response (fallback warn on failure).

    .. deprecated::
        Use ``forge.policy.semantic.verdict.parse_supervisor_verdict_with_status``
        so parse failures remain distinguishable from genuine low-confidence verdicts.
    """
    warnings.warn(
        "parse_supervisor_verdict() is deprecated; use "
        "forge.policy.semantic.verdict.parse_supervisor_verdict_with_status() instead.",
        FutureWarning,
        stacklevel=2,
    )
    return parse_supervisor_verdict_with_status(response)[0]


def _parse_verdict_data(data: dict[str, Any]) -> SupervisorVerdict | None:
    """Parse a schema-valid verdict, returning None for an invalid verdict literal."""
    raw_verdict = data.get("verdict")
    if raw_verdict == "aligned":
        verdict: Literal["aligned", "divergent"] = "aligned"
    elif raw_verdict == "divergent":
        verdict = "divergent"
    else:
        _log.warning("Unknown supervisor verdict %r, failing open", raw_verdict)
        return None

    raw_confidence = data.get("confidence")
    if isinstance(raw_confidence, bool) or not isinstance(raw_confidence, (int, float)):
        _log.warning("Malformed supervisor confidence %r, degrading to 0.0", raw_confidence)
        confidence = 0.0
    elif isinstance(raw_confidence, float) and not math.isfinite(raw_confidence):
        _log.warning("Non-finite supervisor confidence %r, degrading to 0.0", raw_confidence)
        confidence = 0.0
    else:
        confidence = float(max(0, min(1, raw_confidence)))

    raw_violations = data.get("violations", [])
    violations = (
        [dict(violation) for violation in raw_violations if isinstance(violation, Mapping)]
        if isinstance(raw_violations, list)
        else []
    )

    return SupervisorVerdict(
        verdict=verdict,
        confidence=confidence,
        violations=violations,
    )


def _normalize_citations(value: Any) -> list[str]:
    """Return non-blank string citations from the documented JSON list shape."""
    if not isinstance(value, list):
        return []
    return [citation for citation in value if isinstance(citation, str) and citation.strip()]


def verdict_to_decision(verdict: SupervisorVerdict, *, intent: str | None = None) -> PolicyDecision:
    """Convert a SupervisorVerdict to a PolicyDecision.

    Blocking rules:
    - Aligned verdicts always allow
    - Divergent verdicts only block if:
      - Confidence >= CONFIDENCE_THRESHOLD (0.8)
      - At least one violation has citations
    - Low confidence or no citations → warn only

    Args:
        verdict: Parsed supervisor verdict
        intent: Policy intent to attach to deny decisions.

    Returns:
        PolicyDecision (allow, deny, or warn)
    """
    policy_id = "semantic.supervisor"

    # Aligned = allow
    if verdict.verdict == "aligned":
        return PolicyDecision(
            decision="allow",
            policy_id=policy_id,
        )

    # Divergent: check confidence and citations
    blocking_violations: list[Violation] = []
    warnings: list[str] = []

    for v in verdict.violations:
        if not isinstance(v, Mapping):
            continue
        citations = _normalize_citations(v.get("citations"))
        severity_str = v.get("severity", "medium")
        severity: Severity = (
            severity_str if severity_str in ("critical", "high", "medium", "low") else "medium"
        )  # type: ignore[assignment]  # membership check narrows str to Literal at runtime

        violation = Violation(
            rule_id=f"{policy_id}.alignment",
            message=v.get("evidence", "Divergent from plan"),
            severity=severity,
            evidence=v.get("evidence"),
            suggested_fix=v.get("suggested_fix"),
            citations=citations,
        )

        # Only block on high-confidence violations with citations
        if meets_block_bar(verdict.confidence, bool(violation.citations)):
            blocking_violations.append(violation)
        else:
            # Low confidence or no citations → warning only
            warnings.append(f"Possible divergence: {violation.message} (confidence: {verdict.confidence:.0%})")

    if blocking_violations:
        return PolicyDecision(
            decision="deny",
            policy_id=policy_id,
            violations=blocking_violations,
            warnings=warnings,
            intent=intent,
        )

    # No blocking violations (low confidence or no citations)
    if warnings:
        return PolicyDecision(
            decision="warn",
            policy_id=policy_id,
            warnings=warnings,
        )

    # No violations at all (shouldn't happen for divergent, but handle gracefully)
    return PolicyDecision(
        decision="warn",
        policy_id=policy_id,
        warnings=[f"Divergent verdict with no specific violations (confidence: {verdict.confidence:.0%})"],
    )

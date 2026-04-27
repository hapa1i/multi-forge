"""Supervisor verdict parsing and conversion.

Parses structured JSON responses from the semantic supervisor and
converts them to PolicyDecision objects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from forge.core.reactive.structured_output import extract_json_from_response
from forge.guard.types import PolicyDecision, Severity, Violation

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


def parse_supervisor_verdict(response: str) -> SupervisorVerdict:
    """Extract JSON verdict from supervisor response.

    Uses ``extract_json_from_response`` for code-fence/raw JSON extraction,
    then validates the verdict structure. Unparseable responses return a
    divergent verdict with 0.0 confidence (maps to "warn", not deny or
    silent allow).

    Args:
        response: Raw text response from the supervisor

    Returns:
        Parsed SupervisorVerdict
    """
    if not response:
        _log.warning("Empty supervisor response, failing open with warning")
        return _warn_verdict(
            "Supervisor response was empty — check supervisor session health",
            "Verify supervisor resume_id and proxy connectivity",
        )

    data = extract_json_from_response(response)
    if data is None:
        _log.warning("Could not parse supervisor verdict, failing open with warning")
        return _warn_verdict(
            "Supervisor verdict could not be parsed — check supervisor response format",
            "Verify supervisor session responds with valid JSON verdict",
        )

    return _parse_verdict_data(data)


def _parse_verdict_data(data: dict[str, Any]) -> SupervisorVerdict:
    """Parse verdict from JSON data."""
    verdict = data.get("verdict", "aligned")
    if verdict not in ("aligned", "divergent"):
        _log.warning("Unknown verdict '%s', treating as aligned", verdict)
        verdict = "aligned"

    confidence = data.get("confidence", 1.0)
    if not isinstance(confidence, (int, float)):
        confidence = 1.0
    confidence = max(0.0, min(1.0, float(confidence)))

    violations = data.get("violations", [])
    if not isinstance(violations, list):
        violations = []

    return SupervisorVerdict(
        verdict=verdict,  # type: ignore[arg-type]  # mypy doesn't track narrowing from reassignment
        confidence=confidence,
        violations=violations,
    )


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
        citations = v.get("citations", [])
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
            citations=citations if isinstance(citations, list) else [],
        )

        # Only block on high-confidence violations with citations
        if verdict.confidence >= CONFIDENCE_THRESHOLD and citations:
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

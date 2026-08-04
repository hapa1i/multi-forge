"""Regression for D002: malformed supervisor confidence must not deny.

Root cause: the semantic verdict parser defaulted missing and non-numeric
confidence to ``1.0`` while Python booleans and non-finite floats also reached
the numeric clamp. Malformed external data could therefore satisfy the block
threshold.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from forge.policy.semantic.verdict import parse_supervisor_verdict_with_status, verdict_to_decision

pytestmark = pytest.mark.regression

_MISSING = object()


def _divergent_response(confidence: Any = _MISSING) -> str:
    payload: dict[str, Any] = {
        "verdict": "divergent",
        "violations": [{"evidence": "Changed the plan", "citations": ["Plan section 2"]}],
    }
    if confidence is not _MISSING:
        payload["confidence"] = confidence
    return json.dumps(payload)


@pytest.mark.parametrize(
    "confidence",
    [_MISSING, None, True, False, "high", float("nan"), float("inf"), float("-inf")],
    ids=["missing", "null", "true", "false", "string", "nan", "infinity", "negative-infinity"],
)
def test_malformed_confidence_degrades_to_low_and_cannot_deny(confidence: Any) -> None:
    verdict, parsed = parse_supervisor_verdict_with_status(_divergent_response(confidence))

    assert parsed is True
    assert verdict.confidence == 0.0
    assert verdict_to_decision(verdict).decision == "warn"


@pytest.mark.parametrize(
    ("confidence", "normalized", "decision"),
    [
        (-(10**1000), 0.0, "warn"),
        (-0.5, 0.0, "warn"),
        (0.79, 0.79, "warn"),
        (0.8, 0.8, "deny"),
        (1.5, 1.0, "deny"),
        (10**1000, 1.0, "deny"),
    ],
)
def test_finite_numeric_confidence_keeps_clamp_and_threshold_behavior(
    confidence: int | float, normalized: float, decision: str
) -> None:
    verdict, parsed = parse_supervisor_verdict_with_status(_divergent_response(confidence))

    assert parsed is True
    assert verdict.confidence == normalized
    assert verdict_to_decision(verdict).decision == decision

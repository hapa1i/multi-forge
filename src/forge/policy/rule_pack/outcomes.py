"""Compose covered judgments without creating policy permission or denial decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from forge.core.judgments.types import JudgmentResponse, NoulAnswer, validate_answers
from forge.policy.rule_pack.definitions import questions

DECISION_VERSION = "draft-1"
Outcome = Literal["warning", "no_warning", "uncertain", "unavailable", "not_applicable"]
_DIAGNOSTICS = {
    "jev_invalid_response": "Jev returned no usable assessment for this rule.",
    "jev_insufficient_evidence": "The supplied action evidence is insufficient to assess compatibility retention.",
    "jev_coverage_uncertain": "Whether the supplied evidence covers this rule is uncertain.",
    "jev_conflicting_answers": "The answers disagree about whether a retained interface exists.",
    "jev_no_compatibility_retention": "The covered action shows no retained compatibility interface.",
    "jev_retention_uncertain": "Whether this action retains an earlier interface is uncertain.",
    "jev_boundary_uncertain": "Whether a required boundary justifies the retained interface is uncertain.",
    "jev_required_boundary": "The covered action establishes a required boundary for the retained interface.",
    "jev_compatibility_retention": "The covered action appears to retain an earlier interface without a required boundary; review affected callers and compatibility before changing it.",
    "jev_saved_failure": "The saved attempt failed, so this rule was not assessed.",
}


class ProbabilityBand(BaseModel):
    """Require explicit separated true/false cutoffs; no inherited supervisor threshold."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    false_max: Annotated[float, Field(ge=0, lt=0.5, allow_inf_nan=False)]
    true_min: Annotated[float, Field(gt=0.5, le=1, allow_inf_nan=False)]

    def classify(self, probability: float) -> bool | None:
        """Keep the gap between the two cutoffs explicitly uncertain."""
        if probability <= self.false_max:
            return False
        if probability >= self.true_min:
            return True
        return None


class DecisionThresholds(BaseModel):
    """Caller-supplied calibration candidate, not an approved production configuration."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    coverage: ProbabilityBand
    compatibility_retention: ProbabilityBand
    independent_boundary: ProbabilityBand


@dataclass(frozen=True)
class Assessment:
    """A rule assessment and fixed diagnostic, with no engine enforcement authority."""

    outcome: Outcome
    reason: str

    @property
    def diagnostic(self) -> str:
        """Return authored rule feedback without a provider-generated explanation."""
        return _DIAGNOSTICS[self.reason]


def assess_response(response: JudgmentResponse, thresholds: DecisionThresholds) -> Assessment:
    """Gate on evidence coverage, then combine answers without assuming independence."""
    try:
        validate_answers(response, questions())
    except ValueError:
        return Assessment("unavailable", "jev_invalid_response")
    classified: dict[str, bool | None] = {}
    for name, band in (
        ("coverage", thresholds.coverage),
        ("compatibility_retention", thresholds.compatibility_retention),
        ("independent_boundary", thresholds.independent_boundary),
    ):
        answer = response.answers[name]
        if not isinstance(answer, NoulAnswer):
            return Assessment("unavailable", "jev_invalid_response")
        classified[name] = band.classify(answer.noul)

    coverage = classified["coverage"]
    if coverage is False:
        return Assessment("unavailable", "jev_insufficient_evidence")
    if coverage is None:
        return Assessment("uncertain", "jev_coverage_uncertain")
    retention = classified["compatibility_retention"]
    boundary = classified["independent_boundary"]
    if retention is False:
        if boundary is True:
            return Assessment("uncertain", "jev_conflicting_answers")
        return Assessment("no_warning", "jev_no_compatibility_retention")
    if retention is None:
        return Assessment("uncertain", "jev_retention_uncertain")
    if boundary is None:
        return Assessment("uncertain", "jev_boundary_uncertain")
    if boundary is True:
        return Assessment("no_warning", "jev_required_boundary")
    return Assessment("warning", "jev_compatibility_retention")

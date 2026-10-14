"""Question and answer contracts for OpenRouter Decisions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Text = Annotated[str, Field(min_length=1)]
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0)]


class _Question(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    instructions: Text

    @field_validator("instructions")
    @classmethod
    def nonblank_instructions(cls, value: str) -> str:
        """Reject an instruction containing only whitespace."""
        if not value.strip():
            raise ValueError("question instructions must not be blank")
        return value


class ChoiceQuestion(_Question):
    """Choose among named criteria supplied by the caller."""

    type: Literal["choice"] = "choice"
    criteria: Annotated[dict[Text, Text], Field(min_length=1)]


class NoulQuestion(_Question):
    """Estimate the probability of the explicit true criterion."""

    type: Literal["noul"] = "noul"
    criteria: dict[Literal["true", "false"], Text]

    @field_validator("criteria")
    @classmethod
    def complete_criteria(cls, value: dict[Literal["true", "false"], str]) -> dict[Literal["true", "false"], str]:
        """Require both outcomes even though the provider schema is looser."""
        if set(value) != {"true", "false"}:
            raise ValueError("Noul requires true and false criteria")
        return value


class ScoreQuestion(_Question):
    """Score supplied evidence on an ordered list of criteria."""

    type: Literal["score"] = "score"
    criteria: Annotated[list[Text], Field(min_length=2, max_length=10)]


Question = ChoiceQuestion | NoulQuestion | ScoreQuestion


class _Answer(BaseModel):
    # External responses may add metadata; only the validated judgment fields are exposed.
    model_config = ConfigDict(extra="ignore", strict=True, frozen=True, allow_inf_nan=False)


class ChoiceAnswer(_Answer):
    """Preserve the provider's selected label and distribution."""

    type: Literal["choice"]
    choice: Text
    confidence: Probability
    probabilities: dict[str, Probability]


class NoulAnswer(_Answer):
    """Preserve the reported probability of the true criterion."""

    type: Literal["noul"]
    noul: Probability


class ScoreAnswer(_Answer):
    """Preserve the ordered legend, expected score and distribution."""

    type: Literal["score"]
    score: Annotated[float, Field(ge=0)]
    confidence: Probability
    legend: dict[str, str]
    probabilities: dict[str, Probability]


Answer = Annotated[ChoiceAnswer | NoulAnswer | ScoreAnswer, Field(discriminator="type")]


class JudgmentUsage(_Answer):
    """Keep token counts and optional provider-reported USD cost distinct."""

    input_tokens: Count
    output_tokens: Count
    cost: Annotated[float, Field(ge=0)] | None = None


class JudgmentResponse(_Answer):
    """Validate required response fields without requiring optional identity metadata."""

    answers: dict[str, Answer]
    model: Text
    usage: JudgmentUsage
    id: Text | None = None
    provider: Text | None = None


@dataclass(frozen=True)
class ReportedUsage:
    """Independently valid accounting fields, including from invalid responses."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: float | None = None


@dataclass(frozen=True)
class JudgmentAttempt:
    """One physical dispatch; retries never share an attempt or request ID."""

    request_id: str
    downstream_event_id: str
    requested_model: str
    latency_ms: float
    status_code: int | None = None
    failure: str | None = None
    model: str | None = None
    provider: str | None = None
    provider_response_id: str | None = None
    usage: ReportedUsage | None = None


@dataclass(frozen=True)
class JudgmentResult:
    """Return validated answers alongside physical-attempt evidence."""

    response: JudgmentResponse
    attempts: tuple[JudgmentAttempt, ...]


class JudgmentError(Exception):
    """Report unusable judgments without exposing provider response bodies."""

    def __init__(self, kind: str, message: str, *, attempts: tuple[JudgmentAttempt, ...] = ()) -> None:
        super().__init__(message)
        self.kind = kind
        self.attempts = attempts


def validate_answers(response: JudgmentResponse, questions: dict[str, Question]) -> None:
    """Check answer identity and distributions against the actual request."""
    if set(response.answers) != set(questions):
        raise ValueError("answer IDs do not match question IDs")
    for name, question in questions.items():
        answer = response.answers[name]
        if answer.type != question.type:
            raise ValueError("answer type does not match question type")
        if isinstance(answer, ChoiceAnswer) and isinstance(question, ChoiceQuestion):
            if set(answer.probabilities) != set(question.criteria) or answer.choice not in question.criteria:
                raise ValueError("choice labels do not match criteria")
            _validate_distribution(answer.probabilities)
        elif isinstance(answer, ScoreAnswer) and isinstance(question, ScoreQuestion):
            legend = {str(index): value for index, value in enumerate(question.criteria)}
            if answer.legend != legend or set(answer.probabilities) != set(legend):
                raise ValueError("score legend does not match criteria")
            _validate_distribution(answer.probabilities)
            expected = sum(int(key) * probability for key, probability in answer.probabilities.items())
            # Captured score/probability differences are consistent with independent two-decimal rounding.
            # Propagate half-unit rounding bounds without changing any returned value.
            tolerance = 0.005 * (1 + sum(range(len(legend)))) + 1e-9
            if answer.score > len(legend) - 1 or abs(answer.score - expected) > tolerance:
                raise ValueError("score does not match its distribution")


def _validate_distribution(probabilities: dict[str, float]) -> None:
    # Allow rounding in the wire representation, but never repair the provider's probabilities.
    if abs(sum(probabilities.values()) - 1) > 0.005 * len(probabilities) + 1e-9:
        raise ValueError("probabilities do not sum to one")


def partial_metadata(body: Any) -> dict[str, Any]:
    """Recover independently valid usage/identity even from an unusable answer."""
    result: dict[str, Any] = {}
    if not isinstance(body, dict):
        return result
    for source, target in (
        ("id", "provider_response_id"),
        ("model", "model"),
        ("provider", "provider"),
    ):
        value = body.get(source)
        if isinstance(value, str) and value and len(value) <= 256:
            result[target] = value
    raw_usage = body.get("usage")
    if isinstance(raw_usage, dict):
        fields: dict[str, Any] = {}
        for name in ("input_tokens", "output_tokens"):
            value = raw_usage.get(name)
            if type(value) is int and value >= 0:
                fields[name] = value
        cost = raw_usage.get("cost")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            try:
                if math.isfinite(cost) and cost >= 0:
                    fields["cost"] = cost
            except OverflowError:
                pass  # A JSON integer can exceed float range; other usage fields remain usable.
        if fields:
            result["usage"] = ReportedUsage(**fields)
    return result

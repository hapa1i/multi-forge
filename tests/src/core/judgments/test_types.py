"""Validate typed judgments independently of transport and provider availability."""

import copy

import pytest
from pydantic import ValidationError

from forge.core.judgments import ChoiceQuestion, NoulQuestion, ScoreQuestion
from forge.core.judgments.types import (
    JudgmentResponse,
    partial_metadata,
    validate_answers,
)


def valid_response():
    return {
        "model": "typesafe/jev-1.13-20260917",
        "answers": {
            "choice": {"type": "choice", "choice": "yes", "confidence": 0.8, "probabilities": {"yes": 0.8, "no": 0.2}},
            "noul": {"type": "noul", "noul": 0.9},
            "score": {
                "type": "score",
                "score": 0.8,
                "confidence": 0.7,
                "legend": {"0": "Low", "1": "High"},
                "probabilities": {"0": 0.2, "1": 0.8},
            },
        },
        "usage": {"input_tokens": 100, "output_tokens": 20, "cost": 0.0000042},
    }


def questions():
    return {
        "choice": ChoiceQuestion(instructions="Choose", criteria={"yes": "Yes", "no": "No"}),
        "noul": NoulQuestion(instructions="True?", criteria={"true": "True", "false": "False"}),
        "score": ScoreQuestion(instructions="Score", criteria=["Low", "High"]),
    }


def test_distributions_preserved():
    raw = valid_response()
    response = JudgmentResponse.model_validate(raw)
    validate_answers(response, questions())
    assert response.model_dump(exclude_none=True) == raw


@pytest.mark.parametrize("value", [-0.1, 1.01, float("nan"), float("inf"), True, "0.9"])
def test_invalid_probabilities(value):
    raw = valid_response()
    raw["answers"]["noul"]["noul"] = value
    with pytest.raises(ValidationError):
        JudgmentResponse.model_validate(raw)


@pytest.mark.parametrize("value", [-1, True, 0.5, "3"])
def test_invalid_counts(value):
    raw = valid_response()
    raw["usage"]["input_tokens"] = value
    with pytest.raises(ValidationError):
        JudgmentResponse.model_validate(raw)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r["answers"].pop("noul"),
        lambda r: r["answers"].update(extra={"type": "noul", "noul": 0.9}),
        lambda r: r["answers"].update(choice={"type": "noul", "noul": 0.9}),
        lambda r: r["answers"]["choice"].update(choice="unknown"),
        lambda r: r["answers"]["choice"]["probabilities"].update(yes=0.2),
        lambda r: r["answers"]["score"]["legend"].update({"1": "Changed"}),
        lambda r: r["answers"]["score"].update(score=0.1),
    ],
)
def test_mismatched_answers(mutation):
    raw = copy.deepcopy(valid_response())
    mutation(raw)
    with pytest.raises(ValueError):
        validate_answers(JudgmentResponse.model_validate(raw), questions())


def test_incomplete_noul_criteria():
    with pytest.raises(ValidationError):
        NoulQuestion(instructions="True?", criteria={"true": "Yes"})


def test_usage_survives_invalid_answers():
    raw = valid_response()
    raw["answers"] = "invalid"
    assert partial_metadata(raw)["usage"].input_tokens == 100
    assert partial_metadata({"usage": {"input_tokens": True}}) == {}


def test_captured_score_allows_independently_rounded_fields():
    import json
    from pathlib import Path

    raw = json.loads((Path(__file__).resolve().parents[3] / "fixtures/jev/rounded-score.json").read_text())
    question_set = {
        "damage": NoulQuestion(instructions="Damage?", criteria={"true": "Damage", "false": "Intact"}),
        "owner": ChoiceQuestion(instructions="Owner?", criteria={"payments": "Payment", "account": "Account"}),
        "urgency": ScoreQuestion(
            instructions="Urgency?", criteria=["Cosmetic issue", "One customer blocked", "Service-wide outage"]
        ),
    }
    response = JudgmentResponse.model_validate(raw)
    validate_answers(response, question_set)
    assert response.answers["urgency"].score == 0.99
    assert response.answers["urgency"].probabilities["1"] == 0.98
    raw["answers"]["urgency"]["score"] = 1.2
    with pytest.raises(ValueError, match="distribution"):
        validate_answers(JudgmentResponse.model_validate(raw), question_set)


def test_score_rejects_more_than_ten_levels():
    with pytest.raises(ValidationError):
        ScoreQuestion(instructions="Score", criteria=[str(i) for i in range(11)])


def test_unrepresentable_cost_keeps_valid_counts():
    usage = partial_metadata({"usage": {"input_tokens": 30, "cost": 10**1000}})["usage"]
    assert usage.input_tokens == 30
    assert usage.cost is None

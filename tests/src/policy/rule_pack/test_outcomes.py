"""Covered rule findings must remain separate from permissions and abstentions."""

import pytest

from forge.core.judgments.types import JudgmentResponse
from forge.policy.rule_pack.outcomes import (
    DecisionThresholds,
    ProbabilityBand,
    assess_applicability,
    assess_response,
)


@pytest.fixture
def thresholds():
    # Mechanical test cutoffs only; no rule-quality calibration is implied.
    return DecisionThresholds.model_validate(
        {
            name: {"false_max": 0.1, "true_min": 0.9}
            for name in ("coverage", "compatibility_retention", "independent_boundary")
        }
    )


def response(coverage, retention, boundary):
    return JudgmentResponse.model_validate(
        {
            "model": "fixture-model",
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "answers": {
                name: {"type": "noul", "noul": probability}
                for name, probability in zip(
                    ("coverage", "compatibility_retention", "independent_boundary"),
                    (coverage, retention, boundary),
                    strict=True,
                )
            },
        }
    )


@pytest.mark.parametrize("retention", [0.0, 0.5, 1.0])
@pytest.mark.parametrize("boundary", [0.0, 0.5, 1.0])
@pytest.mark.parametrize("coverage,outcome", [(0.0, "unavailable"), (0.5, "uncertain")])
def test_incomplete_or_uncertain_coverage_never_becomes_a_clean_assessment(
    thresholds, retention, boundary, coverage, outcome
):
    assert assess_response(response(coverage, retention, boundary), thresholds).outcome == outcome


@pytest.mark.parametrize(
    "retention,boundary,outcome,reason",
    [
        (0.0, 0.0, "no_warning", "jev_no_compatibility_retention"),
        (0.0, 0.5, "no_warning", "jev_no_compatibility_retention"),
        (0.0, 1.0, "uncertain", "jev_conflicting_answers"),
        (0.5, 0.0, "uncertain", "jev_retention_uncertain"),
        (0.5, 0.5, "uncertain", "jev_retention_uncertain"),
        (0.5, 1.0, "uncertain", "jev_retention_uncertain"),
        (1.0, 0.0, "warning", "jev_compatibility_retention"),
        (1.0, 0.5, "uncertain", "jev_boundary_uncertain"),
        (1.0, 1.0, "no_warning", "jev_required_boundary"),
    ],
)
def test_covered_answer_combinations(thresholds, retention, boundary, outcome, reason):
    result = assess_response(response(1.0, retention, boundary), thresholds)
    assert (result.outcome, result.reason) == (outcome, reason)
    assert result.diagnostic


def test_cutoffs_are_inclusive_and_probabilities_are_not_multiplied(thresholds):
    result = assess_response(response(0.9, 0.9, 0.1), thresholds)
    assert result.outcome == "warning"
    assert assess_response(response(0.899, 0.9, 0.1), thresholds).outcome == "uncertain"


@pytest.mark.parametrize(
    "probabilities,outcome,reason",
    [
        ((0.65, 1.0, 0.0), "uncertain", "jev_coverage_uncertain"),
        ((1.0, 0.65, 0.0), "uncertain", "jev_retention_uncertain"),
        ((1.0, 0.8, 0.35), "warning", "jev_compatibility_retention"),
        ((1.0, 1.0, 0.65), "no_warning", "jev_required_boundary"),
    ],
)
def test_each_question_uses_its_own_band(probabilities, outcome, reason):
    thresholds = DecisionThresholds.model_validate(
        {
            "coverage": {"false_max": 0.1, "true_min": 0.9},
            "compatibility_retention": {"false_max": 0.2, "true_min": 0.8},
            "independent_boundary": {"false_max": 0.4, "true_min": 0.6},
        }
    )
    result = assess_response(response(*probabilities), thresholds)
    assert (result.outcome, result.reason) == (outcome, reason)


@pytest.mark.parametrize(
    "surface,compatibility_decision,tool_name,outcome,reason",
    [
        ("unknown", "approved", "Edit", "unavailable", "unknown_surface"),
        (
            "internal",
            "unknown",
            "Edit",
            "unavailable",
            "unknown_compatibility_decision",
        ),
        (
            "public_preview",
            "unknown",
            "Edit",
            "unavailable",
            "unknown_compatibility_decision",
        ),
        (
            "internal",
            "not_approved",
            "Write",
            "unavailable",
            "write_without_prior_interface_evidence",
        ),
        (
            "public_preview",
            "not_approved",
            "Write",
            "unavailable",
            "write_without_prior_interface_evidence",
        ),
        ("public_stable", "unknown", "Write", "not_applicable", "stable_surface"),
        (
            "public_preview",
            "approved",
            "Write",
            "not_applicable",
            "approved_preview_exception",
        ),
    ],
)
def test_host_applicability_has_fixed_diagnostics(surface, compatibility_decision, tool_name, outcome, reason):
    result = assess_applicability(
        surface=surface,
        compatibility_decision=compatibility_decision,
        tool_name=tool_name,
    )
    assert result is not None
    assert (result.outcome, result.reason) == (outcome, reason)
    assert result.diagnostic and result.diagnostic != reason


@pytest.mark.parametrize("surface", ["internal", "public_preview"])
@pytest.mark.parametrize("tool_name", ["Edit", "apply_patch"])
def test_host_applicability_defers_covered_actions_to_model(surface, tool_name):
    assert assess_applicability(surface=surface, compatibility_decision="not_approved", tool_name=tool_name) is None


@pytest.mark.parametrize(
    "surface,compatibility_decision,error",
    [
        ("internal", "approved", "Internal approved exceptions"),
        ("unrecognized", "not_approved", "Unsupported surface"),
        ("internal", "unrecognized", "Unsupported surface"),
    ],
)
def test_host_applicability_rejects_invalid_scope_facts(surface, compatibility_decision, error):
    with pytest.raises(ValueError, match=error):
        assess_applicability(
            surface=surface,
            compatibility_decision=compatibility_decision,
            tool_name="Edit",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("false_max", -0.1),
        ("false_max", 0.5),
        ("true_min", 0.5),
        ("true_min", 1.1),
        ("true_min", float("nan")),
        ("true_min", True),
        ("true_min", "0.9"),
    ],
)
def test_bad_cutoffs_are_rejected(field, value):
    with pytest.raises(ValueError):
        ProbabilityBand.model_validate({"false_max": 0.1, "true_min": 0.9, field: value})


def test_all_question_thresholds_are_explicit():
    with pytest.raises(ValueError):
        DecisionThresholds.model_validate({})


@pytest.mark.parametrize("change", ["missing", "extra", "wrong_type"])
def test_answer_contract_failure_is_unavailable(thresholds, change):
    raw = response(1.0, 1.0, 0.0).model_dump()
    if change == "missing":
        del raw["answers"]["coverage"]
    elif change == "extra":
        raw["answers"]["extra"] = {"type": "noul", "noul": 1.0}
    else:
        raw["answers"]["coverage"] = {
            "type": "choice",
            "choice": "yes",
            "confidence": 1.0,
            "probabilities": {"yes": 1.0},
        }
    result = assess_response(JudgmentResponse.model_validate(raw), thresholds)
    assert (result.outcome, result.reason) == ("unavailable", "jev_invalid_response")

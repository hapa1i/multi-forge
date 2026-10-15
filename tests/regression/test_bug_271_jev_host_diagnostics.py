"""PR 271: shared host assessments must have authored diagnostics before runtime reuse."""

import pytest

from forge.policy.rule_pack.outcomes import Assessment

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    "outcome,reason",
    [
        ("unavailable", "unknown_surface"),
        ("unavailable", "unknown_compatibility_decision"),
        ("unavailable", "write_without_prior_interface_evidence"),
        ("not_applicable", "stable_surface"),
        ("not_applicable", "approved_preview_exception"),
        ("unavailable", "jev_missing_saved_response"),
        ("unavailable", "jev_transport_failure"),
        ("unavailable", "jev_response_too_large"),
    ],
)
def test_shared_assessment_reports_host_and_missing_observation_diagnostics(outcome, reason):
    diagnostic = Assessment(outcome, reason).diagnostic
    assert diagnostic and diagnostic != reason

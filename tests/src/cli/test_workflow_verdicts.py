"""Unit tests for _evaluate_verdicts() fail-closed verdict evaluation."""

from __future__ import annotations

from forge.cli.workflow import _evaluate_verdicts
from forge.review.models import ReviewResult


def _result(
    name: str = "model-a",
    stdout: str = "",
    success: bool = True,
    error: str | None = None,
) -> ReviewResult:
    return ReviewResult(name, stdout, "", success, 1.0, error=error)


class TestEmptyAndFailedResults:
    def test_empty_results(self):
        passed, reason = _evaluate_verdicts([])
        assert passed is False
        assert reason == "no results"

    def test_single_failed_worker(self):
        passed, reason = _evaluate_verdicts([_result("gpt-5.5", success=False, error="timeout")])
        assert passed is False
        assert "gpt-5.5" in reason
        assert "failed" in reason

    def test_all_workers_failed(self):
        passed, reason = _evaluate_verdicts(
            [
                _result("model-a", success=False, error="err1"),
                _result("model-b", success=False, error="err2"),
            ]
        )
        assert passed is False
        assert "model-a" in reason


class TestMissingVerdicts:
    def test_free_text_no_json(self):
        """Successful worker with free-form text and no JSON → fail."""
        passed, reason = _evaluate_verdicts([_result(stdout="This code looks good overall.")])
        assert passed is False
        assert "no verdict" in reason

    def test_json_without_verdict_fields(self):
        """JSON present but missing both 'passed' and 'verdict' → fail."""
        passed, reason = _evaluate_verdicts([_result(stdout='```json\n{"findings": [], "score": 8}\n```')])
        assert passed is False
        assert "without verdict fields" in reason

    def test_empty_stdout(self):
        passed, reason = _evaluate_verdicts([_result(stdout="")])
        assert passed is False
        assert "no verdict" in reason

    def test_non_dict_json_treated_as_no_verdict(self):
        """JSON array or primitive is not a valid verdict structure."""
        passed, reason = _evaluate_verdicts([_result(stdout='```json\n[{"passed": true}]\n```')])
        assert passed is False
        assert "no verdict" in reason


class TestPassedField:
    def test_passed_true_bool(self):
        passed, reason = _evaluate_verdicts([_result(stdout='```json\n{"passed": true}\n```')])
        assert passed is True
        assert "accepting" in reason

    def test_passed_false_bool(self):
        passed, reason = _evaluate_verdicts([_result(stdout='```json\n{"passed": false}\n```')])
        assert passed is False

    def test_passed_string_true(self):
        passed, _ = _evaluate_verdicts([_result(stdout='```json\n{"passed": "true"}\n```')])
        assert passed is True

    def test_passed_string_false(self):
        """Regression: bool('false') is True in Python; _coerce_passed handles this."""
        passed, _ = _evaluate_verdicts([_result(stdout='```json\n{"passed": "false"}\n```')])
        assert passed is False

    def test_passed_string_yes(self):
        passed, _ = _evaluate_verdicts([_result(stdout='```json\n{"passed": "yes"}\n```')])
        assert passed is True

    def test_passed_string_no(self):
        passed, _ = _evaluate_verdicts([_result(stdout='```json\n{"passed": "no"}\n```')])
        assert passed is False

    def test_passed_int_1(self):
        passed, _ = _evaluate_verdicts([_result(stdout='```json\n{"passed": 1}\n```')])
        assert passed is True

    def test_passed_int_0(self):
        passed, _ = _evaluate_verdicts([_result(stdout='```json\n{"passed": 0}\n```')])
        assert passed is False


class TestVerdictField:
    def test_accept(self):
        passed, reason = _evaluate_verdicts([_result(stdout='```json\n{"verdict": "ACCEPT"}\n```')])
        assert passed is True
        assert "accepting" in reason

    def test_reject(self):
        passed, _ = _evaluate_verdicts([_result(stdout='```json\n{"verdict": "REJECT"}\n```')])
        assert passed is False

    def test_accept_with_conditions(self):
        passed, _ = _evaluate_verdicts([_result(stdout='```json\n{"verdict": "ACCEPT_WITH_CONDITIONS"}\n```')])
        assert passed is True

    def test_pass_verdict(self):
        passed, _ = _evaluate_verdicts([_result(stdout='```json\n{"verdict": "PASS"}\n```')])
        assert passed is True

    def test_passed_verdict(self):
        passed, _ = _evaluate_verdicts([_result(stdout='```json\n{"verdict": "PASSED"}\n```')])
        assert passed is True

    def test_true_verdict(self):
        passed, _ = _evaluate_verdicts([_result(stdout='```json\n{"verdict": "TRUE"}\n```')])
        assert passed is True

    def test_case_insensitive_verdict(self):
        """Verdict values are uppercased before comparison."""
        passed, _ = _evaluate_verdicts([_result(stdout='```json\n{"verdict": "accept"}\n```')])
        assert passed is True

    def test_unknown_verdict_is_reject(self):
        """Unknown verdict strings are not in _ACCEPTING_VERDICTS → fail."""
        passed, _ = _evaluate_verdicts([_result(stdout='```json\n{"verdict": "MAYBE"}\n```')])
        assert passed is False


class TestPassedFieldTakesPrecedence:
    def test_passed_over_verdict(self):
        """When both 'passed' and 'verdict' are present, 'passed' wins."""
        passed, _ = _evaluate_verdicts([_result(stdout='```json\n{"passed": true, "verdict": "REJECT"}\n```')])
        assert passed is True


class TestMultipleWorkers:
    def test_all_pass(self):
        passed, reason = _evaluate_verdicts(
            [
                _result("m1", stdout='```json\n{"passed": true}\n```'),
                _result("m2", stdout='```json\n{"verdict": "ACCEPT"}\n```'),
                _result("m3", stdout='```json\n{"passed": true}\n```'),
            ]
        )
        assert passed is True
        assert "3" in reason
        assert "accepting" in reason

    def test_one_reject_among_passes(self):
        passed, reason = _evaluate_verdicts(
            [
                _result("m1", stdout='```json\n{"passed": true}\n```'),
                _result("m2", stdout='```json\n{"verdict": "REJECT"}\n```'),
                _result("m3", stdout='```json\n{"passed": true}\n```'),
            ]
        )
        assert passed is False

    def test_one_failed_worker_among_passes(self):
        passed, reason = _evaluate_verdicts(
            [
                _result("m1", stdout='```json\n{"passed": true}\n```'),
                _result("m2", success=False, error="timeout"),
                _result("m3", stdout='```json\n{"passed": true}\n```'),
            ]
        )
        assert passed is False
        assert "m2" in reason
        assert "failed" in reason

    def test_one_missing_verdict_among_passes(self):
        passed, reason = _evaluate_verdicts(
            [
                _result("m1", stdout='```json\n{"passed": true}\n```'),
                _result("m2", stdout="Free text, no JSON"),
                _result("m3", stdout='```json\n{"passed": true}\n```'),
            ]
        )
        assert passed is False
        assert "m2" in reason
        assert "no verdict" in reason

    def test_reason_reports_first_failure(self):
        """When multiple failures, reason cites the first one."""
        passed, reason = _evaluate_verdicts(
            [
                _result("first-bad", success=False, error="err"),
                _result("second-bad", stdout="no json here"),
            ]
        )
        assert passed is False
        assert "first-bad" in reason


class TestReasonDiagnostics:
    def test_reason_on_pass(self):
        _, reason = _evaluate_verdicts([_result(stdout='```json\n{"passed": true}\n```')])
        assert "1" in reason
        assert "accepting" in reason

    def test_reason_on_worker_failure(self):
        _, reason = _evaluate_verdicts([_result("my-model", success=False, error="crash")])
        assert "my-model" in reason
        assert "failed" in reason

    def test_reason_on_no_verdict(self):
        _, reason = _evaluate_verdicts([_result("my-model", stdout="text only")])
        assert "my-model" in reason
        assert "no verdict" in reason

    def test_reason_on_json_without_fields(self):
        _, reason = _evaluate_verdicts([_result("my-model", stdout='```json\n{"score": 5}\n```')])
        assert "my-model" in reason
        assert "without verdict fields" in reason

    def test_reason_on_explicit_reject_is_diagnostic(self):
        """Reason for passed=false includes model name and 'rejected', not just model name."""
        _, reason = _evaluate_verdicts([_result("gpt-5.5", stdout='```json\n{"passed": false}\n```')])
        assert "gpt-5.5" in reason
        assert "rejected" in reason

    def test_reason_on_verdict_reject_is_diagnostic(self):
        _, reason = _evaluate_verdicts([_result("gemini-3", stdout='```json\n{"verdict": "REJECT"}\n```')])
        assert "gemini-3" in reason
        assert "rejected" in reason

"""Tests for forge.review.synthesis."""

from __future__ import annotations

import json

from forge.core.invoker import HeadlessRequest, HeadlessResult
from forge.review.engine import _to_review_result
from forge.review.models import MultiReviewOutput, ReviewResult
from forge.review.synthesis import format_json_output, format_synthesis_prompt


def _output(results: list[ReviewResult] | None = None) -> MultiReviewOutput:
    return MultiReviewOutput(
        prompt="Review src/main.py for issues",
        results=results or [],
    )


def _success(name: str = "model-a", stdout: str = "Looks good") -> ReviewResult:
    return ReviewResult(model_name=name, stdout=stdout, stderr="", success=True, duration_seconds=1.5)


def _failure(name: str = "model-b", error: str = "Timeout") -> ReviewResult:
    return ReviewResult(
        model_name=name,
        stdout="",
        stderr="",
        success=False,
        duration_seconds=10.0,
        error=error,
    )


class TestFormatSynthesisPrompt:
    def test_identical_claude_and_codex_final_text_produces_identical_synthesis_input(self):
        text = "Same final review text"
        claude = _to_review_result(
            HeadlessRequest(argv=["claude", "-p"], prompt="review", env={}, label="worker"),
            HeadlessResult(
                label="worker",
                stdout=text,
                stderr="",
                returncode=0,
                duration_seconds=1.0,
            ),
        )
        codex = _to_review_result(
            HeadlessRequest(
                argv=["codex", "exec", "--json", "--sandbox", "read-only"],
                prompt="review",
                env={},
                label="worker",
                output_format=None,
            ),
            HeadlessResult(
                label="worker",
                stdout=text,
                stderr="",
                returncode=0,
                duration_seconds=1.0,
            ),
        )

        assert claude.stdout == codex.stdout == text
        assert format_synthesis_prompt(_output([claude])) == format_synthesis_prompt(_output([codex]))

    def test_includes_prompt_preview(self):
        text = format_synthesis_prompt(_output([_success()]))
        assert "Review src/main.py" in text

    def test_includes_model_response(self):
        text = format_synthesis_prompt(_output([_success(stdout="Found 3 issues")]))
        assert "Found 3 issues" in text

    def test_includes_error_for_failed_model(self):
        text = format_synthesis_prompt(_output([_failure(error="Timeout after 600s")]))
        assert "Timeout after 600s" in text

    def test_includes_synthesis_request(self):
        text = format_synthesis_prompt(_output([_success()]))
        assert "Synthesis Request" in text

    def test_model_name_as_header(self):
        text = format_synthesis_prompt(_output([_success(name="gpt-5.5")]))
        assert "gpt-5.5" in text

    def test_truncates_long_prompt(self):
        long_prompt = "x" * 1000
        out = MultiReviewOutput(prompt=long_prompt, results=[_success()])
        text = format_synthesis_prompt(out)
        assert "..." in text


class TestFormatJsonOutput:
    def test_valid_json(self):
        text = format_json_output(_output([_success()]))
        data = json.loads(text)
        assert "results" in data

    def test_includes_prompt(self):
        data = json.loads(format_json_output(_output([_success()])))
        assert data["prompt"] == "Review src/main.py for issues"

    def test_includes_counts(self):
        data = json.loads(format_json_output(_output([_success(), _failure()])))
        assert data["successful"] == 1
        assert data["failed"] == 1

    def test_result_structure(self):
        data = json.loads(format_json_output(_output([_success(name="gpt-5.5", stdout="output")])))
        result = data["results"]["gpt-5.5"]
        assert result["response"] == "output"
        assert result["success"] is True
        assert result["error"] is None
        assert "duration_seconds" in result

    def test_failed_result_has_null_response(self):
        data = json.loads(format_json_output(_output([_failure(error="Timeout")])))
        result = data["results"]["model-b"]
        assert result["response"] is None
        assert result["error"] == "Timeout"
        assert result["success"] is False

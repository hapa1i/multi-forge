"""Tests for forge.review.models."""

from __future__ import annotations

import pytest

from forge.core.models.catalog import get_compact_name, get_default_model
from forge.review.models import (
    DEFAULT_MODELS,
    ModelSpec,
    MultiReviewOutput,
    ReviewResult,
    resolve_model_specs,
)

# DEFAULT_MODELS keys use compact names (e.g., "gemini-3.1-pro" not "gemini-3.1-pro-preview")
OPENAI_DEFAULT = get_compact_name(get_default_model("openai", "opus"))
GEMINI_DEFAULT = get_compact_name(get_default_model("gemini", "opus"))
ANTHROPIC_DEFAULT = get_default_model("anthropic", "opus")


class TestModelSpec:
    def test_dataclass_fields(self):
        spec = ModelSpec(name="test", proxy="my-proxy", model_flag="opus", description="Test")
        assert spec.name == "test"
        assert spec.proxy == "my-proxy"
        assert spec.model_flag == "opus"

    def test_none_proxy_for_direct(self):
        spec = ModelSpec(name="direct", proxy=None, model_flag="opus", description="Direct")
        assert spec.proxy is None

    def test_prompt_defaults_to_none(self):
        spec = ModelSpec(name="test", proxy="p", model_flag=None, description="Test")
        assert spec.prompt is None

    def test_prompt_can_be_set(self):
        spec = ModelSpec(name="test", proxy="p", model_flag=None, description="Test", prompt="custom")
        assert spec.prompt == "custom"


class TestDefaultModels:
    def test_has_expected_entries(self):
        assert OPENAI_DEFAULT in DEFAULT_MODELS
        assert GEMINI_DEFAULT in DEFAULT_MODELS
        assert "claude-opus" in DEFAULT_MODELS

    def test_gpt_uses_proxy(self):
        assert DEFAULT_MODELS[OPENAI_DEFAULT].proxy == "litellm-openai"

    def test_gemini_uses_proxy(self):
        assert DEFAULT_MODELS[GEMINI_DEFAULT].proxy == "litellm-gemini"

    def test_claude_is_direct(self):
        assert DEFAULT_MODELS["claude-opus"].proxy is None
        assert DEFAULT_MODELS["claude-opus"].model_flag == ANTHROPIC_DEFAULT


class TestReviewResult:
    def test_success_result(self):
        r = ReviewResult(
            model_name="test",
            stdout="good output",
            stderr="",
            success=True,
            duration_seconds=1.5,
        )
        assert r.success
        assert r.error is None

    def test_failure_result(self):
        r = ReviewResult(
            model_name="test",
            stdout="",
            stderr="error output",
            success=False,
            duration_seconds=0.5,
            error="Exit code 1",
        )
        assert not r.success
        assert r.error == "Exit code 1"


class TestMultiReviewOutput:
    def test_successful_count(self):
        output = MultiReviewOutput(
            prompt="test",
            results=[
                ReviewResult("a", "ok", "", True, 1.0),
                ReviewResult("b", "", "", False, 1.0, error="fail"),
                ReviewResult("c", "ok", "", True, 1.0),
            ],
        )
        assert output.successful == 2
        assert output.failed == 1

    def test_empty_results(self):
        output = MultiReviewOutput(prompt="test")
        assert output.successful == 0
        assert output.failed == 0


class TestResolveModelSpecs:
    def test_none_returns_all_defaults(self):
        specs = resolve_model_specs(None)
        assert len(specs) == len(DEFAULT_MODELS)
        assert [s.name for s in specs] == list(DEFAULT_MODELS.keys())

    def test_empty_string_returns_all_defaults(self):
        specs = resolve_model_specs("")
        assert len(specs) == len(DEFAULT_MODELS)

    def test_specific_models_in_order(self):
        specs = resolve_model_specs(f"{OPENAI_DEFAULT},claude-opus")
        assert [s.name for s in specs] == [OPENAI_DEFAULT, "claude-opus"]

    def test_unknown_model_raises(self):
        with pytest.raises(ValueError, match="nonexistent"):
            resolve_model_specs("nonexistent")

    def test_mixed_valid_invalid_raises(self):
        with pytest.raises(ValueError, match="nonexistent"):
            resolve_model_specs(f"{OPENAI_DEFAULT},nonexistent")

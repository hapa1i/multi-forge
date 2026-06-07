"""Tests for OpenAI-compatible conversion helpers (token + reported-cost extraction)."""

from __future__ import annotations

from types import SimpleNamespace

from forge.core.llm.clients.openai_compat import (
    extract_reported_cost_usd,
    openai_response_to_completion,
)


class TestExtractReportedCostUsd:
    """OpenRouter reports spend in usage.cost; extract it when present, else None."""

    def test_attribute_cost(self):
        usage = SimpleNamespace(cost=0.00234)
        assert extract_reported_cost_usd(usage) == 0.00234

    def test_reported_zero_is_not_none(self):
        """A reported $0 is real evidence (free model), distinct from 'no cost field'."""
        usage = SimpleNamespace(cost=0.0)
        assert extract_reported_cost_usd(usage) == 0.0

    def test_dict_cost(self):
        assert extract_reported_cost_usd({"cost": 0.0012}) == 0.0012

    def test_model_extra_fallback(self):
        """SDK models stash unknown provider fields in model_extra."""
        usage = SimpleNamespace(model_extra={"cost": 0.005})
        assert extract_reported_cost_usd(usage) == 0.005

    def test_missing_cost_is_none(self):
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
        assert extract_reported_cost_usd(usage) is None

    def test_none_usage_is_none(self):
        assert extract_reported_cost_usd(None) is None

    def test_bool_is_rejected(self):
        """bool is an int subclass; a True must not be read as cost 1.0."""
        assert extract_reported_cost_usd(SimpleNamespace(cost=True)) is None

    def test_non_numeric_string_is_none(self):
        assert extract_reported_cost_usd(SimpleNamespace(cost="not-a-number")) is None


class TestOpenAIResponseToCompletion:
    """Body-level cost rides into CompletionResponse.cost_usd; tokens stay int."""

    @staticmethod
    def _response(usage: object) -> SimpleNamespace:
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="hi", tool_calls=None))],
            usage=usage,
            error=None,
            model_dump=lambda: {"usage": {}},
        )

    def test_extracts_openrouter_body_cost(self):
        usage = SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            prompt_tokens_details=None,
            cost=0.0023,
        )
        result = openai_response_to_completion(self._response(usage), "openrouter")
        assert result.cost_usd == 0.0023
        assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    def test_no_cost_field_leaves_cost_usd_none(self):
        usage = SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            prompt_tokens_details=None,
        )
        result = openai_response_to_completion(self._response(usage), "litellm")
        assert result.cost_usd is None

    def test_no_usage_leaves_cost_usd_none(self):
        result = openai_response_to_completion(self._response(None), "litellm")
        assert result.cost_usd is None
        assert result.usage is None

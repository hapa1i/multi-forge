"""Tests for OpenAI-compatible conversion helpers (token + reported-cost extraction)."""

from __future__ import annotations

from types import SimpleNamespace

import httpx

from forge.core.llm.clients.openai_compat import (
    extract_reported_cost_usd,
    merge_provider_headers,
    openai_response_to_completion,
    provider_trace_headers,
)
from forge.core.llm.types import CompletionResponse, ProviderTraceMeta


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

    # --- provider_meta population (openrouter_observability Phase 2) ---

    def test_provider_meta_openrouter_lifts_gen_id_and_upstream(self):
        # OpenRouter's body.id is the gen-... generation id (probe 1); `provider` names
        # the selected upstream.
        resp = SimpleNamespace(
            id="gen-abc123",
            provider="Azure",
            choices=[SimpleNamespace(message=SimpleNamespace(content="hi", tool_calls=None))],
            usage=None,
            error=None,
            model_dump=lambda: {},
        )
        meta = openai_response_to_completion(resp, "openrouter").provider_meta
        assert meta is not None
        assert meta.provider == "openrouter"
        assert meta.provider_response_id == "gen-abc123"
        assert meta.provider_generation_id == "gen-abc123"
        assert meta.selected_provider == "Azure"

    def test_provider_meta_non_gen_id_has_no_generation_id(self):
        resp = SimpleNamespace(
            id="chatcmpl-1",
            choices=[SimpleNamespace(message=SimpleNamespace(content="hi", tool_calls=None))],
            usage=None,
            error=None,
            model_dump=lambda: {},
        )
        meta = openai_response_to_completion(resp, "litellm").provider_meta
        assert meta is not None
        assert meta.provider == "litellm"
        assert meta.provider_response_id == "chatcmpl-1"
        assert meta.provider_generation_id is None  # body.id is not a gen- id
        assert meta.selected_provider is None

    def test_provider_meta_selected_provider_from_model_extra(self):
        resp = SimpleNamespace(
            id="gen-x",
            model_extra={"provider": "Fireworks"},
            choices=[SimpleNamespace(message=SimpleNamespace(content="hi", tool_calls=None))],
            usage=None,
            error=None,
            model_dump=lambda: {},
        )
        meta = openai_response_to_completion(resp, "openrouter").provider_meta
        assert meta is not None
        assert meta.selected_provider == "Fireworks"


class TestProviderTraceHeaders:
    """Only a tiny allowlist of correlation headers enters the trace plane (Phase 2).

    Shared by the LiteLLM and direct-OpenRouter paths, so it lives in openai_compat.
    """

    def test_keeps_allowlisted_names_and_values(self):
        headers = httpx.Headers({"x-request-id": "req-1", "x-generation-id": "gen-9"})
        assert provider_trace_headers(headers) == {"x-request-id": "req-1", "x-generation-id": "gen-9"}

    def test_drops_non_allowlisted_auth_and_cookies(self):
        headers = httpx.Headers(
            {
                "x-request-id": "req-1",
                "authorization": "Bearer secret",
                "set-cookie": "session=abc",
                "x-random-thing": "nope",
            }
        )
        assert provider_trace_headers(headers) == {"x-request-id": "req-1"}

    def test_none_when_nothing_allowlisted(self):
        assert provider_trace_headers(httpx.Headers({"content-type": "application/json"})) is None

    def test_none_headers(self):
        assert provider_trace_headers(None) is None

    def test_plain_dict_lowercased(self):
        assert provider_trace_headers({"X-LiteLLM-Call-Id": "call-1"}) == {"x-litellm-call-id": "call-1"}

    def test_non_dict_like_is_none(self):
        assert provider_trace_headers(42) is None


class TestMergeProviderHeaders:
    """merge_provider_headers attaches allowlisted headers to provider_meta (Phase 2)."""

    def test_populates_headers_on_existing_meta(self):
        completion = CompletionResponse(text="hi", provider_meta=ProviderTraceMeta(provider="openrouter"))
        merged = merge_provider_headers(
            completion,
            httpx.Headers({"x-request-id": "req-7", "authorization": "Bearer s"}),
            "openrouter",
        )
        assert merged.provider_meta is not None
        assert merged.provider_meta.headers == {"x-request-id": "req-7"}

    def test_creates_meta_when_absent(self):
        merged = merge_provider_headers(
            CompletionResponse(text="hi"),  # provider_meta None
            httpx.Headers({"x-generation-id": "gen-1"}),
            "openrouter",
        )
        assert merged.provider_meta is not None
        assert merged.provider_meta.provider == "openrouter"
        assert merged.provider_meta.headers == {"x-generation-id": "gen-1"}

    def test_no_allowlisted_headers_leaves_completion_unchanged(self):
        meta = ProviderTraceMeta(provider="openrouter", provider_generation_id="gen-x")
        completion = CompletionResponse(text="hi", provider_meta=meta)
        merged = merge_provider_headers(
            completion,
            httpx.Headers({"content-type": "application/json"}),
            "openrouter",
        )
        assert merged.provider_meta is not None
        assert merged.provider_meta.headers is None
        assert merged.provider_meta.provider_generation_id == "gen-x"  # preserved

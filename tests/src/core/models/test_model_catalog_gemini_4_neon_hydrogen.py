"""Gemini 4 Neon and Hydrogen are the Gemini defaults and add a fourth thinking level."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from forge.config import TierOverride
from forge.core.llm.clients.openai_compat import build_chat_completion_kwargs
from forge.core.llm.types import Message, ModelHyperparameters, ModelReasoningEffort
from forge.core.models import get_model_spec, load_model_catalog, resolve_model_id
from forge.core.models.model_routes import (
    load_model_route_catalog,
    normalize_model_route_request,
)
from forge.proxy.reasoning import resolve_reasoning_effort_record

MODELS = ("gemini-4-neon", "gemini-4-hydrogen")
EFFORTS = ("low", "medium", "high", "xhigh")
PROVIDER_PREFIXES = ("google", "gemini", "vertex_ai")


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("prefix", ["", *(f"{prefix}/" for prefix in PROVIDER_PREFIXES)])
def test_provider_aliases_share_one_route_identity(model: str, prefix: str) -> None:
    alias = f"{prefix}{model}"
    request = normalize_model_route_request(alias)

    assert resolve_model_id(alias) == model
    assert request.requested_model == model
    assert request.route_key == model
    assert request.claude_tier is None
    assert request.transport_1m is False


def test_gemini_defaults_use_hydrogen_and_neon() -> None:
    assert load_model_catalog().defaults["gemini"] == {
        "haiku": "gemini-4-hydrogen",
        "sonnet": "gemini-4-neon",
        "opus": "gemini-4-neon",
    }


@pytest.mark.parametrize("model", MODELS)
def test_capabilities_add_xhigh_and_default_to_high(model: str) -> None:
    spec = get_model_spec(model)

    assert spec.context_window_tokens == 1_048_576
    assert spec.max_output_tokens == 65_536
    assert spec.prompt_cache_mechanism == "auto"
    assert spec.supports_images is True
    assert spec.supports_thinking is True
    assert spec.supports_sampling_overrides is False
    assert spec.supports_top_p is False
    assert spec.native_thinking_param == "thinking_level"
    assert spec.thinking_levels == EFFORTS
    assert spec.litellm_reasoning_efforts == EFFORTS
    assert spec.default_thinking_level == "high"
    assert spec.default_reasoning_effort == "high"


@pytest.mark.parametrize("model", ["gemini-4-carbon", "gemini-4-argon", "gemini-3.8-flash"])
def test_prior_defaults_keep_their_three_levels(model: str) -> None:
    spec = get_model_spec(model)

    assert spec.litellm_reasoning_efforts == ("low", "medium", "high")
    assert spec.default_reasoning_effort == "medium"


@pytest.mark.parametrize(
    ("model", "coverage_model", "preferred_template"),
    [
        ("gemini-4-neon", "gemini-4-carbon", "openrouter-gemini"),
        ("gemini-4-hydrogen", "gemini-3.8-flash", "openrouter-gemini-flash"),
    ],
)
def test_routes_match_the_replaced_default_with_provider_spelling(
    model: str, coverage_model: str, preferred_template: str
) -> None:
    catalog = load_model_route_catalog()
    routes = catalog.models[model]

    assert [(route.source_id, route.template) for route in routes] == [
        (route.source_id, route.template) for route in catalog.models[coverage_model]
    ]
    assert routes[0].template == preferred_template
    for route in routes:
        assert route.source_id is not None
        expected_prefix = {"openrouter": "google", "litellm-remote": "vertex_ai", "litellm-gemini-local": "gemini"}[
            route.source_id
        ]
        assert route.model_ref == f"{expected_prefix}/{model}"


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("effort", EFFORTS)
def test_accepts_every_supported_explicit_effort(model: str, effort: str) -> None:
    record = resolve_reasoning_effort_record(
        SimpleNamespace(reasoning_effort=effort),
        tier_override=None,
        model_id=f"google/{model}",
        request_id="gemini-4-explicit",
    )

    assert record.resolved == effort


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("effort", ["none", "disable", "minimal", "max"])
def test_rejects_explicit_unsupported_effort(model: str, effort: str) -> None:
    with pytest.raises(HTTPException) as error:
        resolve_reasoning_effort_record(
            SimpleNamespace(reasoning_effort=effort),
            tier_override=None,
            model_id=f"google/{model}",
            request_id="gemini-4-explicit",
        )

    assert error.value.status_code == 400
    assert "not supported" in str(error.value.detail)


@pytest.mark.parametrize("model", MODELS)
def test_clamps_derived_thinking_disabled_to_low(model: str) -> None:
    record = resolve_reasoning_effort_record(
        SimpleNamespace(thinking={"type": "disabled"}),
        tier_override=None,
        model_id=f"google/{model}",
        request_id="gemini-4-derived",
    )

    assert record.resolved == "low"


@pytest.mark.parametrize(
    ("model", "expected"), [("gemini-4-neon", "xhigh"), ("gemini-4-hydrogen", "xhigh"), ("gemini-4-carbon", "high")]
)
def test_large_thinking_budget_reaches_xhigh_only_on_the_new_models(model: str, expected: str) -> None:
    record = resolve_reasoning_effort_record(
        SimpleNamespace(thinking={"type": "enabled", "budget_tokens": 32_000}),
        tier_override=TierOverride(reasoning_effort="medium"),
        model_id=f"google/{model}",
        request_id="gemini-4-budget",
    )

    assert record.derived == "xhigh"
    assert record.resolved == expected


@pytest.mark.parametrize("model", MODELS)
def test_clamps_opted_in_client_max_to_xhigh(model: str) -> None:
    record = resolve_reasoning_effort_record(
        SimpleNamespace(output_config={"effort": "max"}, thinking={"type": "adaptive"}),
        tier_override=TierOverride(reasoning_effort="medium"),
        model_id=f"google/{model}",
        request_id="gemini-4-client",
        honor_client_effort=True,
    )

    assert record.source == "client"
    assert record.resolved == "xhigh"


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("prefix", PROVIDER_PREFIXES)
@pytest.mark.parametrize("effort", EFFORTS)
def test_request_preserves_tools_and_effort_without_sampling(
    model: str, prefix: str, effort: ModelReasoningEffort
) -> None:
    model_ref = f"{prefix}/{model}"
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]
    params = ModelHyperparameters(
        max_tokens=65_536,
        temperature=0.7,
        top_p=0.9,
        reasoning_effort=effort,
        extra={
            "openai": {
                "top_k": 40,
                "tool_choice": "auto",
                "extra_body": {"temperature": 0.5, "top_p": 0.8, "top_k": 20},
            }
        },
    )
    original_params = params.model_dump()

    request = build_chat_completion_kwargs(model_ref, [Message(role="user", content="Inspect the code")], tools, params)

    assert request["model"] == model_ref
    assert request["max_tokens"] == 65_536
    assert request["reasoning_effort"] == effort
    assert request["tools"] == tools
    assert request["tool_choice"] == "auto"
    assert {"temperature", "top_p", "top_k"}.isdisjoint(request)
    assert {"temperature", "top_p", "top_k"}.isdisjoint(request["extra_body"])
    assert params.model_dump() == original_params

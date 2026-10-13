"""Gemini 4 Argon routing and request constraints preserve older model pins."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from forge.core.llm.clients.openai_compat import build_chat_completion_kwargs
from forge.core.llm.types import Message, ModelHyperparameters, ModelReasoningEffort
from forge.core.models import get_model_spec, load_model_catalog, resolve_model_id
from forge.core.models.model_routes import (
    load_model_route_catalog,
    normalize_model_route_request,
)
from forge.proxy.reasoning import resolve_reasoning_effort


@pytest.mark.parametrize(
    "alias",
    [
        "gemini-4-argon",
        "google/gemini-4-argon",
        "gemini/gemini-4-argon",
        "vertex_ai/gemini-4-argon",
    ],
)
def test_argon_provider_aliases_share_one_route_identity(alias: str) -> None:
    request = normalize_model_route_request(alias)

    assert request.requested_model == "gemini-4-argon"
    assert request.route_key == "gemini-4-argon"
    assert request.claude_tier is None
    assert request.transport_1m is False


def test_argon_replaces_pro_defaults_without_changing_explicit_prior_models() -> None:
    catalog = load_model_catalog()

    assert catalog.defaults["gemini"] == {
        "haiku": "gemini-3.8-flash",
        "sonnet": "gemini-4-argon",
        "opus": "gemini-4-argon",
    }
    for model in ("gemini-3.1-pro-preview", "gemini-2.5-pro"):
        for prefix in ("", "google/", "gemini/", "vertex_ai/"):
            assert resolve_model_id(f"{prefix}{model}") == model
    assert get_model_spec("gemini-3.1-pro-preview").thinking_levels == ("low", "high")
    assert get_model_spec("gemini-3.1-pro-preview").default_reasoning_effort == "high"


def test_argon_capabilities_exclude_unsupported_sampling_and_thinking_levels() -> None:
    spec = get_model_spec("gemini-4-argon")

    assert spec.context_window_tokens == 1_048_576
    assert spec.max_output_tokens == 65_536
    assert spec.supports_images is True
    assert spec.supports_thinking is True
    assert spec.supports_sampling_overrides is False
    assert spec.supports_top_p is False
    assert spec.native_thinking_param == "thinking_level"
    assert spec.thinking_levels == ("low", "medium", "high")
    assert spec.litellm_reasoning_efforts == ("low", "medium", "high")
    assert spec.default_thinking_level == "medium"
    assert spec.default_reasoning_effort == "medium"


def test_argon_routes_retain_pro_family_template_coverage_and_provider_spelling() -> None:
    catalog = load_model_route_catalog()
    routes = catalog.models["gemini-4-argon"]
    prior = catalog.models["gemini-3.1-pro-preview"]

    assert {(route.source_id, route.template) for route in routes} == {
        (route.source_id, route.template) for route in prior
    }
    assert routes[0].template == "openrouter-gemini"
    for route in routes:
        assert route.source_id is not None
        expected_prefix = {
            "openrouter": "google",
            "litellm-remote": "vertex_ai",
            "litellm-gemini-local": "gemini",
        }[route.source_id]
        assert route.model_ref == f"{expected_prefix}/gemini-4-argon"


@pytest.mark.parametrize("effort", ["none", "disable", "minimal", "xhigh", "max"])
def test_argon_rejects_explicit_unsupported_effort(effort: str) -> None:
    with pytest.raises(HTTPException) as error:
        resolve_reasoning_effort(
            SimpleNamespace(reasoning_effort=effort),
            tier_override=None,
            model_id="google/gemini-4-argon",
            request_id="argon-explicit",
        )

    assert error.value.status_code == 400
    assert "not supported" in str(error.value.detail)


def test_argon_clamps_derived_thinking_disabled_to_low() -> None:
    assert (
        resolve_reasoning_effort(
            SimpleNamespace(thinking={"type": "disabled"}),
            tier_override=None,
            model_id="google/gemini-4-argon",
            request_id="argon-derived",
        )
        == "low"
    )


@pytest.mark.parametrize(
    "model",
    ["google/gemini-4-argon", "gemini/gemini-4-argon", "vertex_ai/gemini-4-argon"],
)
@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_argon_request_preserves_tools_and_effort_without_sampling(model: str, effort: ModelReasoningEffort) -> None:
    tools = [
        {
            "type": "function",
            "function": {"name": "lookup", "parameters": {"type": "object"}},
        }
    ]
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

    request = build_chat_completion_kwargs(model, [Message(role="user", content="Inspect the code")], tools, params)

    assert request["model"] == model
    assert request["max_tokens"] == 65_536
    assert request["reasoning_effort"] == effort
    assert request["tools"] == tools
    assert request["tool_choice"] == "auto"
    assert {"temperature", "top_p", "top_k"}.isdisjoint(request)
    assert {"temperature", "top_p", "top_k"}.isdisjoint(request["extra_body"])
    assert params.model_dump() == original_params

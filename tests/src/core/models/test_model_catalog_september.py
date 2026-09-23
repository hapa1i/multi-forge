"""Provider contracts for the September 2026 model additions."""

import pytest

from forge.core.models import get_model_spec, load_model_catalog, resolve_model_id
from forge.core.models.catalog import _load_catalog_yaml
from forge.core.models.model_routes import (
    load_model_route_catalog,
    normalize_model_route_request,
)


@pytest.mark.parametrize("model", ["gpt-6-sol", "gpt-6-sol-pro", "gpt-6-luna", "gpt-6-luna-pro"])
def test_gpt6_sol_and_luna_allow_none_but_route_reasoning_through_responses(model: str) -> None:
    spec = get_model_spec(model)

    assert resolve_model_id(f"openai/{model}") == model
    assert resolve_model_id(model.removeprefix("gpt-6-")) == model
    assert spec.context_window_tokens == 1_050_000
    assert spec.max_output_tokens == 128_000
    assert spec.supports_images is True
    assert spec.use_responses_api is True
    assert spec.supports_sampling_overrides is (not model.endswith("-pro"))
    assert spec.supports_top_p is (not model.endswith("-pro"))
    assert spec.sampling_requires_no_reasoning is (not model.endswith("-pro"))
    assert spec.litellm_reasoning_efforts == ("none", "low", "medium", "high", "xhigh", "max")
    assert spec.default_reasoning_effort == "medium"

    routes = load_model_route_catalog().models[model]
    assert routes[0].template == "openrouter-openai"
    if model.endswith("-pro"):
        # Pro is an OpenRouter slug; OpenAI represents it with reasoning.mode.
        assert {route.source_id for route in routes} == {"openrouter"}
    else:
        assert {route.source_id for route in routes} == {
            "openrouter",
            "codex-responses-local",
            "litellm-openai-local",
            "litellm-remote",
        }


@pytest.mark.parametrize(
    "alias",
    ["opus", "claude-opus", "opus-5.5", "opus-5-5", "anthropic/claude-opus-5.5", "anthropic/claude-opus-5-5"],
)
def test_opus55_aliases_share_direct_route_without_retargeting_opus5(alias: str) -> None:
    request = normalize_model_route_request(alias)

    assert request.requested_model == "claude-opus-5-5"
    assert request.route_key == "claude-opus-5-5"
    assert request.claude_tier == "opus"
    assert resolve_model_id("opus-5") == "claude-opus-5"
    assert resolve_model_id("anthropic/claude-opus-5") == "claude-opus-5"


def test_opus55_adopts_medium_effort_without_changing_prior_versions() -> None:
    catalog = load_model_catalog()
    spec = get_model_spec("claude-opus-5-5")

    assert catalog.defaults["anthropic"]["opus"] == "claude-opus-5-5"
    assert catalog.defaults["openrouter"]["opus"] == "claude-opus-5-5"
    assert spec.context_window_tokens == 1_000_000
    assert spec.max_output_tokens == 128_000
    assert spec.supports_1m_context is True
    assert spec.thinking_modes == ("adaptive",)
    assert spec.litellm_reasoning_efforts == ("low", "medium", "high", "xhigh", "max")
    assert spec.default_reasoning_effort == "medium"
    assert spec.supports_sampling_overrides is False
    assert spec.supports_top_p is False
    assert get_model_spec("claude-opus-5").default_reasoning_effort == "high"
    assert _load_catalog_yaml()["models"]["claude-opus-5-5"]["prompt_caching"]["min_tokens"] == 512


@pytest.mark.parametrize(
    ("model", "provider", "vision"),
    [
        ("deepseek-v4.1-flash", "deepseek", True),
        ("deepseek-v4-pro-0813", "deepseek", False),
        ("qwen3.8-flash", "qwen", True),
        ("qwen3.8-max-0902", "qwen", True),
        ("glm-5.3-flash", "z-ai", True),
        ("glm-5.3-flashx", "z-ai", True),
    ],
)
def test_openrouter_models_preserve_their_provider_identity(model: str, provider: str, vision: bool) -> None:
    assert resolve_model_id(f"{provider}/{model}") == model
    assert get_model_spec(model).supports_images is vision
    routes = load_model_route_catalog().models[model]
    assert {route.source_id for route in routes} == {"openrouter"}
    assert {route.model_ref for route in routes} == {f"{provider}/{model}"}
    family = "glm" if provider == "z-ai" else provider
    assert routes[0].template == f"openrouter-{family}"


@pytest.mark.parametrize("model", ["deepseek-v4.1-flash", "deepseek-v4-pro-0813"])
def test_deepseek_new_releases_use_max_instead_of_xhigh(model: str) -> None:
    spec = get_model_spec(model)

    assert spec.context_window_tokens == 1_048_576
    assert spec.max_output_tokens == 384_000
    assert spec.litellm_reasoning_efforts == ("low", "high", "max")
    assert spec.default_reasoning_effort == "high"


def test_qwen_flash_does_not_advertise_max_snapshot_effort_controls() -> None:
    flash = get_model_spec("qwen3.8-flash")
    maximum = get_model_spec("qwen3.8-max-0902")

    assert flash.supports_thinking is True
    assert flash.native_thinking_param is None
    assert flash.litellm_reasoning_efforts is None
    assert flash.default_reasoning_effort is None
    assert maximum.litellm_reasoning_efforts == ("minimal", "low", "medium", "high", "xhigh")
    assert maximum.default_reasoning_effort == "xhigh"
    for spec in (flash, maximum):
        assert spec.context_window_tokens == 1_000_000
        assert spec.max_output_tokens == 131_072


@pytest.mark.parametrize("model", ["glm-5.3-flash", "glm-5.3-flashx"])
def test_glm_flash_uses_the_official_envelope_and_efforts(model: str) -> None:
    spec = get_model_spec(model)

    assert spec.context_window_tokens == 1_048_576
    assert spec.max_output_tokens == 131_072
    assert spec.litellm_reasoning_efforts == ("low", "high", "max")
    assert spec.default_reasoning_effort == "max"

"""October OpenRouter alternatives keep model identity and request constraints."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from forge.core.models import get_model_spec, resolve_model_id
from forge.core.models.model_routes import normalize_model_route_request
from forge.proxy.reasoning import resolve_reasoning_effort


@pytest.mark.parametrize(
    ("model", "prefix", "max_output", "efforts", "default_effort"),
    [
        ("kimi-k3.1-pro", "moonshotai", 943_718, ("low", "high", "max"), "max"),
        ("minimax-m3.1-flash", "minimax", 524_288, ("low", "medium", "high", "xhigh", "max"), "max"),
        ("deepseek-v4.1-flash-1017", "deepseek", 393_216, ("low", "high", "max"), "high"),
    ],
)
def test_october_model_identity_and_provider_envelope(
    model: str, prefix: str, max_output: int, efforts: tuple[str, ...], default_effort: str
) -> None:
    slug = f"{prefix}/{model}"
    assert resolve_model_id(slug) == model
    assert normalize_model_route_request(slug).route_key == model
    spec = get_model_spec(slug)
    assert spec.context_window_tokens == 1_048_576
    assert spec.max_output_tokens == max_output
    assert spec.supports_images is True
    assert spec.supports_forced_tool_choice is (model != "kimi-k3.1-pro")
    assert spec.prompt_cache_mechanism == "auto"
    assert spec.native_thinking_param == "reasoning_effort"
    assert spec.litellm_reasoning_efforts == efforts
    assert spec.default_reasoning_effort == default_effort
    for effort in efforts:
        assert (
            resolve_reasoning_effort(
                SimpleNamespace(reasoning_effort=effort),
                tier_override=None,
                model_id=slug,
                request_id="october-explicit",
            )
            == effort
        )


@pytest.mark.parametrize("model", ["moonshotai/kimi-k3.1-pro", "minimax/minimax-m3.1-flash"])
def test_always_thinking_models_reject_explicit_off_and_clamp_derived_off(model: str) -> None:
    with pytest.raises(HTTPException) as error:
        resolve_reasoning_effort(
            SimpleNamespace(reasoning_effort="none"), tier_override=None, model_id=model, request_id="explicit-off"
        )
    assert error.value.status_code == 400
    assert (
        resolve_reasoning_effort(
            SimpleNamespace(thinking={"type": "disabled"}),
            tier_override=None,
            model_id=model,
            request_id="derived-off",
        )
        == "low"
    )


def test_deepseek_snapshot_does_not_retarget_undated_model() -> None:
    assert resolve_model_id("v4.1-flash-1017") == "deepseek-v4.1-flash-1017"
    assert resolve_model_id("v4.1-flash") == "deepseek-v4.1-flash"


def test_minimax_m3_retains_its_original_effort_surface() -> None:
    assert get_model_spec("minimax-m3").litellm_reasoning_efforts is None

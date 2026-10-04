"""GPT-6.1 Sol aliases and request constraints preserve explicit prior versions."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from forge.core.models import get_model_spec, load_model_catalog, resolve_model_id
from forge.core.models.model_routes import normalize_model_route_request
from forge.proxy.reasoning import resolve_reasoning_effort


@pytest.mark.parametrize("alias", ["sol", "gpt-sol", "gpt-6.1-sol", "openai/gpt-6.1-sol"])
def test_sol_aliases_adopt_61_without_retargeting_versioned_pins(alias: str) -> None:
    request = normalize_model_route_request(alias)

    assert request.requested_model == "gpt-6.1-sol"
    assert request.route_key == "gpt-6.1-sol"
    assert resolve_model_id("gpt-6-sol") == "gpt-6-sol"
    assert resolve_model_id("openai/gpt-6-sol") == "gpt-6-sol"
    assert load_model_catalog().defaults["openai"]["opus"] == "gpt-6-astra"
    spec = get_model_spec(alias)
    assert spec.context_window_tokens == 1_050_000
    assert spec.max_output_tokens == 128_000
    assert spec.use_responses_api is True
    assert spec.supports_images is True
    assert spec.supports_sampling_overrides is False
    assert spec.supports_top_p is False
    assert spec.default_reasoning_effort == "medium"
    assert spec.litellm_reasoning_efforts == ("low", "medium", "high", "xhigh", "max")


@pytest.mark.parametrize("effort", ["none", "minimal"])
def test_sol61_rejects_explicit_unsupported_efforts_but_clamps_thinking_off(effort: str) -> None:
    with pytest.raises(HTTPException) as error:
        resolve_reasoning_effort(
            SimpleNamespace(reasoning_effort=effort),
            tier_override=None,
            model_id="openai/gpt-6.1-sol",
            request_id="sol61-explicit",
        )
    assert error.value.status_code == 400
    assert "not supported" in str(error.value.detail)

    assert (
        resolve_reasoning_effort(
            SimpleNamespace(thinking={"type": "disabled"}),
            tier_override=None,
            model_id="openai/gpt-6.1-sol",
            request_id="sol61-derived",
        )
        == "low"
    )

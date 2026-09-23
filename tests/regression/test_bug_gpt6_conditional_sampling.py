"""GPT-6 sampling is validated for tiers and filtered for model alternatives."""

import pytest

from forge.config.dataclass_utils import dict_to_dataclass
from forge.config.loader import load_proxy_instance_config_from_dict
from forge.config.schema import ForgeConfig, ProviderConfig, ProxyInstanceConfig
from forge.core.llm.clients.openai_compat import build_chat_completion_kwargs
from forge.core.llm.clients.openrouter import OpenRouterClient
from forge.core.llm.types import ModelHyperparameters, ModelReasoningEffort

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("config_kind", ["template", "instance"])
@pytest.mark.parametrize("model", ["gpt-6-sol", "openai/gpt-6-luna"])
@pytest.mark.parametrize("effort", [None, "medium", "high"])
@pytest.mark.parametrize("temperature", [0.0, 0.7])
def test_tier_temperature_requires_explicit_no_reasoning(
    config_kind: str, model: str, effort: str | None, temperature: float
) -> None:
    override: dict[str, float | str] = {"temperature": temperature}
    if effort is not None:
        override["reasoning_effort"] = effort

    with pytest.raises(ValueError, match=r"tier_overrides.sonnet.reasoning_effort='none'"):
        _load_proxy_config(config_kind, {"tiers": {"sonnet": model}, "tier_overrides": {"sonnet": override}})


@pytest.mark.parametrize("config_kind", ["template", "instance"])
@pytest.mark.parametrize("model", ["gpt-6-sol", "openai/gpt-6-luna"])
def test_tier_temperature_is_accepted_with_no_reasoning(config_kind: str, model: str) -> None:
    config = _load_proxy_config(
        config_kind,
        {
            "tiers": {"sonnet": model},
            "tier_overrides": {"sonnet": {"temperature": 0.7, "reasoning_effort": "none"}},
        },
    )

    assert config.tier_overrides.sonnet is not None
    assert config.tier_overrides.sonnet.temperature == 0.7
    assert config.tier_overrides.sonnet.reasoning_effort == "none"


@pytest.mark.parametrize("config_kind", ["template", "instance"])
@pytest.mark.parametrize("model", ["gpt-6-sol", "openai/gpt-6-luna"])
def test_tier_keeps_default_reasoning_without_temperature(config_kind: str, model: str) -> None:
    config = _load_proxy_config(
        config_kind, {"tiers": {"sonnet": model}, "tier_overrides": {"sonnet": {"verbosity": "low"}}}
    )

    assert config.tier_overrides.sonnet is not None
    assert config.tier_overrides.sonnet.temperature is None
    assert config.tier_overrides.sonnet.reasoning_effort is None


@pytest.mark.parametrize("config_kind", ["template", "instance"])
@pytest.mark.parametrize("model", ["gpt-6-sol", "openai/gpt-6-luna"])
def test_alternative_preserves_default_model_temperature_and_filters_request(config_kind: str, model: str) -> None:
    config = _load_proxy_config(
        config_kind,
        {
            "tiers": {"sonnet": "openai/gpt-4.1"},
            "tier_overrides": {"sonnet": {"temperature": 0.7}},
            "model_alternatives": {"sonnet": {model: model}},
        },
    )
    override = config.tier_overrides.sonnet
    assert override is not None
    params = ModelHyperparameters(temperature=override.temperature)

    default_request = build_chat_completion_kwargs(config.tiers.sonnet, [], None, params)
    alternative_request = build_chat_completion_kwargs(model, [], None, params)

    assert default_request["temperature"] == 0.7
    assert "temperature" not in alternative_request
    assert override.temperature == 0.7


def _load_proxy_config(config_kind: str, provider_data: dict) -> ProviderConfig | ProxyInstanceConfig:
    if config_kind == "template":
        config = dict_to_dataclass(
            ForgeConfig, {"proxy": {"family": "openai", "openrouter": provider_data}}, strict=True
        )
        return config.proxy.openrouter
    return load_proxy_instance_config_from_dict(
        {
            "provider": "openrouter",
            "proxy_endpoint": "http://localhost:8084",
            "port": 8084,
            "upstream_base_url": "https://openrouter.ai/api/v1",
            **provider_data,
        }
    )


@pytest.mark.parametrize("model", ["openai/gpt-6-sol", "openai/gpt-6-luna"])
@pytest.mark.parametrize(
    ("flat_effort", "nested_effort", "effective_effort"),
    [("none", "medium", "none"), ("medium", "none", "medium"), (None, "none", "none"), (None, "medium", "medium")],
)
def test_sampling_follows_the_reasoning_effort_sent_to_openrouter(
    model: str, flat_effort: ModelReasoningEffort | None, nested_effort: str, effective_effort: str
) -> None:
    params = ModelHyperparameters(
        temperature=0.7,
        top_p=0.8,
        reasoning_effort=flat_effort,
        extra={"openai": {"extra_body": {"reasoning": {"effort": nested_effort}, "temperature": 0.6, "top_p": 0.9}}},
    )

    request = OpenRouterClient._translate_params(build_chat_completion_kwargs(model, [], None, params))
    extra_body = request.pop("extra_body")
    wire_body = {**request, **extra_body}

    assert wire_body["reasoning"] == {"effort": effective_effort}
    if effective_effort == "none":
        assert wire_body["temperature"] == 0.6
        assert wire_body["top_p"] == 0.9
    else:
        assert "temperature" not in wire_body
        assert "top_p" not in wire_body

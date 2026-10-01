"""Sonnet 5.5 adoption retains prior pins and unrelated family defaults."""

import pytest

from forge.config import load_config
from forge.core.models import get_model_spec, load_model_catalog, resolve_model_id
from forge.core.models.catalog import _load_catalog_yaml
from forge.core.models.direct_model import resolve_direct_model_pin
from forge.core.models.model_routes import (
    load_model_route_catalog,
    normalize_model_route_request,
)
from forge.review.models import resolve_model_specs


@pytest.mark.parametrize(
    "alias",
    [
        "sonnet",
        "claude-sonnet",
        "sonnet-5.5",
        "sonnet-5-5",
        "claude-sonnet-5.5",
        "anthropic/claude-sonnet-5.5",
        "anthropic/claude-sonnet-5-5",
    ],
)
def test_sonnet55_aliases_use_one_native_route(alias: str) -> None:
    request = normalize_model_route_request(alias)

    assert request.requested_model == "claude-sonnet-5-5"
    assert request.claude_tier == "sonnet"
    routes = load_model_route_catalog().models[request.route_key]
    assert len(routes) == 1
    assert routes[0].model_ref == "claude-sonnet-5-5"
    assert routes[0].runtime == "claude_code"
    assert resolve_model_id("sonnet-5") == "claude-sonnet-5"
    assert resolve_model_id("anthropic/claude-sonnet-5") == "claude-sonnet-5"


def test_sonnet55_defaults_and_capabilities() -> None:
    catalog = load_model_catalog()
    spec = get_model_spec("claude-sonnet-5-5")

    for provider in ("anthropic", "openrouter"):
        assert catalog.defaults[provider]["sonnet"] == "claude-sonnet-5-5"
        assert catalog.defaults[provider]["opus"] == "claude-opus-5-5"
    assert catalog.defaults["gemini"] == {
        "haiku": "gemini-3.8-flash",
        "sonnet": "gemini-3.1-pro-preview",
        "opus": "gemini-3.1-pro-preview",
    }
    assert spec.context_window_tokens == 1_000_000
    assert spec.max_output_tokens == 128_000
    assert spec.supports_1m_context is True
    assert spec.thinking_modes == ("adaptive", "between_tools")
    assert spec.litellm_reasoning_efforts == ("low", "medium", "high", "xhigh", "max")
    assert spec.default_reasoning_effort == "high"
    assert spec.supports_sampling_overrides is False
    assert spec.supports_top_p is False
    assert _load_catalog_yaml()["models"]["claude-sonnet-5-5"]["prompt_caching"]["min_tokens"] == 512


@pytest.mark.parametrize("template", ["openrouter-anthropic", "litellm-anthropic", "litellm-anthropic-local"])
def test_fresh_templates_keep_prior_sonnet_selectable(template: str) -> None:
    config = load_config(template=template)
    provider = getattr(config.proxy, config.proxy.preferred_provider)
    expected = (
        "anthropic/claude-sonnet-5.5"
        if config.proxy.preferred_provider == "openrouter"
        else "anthropic/claude-sonnet-5-5"
    )

    assert provider.tiers.sonnet == expected
    assert provider.model_alternatives["sonnet"]["claude-sonnet-5"] == "anthropic/claude-sonnet-5"


@pytest.mark.parametrize("worker", ["claude-sonnet", "claude-sonnet-5.5", "claude-sonnet-5"])
def test_workflow_and_direct_pins_agree(worker: str) -> None:
    model = resolve_model_specs(worker)[0]
    pin = resolve_direct_model_pin(model.model_id)

    assert model.family == "anthropic"
    assert pin is not None
    assert pin.canonical_model == ("claude-sonnet-5" if worker.endswith("-5") else "claude-sonnet-5-5")

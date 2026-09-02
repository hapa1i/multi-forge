"""Pure helpers for the effective proxy model routes used at dispatch."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from forge.core.models.model_reference import strip_transport_model_suffix

# Full bundled-default/alternative audit against OpenRouter's ZDR endpoint
# catalog on 2026-08-21, refreshed for Fable 5.1 on 2026-09-02. These eight
# slugs had no eligible endpoint. Request-level provider.zdr remains authoritative
# if this dated snapshot becomes stale.
BUILTIN_OPENROUTER_ZDR_FALLBACKS = {
    "anthropic/claude-fable-5.1": "anthropic/claude-opus-5",
    "anthropic/claude-fable-5": "anthropic/claude-opus-5",
    "qwen/qwen3.6-flash": "qwen/qwen3.8-27b",
    "qwen/qwen3.6-plus": "qwen/qwen3.8-27b",
    "qwen/qwen3.6-max-preview": "qwen/qwen3.8-2.4t-a95b",
    "qwen/qwen3.7-plus": "qwen/qwen3.8-27b",
    "qwen/qwen3.7-max": "qwen/qwen3.8-2.4t-a95b",
    "qwen/qwen3.8-max": "qwen/qwen3.8-2.4t-a95b",
}


def openrouter_zdr_fallbacks(provider_config: object) -> dict[str, str]:
    """Return bundled ZDR fallbacks plus user-owned replacements."""
    fallbacks = dict(BUILTIN_OPENROUTER_ZDR_FALLBACKS)
    fallbacks.update(_field(provider_config, "zdr_fallbacks", {}))
    return fallbacks


def model_for_zdr_policy(model: str, *, provider: str, provider_config: object) -> str:
    """Apply the same OpenRouter required-ZDR substitution as dispatch."""
    if provider != "openrouter" or _field(provider_config, "allow_non_zdr", False):
        return model
    lookup = strip_transport_model_suffix(model)
    return openrouter_zdr_fallbacks(provider_config).get(lookup, model)


def effective_proxy_model_maps(
    proxy_config: Any,
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Return effective nonempty tier defaults and alternatives after ZDR policy."""
    provider = proxy_config.preferred_provider
    provider_config = proxy_config.get_provider(provider)
    configured_tiers = _field(provider_config, "tiers", {})
    configured_alternatives = _field(provider_config, "model_alternatives", {})
    tiers = {
        tier: model_for_zdr_policy(model, provider=provider, provider_config=provider_config)
        for tier in ("haiku", "sonnet", "opus")
        if (model := _field(configured_tiers, tier))
    }
    alternatives = {
        tier: {
            request_model: model_for_zdr_policy(
                route_model,
                provider=provider,
                provider_config=provider_config,
            )
            for request_model, route_model in _field(configured_alternatives, tier, {}).items()
        }
        for tier in ("haiku", "sonnet", "opus")
        if _field(configured_alternatives, tier)
    }
    return tiers, alternatives


def _field(source: object, name: str, default: Any = None) -> Any:
    """Read model-route config from mapping or schema-object representations."""
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)

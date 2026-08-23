"""CLI-free context-limit resolution for proxy-routed Claude launches."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _default_context_limit() -> int:
    from forge.runtime_config import get_runtime_config

    return get_runtime_config().context_limit


def _context_window_for_proxy_model(model: str) -> int:
    """Return catalog context for a proxy tier model, honoring Claude Code's [1m] suffix."""
    from forge.core.models import (
        get_context_window_tokens,
        model_exists,
        resolve_model_id,
        strip_transport_model_suffix,
    )

    lookup_model = strip_transport_model_suffix(model)
    if lookup_model != model:
        canonical_model = resolve_model_id(lookup_model)
        one_m_model = canonical_model if canonical_model.endswith("-1m") else f"{canonical_model}-1m"
        if model_exists(one_m_model):
            lookup_model = one_m_model

    return get_context_window_tokens(lookup_model)


def _largest_configured_context_limit(models: list[tuple[str, str]]) -> int:
    """Return the largest catalog-known tier context, or the runtime default."""
    tier_limits: list[tuple[int, str, str]] = []
    for tier, model in models:
        if not model:
            continue
        try:
            tier_limits.append((_context_window_for_proxy_model(model), tier, model))
        except Exception as e:
            logger.debug(f"Skipping unknown model {model!r} for tier {tier}: {e}")

    if not tier_limits:
        return _default_context_limit()

    context_limit, tier, model = max(tier_limits, key=lambda item: item[0])
    logger.debug(f"Computed context limit {context_limit} for model {model} (tier {tier})")
    return context_limit


def _get_context_limit_for_proxy(proxy_id: str) -> int:
    """Compute context limit from the largest configured proxy tier model.

    Deterministic: uses the specific proxy_id to look up the exact model config,
    unlike heuristic template matching, which picks the first matching template.
    """
    try:
        from forge.config.loader import load_proxy_instance_config

        proxy_config = load_proxy_instance_config(proxy_id)
        if proxy_config is None:
            logger.debug(f"No proxy config found for {proxy_id}, using default context limit")
            return _default_context_limit()

        return _largest_configured_context_limit(
            [(tier, proxy_config.tiers.get(tier)) for tier in ("haiku", "sonnet", "opus")]
        )

    except Exception as e:
        logger.debug(f"Failed to compute context limit: {e}, using default")
        return _default_context_limit()


def _get_context_limit_for_template(template: str) -> int:
    """Compute a prospective context limit without creating a proxy instance."""
    try:
        from forge.config.loader import load_config

        provider = load_config(template=template).proxy.get_provider()
        return _largest_configured_context_limit(
            [(tier, provider.tiers.get(tier)) for tier in ("haiku", "sonnet", "opus")]
        )
    except Exception as e:
        logger.debug(f"Failed to compute context limit for template {template!r}: {e}")
        return _default_context_limit()


def _resolve_context_limit(proxy_ref: str | None) -> int:
    """Compute context limit by resolving a proxy for the given proxy_id or template name.

    Uses resolve_proxy_optional() which tries exact proxy_id match first,
    then unique active template match. Falls back to _default_context_limit()
    if no match, ambiguous, or config is malformed.

    Args:
        proxy_ref: Proxy ID or template name (e.g., "openrouter-gemini").

    Returns:
        Context window size in tokens, or _default_context_limit() if no match found.
    """
    if not proxy_ref:
        return _default_context_limit()

    try:
        from forge.proxy.proxies import ProxyRegistryStore, resolve_proxy_optional

        store = ProxyRegistryStore()
        registry = store.read()

        entry = resolve_proxy_optional(registry, proxy_ref)
        if entry is None:
            logger.debug(f"No matching proxy found for '{proxy_ref}', using default")
            return _default_context_limit()

        context_limit = _get_context_limit_for_proxy(entry.proxy_id)
        logger.debug(f"Computed context limit {context_limit} for '{proxy_ref}' via proxy {entry.proxy_id}")
        return context_limit
    except Exception as e:
        logger.debug(f"Failed to compute context limit for '{proxy_ref}': {e}")
        return _default_context_limit()

"""Proxy registry lookup utility.

Provides a shared function for looking up proxy base URLs from the
registry. Used by the semantic supervisor, handoff agent, and review engine.

Note: This module is intentionally NOT re-exported from __init__.py
because it lazy-imports forge.proxy.proxies (a top-level component).
Consumers import directly: ``from forge.core.reactive.proxy import lookup_proxy_base_url``.
"""

from __future__ import annotations


def lookup_proxy_base_url(proxy: str | None) -> str | None:
    """Look up base_url from the proxy registry by proxy_id or template name.

    Internal boundary: if ``proxy`` is provided but resolution fails, the
    exception propagates (ProxyResolutionError, AmbiguousProxyError, or
    ProxyRegistryCorruptedError). Callers decide how to handle the failure.

    Args:
        proxy: Proxy identifier or template name to look up. If None, returns None.

    Returns:
        The proxy's base_url if found, None if proxy is None/empty.

    Raises:
        ProxyResolutionError: If proxy name is provided but cannot be resolved.
        ProxyRegistryCorruptedError: If the registry file is unreadable.
    """
    if not proxy:
        return None

    from forge.proxy.proxies import ProxyRegistryStore, resolve_proxy

    registry = ProxyRegistryStore().read()
    entry = resolve_proxy(registry, proxy)
    return entry.base_url

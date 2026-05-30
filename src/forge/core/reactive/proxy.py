"""Proxy registry lookup utility.

Provides a shared function for looking up proxy base URLs from the
registry. Used by the semantic supervisor, memory writer, and review engine.

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


def check_proxy_reachable(
    proxy: str,
    timeout_s: float = 1.0,
) -> tuple[bool, str, str | None]:
    """Check if a named proxy is locally routable.

    Resolves via registry, then HTTP health-checks the endpoint.
    "Ready" means the proxy responds at its base_url with valid
    proxy metadata -- not just that it exists in the registry.

    Returns:
        (reachable, reason, base_url):
        - reachable: True if proxy resolves AND health check passes
        - reason: empty if reachable, human-readable otherwise
        - base_url: proxy URL if resolved, None otherwise
    """
    from forge.proxy.proxies import ProxyRegistryStore, resolve_proxy
    from forge.proxy.proxy_orchestrator import check_proxy_health

    try:
        registry = ProxyRegistryStore().read()
    except Exception as e:
        return (False, f"Registry error: {e}", None)

    try:
        entry = resolve_proxy(registry, proxy)
    except Exception as e:
        return (False, str(e), None)

    if not check_proxy_health(
        base_url=entry.base_url,
        expected_template=entry.template,
        expected_proxy_id=entry.proxy_id,
        timeout_s=timeout_s,
    ):
        return (False, f"Proxy '{proxy}' not responding at {entry.base_url}", entry.base_url)

    return (True, "", entry.base_url)

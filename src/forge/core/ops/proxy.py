"""Shared proxy operations (command-core).

These operations are UI-agnostic and can be invoked from both:

- the CLI (`forge proxy ...`), and
- the in-chat direct command dispatcher (`%proxy ...`).

They return structured data and raise typed exceptions on failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from forge.config.loader import load_proxy_instance_config
from forge.config.schema import ProxyInstanceConfig
from forge.proxy.proxies import (
    ProxyEntry,
    ProxyRegistryCorruptedError,
    ProxyRegistryStore,
)

from .context import ExecutionContext
from .session import ForgeOpError

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ListProxiesItem:
    proxy_id: str
    entry: ProxyEntry
    config: ProxyInstanceConfig | None  # None if proxy.yaml missing/corrupt


@dataclass(frozen=True)
class ListProxiesResult:
    proxies: list[ListProxiesItem]


@dataclass(frozen=True)
class ShowProxyResult:
    proxy_id: str
    entry: ProxyEntry | None  # None if proxy has config file but no registry entry
    config: ProxyInstanceConfig | None
    config_yaml: str | None  # Raw YAML content for display


def list_proxies(*, ctx: ExecutionContext) -> ListProxiesResult:
    """List all registered proxies with their configurations.

    This is a global operation (lists from ~/.forge/proxies/index.json).
    The ctx is accepted for API consistency.

    Args:
        ctx: execution context (unused, for API consistency).

    Returns:
        ListProxiesResult with proxy entries and configs.

    Raises:
        ForgeOpError: if the proxy registry cannot be read.
    """
    _log.debug("list_proxies: cwd=%s", ctx.cwd)

    store = ProxyRegistryStore()

    try:
        registry = store.read()
    except ProxyRegistryCorruptedError as e:
        raise ForgeOpError(f"Proxy registry error: {e}") from e

    items: list[ListProxiesItem] = []
    for proxy_id, entry in registry.proxies.items():
        # Best-effort config load
        config: ProxyInstanceConfig | None = None
        try:
            config = load_proxy_instance_config(proxy_id)
        except Exception as e:
            _log.debug("Failed to load config for proxy %r: %s", proxy_id, e)

        items.append(ListProxiesItem(proxy_id=proxy_id, entry=entry, config=config))

    # Sort by proxy_id for consistent output
    items.sort(key=lambda x: x.proxy_id)

    return ListProxiesResult(proxies=items)


def show_proxy(*, ctx: ExecutionContext, proxy_id: str) -> ShowProxyResult:
    """Show details for a specific proxy.

    The proxy must have either a registry entry or a config file (or both).
    Registry info (status, PID) is best-effort enrichment.

    Args:
        ctx: execution context (unused, for API consistency).
        proxy_id: the proxy ID to show.

    Returns:
        ShowProxyResult with entry, config, and raw YAML.

    Raises:
        ForgeOpError: if the proxy is not found in both registry and filesystem.
    """
    _log.debug("show_proxy: proxy_id=%s", proxy_id)

    # Best-effort registry lookup
    entry: ProxyEntry | None = None
    store = ProxyRegistryStore()
    try:
        registry = store.read()
        entry = registry.proxies.get(proxy_id)
    except ProxyRegistryCorruptedError:
        _log.debug("Registry unreadable, proceeding without registry info")

    # Load config
    config: ProxyInstanceConfig | None = None
    config_yaml: str | None = None

    try:
        config = load_proxy_instance_config(proxy_id)
    except Exception as e:
        _log.debug("Failed to load config for proxy %r: %s", proxy_id, e)

    # Load raw YAML for display
    from forge.config.loader import get_proxy_file_path

    proxy_path = get_proxy_file_path(proxy_id)
    if proxy_path.exists():
        try:
            config_yaml = proxy_path.read_text()
        except Exception as e:
            _log.debug("Failed to read proxy file %s: %s", proxy_path, e)

    # Must have at least one source of truth
    if entry is None and config_yaml is None:
        raise ForgeOpError(f"Proxy '{proxy_id}' not found")

    return ShowProxyResult(
        proxy_id=proxy_id,
        entry=entry,
        config=config,
        config_yaml=config_yaml,
    )

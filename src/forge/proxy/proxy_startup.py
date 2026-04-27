"""Proxy-scoped startup validation for the proxy (B2.1.3).

This module exists so we can unit-test strict proxy startup invariants without
starting uvicorn.

Rules (strict):
- If proxy_id is provided, it must exist in the proxy registry.
- proxy.template must match the active template.
- proxy.port must match the effective runtime port.

Note: We intentionally do NOT validate base_url here because the proxy may bind
0.0.0.0 while the registry stores localhost.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProxyStartupContext:
    proxy_id: str
    template: str
    port: int


class ProxyStartupValidationError(ValueError):
    """Raised when proxy-scoped startup invariants are violated."""


def validate_proxy_startup(*, ctx: ProxyStartupContext) -> None:
    """Validate proxy-scoped startup invariants.

    Raises:
        ProxyStartupValidationError: if ctx violates invariants.
    """
    from forge.proxy.proxies import ProxyRegistryStore

    store = ProxyRegistryStore()
    registry = store.read()

    entry = registry.proxies.get(ctx.proxy_id)
    if entry is None:
        raise ProxyStartupValidationError(f"can't start proxy with overlay for unregistered proxy: {ctx.proxy_id}")

    if entry.template != ctx.template:
        raise ProxyStartupValidationError(
            f"proxy template mismatch for {ctx.proxy_id}: registry has '{entry.template}', server started with '{ctx.template}'"
        )

    if int(entry.port) != int(ctx.port):
        raise ProxyStartupValidationError(
            f"proxy port mismatch for {ctx.proxy_id}: registry has {entry.port}, server started on {ctx.port}"
        )

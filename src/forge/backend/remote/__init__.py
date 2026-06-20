"""Backend remote-reconciliation: account-side metadata adapters.

Read/account-side sibling of ``backend.adapters`` (local lifecycle). A source is
remote-reconcile capable iff it has a registered adapter here. This package owns the registry
wiring so the leaf ``base`` module stays import-light (no provider client imports).
"""

from __future__ import annotations

from forge.backend.remote.base import (
    BackendRemoteAdapter,
    KeyClass,
    RemoteAdapterError,
    RemoteAdapterNotFoundError,
    RemoteCapability,
    RemoteOutcome,
    RemoteRecord,
    get_remote_adapter,
    has_remote_adapter,
    list_remote_adapter_ids,
    register_remote_adapter,
)
from forge.backend.remote.openrouter import OpenRouterRemoteAdapter

# Register built-in adapters. OpenRouter is the first; add a source's adapter here to make it
# remote-reconcile capable.
register_remote_adapter(OpenRouterRemoteAdapter())

__all__ = [
    "BackendRemoteAdapter",
    "KeyClass",
    "OpenRouterRemoteAdapter",
    "RemoteAdapterError",
    "RemoteAdapterNotFoundError",
    "RemoteCapability",
    "RemoteOutcome",
    "RemoteRecord",
    "get_remote_adapter",
    "has_remote_adapter",
    "list_remote_adapter_ids",
    "register_remote_adapter",
]

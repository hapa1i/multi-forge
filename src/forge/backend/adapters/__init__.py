"""Backend adapters for different backend types."""

from __future__ import annotations

from forge.backend import BackendAdapter
from forge.backend.adapters.litellm import LiteLLMAdapter

# Registry of known adapter types
_ADAPTER_REGISTRY: dict[str, type["BackendAdapter"]] = {
    "litellm": LiteLLMAdapter,
}


def get_adapter(adapter_type: str) -> "BackendAdapter":
    """Get an adapter instance by type.

    Args:
        adapter_type: Adapter type (e.g., "litellm")

    Returns:
        New adapter instance

    Raises:
        ValueError: If adapter type is unknown
    """
    adapter_class = _ADAPTER_REGISTRY.get(adapter_type)
    if adapter_class is None:
        available = ", ".join(sorted(_ADAPTER_REGISTRY.keys()))
        raise ValueError(f"Unknown adapter type: '{adapter_type}'. Available: {available}")
    return adapter_class()


def get_supported_adapters() -> list[str]:
    """Get list of supported adapter types."""
    return sorted(_ADAPTER_REGISTRY.keys())


__all__ = ["LiteLLMAdapter", "get_adapter", "get_supported_adapters"]

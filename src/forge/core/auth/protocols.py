"""Authentication protocols shared across auth and LLM modules."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SecretsProvider(Protocol):
    """Protocol for optional and required secret lookup."""

    def get(self, key: str, default: Any = None) -> Any:
        """Get a secret value, returning default if not found or empty."""
        ...

    def require(self, key: str) -> str:
        """Get a required secret value, raising if not found or empty."""
        ...

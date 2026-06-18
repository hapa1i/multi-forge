"""Dependency-light backend dependency type."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BackendDependency:
    """Backend dependency declaration (proxy runtime requirement).

    Declares that a proxy template requires a backend service to be running.
    Example: local LiteLLM proxies require LiteLLM backend on port 4000.
    """

    adapter: str  # e.g., "litellm"
    port: int
    required_env_vars: list[str] = field(default_factory=list)


__all__ = ["BackendDependency"]

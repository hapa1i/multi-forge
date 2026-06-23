"""Backend management for Forge.

Backends are underlying services that proxies depend on (e.g., LiteLLM).
They have their own lifecycle, registry, and CLI commands.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from forge.backend.registry import (
    BackendInstance,
    BackendRegistry,
    BackendRegistryStore,
)
from forge.backend.sources import (
    LocalBackendLifecycle,
    ModelSource,
    ModelSourceCapabilities,
    ModelSourceCatalogError,
    ModelSourceNotFoundError,
    SourceEndpoint,
    get_model_source,
    list_model_sources,
    model_source_for_template,
    required_env_vars_for_source,
    resolve_model_source_id,
    template_env_vars_by_template,
    validate_model_sources,
)


@dataclass(frozen=True)
class BackendEnsureResult:
    """Result of ensure_backend() operation."""

    instance: BackendInstance
    source: Literal["reuse", "start"]


class BackendAdapter(ABC):
    """Abstract base class for backend lifecycle management."""

    @abstractmethod
    def start(self, backend_id: str, config_path: Path, port: int) -> BackendInstance:
        """Start backend, return instance details.

        Args:
            backend_id: Unique instance ID (e.g., "litellm-4000")
            config_path: Path to backend config file
            port: Port number to bind

        Returns:
            BackendInstance with PID and status

        Raises:
            BackendStartError: If backend fails to start
        """

    @abstractmethod
    def stop(self, instance: BackendInstance) -> None:
        """Stop backend (best effort).

        Args:
            instance: Backend instance to stop
        """

    @abstractmethod
    def health_check(self, instance: BackendInstance) -> bool:
        """Check if backend is healthy.

        Args:
            instance: Backend instance to check

        Returns:
            True if healthy, False otherwise
        """


class BackendStartError(Exception):
    """Raised when backend fails to start."""


class BackendManager:
    """Orchestrates backends via adapters."""

    def __init__(self, registry_store: BackendRegistryStore) -> None:
        """Initialize backend manager.

        Args:
            registry_store: Backend registry store
        """
        self.registry_store = registry_store
        self.adapters: dict[str, BackendAdapter] = {}

    def register_adapter(self, adapter_type: str, adapter: BackendAdapter) -> None:
        """Register a backend adapter.

        Args:
            adapter_type: Adapter type (e.g., "litellm")
            adapter: Adapter instance
        """
        self.adapters[adapter_type] = adapter

    def ensure_backend(self, backend_id: str, adapter_type: str, port: int) -> BackendEnsureResult:
        """Ensure backend is running (reuse -> start pattern).

        Args:
            backend_id: Backend instance ID (e.g., "litellm-4000")
            adapter_type: Adapter type (e.g., "litellm")
            port: Port number

        Returns:
            BackendEnsureResult with instance and source ("reuse" or "start")

        Raises:
            BackendStartError: If backend fails to start
        """
        from forge.backend.creation import get_backend_config_path

        adapter = self.adapters.get(adapter_type)
        if not adapter:
            raise ValueError(f"No adapter registered for type: {adapter_type}")

        registry = self.registry_store.read()
        existing = registry.backends.get(backend_id)

        if existing:
            # health_check works with or without PID (port probe fallback)
            if adapter.health_check(existing):
                return BackendEnsureResult(instance=existing, source="reuse")

            def remove_dead(reg: BackendRegistry) -> None:
                reg.backends.pop(backend_id, None)

            self.registry_store.update(timeout_s=10.0, mutate=remove_dead)

        config_path = get_backend_config_path(adapter_type)
        if not config_path.exists():
            raise BackendStartError(
                f"Backend config not found: {config_path}\n"
                f"Create it with: forge model backend create {adapter_type}"
            )

        instance = adapter.start(backend_id, config_path, port)

        def add_instance(reg: BackendRegistry) -> None:
            reg.backends[backend_id] = instance

        self.registry_store.update(timeout_s=10.0, mutate=add_instance)

        return BackendEnsureResult(instance=instance, source="start")

    def stop_backend(self, backend_id: str) -> None:
        """Stop backend and remove from registry.

        Args:
            backend_id: Backend instance ID

        Raises:
            ValueError: If backend not found
        """
        registry = self.registry_store.read()
        instance = registry.backends.get(backend_id)

        if not instance:
            raise ValueError(f"Backend not found: {backend_id}")

        adapter = self.adapters.get(instance.adapter_type)
        if adapter:
            adapter.stop(instance)

        def remove_instance(reg: BackendRegistry) -> None:
            reg.backends.pop(backend_id, None)

        self.registry_store.update(timeout_s=10.0, mutate=remove_instance)


__all__ = [
    "BackendAdapter",
    "BackendEnsureResult",
    "BackendInstance",
    "BackendManager",
    "BackendRegistry",
    "BackendRegistryStore",
    "BackendStartError",
    "LocalBackendLifecycle",
    "ModelSource",
    "ModelSourceCapabilities",
    "ModelSourceCatalogError",
    "ModelSourceNotFoundError",
    "SourceEndpoint",
    "get_model_source",
    "list_model_sources",
    "model_source_for_template",
    "required_env_vars_for_source",
    "resolve_model_source_id",
    "template_env_vars_by_template",
    "validate_model_sources",
]

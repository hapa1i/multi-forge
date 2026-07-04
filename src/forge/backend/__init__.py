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
    ManagedBackendProcess,
    BackendRegistry,
    BackendRegistryStore,
)
from forge.backend.sources import (
    BackendInstanceAmbiguousError,
    BackendInstanceMatchKind,
    BackendInstanceNotFoundError,
    BackendInstanceResolution,
    BackendInstanceResolutionError,
    LocalBackendLifecycle,
    ModelSource,
    ModelSourceCapabilities,
    ModelSourceCatalogError,
    ModelSourceNotFoundError,
    SourceEndpoint,
    backend_kind_for_source,
    get_model_source,
    list_model_sources,
    model_source_for_template,
    required_env_vars_for_source,
    resolve_backend_instance,
    resolve_backend_instance_id,
    resolve_model_source_id,
    template_env_vars_by_template,
    validate_model_sources,
)


@dataclass(frozen=True)
class BackendEnsureResult:
    """Result of ensure_backend() operation."""

    process: ManagedBackendProcess
    source: Literal["reuse", "start"]


class BackendAdapter(ABC):
    """Abstract base class for backend lifecycle management."""

    @abstractmethod
    def start(self, process_id: str, config_path: Path, port: int) -> ManagedBackendProcess:
        """Start backend, return managed process details.

        Args:
            process_id: Managed process ID (e.g., "litellm-4000")
            config_path: Path to backend config file
            port: Port number to bind

        Returns:
            ManagedBackendProcess with PID and status

        Raises:
            BackendStartError: If backend fails to start
        """

    @abstractmethod
    def stop(self, process: ManagedBackendProcess) -> None:
        """Stop backend (best effort).

        Args:
            process: Managed backend process to stop
        """

    @abstractmethod
    def health_check(self, process: ManagedBackendProcess) -> bool:
        """Check if backend is healthy.

        Args:
            process: Managed backend process to check

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

    def ensure_backend(self, process_id: str, adapter_type: str, port: int) -> BackendEnsureResult:
        """Ensure backend is running (reuse -> start pattern).

        Args:
            process_id: Managed process ID (e.g., "litellm-4000")
            adapter_type: Adapter type (e.g., "litellm")
            port: Port number

        Returns:
            BackendEnsureResult with process and source ("reuse" or "start")

        Raises:
            BackendStartError: If backend fails to start
        """
        from forge.backend.creation import get_backend_config_path

        adapter = self.adapters.get(adapter_type)
        if not adapter:
            raise ValueError(f"No adapter registered for type: {adapter_type}")

        registry = self.registry_store.read()
        existing = registry.processes.get(process_id)

        if existing:
            # health_check works with or without PID (port probe fallback)
            if adapter.health_check(existing):
                return BackendEnsureResult(process=existing, source="reuse")

            def remove_dead(reg: BackendRegistry) -> None:
                reg.processes.pop(process_id, None)

            self.registry_store.update(timeout_s=10.0, mutate=remove_dead)

        config_path = get_backend_config_path(adapter_type)
        if not config_path.exists():
            raise BackendStartError(
                f"Backend config not found: {config_path}\n"
                f"Create it with: forge model backend create {adapter_type}"
            )

        process = adapter.start(process_id, config_path, port)

        def add_process(reg: BackendRegistry) -> None:
            reg.processes[process_id] = process

        self.registry_store.update(timeout_s=10.0, mutate=add_process)

        return BackendEnsureResult(process=process, source="start")

    def stop_backend(self, process_id: str) -> None:
        """Stop backend and remove from registry.

        Args:
            process_id: Managed process ID

        Raises:
            ValueError: If managed process not found
        """
        registry = self.registry_store.read()
        process = registry.processes.get(process_id)

        if not process:
            raise ValueError(f"Managed process not found: {process_id}")

        adapter = self.adapters.get(process.adapter_type)
        if adapter:
            adapter.stop(process)

        def remove_process(reg: BackendRegistry) -> None:
            reg.processes.pop(process_id, None)

        self.registry_store.update(timeout_s=10.0, mutate=remove_process)


__all__ = [
    "BackendAdapter",
    "BackendEnsureResult",
    "BackendInstanceAmbiguousError",
    "ManagedBackendProcess",
    "BackendInstanceMatchKind",
    "BackendManager",
    "BackendInstanceNotFoundError",
    "BackendInstanceResolution",
    "BackendInstanceResolutionError",
    "BackendRegistry",
    "BackendRegistryStore",
    "BackendStartError",
    "LocalBackendLifecycle",
    "ModelSource",
    "ModelSourceCapabilities",
    "ModelSourceCatalogError",
    "ModelSourceNotFoundError",
    "SourceEndpoint",
    "backend_kind_for_source",
    "get_model_source",
    "list_model_sources",
    "model_source_for_template",
    "required_env_vars_for_source",
    "resolve_backend_instance",
    "resolve_backend_instance_id",
    "resolve_model_source_id",
    "template_env_vars_by_template",
    "validate_model_sources",
]

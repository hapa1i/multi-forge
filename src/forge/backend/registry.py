"""Local backend process registry for Forge backend services.

A backend is a service that proxies depend on (e.g., LiteLLM on port 4000).
The backend registry is stored at:

- ~/.forge/backends/index.json

This module implements a small, versioned JSON store with atomic writes.

Ownership: Forge Backend Manager (`forge model backend` CLI).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, NoReturn

import dacite

from forge.core.paths import get_forge_home
from forge.core.state import (
    StateCorruptedError,
    StateUnreadableError,
    atomic_write_json,
    file_lock_for_target,
    read_versioned_json_object,
)

logger = logging.getLogger(__name__)

BACKEND_REGISTRY_VERSION = 2
BACKENDS_DIR = "backends"
BACKEND_INDEX_FILENAME = "index.json"
OLD_BACKEND_ID_PROCESS_FIELD_TIP = (
    "local backend process registry uses old backend_id records; "
    "stop local backends first (or free their ports), then delete ~/.forge/backends/index.json "
    "and restart local backends."
)

CLI_LOCK_TIMEOUT_S = 5.0


from forge.core.process import is_pid_alive as is_pid_alive  # noqa: E402, F401  # re-export


class BackendRegistryCorruptedError(StateCorruptedError):
    """Raised when the backend registry cannot be parsed."""

    pass


class BackendRegistryUnreadableError(StateUnreadableError):
    """Raised when the backend registry exists but the read failed (OSError), not corruption.

    A ``StateUnreadableError`` (not ``StateCorruptedError``) so ``forge clean`` never
    deletes a registry it merely failed to open.
    """

    pass


@dataclass
class ManagedBackendProcess:
    """A Forge-managed local backend process.

    Timestamps are stored as ISO8601 strings.
    """

    process_id: str  # e.g., "litellm-4000"
    adapter_type: str  # e.g., "litellm"
    port: int
    pid: int | None = None
    status: Literal["healthy", "unhealthy", "stopped", "unknown"] = "unknown"
    created_at: str | None = None


@dataclass
class BackendRegistry:
    """Backend registry file format."""

    version: int = BACKEND_REGISTRY_VERSION
    processes: dict[str, ManagedBackendProcess] = field(default_factory=dict)


def get_backend_registry_path() -> Path:
    """Return the full path to the backend registry file."""

    return get_forge_home() / BACKENDS_DIR / BACKEND_INDEX_FILENAME


def _uses_old_backend_id_process_records(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    entries = data.get("backends")
    if not isinstance(entries, dict):
        return False
    return any(isinstance(entry, dict) and "backend_id" in entry for entry in entries.values())


def _handle_registry_version_mismatch(path: Path, data: dict[str, Any], version: Any) -> NoReturn:
    if version == 1 and _uses_old_backend_id_process_records(data):
        raise BackendRegistryCorruptedError(str(path), OLD_BACKEND_ID_PROCESS_FIELD_TIP)
    raise BackendRegistryCorruptedError(
        str(path),
        f"incompatible version {version} (this Forge expects {BACKEND_REGISTRY_VERSION}). "
        f"Delete this file and retry.",
    )


class BackendRegistryStore:
    """Manage the backend registry at ~/.forge/backends/index.json.

    Error handling:
    - Missing file: returns empty registry (self-healing)
    - Corrupted file: raises BackendRegistryCorruptedError
    """

    def __init__(self, registry_path: Path | None = None) -> None:
        self._registry_path = registry_path or get_backend_registry_path()

    @property
    def registry_path(self) -> Path:
        return self._registry_path

    def exists(self) -> bool:
        return self._registry_path.is_file()

    def read(self) -> BackendRegistry:
        if not self.exists():
            return BackendRegistry()

        data = read_versioned_json_object(
            self._registry_path,
            version_key="version",
            expected_version=BACKEND_REGISTRY_VERSION,
            corrupted_error=BackendRegistryCorruptedError,
            unreadable_error=BackendRegistryUnreadableError,
            on_version_mismatch=_handle_registry_version_mismatch,
        )

        try:
            return dacite.from_dict(
                data_class=BackendRegistry,
                data=data,
                config=dacite.Config(strict=True),
            )
        except (dacite.DaciteError, TypeError, KeyError) as e:
            raise BackendRegistryCorruptedError(str(self._registry_path), f"deserialization error: {e}")

    def write(self, registry: BackendRegistry) -> None:
        data = asdict(registry)
        atomic_write_json(self._registry_path, data)

    def update(self, *, timeout_s: float, mutate: Callable[[BackendRegistry], None]) -> BackendRegistry:
        """Update registry via a locked read-modify-write cycle."""

        with file_lock_for_target(target_path=self._registry_path, timeout_s=timeout_s):
            registry = self.read()
            mutate(registry)
            self.write(registry)
            return registry

    def prune_dead_pids(self, *, timeout_s: float = CLI_LOCK_TIMEOUT_S) -> list[str]:
        """Remove registry entries whose Forge-spawned pid is no longer running.

        Definition of stale (normative):
        - Only entries with pid != None are considered (Forge-spawned backends).
        - Entries with pid == None are never auto-pruned.

        Returns:
            List of managed process IDs removed from the registry.
        """

        with file_lock_for_target(target_path=self._registry_path, timeout_s=timeout_s):
            registry = self.read()

            stale_ids: list[str] = []
            for process_id, entry in list(registry.processes.items()):
                if entry.pid is None:
                    continue
                if not is_pid_alive(entry.pid):
                    del registry.processes[process_id]
                    stale_ids.append(process_id)

            if stale_ids:
                self.write(registry)

            return stale_ids

    def list_processes(self) -> list[ManagedBackendProcess]:
        """List all managed backend processes (prunes dead PIDs first).

        Returns:
            List of managed processes, ordered by creation time (oldest first).
        """

        self.prune_dead_pids()
        registry = self.read()

        processes = list(registry.processes.values())
        processes.sort(key=lambda x: x.created_at or "")
        return processes

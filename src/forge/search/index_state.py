"""Search index state for incremental transcript indexing.

Tracks which transcript files have been indexed via mtime/size fingerprints,
enabling the search system to skip already-indexed files and detect changes.

Two-layer architecture:
- IndexState (dataclass): pure in-memory operations (needs_reindex, mark_indexed, prune)
- IndexStateStore: persistence + locking (read, write, update with file_lock_for_target)

State file location: <project_root>/.forge/search-index/state.json

Follows the BackendRegistry/BackendRegistryStore pattern from forge.backend.registry.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, NoReturn

from forge.core.state import (
    SchemaVersionError,
    atomic_write_json,
    file_lock_for_target,
    now_iso,
    read_versioned_json_object,
)

from .exceptions import IndexStateCorruptedError, IndexStateUnreadableError

# Directory and file names
SEARCH_INDEX_DIR = "search-index"
STATE_FILENAME = "state.json"

# Schema version — reject anything else (no migration, per coding_standards.md)
INDEX_STATE_VERSION = 1

# Lock timeouts
CLI_LOCK_TIMEOUT_S = 5.0
HANDLER_LOCK_TIMEOUT_S = 1.0


def get_project_index_state_path(forge_root: Path) -> Path:
    """Return the index state path for a Forge project.

    Path: <forge_root>/.forge/search-index/state.json
    """
    return forge_root / ".forge" / SEARCH_INDEX_DIR / STATE_FILENAME


def _handle_index_state_version_mismatch(path: Path, _data: dict[str, Any], version: Any) -> NoReturn:
    raise SchemaVersionError(str(path), INDEX_STATE_VERSION, version)


def _require_absolute(path: Path) -> None:
    """Raise ValueError if path is not absolute."""
    if not path.is_absolute():
        raise ValueError(f"path must be absolute, got: {path}")


# --- Data layer ---


@dataclass
class IndexedFileEntry:
    """Tracking metadata for a single indexed transcript file."""

    mtime: float
    size: int
    indexed_at: str


@dataclass
class IndexState:
    """In-memory representation of the search index state.

    Pure operations — no disk I/O. Persistence is handled by IndexStateStore.
    """

    schema_version: int = INDEX_STATE_VERSION
    updated_at: str = ""
    indexed_files: dict[str, IndexedFileEntry] = field(default_factory=dict)

    def needs_reindex(self, path: Path) -> bool:
        """Check if a file needs (re)indexing based on mtime/size.

        Returns True if the file is new or has changed since last indexing.
        Returns False if the file is unchanged OR if the file does not exist on disk.

        Missing-file semantics:
        - No entry + file missing → False (nothing to do)
        - Entry exists + file deleted → False (prune_missing() handles cleanup)

        Raises:
            ValueError: If path is not absolute.
        """
        _require_absolute(path)

        try:
            stat = os.stat(path)
        except OSError:
            return False

        key = str(path)
        entry = self.indexed_files.get(key)
        if entry is None:
            return True

        return entry.mtime != stat.st_mtime or entry.size != stat.st_size

    def mark_indexed(self, path: Path) -> None:
        """Record that a file has been indexed with its current mtime/size.

        Creates or updates the entry for the given path using the file's
        current stat() values and the current timestamp.

        Raises:
            ValueError: If path is not absolute.
            FileNotFoundError: If path does not exist on disk.
        """
        _require_absolute(path)

        try:
            stat = os.stat(path)
        except FileNotFoundError:
            raise
        except OSError as e:
            raise FileNotFoundError(str(path)) from e

        self.indexed_files[str(path)] = IndexedFileEntry(
            mtime=stat.st_mtime,
            size=stat.st_size,
            indexed_at=now_iso(),
        )

    def prune_missing(self) -> list[str]:
        """Remove entries for files that no longer exist on disk.

        Returns:
            List of path strings that were removed.
        """
        to_remove = [key for key in self.indexed_files if not Path(key).is_file()]
        for key in to_remove:
            del self.indexed_files[key]
        return to_remove


# --- Persistence layer ---


class IndexStateStore:
    """Manage per-project search index state.

    Store location: <project_root>/.forge/search-index/state.json
    Tracks which transcript files have been indexed for incremental updates.
    Uses atomic writes and advisory file locking for concurrent safety.

    Error handling:
    - Missing file: returns empty state (self-healing)
    - Corrupted file: raises IndexStateCorruptedError
    - Wrong schema version: raises SchemaVersionError
    """

    def __init__(
        self,
        forge_root: Path | None = None,
        *,
        state_path: Path | None = None,
    ) -> None:
        if state_path:
            self._state_path = state_path  # Explicit override (tests)
        elif forge_root:
            self._state_path = get_project_index_state_path(forge_root)
        else:
            raise ValueError("Either forge_root or state_path required")

    @property
    def state_path(self) -> Path:
        return self._state_path

    def exists(self) -> bool:
        return self._state_path.is_file()

    def read(self) -> IndexState:
        """Read the index state from disk.

        Returns empty IndexState if the file does not exist (self-healing).

        Raises:
            IndexStateCorruptedError: If the file contains invalid JSON or structure.
            SchemaVersionError: If the schema version doesn't match INDEX_STATE_VERSION.
        """
        if not self.exists():
            return IndexState()

        data = read_versioned_json_object(
            self._state_path,
            version_key="schema_version",
            expected_version=INDEX_STATE_VERSION,
            corrupted_error=IndexStateCorruptedError,
            unreadable_error=IndexStateUnreadableError,
            missing_version_reason="missing schema_version",
            on_version_mismatch=_handle_index_state_version_mismatch,
        )

        # Deserialize indexed_files: dict[str, dict] → dict[str, IndexedFileEntry]
        indexed_files: dict[str, IndexedFileEntry] = {}
        raw_files = data.get("indexed_files", {})
        if isinstance(raw_files, dict):
            for key, val in raw_files.items():
                if isinstance(val, dict):
                    try:
                        indexed_files[key] = IndexedFileEntry(
                            mtime=float(val["mtime"]),
                            size=int(val["size"]),
                            indexed_at=str(val.get("indexed_at", "")),
                        )
                    except (KeyError, TypeError, ValueError):
                        # Skip malformed entries rather than failing the whole read
                        continue

        return IndexState(
            schema_version=INDEX_STATE_VERSION,
            updated_at=data.get("updated_at", ""),
            indexed_files=indexed_files,
        )

    def write(self, state: IndexState) -> None:
        """Write the index state atomically.

        Sets state.updated_at to the current timestamp before writing.
        Creates parent directories if needed.
        """
        state.updated_at = now_iso()
        data = asdict(state)
        atomic_write_json(self._state_path, data)

    def update(self, *, timeout_s: float, mutate: Callable[[IndexState], None]) -> IndexState:
        """Locked read-modify-write cycle.

        Acquires an advisory file lock, reads the state, calls mutate(state),
        then writes the updated state. Exceptions from mutate propagate
        (not swallowed).

        Args:
            timeout_s: Maximum time to wait for the lock.
            mutate: Callable that modifies the IndexState in-place.

        Returns:
            The updated IndexState after mutation and write.
        """
        with file_lock_for_target(target_path=self._state_path, timeout_s=timeout_s):
            state = self.read()
            mutate(state)
            self.write(state)
            return state

    # -- Convenience wrappers --

    def mark_indexed(self, path: Path, *, timeout_s: float = HANDLER_LOCK_TIMEOUT_S) -> None:
        """Mark a file as indexed (locked read-modify-write).

        Convenience wrapper around update() that calls state.mark_indexed(path).

        Raises:
            ValueError: If path is not absolute.
            FileNotFoundError: If path does not exist on disk.
        """

        def _mutate(state: IndexState) -> None:
            state.mark_indexed(path)

        self.update(timeout_s=timeout_s, mutate=_mutate)

    def find_missing(self) -> list[str]:
        """Return indexed paths whose files no longer exist on disk.

        Read-only counterpart to prune_missing (no lock, no write): the preview
        for `forge search clean`. Same predicate as IndexState.prune_missing, so
        the count a preview reports matches what --yes would remove.
        """
        return [key for key in self.read().indexed_files if not Path(key).is_file()]

    def prune_missing(self, *, timeout_s: float = CLI_LOCK_TIMEOUT_S) -> list[str]:
        """Remove entries for deleted files (locked read-modify-write).

        Convenience wrapper around update() that calls state.prune_missing().

        Returns:
            List of path strings that were removed.
        """
        removed: list[str] = []

        def _mutate(state: IndexState) -> None:
            removed.extend(state.prune_missing())

        self.update(timeout_s=timeout_s, mutate=_mutate)
        return removed

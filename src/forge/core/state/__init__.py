"""Shared state utilities for Forge file-based state system.

This module provides:
- Atomic file write operations (tempfile + os.replace pattern)
- Timestamp helpers (ISO8601, UTC-only)
- Base exception hierarchy for state operations

Usage:
    from forge.core.state import atomic_write_json, now_iso
    from forge.core.state import StateCorruptedError, SchemaVersionError

For domain-specific state operations, use the domain modules:
    from forge.session import SessionStore, IndexStore
    from forge.proxy.proxies import ProxyRegistryStore
"""

# IO utilities
from .io import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    decode_json_object,
    open_secure_append,
    read_json,
)

# Locking utilities
from .lock import (
    FileLockTimeoutError,
    file_lock,
    file_lock_for_target,
    get_lock_path_for_target,
)

# Retention utilities
from .retention import prune_jsonl_shards

# Timestamp utilities
from .timestamps import iso_to_timestamp, now_iso, parse_iso, utc_timestamp_z

# Versioned JSON store utilities
from .versioned_store import read_versioned_json_object

# Exceptions
from .exceptions import (
    SchemaVersionError,
    StateCorruptedError,
    StateError,
    StateNotFoundError,
    StateUnreadableError,
)

__all__ = [
    # IO
    "atomic_write_bytes",
    "atomic_write_text",
    "atomic_write_json",
    "decode_json_object",
    "open_secure_append",
    "read_json",
    # Locking
    "get_lock_path_for_target",
    "file_lock",
    "file_lock_for_target",
    "FileLockTimeoutError",
    # Retention
    "prune_jsonl_shards",
    # Timestamps
    "now_iso",
    "utc_timestamp_z",
    "parse_iso",
    "iso_to_timestamp",
    # Versioned JSON stores
    "read_versioned_json_object",
    # Exceptions
    "StateError",
    "StateNotFoundError",
    "StateCorruptedError",
    "StateUnreadableError",
    "SchemaVersionError",
]

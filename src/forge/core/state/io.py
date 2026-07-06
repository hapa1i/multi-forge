"""Atomic file operations for Forge state files.

All write operations use the tempfile + os.replace() pattern for atomicity.
This ensures that readers never see partial writes. The temp file is fsynced
before replacement and the parent directory is fsynced best-effort after
replacement, so durable checkpoints such as spend-cap state survive ordinary
process crashes as well as partial writes.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .exceptions import StateCorruptedError, StateNotFoundError


def decode_json_object(line: str) -> dict[str, Any] | None:
    """Decode one JSONL line to a dict, or return None to skip it.

    Returns None for a blank line, malformed JSON, or valid-but-non-object JSON
    (``[]`` / ``1`` / ``"x"`` / ``null``). Centralizes the guard every append-only
    cost/usage/audit reader needs: a stray non-object line must be skipped, never
    crashed on with an ``AttributeError`` from a ``.get`` on a list/scalar.
    """
    line = line.strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None


def open_secure_append(path: Path) -> Any:
    """Open a file for append with 0600 permissions (owner read/write only).

    Used for log files that may contain sensitive payloads (request bodies,
    tool inputs, error messages). Creates the file with 0600 if missing;
    chmods to 0600 if it already exists.

    The post-open chmod has a tiny TOCTOU window for pre-existing files but
    closes it on every subsequent write. New files are created with 0600
    atomically (subject to umask, which only clears bits we already want clear).
    """
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600)
    except OSError:
        pass  # best-effort: some filesystems (e.g., CIFS) may not support fchmod
    return os.fdopen(fd, "a", encoding="utf-8")


def atomic_write_text(
    path: Path,
    content: str,
    *,
    mode: int | None = None,
    create_parents: bool = True,
) -> None:
    """Write text to a file atomically.

    Uses tempfile + os.replace() pattern to ensure readers never see
    partial writes. The temp file is created in the same directory as
    the target to ensure atomic rename works (same filesystem).

    Args:
        path: Target file path.
        content: Text content to write.
        mode: Optional final file mode (for example, 0o600).
        create_parents: Create parent directories if they don't exist.

    Raises:
        OSError: If the write or rename fails.
    """
    atomic_write_bytes(path, content.encode("utf-8"), mode=mode, create_parents=create_parents)


def atomic_write_bytes(
    path: Path,
    content: bytes,
    *,
    mode: int | None = None,
    create_parents: bool = True,
) -> None:
    """Write bytes to a file atomically.

    Uses tempfile + os.replace() pattern to ensure readers never see
    partial writes. The temp file is created in the same directory as
    the target to ensure atomic rename works (same filesystem).

    Args:
        path: Target file path.
        content: Bytes to write.
        mode: Optional final file mode (for example, 0o600).
        create_parents: Create parent directories if they don't exist.

    Raises:
        OSError: If the write or rename fails.
    """
    if create_parents:
        path.parent.mkdir(parents=True, exist_ok=True)

    # Create temp file in same directory for atomic rename
    fd, temp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.stem}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            if mode is not None:
                os.fchmod(f.fileno(), mode)
            os.fsync(f.fileno())
        os.replace(temp_path, str(path))
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except BaseException:
        # Clean up temp file on failure
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def atomic_write_json(
    path: Path,
    data: dict[str, Any],
    *,
    indent: int = 2,
    create_parents: bool = True,
) -> None:
    """Write JSON to a file atomically.

    Serializes the dict to JSON and writes it atomically using
    tempfile + os.replace(). Adds a trailing newline for git-friendliness.

    Args:
        path: Target file path.
        data: Dict to serialize as JSON.
        indent: JSON indentation level (default 2).
        create_parents: Create parent directories if they don't exist.

    Raises:
        OSError: If the write or rename fails.
        TypeError: If data contains non-serializable values.
    """
    content = json.dumps(data, indent=indent)
    content += "\n"  # Trailing newline
    atomic_write_text(path, content, create_parents=create_parents)


def read_json(path: Path) -> dict[str, Any]:
    """Read and parse a JSON file.

    Args:
        path: Path to JSON file.

    Returns:
        Parsed JSON as a dict.

    Raises:
        StateNotFoundError: If the file does not exist.
        StateCorruptedError: If the file contains invalid JSON or is not a JSON object.
    """
    if not path.exists():
        raise StateNotFoundError(str(path))

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise StateCorruptedError(str(path), f"invalid JSON: {e}") from e
    except OSError as e:
        raise StateCorruptedError(str(path), f"read error: {e}") from e

    if not isinstance(data, dict):
        raise StateCorruptedError(
            str(path),
            f"expected JSON object, got {type(data).__name__}",
        )

    return data

"""Small helpers for versioned JSON object stores."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

from .exceptions import StateCorruptedError, StateUnreadableError

_MISSING = object()

VersionMismatchHandler = Callable[[Path, dict[str, Any], Any], NoReturn]


def read_versioned_json_object(
    path: Path,
    *,
    version_key: str,
    expected_version: int,
    corrupted_error: type[StateCorruptedError],
    unreadable_error: type[StateUnreadableError],
    missing_version: Any = _MISSING,
    missing_version_reason: str | None = None,
    none_is_missing: bool = True,
    on_version_mismatch: VersionMismatchHandler | None = None,
) -> dict[str, Any]:
    """Read a versioned JSON object and map read failures to domain errors.

    The helper owns only the common file/JSON/object/version skeleton. Callers keep
    their own self-healing missing-file behavior, schema-version policy, and typed
    deserialization.
    """
    path_str = str(path)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise corrupted_error(path_str, f"invalid JSON: {e}") from e
    except OSError as e:
        raise unreadable_error(path_str, f"read error: {e}") from e

    if not isinstance(data, dict):
        raise corrupted_error(path_str, f"expected JSON object, got {type(data).__name__}")

    version = data.get(version_key, missing_version)
    if version is _MISSING or (version is None and none_is_missing):
        reason = missing_version_reason or f"missing {version_key} field"
        raise corrupted_error(path_str, reason)
    if version != expected_version:
        if on_version_mismatch is not None:
            on_version_mismatch(path, data, version)
        raise corrupted_error(
            path_str,
            f"incompatible version {version} (this Forge expects {expected_version}). Delete this file and retry.",
        )

    return data

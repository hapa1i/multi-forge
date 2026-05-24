"""Override manipulation operations.

This module provides functions for validating, parsing, and manipulating
session override values with strict schema validation.

Key validation is strict:
- Keys must be valid SessionIntent paths (derived via dataclass introspection)
- Wildcards (<top_level>.*) are supported and expanded at operation time
"""

from __future__ import annotations

import json
import logging
from dataclasses import fields, is_dataclass
from typing import Any, get_type_hints

from forge.core.typing_helpers import unwrap_optional

from .exceptions import InvalidOverrideKeyError
from .models import SessionIntent

logger = logging.getLogger(__name__)

# Top-level manifest fields that cannot be overridden
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "name",
        "created_at",
        "last_accessed_at",
        "parent_session",
        "is_fork",
        "is_incognito",
        "worktree",
        "intent",
        "overrides",
        "confirmed",
    }
)

# Cache for valid intent paths (computed once)
_valid_paths_cache: set[str] | None = None


def get_valid_intent_paths() -> set[str]:
    """Introspect SessionIntent dataclass to build valid dot-paths.

    This function recursively walks the SessionIntent dataclass and its nested
    dataclasses to build a set of valid override key paths.

    Rules:
    - Optional fields are included (e.g., proxy.template valid even when proxy is None)

    Returns:
        Set of valid dot-notation paths (e.g., {"agent", "proxy.template", ...})
    """
    global _valid_paths_cache
    if _valid_paths_cache is not None:
        return _valid_paths_cache

    paths: set[str] = set()
    _collect_paths(SessionIntent, "", paths)
    _valid_paths_cache = paths
    return paths


def _collect_paths(cls: type | Any, prefix: str, paths: set[str]) -> None:
    """Recursively collect valid paths from a dataclass."""
    if not is_dataclass(cls):
        return

    try:
        hints = get_type_hints(cls)
    except Exception as e:
        logger.debug("Cannot get type hints for %s: %s (using field names)", getattr(cls, "__name__", cls), e)
        hints = {}

    for f in fields(cls):
        name = f.name
        if name.startswith("_"):
            continue

        path = f"{prefix}{name}" if prefix else name
        paths.add(path)

        field_type = hints.get(name, f.type)
        actual_type = unwrap_optional(field_type)

        if is_dataclass(actual_type):
            _collect_paths(actual_type, f"{path}.", paths)


def expand_wildcard(pattern: str, valid_paths: set[str] | None = None) -> list[str]:
    """Expand a wildcard pattern to matching valid paths.

    Only supports <top_level_field>.* patterns (single-segment wildcard).
    More complex patterns like *.tags or proxy.*.foo are not supported in v1.

    Args:
        pattern: Wildcard pattern (e.g., "proxy.*", "memory.*")
        valid_paths: Set of valid paths (defaults to get_valid_intent_paths())

    Returns:
        List of concrete paths matching the pattern.

    Raises:
        InvalidOverrideKeyError: If pattern matches nothing or is unsupported.
    """
    if valid_paths is None:
        valid_paths = get_valid_intent_paths()

    if "*" not in pattern:
        raise InvalidOverrideKeyError(pattern, "not a wildcard pattern")

    parts = pattern.split(".")
    if len(parts) != 2 or parts[1] != "*":
        raise InvalidOverrideKeyError(
            pattern,
            "unsupported wildcard format",
            hint="only <top_level>.* patterns supported (e.g., proxy.*, memory.*)",
        )

    prefix = parts[0]

    if prefix == "custom":
        raise InvalidOverrideKeyError(pattern, "custom.* is not supported")

    matching = [p for p in valid_paths if p.startswith(f"{prefix}.")]

    if not matching:
        if prefix not in valid_paths:
            raise InvalidOverrideKeyError(
                pattern,
                f"unknown field '{prefix}'",
                hint=f"valid top-level fields: {', '.join(sorted(p for p in valid_paths if '.' not in p))}",
            )
        raise InvalidOverrideKeyError(
            pattern,
            f"'{prefix}' has no nested fields to expand",
        )

    return sorted(matching)


def validate_key(key: str) -> list[str]:
    """Validate a dot-notation key and return path segments.

    This performs strict validation against the SessionIntent schema:
    - Rejects empty key or empty segments
    - Rejects intent.* prefix (keys are relative to intent)
    - Rejects confirmed.* (immutable)
    - Rejects top-level manifest fields
    - For other keys: validates against known SessionIntent paths

    Args:
        key: Dot-notation path (e.g., "agent", "proxy.template")

    Returns:
        List of path segments (e.g., ["proxy", "template"]).

    Raises:
        InvalidOverrideKeyError: If key is invalid.
    """
    if not key:
        raise InvalidOverrideKeyError(key, "key cannot be empty")

    parts = key.split(".")

    # Empty segments (e.g., "foo..bar" or ".foo" or "foo.")
    for part in parts:
        if not part:
            raise InvalidOverrideKeyError(key, "empty segment in path")

    first_part = parts[0]

    if first_part == "intent":
        raise InvalidOverrideKeyError(
            key,
            "keys should be relative to intent",
            hint="use 'agent' not 'intent.agent'",
        )

    if first_part == "confirmed":
        raise InvalidOverrideKeyError(
            key,
            "cannot override confirmed.* fields",
            hint="confirmed values are set by hooks and immutable",
        )

    if first_part in _MANIFEST_FIELDS:
        raise InvalidOverrideKeyError(
            key,
            f"'{first_part}' is a manifest field, not an intent field",
            hint="overrides apply to intent configuration only",
        )

    if first_part == "custom":
        raise InvalidOverrideKeyError(key, "custom.* is not supported")

    if "*" in key:
        # Wildcards are handled separately by expand_wildcard
        # validate_key should not receive wildcard keys directly
        raise InvalidOverrideKeyError(
            key,
            "use expand_wildcard() for wildcard patterns",
        )

    valid_paths = get_valid_intent_paths()

    if key in valid_paths:
        return parts

    # Check if it's a valid prefix (for nested access)
    # e.g., "proxy" is valid even though "proxy.template" is what you'd usually set
    if any(p.startswith(f"{key}.") for p in valid_paths):
        return parts

    similar = _find_similar_paths(key, valid_paths)
    hint = None
    if similar:
        hint = f"did you mean: {', '.join(similar[:3])}"
    else:
        top_level = sorted(p for p in valid_paths if "." not in p)
        hint = f"valid top-level fields: {', '.join(top_level)}"

    raise InvalidOverrideKeyError(key, f"unknown field '{key}'", hint=hint)


def _find_similar_paths(key: str, valid_paths: set[str]) -> list[str]:
    """Find paths similar to the given key (simple substring matching)."""
    key_lower = key.lower()
    similar = []
    for path in valid_paths:
        if key_lower in path.lower() or path.lower() in key_lower:
            similar.append(path)
    return sorted(similar)


def parse_value(value: str) -> Any:
    """Parse a value string as JSON-first, fallback to string.

    JSON-first parsing:
    - "true" -> bool True
    - "false" -> bool False
    - "null" -> None
    - "123" -> int 123
    - "3.14" -> float 3.14
    - '["a","b"]' -> list
    - '{"key": "value"}' -> dict
    - Fallback: stored as string

    To force a string value, use JSON string syntax: '"true"' -> "true"

    Args:
        value: The value string from CLI input.

    Returns:
        The parsed value (could be any JSON type or string).
    """
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        # Fallback to string
        return value


def set_override(overrides: dict[str, Any], key: str, value: Any) -> None:
    """Set an override value at the given key path.

    Creates intermediate dicts as needed for nested paths.
    If key contains a wildcard, expands and sets each matching path.

    Args:
        overrides: The overrides dict to modify (mutated in place).
        key: Dot-notation path or wildcard pattern (e.g., "agent", "proxy.*").
        value: The value to set.
    """
    if "*" in key:
        expanded = expand_wildcard(key)
        for path in expanded:
            _set_path(overrides, path.split("."), value)
        return

    parts = validate_key(key)
    _set_path(overrides, parts, value)


def _set_path(d: dict[str, Any], parts: list[str], value: Any) -> None:
    """Set a value at the given path, creating intermediate dicts."""
    current = d
    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        elif not isinstance(current[part], dict):
            # Overwrite non-dict intermediate
            current[part] = {}
        current = current[part]

    current[parts[-1]] = value


def delete_override(overrides: dict[str, Any], key: str) -> bool:
    """Delete an override at the given key path.

    If key contains a wildcard, expands and deletes each matching path.

    Args:
        overrides: The overrides dict to modify (mutated in place).
        key: Dot-notation path or wildcard pattern.

    Returns:
        True if any key was deleted, False if nothing existed to delete.
    """
    if "*" in key:
        expanded = expand_wildcard(key)
        any_deleted = False
        for path in expanded:
            if _delete_path(overrides, path.split(".")):
                any_deleted = True
        return any_deleted

    # Validate key (allows us to catch invalid paths even on delete)
    parts = validate_key(key)
    return _delete_path(overrides, parts)


def _delete_path(d: dict[str, Any], parts: list[str]) -> bool:
    """Delete a value at the given path. Returns True if deleted."""
    current = d
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            return False
        current = current[part]

    if parts[-1] in current:
        del current[parts[-1]]
        return True
    return False


def clear_overrides(overrides: dict[str, Any]) -> None:
    """Clear all overrides."""
    overrides.clear()

"""Effective configuration computation (intent + overrides).

This module provides functions for computing the effective session configuration
by merging the baseline intent with runtime overrides.

Merge semantics:
- Scalars: override replaces base value
- Dicts: recursively merge (override keys win on conflict)
- Lists: override replaces entire list (no concatenation)
- None in override: clears the field (effective value becomes None)
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any

import dacite

from .exceptions import InvalidOverrideKeyError, InvalidOverrideValueError
from .models import SessionIntent, SessionState


def apply_overrides(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Apply user overrides to a base configuration dict.

    This is a generic merge function with no schema awareness.
    Schema validation happens in compute_effective_intent().

    Merge semantics:
    - Scalars: override replaces base
    - Dicts: recursively merge (both must be dicts)
    - Lists: override replaces entire list (no concatenation)
    - None in override: sets field to None (clears it)
    - New keys in override: added to result

    Args:
        base: The base dictionary (typically from intent).
        overrides: The overrides dictionary (sparse, only changed fields).

    Returns:
        A new dict with overrides applied to base.
    """
    result = deepcopy(base)

    for key, value in overrides.items():
        if value is None:
            result[key] = None
        elif isinstance(value, dict) and key in result and isinstance(result[key], dict):
            result[key] = apply_overrides(result[key], value)
        else:
            result[key] = deepcopy(value)

    return result


def compute_effective_intent(
    state: SessionState,
    strict: bool = True,
    override_key: str | None = None,
) -> SessionIntent:
    """Compute effective config by merging intent with overrides.

    Args:
        state: The session state containing intent and overrides.
        strict: If True, validate the merged result can become a valid SessionIntent.
                Raises InvalidOverrideValueError on type mismatches.
        override_key: If provided, used in error messages to identify which override
                      caused the failure. Typically the key being set via CLI.

    Returns:
        A SessionIntent representing the effective configuration.

    Raises:
        InvalidOverrideValueError: If strict=True and the merged config has invalid types.
    """
    intent_dict = asdict(state.intent)

    if state.overrides:
        merged = apply_overrides(intent_dict, state.overrides)
    else:
        merged = intent_dict

    # Defensive: strip removed designated_docs from merged dict. Primary guard
    # is store.strip_preview_memory_doc_lists(); this covers code paths that
    # construct a merged dict without going through SessionStore.read().
    mem = merged.get("memory")
    if isinstance(mem, dict):
        mem.pop("designated_docs", None)

    if strict:
        try:
            return dacite.from_dict(
                data_class=SessionIntent,
                data=merged,
                config=dacite.Config(strict=True),
            )
        except (dacite.DaciteError, TypeError, ValueError) as e:
            key = override_key or "unknown"
            actual = _infer_actual_type(e, merged)
            expected = _infer_expected_type(e)
            raise InvalidOverrideValueError(key, expected, actual) from e

    return dacite.from_dict(
        data_class=SessionIntent,
        data=merged,
        config=dacite.Config(strict=True),
    )


def get_effective_value(state: SessionState, key: str) -> Any | None:
    """Get effective value for a specific dot-notation key.

    This function validates the key syntax but returns None for valid keys
    that are not present in the effective config (rather than raising).

    Args:
        state: The session state.
        key: Dot-notation path (e.g., "agent", "proxy.template").

    Returns:
        The effective value, or None if key is valid but not set.

    Raises:
        InvalidOverrideKeyError: If key syntax is invalid (empty, empty segments).
    """
    if not key:
        raise InvalidOverrideKeyError(key, "key cannot be empty")

    parts = key.split(".")
    for part in parts:
        if not part:
            raise InvalidOverrideKeyError(key, "empty segment in path")

    effective = compute_effective_intent(state, strict=True)
    effective_dict = asdict(effective)

    current: Any = effective_dict
    for part in parts:
        if not isinstance(current, dict):
            return None
        if part not in current:
            return None
        current = current[part]

    return current


def _infer_actual_type(error: Exception, merged: dict[str, Any]) -> str:
    """Try to infer the actual type/value from a dacite error."""
    error_str = str(error)

    if "expected" in error_str.lower() and "got" in error_str.lower():
        return error_str

    return f"invalid value ({error_str})"


def _infer_expected_type(error: Exception) -> str:
    """Try to infer the expected type from a dacite error."""
    error_str = str(error)

    if "str" in error_str:
        return "str"
    if "list" in error_str:
        return "list"
    if "int" in error_str:
        return "int"
    if "bool" in error_str:
        return "bool"

    return "valid type"

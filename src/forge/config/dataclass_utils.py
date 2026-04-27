"""Dict-to-dataclass conversion utilities.

Extracted from loader.py to break the loader ↔ schema import cycle (CR-007).
"""

from __future__ import annotations

import types
from dataclasses import fields, is_dataclass
from typing import Any, Union, get_args, get_origin


def _is_union_type(origin: Any) -> bool:
    """Check if origin indicates a Union type (typing.Union or types.UnionType)."""
    if origin is Union:
        return True
    # PEP604 union (e.g., int | str, X | None) — Python 3.10+
    if origin is types.UnionType:
        return True
    return False


def _unwrap_optional(field_type: Any) -> tuple[Any, bool]:
    """Unwrap Optional[X] or X | None to X.

    Returns:
        (unwrapped_type, is_optional): The unwrapped type and whether it was Optional.
    """
    origin = get_origin(field_type)
    if not _is_union_type(origin):
        return field_type, False

    args = get_args(field_type)
    non_none_args = [a for a in args if a is not type(None)]

    if type(None) in args and len(non_none_args) == 1:
        return non_none_args[0], True

    return field_type, False


def dict_to_dataclass(cls: type[Any], data: dict, *, strict: bool = False) -> Any:
    """Convert nested dict to dataclass instance.

    Recursively converts nested dicts to their corresponding dataclass types.
    Handles Optional types, lists, and primitive types.

    Args:
        strict: If True, raise ValueError on unknown keys not present in the dataclass.
    """
    if not is_dataclass(cls):
        return data  # type: ignore[return-value]  # returns raw dict when cls is not a dataclass

    if strict:
        known = {f.name for f in fields(cls)}
        unknown = set(data.keys()) - known
        if unknown:
            raise ValueError(f"{cls.__name__} has unknown fields: {', '.join(sorted(unknown))}")

    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue

        value = data[f.name]
        field_type = f.type

        unwrapped_type, is_optional = _unwrap_optional(field_type)

        if value is None and is_optional:
            kwargs[f.name] = value
            continue

        origin = get_origin(unwrapped_type)

        if origin is list and isinstance(value, list):
            kwargs[f.name] = value
        elif is_dataclass(unwrapped_type) and isinstance(value, dict):
            if isinstance(unwrapped_type, type):
                kwargs[f.name] = dict_to_dataclass(unwrapped_type, value, strict=strict)
            else:
                kwargs[f.name] = value
        elif _is_union_type(origin):
            kwargs[f.name] = value
        else:
            kwargs[f.name] = value

    return cls(**kwargs)

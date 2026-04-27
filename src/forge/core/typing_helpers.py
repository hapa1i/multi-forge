"""Typing utility helpers shared across Forge modules."""

from __future__ import annotations

from typing import Any, get_args, get_origin


def unwrap_optional(tp: Any) -> Any:
    """Unwrap Optional[T] (i.e., Union[T, None]) to get T.

    Returns the original type unchanged if it is not Optional.
    """
    origin = get_origin(tp)
    if origin is None:
        return tp

    # Handle Union types (Optional is Union[T, None])
    args = get_args(tp)
    if args:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]

    return tp

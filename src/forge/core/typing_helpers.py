"""Typing utility helpers shared across Forge modules."""

from __future__ import annotations

import types
from typing import Any, Union, get_args, get_origin


def unwrap_optional(tp: Any) -> Any:
    """Unwrap Optional[T] (i.e., Union[T, None]) to get T.

    Returns the original type unchanged if it is not Optional.
    """
    origin = get_origin(tp)
    if origin is not Union and origin is not types.UnionType:
        return tp

    args = get_args(tp)
    non_none = [arg for arg in args if arg is not type(None)]
    if type(None) in args and len(non_none) == 1:
        return non_none[0]

    return tp

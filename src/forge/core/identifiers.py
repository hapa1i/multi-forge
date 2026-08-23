"""Dependency-light identifier grammar shared across backend boundaries."""

from __future__ import annotations

import re

_LOWERCASE_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


def is_lowercase_identifier(value: object) -> bool:
    """Return whether a value uses Forge's lowercase safe-token grammar."""
    return isinstance(value, str) and _LOWERCASE_IDENTIFIER_RE.fullmatch(value) is not None


__all__ = ["is_lowercase_identifier"]

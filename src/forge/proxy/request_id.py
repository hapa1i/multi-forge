"""Validation for untrusted client request-correlation identifiers."""

from __future__ import annotations

import re
from typing import TypeGuard

REQUEST_ID_MAX_LENGTH = 128

_REQUEST_ID_RE = re.compile(rf"[A-Za-z0-9._-]{{1,{REQUEST_ID_MAX_LENGTH}}}")


def is_valid_request_id(value: str | None) -> TypeGuard[str]:
    """Return whether ``value`` is a bounded, single-token client request ID.

    Accepted values are preserved exactly. Rejecting rather than normalizing keeps
    two distinct client identifiers from collapsing onto the same correlation key.
    """
    if value is None or len(value) > REQUEST_ID_MAX_LENGTH:
        return False
    return _REQUEST_ID_RE.fullmatch(value) is not None

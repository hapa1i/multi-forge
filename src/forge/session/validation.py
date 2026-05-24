"""Session name and path validation."""

from __future__ import annotations

import re
from pathlib import Path

from .exceptions import InvalidSessionNameError

# Constants
MIN_NAME_LENGTH = 2
MAX_NAME_LENGTH = 64

# Regex: lowercase alphanumeric, hyphens allowed in middle, no consecutive hyphens
# Must start and end with alphanumeric
_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def validate_name(name: str) -> None:
    """Validate a session name.

    Raises:
        InvalidSessionNameError: If name is invalid, with specific reason.

    Rules:
        - Length: 2-64 characters
        - Characters: lowercase alphanumeric + hyphens
        - Must start with alphanumeric
        - Must end with alphanumeric
        - No consecutive hyphens

    Examples:
        Valid: "auth-feature", "bugfix-123", "a1"
        Invalid: "-invalid", "invalid-", "in--valid", "UPPERCASE"
    """
    if len(name) < MIN_NAME_LENGTH:
        raise InvalidSessionNameError(f"name must be at least {MIN_NAME_LENGTH} characters")

    if len(name) > MAX_NAME_LENGTH:
        raise InvalidSessionNameError(f"name must be at most {MAX_NAME_LENGTH} characters")

    if not _NAME_PATTERN.match(name):
        raise InvalidSessionNameError(
            "name must be lowercase alphanumeric with hyphens, starting and ending with alphanumeric"
        )

    if "--" in name:
        raise InvalidSessionNameError("name cannot contain consecutive hyphens")


# ---------------------------------------------------------------------------
# Path safety validation
# ---------------------------------------------------------------------------

_UNSAFE_PATH_RE = re.compile(r"[`\x00-\x1f\x7f]")


def is_safe_designated_doc_path(path: str, base: Path, resolved_base: Path) -> str | None:
    """Check a single path for safety. Return rejection reason or None if safe."""
    if Path(path).is_absolute():
        return f"absolute path: {path}"
    if _UNSAFE_PATH_RE.search(path):
        return f"unsafe characters: {path!r}"
    abs_path = (base / path).resolve()
    if not abs_path.is_relative_to(resolved_base):
        return f"escapes base directory: {path}"
    return None

"""Session name validation."""

from __future__ import annotations

import re

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

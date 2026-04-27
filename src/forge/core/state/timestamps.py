"""Timestamp utilities for Forge state files.

All timestamps are stored as ISO8601 strings for JSON compatibility.
Uses UTC exclusively for consistent timestamps across time zones.
"""

from __future__ import annotations

from datetime import UTC, datetime


def now_iso() -> str:
    """Return current UTC time as ISO8601 string.

    Format: '2024-01-15T10:30:00+00:00'

    Returns:
        ISO8601 formatted string with UTC timezone (+00:00 suffix).
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_iso(s: str) -> datetime:
    """Parse ISO8601 string to timezone-aware datetime in UTC.

    Handles common ISO8601 formats:
    - With 'Z' suffix: '2024-01-15T10:30:00Z'
    - With offset: '2024-01-15T10:30:00+00:00'

    Args:
        s: ISO8601 formatted string.

    Returns:
        Timezone-aware datetime normalized to UTC.

    Raises:
        ValueError: If the string is not valid ISO8601 or lacks timezone info.
    """
    normalized = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)

    if dt.tzinfo is None:
        raise ValueError(f"ISO8601 string must include timezone info, got naive datetime: '{s}'")

    return dt.astimezone(UTC)


def iso_to_timestamp(iso_str: str) -> float:
    """Convert ISO8601 string to Unix timestamp.

    Args:
        iso_str: ISO8601 formatted string with timezone.

    Returns:
        Unix timestamp as float (seconds since epoch).

    Raises:
        ValueError: If the string is not valid ISO8601 or lacks timezone info.
    """
    return parse_iso(iso_str).timestamp()

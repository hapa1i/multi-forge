"""Timestamp parsing, local-period, and elapsed-time utilities.

All timestamps are stored as ISO8601 strings for JSON compatibility.
Stored values and returned bounds use UTC consistently across time zones.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta, tzinfo
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo

from dateutil.tz import gettz


class RelativeTimeStyle(StrEnum):
    """Named presentation policies for elapsed timestamps."""

    COMPACT = "compact"
    FULL_WORDS = "full_words"


def _local_timezone() -> tzinfo:
    """Resolve the host timezone with transition rules when the platform exposes them.

    ``TZ`` accepts the process-local forms supported by POSIX environments: an
    empty value selects UTC, while IANA keys, absolute or colon-prefixed TZif
    paths, and POSIX rule strings retain their transition rules. Invalid values
    fall back to ``/etc/localtime``.
    """
    timezone_name = os.environ.get("TZ")
    if timezone_name == "":
        return UTC
    if timezone_name is not None:
        try:
            if timezone := gettz(timezone_name):
                return timezone
        except (OSError, ValueError):
            pass

    try:
        with Path("/etc/localtime").open("rb") as localtime_file:
            return ZoneInfo.from_file(localtime_file)
    except (OSError, ValueError):
        # Some platforms expose only the current fixed offset. It remains a safe
        # fallback, though callers can supply an aware ``now`` for exact zone rules.
        return datetime.now().astimezone().tzinfo or UTC


def now_iso() -> str:
    """Return current UTC time as ISO8601 string.

    Format: '2024-01-15T10:30:00+00:00'

    Returns:
        ISO8601 formatted string with UTC timezone (+00:00 suffix).
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def utc_timestamp_z() -> str:
    """Return the current UTC time as a second-precision ISO8601 ``Z`` timestamp."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_today() -> date:
    """Return the current UTC calendar date."""
    return datetime.now(UTC).date()


def parse_iso(s: str, *, assume_naive_utc: bool = False) -> datetime:
    """Parse ISO8601 string to timezone-aware datetime in UTC.

    Handles common ISO8601 formats:
    - With 'Z' suffix: '2024-01-15T10:30:00Z'
    - With offset: '2024-01-15T10:30:00+00:00'

    Args:
        s: ISO8601 formatted string.
        assume_naive_utc: Treat a timestamp without timezone information as UTC.
            The strict default rejects naive values; compatibility readers must opt in
            explicitly rather than inheriting the host timezone.

    Returns:
        Timezone-aware datetime normalized to UTC.

    Raises:
        ValueError: If the string is not valid ISO8601 or lacks timezone info under
            the selected policy.
    """
    normalized = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)

    if dt.tzinfo is None:
        if not assume_naive_utc:
            raise ValueError(f"ISO8601 string must include timezone info, got naive datetime: '{s}'")
        dt = dt.replace(tzinfo=UTC)

    return dt.astimezone(UTC)


def try_parse_iso(value: object, *, assume_naive_utc: bool = False) -> datetime | None:
    """Best-effort ISO parser with explicit naive-value policy.

    Non-string and malformed values return ``None``. Naive strings are rejected by
    default or interpreted as UTC only when ``assume_naive_utc`` is explicitly set.
    Valid offsets are always normalized to UTC.
    """
    if not isinstance(value, str):
        return None
    try:
        return parse_iso(value, assume_naive_utc=assume_naive_utc)
    except (TypeError, ValueError):
        return None


def local_period_bounds(period: str, *, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return UTC bounds for a local-calendar ``today``, ``week``, or ``month``.

    ``now`` must be timezone-aware when supplied; its timezone defines the local
    calendar and retains DST transitions while calculating earlier boundaries. The
    default uses the host's current local timezone. Callers own any ``all`` sentinel.
    """
    now_local = now if now is not None else datetime.now(_local_timezone())
    if now_local.tzinfo is None:
        raise ValueError("local period calculation requires a timezone-aware datetime")

    midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        start = midnight
    elif period == "week":
        start = midnight - timedelta(days=midnight.weekday())
    elif period == "month":
        start = midnight.replace(day=1)
    else:
        raise ValueError(f"Unknown local period: {period!r}")
    return start.astimezone(UTC), now_local.astimezone(UTC)


def format_compact_duration(seconds: float) -> str:
    """Format elapsed seconds with compact proxy-style units."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.0f}m"
    if seconds < 86400:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    return f"{days}d {hours}h"


def format_relative_time(
    value: object,
    *,
    style: RelativeTimeStyle,
    invalid: str,
    assume_naive_utc: bool = False,
    now: datetime | None = None,
) -> str:
    """Render an ISO timestamp relative to ``now`` using a named style.

    ``invalid`` and ``assume_naive_utc`` make each caller's compatibility policy
    explicit. Future values render as ``just now`` in both established styles.
    """
    parsed = try_parse_iso(value, assume_naive_utc=assume_naive_utc)
    if parsed is None:
        return invalid

    current = now if now is not None else datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("relative-time calculation requires a timezone-aware datetime")
    seconds = (current.astimezone(UTC) - parsed).total_seconds()
    if seconds < 0:
        return "just now"

    if style is RelativeTimeStyle.COMPACT:
        return f"{format_compact_duration(seconds)} ago"
    if style is not RelativeTimeStyle.FULL_WORDS:
        raise ValueError(f"Unknown relative-time style: {style!r}")
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes} min{'s' if minutes != 1 else ''} ago"
    if seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    if seconds < 604800:
        days = int(seconds / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    weeks = int(seconds / 604800)
    return f"{weeks} week{'s' if weeks != 1 else ''} ago"


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

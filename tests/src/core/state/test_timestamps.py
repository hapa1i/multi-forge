"""Tests for core.state.timestamps module."""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from forge.core.state import iso_to_timestamp, now_iso, parse_iso, utc_timestamp_z


class TestNowIso:
    """Tests for now_iso function."""

    def test_returns_string(self) -> None:
        """now_iso returns a string."""
        result = now_iso()
        assert isinstance(result, str)

    def test_returns_utc_with_offset_suffix(self) -> None:
        """now_iso returns timestamp with +00:00 suffix (not Z)."""
        result = now_iso()
        assert result.endswith("+00:00")

    def test_is_valid_iso8601(self) -> None:
        """now_iso returns valid ISO8601 that can be parsed."""
        result = now_iso()
        # Should parse without error
        dt = datetime.fromisoformat(result)
        assert dt.tzinfo is not None

    def test_is_approximately_current_time(self) -> None:
        """now_iso returns approximately the current time (second precision)."""
        before = datetime.now(UTC).replace(microsecond=0)
        result = now_iso()
        after = datetime.now(UTC).replace(microsecond=0)

        parsed = datetime.fromisoformat(result)
        assert before <= parsed <= after


class TestUtcTimestampZ:
    """Tests for the compact telemetry timestamp helper."""

    def test_returns_second_precision_z_timestamp(self) -> None:
        result = utc_timestamp_z()
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", result)
        assert parse_iso(result).tzinfo is UTC

    def test_now_iso_has_single_def(self) -> None:
        repo_root = Path(__file__).resolve().parents[4]
        matches: list[Path] = []
        for path in (repo_root / "src" / "forge").rglob("*.py"):
            if re.search(r"def _?now_iso", path.read_text(encoding="utf-8")):
                matches.append(path.relative_to(repo_root))
        assert matches == [Path("src/forge/core/state/timestamps.py")]


class TestParseIso:
    """Tests for parse_iso function."""

    def test_parses_offset_format(self) -> None:
        """parse_iso handles +00:00 format."""
        result = parse_iso("2024-01-15T10:30:00+00:00")
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30
        assert result.second == 0
        assert result.tzinfo is UTC

    def test_parses_z_suffix(self) -> None:
        """parse_iso handles Z suffix."""
        result = parse_iso("2024-01-15T10:30:00Z")
        assert result.year == 2024
        assert result.tzinfo is UTC

    def test_parses_non_utc_offset(self) -> None:
        """parse_iso normalizes non-UTC offsets to UTC."""
        result = parse_iso("2024-01-15T10:30:00+05:30")
        assert result.tzinfo is UTC
        # 10:30 at +05:30 == 05:00 UTC
        assert result.hour == 5
        assert result.minute == 0

    def test_rejects_naive_datetime(self) -> None:
        """parse_iso rejects naive datetimes (no timezone)."""
        with pytest.raises(ValueError) as exc_info:
            parse_iso("2024-01-15T10:30:00")
        assert "timezone" in str(exc_info.value).lower()
        assert "naive" in str(exc_info.value).lower()

    def test_roundtrip_with_now_iso(self) -> None:
        """parse_iso can parse output of now_iso."""
        original = now_iso()
        parsed = parse_iso(original)
        assert isinstance(parsed, datetime)
        assert parsed.tzinfo is not None


class TestIsoToTimestamp:
    """Tests for iso_to_timestamp function."""

    def test_returns_float(self) -> None:
        """iso_to_timestamp returns a float."""
        result = iso_to_timestamp("2024-01-15T10:30:00+00:00")
        assert isinstance(result, float)

    def test_known_timestamp(self) -> None:
        """iso_to_timestamp returns correct Unix timestamp."""
        # 2024-01-15T00:00:00+00:00 = Unix timestamp 1705276800
        result = iso_to_timestamp("2024-01-15T00:00:00+00:00")
        assert result == 1705276800.0

    def test_handles_z_suffix(self) -> None:
        """iso_to_timestamp handles Z suffix."""
        result = iso_to_timestamp("2024-01-15T00:00:00Z")
        assert result == 1705276800.0

    def test_rejects_naive_datetime(self) -> None:
        """iso_to_timestamp rejects naive datetimes."""
        with pytest.raises(ValueError):
            iso_to_timestamp("2024-01-15T10:30:00")

    def test_useful_for_sorting(self) -> None:
        """Timestamps can be used for sorting."""
        earlier = iso_to_timestamp("2024-01-15T10:00:00+00:00")
        later = iso_to_timestamp("2024-01-15T11:00:00+00:00")
        assert earlier < later

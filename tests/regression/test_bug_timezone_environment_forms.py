"""Regression: local period filters must honor every valid process ``TZ`` form."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from zoneinfo import TZPATH

import pytest

from forge.core.state import local_period_bounds
from forge.core.state import timestamps as timestamps_module

pytestmark = pytest.mark.regression


def _new_york_tzif() -> Path:
    for root in TZPATH:
        candidate = Path(root) / "America" / "New_York"
        if candidate.is_file():
            return candidate
    raise AssertionError("America/New_York TZif data is required on supported POSIX platforms")


class _FrozenSummerDateTime(datetime):
    @classmethod
    def now(cls, timezone: tzinfo | None = None) -> "_FrozenSummerDateTime":
        return cls(2026, 8, 14, 12, 30, tzinfo=timezone)


def test_empty_tz_selects_utc_for_local_period_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_resolution(_value: object) -> None:
        raise AssertionError("empty TZ must not reach dateutil or /etc/localtime")

    monkeypatch.setenv("TZ", "")
    monkeypatch.setattr(timestamps_module, "gettz", unexpected_resolution)
    monkeypatch.setattr(timestamps_module, "Path", unexpected_resolution)

    assert timestamps_module._local_timezone() is UTC

    monkeypatch.setattr(timestamps_module, "datetime", _FrozenSummerDateTime)
    assert local_period_bounds("today") == (
        datetime(2026, 8, 14, tzinfo=UTC),
        datetime(2026, 8, 14, 12, 30, tzinfo=UTC),
    )


@pytest.mark.parametrize("colon_prefix", [False, True])
def test_absolute_tzif_path_controls_local_period_bounds(
    monkeypatch: pytest.MonkeyPatch,
    colon_prefix: bool,
) -> None:
    zone_path = str(_new_york_tzif())
    monkeypatch.setenv("TZ", f":{zone_path}" if colon_prefix else zone_path)
    monkeypatch.setattr(timestamps_module, "datetime", _FrozenSummerDateTime)

    assert local_period_bounds("today") == (
        datetime(2026, 8, 14, 4, tzinfo=UTC),
        datetime(2026, 8, 14, 16, 30, tzinfo=UTC),
    )


def test_posix_rule_tz_retains_summer_and_winter_transitions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "EST5EDT,M3.2.0,M11.1.0")
    timezone = timestamps_module._local_timezone()

    assert datetime(2026, 1, 15, tzinfo=timezone).utcoffset() == -timedelta(hours=5)
    assert datetime(2026, 8, 14, tzinfo=timezone).utcoffset() == -timedelta(hours=4)

    monkeypatch.setattr(timestamps_module, "datetime", _FrozenSummerDateTime)
    assert local_period_bounds("today") == (
        datetime(2026, 8, 14, 4, tzinfo=UTC),
        datetime(2026, 8, 14, 16, 30, tzinfo=UTC),
    )

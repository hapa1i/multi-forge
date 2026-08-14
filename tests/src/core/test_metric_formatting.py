"""Golden tests for shared metric presentation policies."""

from __future__ import annotations

from collections.abc import Callable
from inspect import Parameter, signature

import pytest

from forge.core.metric_formatting import (
    TokenDisplayPolicy,
    UsdDisplayPolicy,
    format_token_count,
    format_usd,
    format_usd_micros,
)


@pytest.mark.parametrize("formatter", [format_token_count, format_usd, format_usd_micros])
def test_presentation_policy_is_mandatory(formatter: Callable[..., str]) -> None:
    parameter = signature(formatter).parameters["policy"]

    assert parameter.kind is Parameter.KEYWORD_ONLY
    assert parameter.default is Parameter.empty


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (-1, "-1"),
        (42, "42"),
        (999, "999"),
        (1_000, "1.0K"),
        (12_500, "12.5K"),
        (999_999, "1000.0K"),
        (1_000_000, "1.0M"),
        (1_500_000, "1.5M"),
    ],
)
def test_upper_tenths_token_policy(count: int, expected: str) -> None:
    assert format_token_count(count, policy=TokenDisplayPolicy.UPPER_TENTHS) == expected


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (-1, "-1"),
        (42, "42"),
        (999, "999"),
        (1_000, "1k"),
        (12_500, "12k"),
        (13_500, "14k"),
        (999_999, "1000k"),
        (1_000_000, "1.0M"),
    ],
)
def test_activity_compact_token_policy(count: int, expected: str) -> None:
    assert format_token_count(count, policy=TokenDisplayPolicy.ACTIVITY_COMPACT) == expected


@pytest.mark.parametrize(
    ("micros", "expected"),
    [
        (0, "$0.00"),
        (1, "$0.000001"),
        (3, "$0.000003"),
        (99, "$0.000099"),
        (100, "$0.0001"),
        (500, "$0.0005"),
        (9_999, "$0.0100"),
        (10_000, "$0.01"),
        (50_000, "$0.05"),
        (999_999, "$1.00"),
        (1_000_000, "$1.00"),
        (1_500_000, "$1.50"),
        (1_234_567_890, "$1,234.57"),
    ],
)
def test_cost_detail_usd_policy(micros: int, expected: str) -> None:
    assert format_usd_micros(micros, policy=UsdDisplayPolicy.COST_DETAIL) == expected


@pytest.mark.parametrize(
    ("micros", "expected"),
    [
        (0, "$0.00"),
        (1, "$0.0000"),
        (1_200, "$0.0012"),
        (9_999, "$0.0100"),
        (10_000, "$0.01"),
        (40_000, "$0.04"),
        (-1_200, "$-0.0012"),
    ],
)
def test_activity_detail_usd_policy(micros: int, expected: str) -> None:
    assert format_usd_micros(micros, policy=UsdDisplayPolicy.ACTIVITY_DETAIL) == expected


@pytest.mark.parametrize(
    ("micros", "expected"),
    [(0, "$0.00"), (4_000, "$0.00"), (40_000, "$0.04"), (1_234_567, "$1.23")],
)
def test_fixed_cents_usd_policy(micros: int, expected: str) -> None:
    assert format_usd_micros(micros, policy=UsdDisplayPolicy.FIXED_CENTS) == expected


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(0.005, "0c"), (0.009999, "0c"), (0.01, "$0.01"), (1.234, "$1.23")],
)
def test_status_whole_cents_usd_policy(amount: float, expected: str) -> None:
    assert format_usd(amount, policy=UsdDisplayPolicy.STATUS_WHOLE_CENTS) == expected


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(0.00001, "0.0c"), (0.005, "0.5c"), (0.00509, "0.5c"), (0.009999, "0.99c"), (0.01, "$0.01"), (1.234, "$1.23")],
)
def test_status_fractional_cents_usd_policy(amount: float, expected: str) -> None:
    assert format_usd(amount, policy=UsdDisplayPolicy.STATUS_FRACTIONAL_CENTS) == expected


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(0.0, "$0.00"), (0.0005, "$0.0005"), (0.001, "$0.0010"), (0.01, "$0.01"), (42.0, "$42.00")],
)
def test_spend_cap_usd_policy(amount: float, expected: str) -> None:
    assert format_usd(amount, policy=UsdDisplayPolicy.SPEND_CAP) == expected

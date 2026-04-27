"""Tests for reasoning effort derivation and ranking in the proxy server.

Covers _derive_reasoning_effort (thinking config -> effort string) and
_max_effort (effort comparison for tier override floor).
"""

import pytest

from forge.proxy.server import _derive_reasoning_effort, _max_effort


class TestDeriveReasoningEffort:
    """Tests for thinking config -> reasoning_effort translation."""

    # -- budget_tokens path (primary) --

    @pytest.mark.parametrize(
        "budget, expected",
        [
            (30_000, "xhigh"),
            (25_000, "xhigh"),
            (24_999, "high"),
            (10_000, "high"),
            (9_999, "medium"),
            (2_000, "medium"),
            (1_999, "low"),
            (500, "low"),
            (499, "minimal"),
            (1, "minimal"),
        ],
    )
    def test_budget_thresholds(self, budget: int, expected: str):
        """Budget tokens map to correct effort levels at each boundary."""
        result = _derive_reasoning_effort({"budget_tokens": budget})
        assert result == expected

    def test_fractional_budget_below_one(self):
        """Fractional budget in (0, 1) falls through to minimal."""
        result = _derive_reasoning_effort({"budget_tokens": 0.5})
        assert result == "minimal"

    def test_zero_budget_skips_budget_path(self):
        """budget_tokens=0 is not > 0, so budget path is skipped."""
        result = _derive_reasoning_effort({"budget_tokens": 0})
        assert result is None

    def test_negative_budget_skips_budget_path(self):
        result = _derive_reasoning_effort({"budget_tokens": -100})
        assert result is None

    # -- type-based fallback --

    @pytest.mark.parametrize(
        "thinking_type, expected",
        [
            ("enabled", "high"),
            ("adaptive", "medium"),
            ("disabled", "none"),
        ],
    )
    def test_type_mapping(self, thinking_type: str, expected: str):
        result = _derive_reasoning_effort({"type": thinking_type})
        assert result == expected

    def test_unknown_type_defaults_to_medium(self):
        result = _derive_reasoning_effort({"type": "experimental"})
        assert result == "medium"

    # -- budget takes priority over type --

    def test_budget_overrides_type(self):
        """When both budget_tokens and type are present, budget wins."""
        result = _derive_reasoning_effort({"type": "disabled", "budget_tokens": 10_000})
        assert result == "high"  # budget says high, not type's "none"

    # -- edge cases --

    def test_none_input(self):
        assert _derive_reasoning_effort(None) is None

    def test_non_dict_input(self):
        assert _derive_reasoning_effort("high") is None

    def test_empty_dict(self):
        assert _derive_reasoning_effort({}) is None


class TestMaxEffort:
    """Tests for _max_effort (picks the higher of two effort levels)."""

    def test_none_left_returns_right(self):
        assert _max_effort(None, "high") == "high"

    def test_none_right_returns_left(self):
        assert _max_effort("low", None) == "low"

    def test_both_none(self):
        assert _max_effort(None, None) is None

    @pytest.mark.parametrize(
        "a, b, expected",
        [
            ("high", "low", "high"),
            ("low", "high", "high"),
            ("medium", "medium", "medium"),
            ("xhigh", "high", "xhigh"),
            ("high", "xhigh", "xhigh"),
            ("minimal", "low", "low"),
            ("none", "minimal", "minimal"),
            ("disable", "minimal", "minimal"),  # disable aliases none (rank 0)
            ("xhigh", "none", "xhigh"),
        ],
    )
    def test_picks_higher(self, a: str, b: str, expected: str):
        assert _max_effort(a, b) == expected

    def test_unknown_value_treated_as_medium(self):
        """Unknown effort strings get default rank (3 = medium)."""
        # "turbo" isn't in _EFFORT_RANK, defaults to rank 3 (medium)
        assert _max_effort("turbo", "low") == "turbo"  # rank 3 > rank 2
        assert _max_effort("turbo", "high") == "high"  # rank 3 < rank 4

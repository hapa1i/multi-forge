"""Tests for the proxy's thinking -> reasoning_effort translation module.

Covers derive_reasoning_effort (thinking config -> effort string),
max_effort (effort comparison for tier override floor), and the
model-aware normalization (supported_efforts_for_model,
clamp_effort_to_supported, resolve_reasoning_effort).
"""

from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import HTTPException

from forge.config import TierOverride
from forge.proxy.reasoning import (
    clamp_effort_to_supported,
    derive_reasoning_effort,
    max_effort,
    resolve_reasoning_effort,
    supported_efforts_for_model,
)


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
        result = derive_reasoning_effort({"budget_tokens": budget})
        assert result == expected

    def test_fractional_budget_below_one(self):
        """Fractional budget in (0, 1) falls through to minimal."""
        result = derive_reasoning_effort({"budget_tokens": 0.5})
        assert result == "minimal"

    def test_zero_budget_skips_budget_path(self):
        """budget_tokens=0 is not > 0, so budget path is skipped."""
        result = derive_reasoning_effort({"budget_tokens": 0})
        assert result is None

    def test_negative_budget_skips_budget_path(self):
        result = derive_reasoning_effort({"budget_tokens": -100})
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
        result = derive_reasoning_effort({"type": thinking_type})
        assert result == expected

    def test_unknown_type_defaults_to_medium(self):
        result = derive_reasoning_effort({"type": "experimental"})
        assert result == "medium"

    # -- budget takes priority over type --

    def test_budget_overrides_type(self):
        """When both budget_tokens and type are present, budget wins."""
        result = derive_reasoning_effort({"type": "disabled", "budget_tokens": 10_000})
        assert result == "high"  # budget says high, not type's "none"

    # -- edge cases --

    def test_none_input(self):
        assert derive_reasoning_effort(None) is None

    def test_non_dict_input(self):
        assert derive_reasoning_effort("high") is None

    def test_empty_dict(self):
        assert derive_reasoning_effort({}) is None


class TestMaxEffort:
    """Tests for max_effort (picks the higher of two effort levels)."""

    def test_none_left_returns_right(self):
        assert max_effort(None, "high") == "high"

    def test_none_right_returns_left(self):
        assert max_effort("low", None) == "low"

    def test_both_none(self):
        assert max_effort(None, None) is None

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
        assert max_effort(a, b) == expected

    def test_unknown_value_treated_as_medium(self):
        """Unknown effort strings get default rank (3 = medium)."""
        # "turbo" isn't in EFFORT_RANK, defaults to rank 3 (medium)
        assert max_effort("turbo", "low") == "turbo"  # rank 3 > rank 2
        assert max_effort("turbo", "high") == "high"  # rank 3 < rank 4


class TestSupportedEffortsForModel:
    """Tests for catalog effort-level lookup by mapped model id."""

    def test_cataloged_model_via_prefixed_alias(self):
        """Provider-prefixed ids resolve through the catalog alias table."""
        assert supported_efforts_for_model("gemini/gemini-3.5-flash") == (
            "none",
            "disable",
            "minimal",
            "low",
            "medium",
            "high",
        )

    def test_uncataloged_model_fails_open(self):
        """Arbitrary backend slugs are legal — no constraint applies."""
        assert supported_efforts_for_model("someorg/unlisted-model") is None

    def test_model_without_effort_list_is_unconstrained(self):
        assert supported_efforts_for_model("gpt-4o") is None


class TestClampEffortToSupported:
    """Tests for clamping derived efforts to a model's supported levels."""

    def test_none_effort_passes_through(self):
        assert clamp_effort_to_supported(None, ("low", "high")) is None

    def test_unconstrained_model_passes_through(self):
        assert clamp_effort_to_supported("xhigh", None) == "xhigh"

    def test_supported_effort_passes_through(self):
        assert clamp_effort_to_supported("medium", ("low", "medium", "high")) == "medium"

    @pytest.mark.parametrize(
        "effort, supported, expected",
        [
            # Highest supported level at or below the request.
            ("xhigh", ("none", "disable", "minimal", "low", "medium", "high"), "high"),
            ("xhigh", ("low", "high"), "high"),
            ("medium", ("low", "high"), "low"),
            ("minimal", ("medium", "high", "xhigh"), "medium"),
            ("xhigh", ("high",), "high"),
            # Below every supported level -> lowest supported (a provider
            # default could be the model's highest level).
            ("none", ("low", "high"), "low"),
            ("disable", ("minimal", "low", "medium", "high"), "minimal"),
        ],
    )
    def test_clamps_unsupported_levels(self, effort: str, supported: tuple[str, ...], expected: str):
        assert clamp_effort_to_supported(effort, supported) == expected


class TestResolveReasoningEffort:
    """Tests for the full request-effort resolution (explicit/derived/floor + normalization)."""

    @staticmethod
    def _request(reasoning_effort=None, thinking=None):
        return SimpleNamespace(reasoning_effort=reasoning_effort, thinking=thinking)

    def test_explicit_supported_passes_through(self):
        result = resolve_reasoning_effort(
            self._request(reasoning_effort="high"),
            tier_override=None,
            model_id="gemini/gemini-3.5-flash",
            request_id="req-1",
        )
        assert result == "high"

    def test_explicit_unsupported_rejected_with_supported_list(self):
        with pytest.raises(HTTPException) as exc_info:
            resolve_reasoning_effort(
                self._request(reasoning_effort="xhigh"),
                tier_override=None,
                model_id="gemini/gemini-3.5-flash",
                request_id="req-1",
            )
        assert exc_info.value.status_code == 400
        assert isinstance(exc_info.value.detail, dict)
        detail = cast("dict[str, str]", exc_info.value.detail)
        assert detail["type"] == "invalid_request_error"
        assert "xhigh" in detail["message"]
        assert "none, disable, minimal, low, medium, high" in detail["message"]

    def test_explicit_for_uncataloged_model_passes_through(self):
        result = resolve_reasoning_effort(
            self._request(reasoning_effort="xhigh"),
            tier_override=None,
            model_id="someorg/unlisted-model",
            request_id="req-1",
        )
        assert result == "xhigh"

    def test_derived_budget_clamps_to_model_ceiling(self):
        """A 30k thinking budget derives xhigh; gemini-3.5-flash tops at high."""
        result = resolve_reasoning_effort(
            self._request(thinking={"budget_tokens": 30_000}),
            tier_override=None,
            model_id="gemini/gemini-3.5-flash",
            request_id="req-1",
        )
        assert result == "high"

    def test_tier_floor_result_clamps_to_model_ceiling(self):
        """The tier-override floor is applied first, then the model clamp."""
        result = resolve_reasoning_effort(
            self._request(thinking={"budget_tokens": 3_000}),  # derives medium
            tier_override=TierOverride(reasoning_effort="xhigh"),
            model_id="gemini/gemini-3.5-flash",
            request_id="req-1",
        )
        assert result == "high"

    def test_derived_for_uncataloged_model_not_clamped(self):
        result = resolve_reasoning_effort(
            self._request(thinking={"budget_tokens": 30_000}),
            tier_override=None,
            model_id="someorg/unlisted-model",
            request_id="req-1",
        )
        assert result == "xhigh"

    def test_no_sources_returns_none(self):
        result = resolve_reasoning_effort(
            self._request(),
            tier_override=None,
            model_id="gemini/gemini-3.5-flash",
            request_id="req-1",
        )
        assert result is None

    def test_missing_stub_fields_returns_none(self):
        """Request stubs without the new fields resolve to None (getattr path)."""
        result = resolve_reasoning_effort(
            SimpleNamespace(),
            tier_override=None,
            model_id="gemini/gemini-3.5-flash",
            request_id="req-1",
        )
        assert result is None

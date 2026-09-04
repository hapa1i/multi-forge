"""Regression coverage for passthrough native-effort floor normalization."""

from __future__ import annotations

from copy import deepcopy

import pytest

from forge.proxy import intercept
from forge.proxy.reasoning import clamp_effort_to_supported

pytestmark = pytest.mark.regression


def _body(model: str) -> dict[str, object]:
    return {
        "model": model,
        "max_tokens": 64_000,
        "messages": [{"role": "user", "content": "hi"}],
    }


@pytest.mark.parametrize(
    ("model", "floor"),
    [
        ("claude-opus-4-8[1m]", "high"),
        ("anthropic/claude-fable-5.1[1m]", "max"),
    ],
)
def test_transport_suffix_preserves_native_effort_routing(model: str, floor: str) -> None:
    body = _body(model)

    result = intercept.apply_override(body, reasoning_floor_effort=floor)

    assert body["output_config"] == {"effort": floor}
    assert "thinking" not in body
    assert result.mutation_record is not None
    assert result.mutation_record["mutations"][0]["target"] == "output_config.effort"


def test_native_floor_normalizes_upward_without_changing_translated_clamp() -> None:
    supported = ("low", "medium", "high", "max")
    body = _body("claude-opus-4-6")

    result = intercept.apply_override(body, reasoning_floor_effort="xhigh")

    assert body["output_config"] == {"effort": "max"}
    assert result.mutation_record is not None
    assert result.mutation_record["mutations"][0]["effort_after"] == "max"
    assert clamp_effort_to_supported("xhigh", supported) == "high"


def test_unknown_model_max_floor_remains_safely_rejected() -> None:
    with pytest.raises(intercept.ReasoningOverrideError, match="cannot be represented safely"):
        intercept.apply_override(_body("future-claude"), reasoning_floor_effort="max")


@pytest.mark.parametrize("model", ["claude-opus-5[1m]", "anthropic/claude-fable-5.1[1m]"])
def test_one_m_adaptive_request_with_manual_thinking_is_rejected(model: str) -> None:
    """Transport suffix normalization must preserve the adaptive-only validation."""
    body = _body(model)
    body["thinking"] = {"type": "enabled", "budget_tokens": 16_000}
    before = deepcopy(body)

    with pytest.raises(intercept.ReasoningOverrideError, match="requires adaptive thinking"):
        intercept.apply_override(body, reasoning_floor_effort="low")

    assert body == before


@pytest.mark.parametrize("floor", ["none", "disable"])
def test_no_floor_spelling_does_not_pin_the_lowest_supported_effort(floor: str) -> None:
    """A 'no reasoning' floor must not normalize upward into the weakest supported level."""
    body = _body("claude-opus-4-6")
    body["temperature"] = 0.7

    result = intercept.apply_override(body, reasoning_floor_effort=floor)

    assert "output_config" not in body
    assert body["temperature"] == 0.7
    assert result.mutation_record is None


def test_unknown_native_effort_floor_is_rejected_before_dispatch_or_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _body("claude-fable-5-1")
    body["system"] = "original"
    before = deepcopy(body)
    invalid_floor = "private-unknown-floor"
    monkeypatch.setattr(
        intercept,
        "_native_effort_support",
        lambda _model: pytest.fail("invalid floor reached native/legacy dispatch"),
    )

    with pytest.raises(intercept.ReasoningOverrideError, match="reasoning effort floor must be one of") as exc_info:
        intercept.apply_override(
            body,
            system_prompt_augment="must-not-be-applied",
            reasoning_floor_effort=invalid_floor,
        )

    assert invalid_floor not in str(exc_info.value)
    assert body == before


def test_non_string_legacy_effort_floor_is_rejected_before_dispatch_or_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _body("future-claude")
    body["system"] = "original"
    before = deepcopy(body)
    invalid_floor = ["private-list-floor"]
    monkeypatch.setattr(
        intercept,
        "_native_effort_support",
        lambda _model: pytest.fail("invalid floor reached native/legacy dispatch"),
    )

    with pytest.raises(intercept.ReasoningOverrideError, match="reasoning effort floor must be one of") as exc_info:
        intercept.apply_override(
            body,
            system_prompt_augment="must-not-be-applied",
            reasoning_floor_effort=invalid_floor,
        )

    assert "private-list-floor" not in str(exc_info.value)
    assert body == before

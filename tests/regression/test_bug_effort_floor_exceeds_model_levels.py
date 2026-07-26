"""Regression: derived reasoning_effort must not exceed the model's catalog levels.

Bug: the /v1/messages translation derived reasoning_effort from Claude Code's
thinking budget (>=25k tokens -> xhigh) and applied tier_overrides as a floor
(max_effort), with no model-aware normalization. gemini-3.5-flash's catalog
list tops out at high, so a routine 30k thinking budget sent
reasoning_effort=xhigh upstream — an unsupported value.

Fixed in src/forge/proxy/reasoning.py by resolve_reasoning_effort (applied at
the server.py /v1/messages seam): derived values clamp to the model's
litellm_reasoning_efforts; explicit unsupported values are rejected.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from forge.config import TierOverride
from forge.core.models import get_model_spec
from forge.proxy.reasoning import derive_reasoning_effort, resolve_reasoning_effort

pytestmark = pytest.mark.regression


def _request(thinking: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(reasoning_effort=None, thinking=thinking)


def test_bug_large_budget_no_longer_leaks_xhigh_past_model_ceiling() -> None:
    """The exact failure: 30k budget derives xhigh, which the model does not support."""
    supported = get_model_spec("gemini/gemini-3.5-flash").litellm_reasoning_efforts
    assert supported is not None

    # The pre-fix ingredients: the derivation produces a level outside the list.
    assert derive_reasoning_effort({"budget_tokens": 30_000}) == "xhigh"
    assert "xhigh" not in supported

    # Post-fix: the resolved value is the model's highest supported level.
    result = resolve_reasoning_effort(
        _request({"budget_tokens": 30_000}),
        tier_override=None,
        model_id="gemini/gemini-3.5-flash",
        request_id="regression",
    )
    assert result == "high"


def test_bug_tier_override_floor_no_longer_leaks_xhigh() -> None:
    """The floor path had the same leak: tier xhigh over a modest budget."""
    result = resolve_reasoning_effort(
        _request({"budget_tokens": 3_000}),
        tier_override=TierOverride(reasoning_effort="xhigh"),
        model_id="gemini/gemini-3.5-flash",
        request_id="regression",
    )
    assert result == "high"

"""Effort resolution facts and launch-scoped observations stay separate from wire payloads."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from forge.config import TierOverride
from forge.core.effort_observation import AppliedEffort
from forge.proxy.effort_observation import EffortObservations
from forge.proxy.reasoning import resolve_reasoning_effort_record

LAUNCH_A = "run_aaaaaaaaaaaa"
LAUNCH_B = "run_bbbbbbbbbbbb"


@pytest.mark.parametrize(
    "thinking,opt_in,floor,derived,pre_clamp,resolved,source,applicable",
    [
        ("adaptive", False, "high", "medium", "high", "high", "floor", True),
        ("adaptive", True, "low", "medium", "max", "high", "client", True),
        ("between_tools", True, None, "none", "none", "low", "thinking", False),
        ("disabled", True, None, "none", "none", "low", "thinking", False),
        ("between_tools", True, "high", "none", "high", "high", "floor", False),
        ("disabled", True, "high", "none", "high", "high", "floor", False),
    ],
)
def test_resolution_preserves_opt_in_applicability_and_each_resolution_stage(
    thinking, opt_in, floor, derived, pre_clamp, resolved, source, applicable
):
    request = SimpleNamespace(output_config={"effort": "max"}, thinking={"type": thinking})
    kwargs: dict[str, Any] = dict(
        tier_override=TierOverride(reasoning_effort=floor),
        model_id="gemini-4-argon",
        request_id="effort-test",
        honor_client_effort=opt_in,
    )
    record = resolve_reasoning_effort_record(request, **kwargs)
    assert record.requested == "max"
    assert record.thinking == thinking
    assert record.opt_in is opt_in
    assert record.client_applicable is applicable
    assert record.derived == derived
    assert record.floor == floor
    assert record.pre_clamp == pre_clamp
    assert record.supported == ("low", "medium", "high")
    assert record.resolved == resolved
    assert record.source == source


def test_explicit_effort_retains_precedence_and_rejects_unsupported_values():
    request = SimpleNamespace(reasoning_effort="low", output_config={"effort": "max"}, thinking={"type": "adaptive"})
    kwargs: dict[str, Any] = dict(
        tier_override=TierOverride(reasoning_effort="high"), model_id="gemini-4-argon", request_id="explicit"
    )
    record = resolve_reasoning_effort_record(request, honor_client_effort=True, **kwargs)
    assert (record.resolved, record.source) == ("low", "explicit")
    request.reasoning_effort = "max"
    with pytest.raises(HTTPException) as error:
        resolve_reasoning_effort_record(request, **kwargs)
    assert error.value.status_code == 400


def _observer(cache: EffortObservations, launch: str | None, tier: str = "opus"):
    resolution = resolve_reasoning_effort_record(
        SimpleNamespace(output_config={"effort": "xhigh"}, thinking={"type": "adaptive"}),
        tier_override=TierOverride(reasoning_effort="high"),
        model_id="unlisted/model",
        request_id="cache",
    )
    return cache.observer(
        launch,
        tier=tier,
        tier_source="request",
        client_model="claude-opus-5-5",
        mapped_model="unlisted/model",
        resolution=resolution,
    )


def test_cache_is_scoped_bounded_and_latest_per_launch_tier():
    cache = EffortObservations(max_entries=2)
    observe_a = _observer(cache, LAUNCH_A)
    observe_b = _observer(cache, LAUNCH_B)
    assert observe_a is not None and observe_b is not None
    assert cache.snapshot(LAUNCH_A) == {}  # Resolution alone is not an outbound observation.
    observe_a(AppliedEffort("high", "reasoning.effort"))
    observe_b(AppliedEffort("low", "reasoning_effort"))
    assert cache.snapshot(LAUNCH_A)["opus"]["applied"] == "high"
    assert cache.snapshot(LAUNCH_B)["opus"]["applied"] == "low"
    observe_a(AppliedEffort(None, "dropped", "tools do not support effort"))
    observe_other_tier = _observer(cache, LAUNCH_A, "haiku")
    assert observe_other_tier is not None
    observe_other_tier(AppliedEffort("medium", "reasoning_effort"))
    assert cache.snapshot(LAUNCH_B) == {}  # The least-recently written entry was evicted.
    snapshot = cache.snapshot(LAUNCH_A)
    assert set(snapshot) == {"opus", "haiku"}
    assert snapshot["opus"]["wire"] == "dropped"
    assert snapshot["opus"]["supported"] is None
    snapshot["opus"]["applied"] = "invented"
    assert cache.snapshot(LAUNCH_A)["opus"]["applied"] is None
    assert EffortObservations().snapshot(LAUNCH_A) == {}  # Restart has no durable observations.


def test_client_default_is_distinct_from_unset_resolution():
    cache = EffortObservations()
    resolution = resolve_reasoning_effort_record(
        SimpleNamespace(), tier_override=None, model_id="unlisted/model", request_id="default"
    )
    observer = cache.observer(
        LAUNCH_A,
        tier="opus",
        tier_source="request",
        client_model="claude-opus-5-5",
        mapped_model="unlisted/model",
        resolution=resolution,
    )
    assert observer is not None
    observer(AppliedEffort("high", "reasoning_effort"))
    record = cache.snapshot(LAUNCH_A)["opus"]
    assert record["resolved"] is None
    assert record["applied"] == "high"
    assert "after resolution left it unset" in record["note"]


@pytest.mark.parametrize("launch", [None, "", "run_AAAAAAAAAAAA", "run_aaaaaaaaaaaa\n", "other", "a" * 200])
def test_invalid_launch_cannot_create_observations(launch):
    assert _observer(EffortObservations(), launch) is None

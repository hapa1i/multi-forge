"""Structural parent admission and recovery without runtime readiness checks."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any

import pytest

from forge.policy.semantic import identity
from forge.session.consumer_lanes import ensure_consumer_lane_binding
from forge.session.derived_overrides import validate_derived_session_overrides
from forge.session.exceptions import InvalidDerivedSessionOverridesError
from forge.session.models import (
    LaneRecord,
    LaunchIntent,
    MemoryIntent,
    NativeSupervisorSource,
    PolicyIntent,
    SessionState,
    SupervisorConfig,
    create_session_state,
)


@pytest.fixture
def parent() -> SessionState:
    state = create_session_state("parent", worktree_path="/project")
    state.intent.launch = LaunchIntent()
    state.intent.policy = PolicyIntent()
    state.intent.memory = MemoryIntent()
    return state


@pytest.mark.parametrize(
    ("overrides", "path"),
    [
        ({"verification": {"bypass": "bad"}}, "verification.bypass"),
        ({"memory": "bad"}, "memory"),
        ({"memory": {"tags": [False]}}, "memory.tags"),
        ({"memory": {"auto_update": {"min_turns": "bad"}}}, "memory.auto_update.min_turns"),
        ({"policy": {"supervisor": {"timeout_seconds": "bad"}}}, "policy.supervisor.timeout_seconds"),
        ({"memory": {"auto_update": {"effort": "bad"}}}, "memory.auto_update.effort"),
    ],
)
def test_malformed_values_name_the_exact_path_without_mutation(
    parent: SessionState, overrides: dict[str, Any], path: str
) -> None:
    parent.overrides = overrides
    before = deepcopy(parent)

    with pytest.raises(InvalidDerivedSessionOverridesError) as caught:
        validate_derived_session_overrides(parent)

    assert caught.value.key == path
    assert path in str(caught.value)
    assert parent == before


@pytest.mark.parametrize(
    ("overrides", "path", "reset_arg"),
    [
        ({"launch": {"runtime": "codex"}}, "launch.runtime", "launch.runtime"),
        ({"launch": {"runtime": None}}, "launch.runtime", "launch.runtime"),
        ({"launch": {"mode": "host", "model_route": None}}, "launch.model_route", "launch.model_route"),
        ({"launch": {"model_route": {"requested_model": "opus"}}}, "launch.model_route", "launch.model_route"),
        ({"authority": None}, "authority", "--all"),
        ({"authority": {"mode": "advisory"}}, "authority", "--all"),
        ({"consumer_lanes": None}, "consumer_lanes", "--all"),
        ({"consumer_lanes": {"memory_writer": None}}, "consumer_lanes", "--all"),
        (
            {"policy": {"supervisor": {"native_source": None}}},
            "policy.supervisor.native_source",
            "policy.supervisor.native_source",
        ),
    ],
)
def test_lifecycle_fields_are_detected_inside_supplied_objects(
    parent: SessionState, overrides: dict[str, Any], path: str, reset_arg: str
) -> None:
    parent.overrides = overrides
    before = deepcopy(parent)

    with pytest.raises(InvalidDerivedSessionOverridesError) as caught:
        validate_derived_session_overrides(parent)

    assert caught.value.key == path
    assert f"forge session reset --session parent {reset_arg}" in caught.value.recovery
    assert parent == before


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"memory": None},
        {"policy": None},
        {"launch": None},
        {"policy": {"supervisor": None}},
        {"launch": {"mode": "sidecar"}},
        {"memory": {"tags": ["one", "two"], "auto_update": None}},
        {"policy": {"bundle_config": {"coding_standards": {"custom": {"launch": {"runtime": "data"}}}}}},
        {"verification": {"type": "legacy-unknown-type", "on_incomplete": "legacy-mode"}},
    ],
)
def test_valid_overrides_keep_nullable_and_free_form_semantics(parent: SessionState, overrides: dict[str, Any]) -> None:
    parent.overrides = overrides
    before = deepcopy(parent)

    validate_derived_session_overrides(parent)

    assert parent == before


def test_valid_unrelated_override_does_not_admit_unavailable_reviewer(
    parent: SessionState, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent.intent.policy = PolicyIntent(
        enabled=False,
        supervisor=SupervisorConfig(plan_override_path="/missing-plan", supervisor_model="unavailable-model"),
    )
    parent.overrides = {"verification": {"bypass": True}}

    def unexpected(*args: Any, **kwargs: Any) -> None:
        pytest.fail("structural validation must not admit or resolve a reviewer")

    monkeypatch.setattr(identity, "snapshot_supervisor_options", unexpected)
    monkeypatch.setattr(identity, "validate_supervisor_transition", unexpected)
    monkeypatch.setattr(identity, "validate_reviewer", unexpected)
    monkeypatch.setattr(identity, "select_supervisor_lane", unexpected)

    validate_derived_session_overrides(parent)


def test_malformed_value_advertises_keyed_reset(parent: SessionState) -> None:
    parent.overrides = {"verification": {"bypass": "bad"}, "memory": {"auto_recall": True}}

    with pytest.raises(InvalidDerivedSessionOverridesError) as caught:
        validate_derived_session_overrides(parent)

    assert caught.value.recovery == "Run 'forge session reset --session parent verification.bypass' before retrying."


@pytest.mark.parametrize("supervisor_override", [{"auth_mode": "bad"}, {"timeout_seconds": "bad"}])
def test_constructor_failure_does_not_blame_unrelated_override(
    parent: SessionState, supervisor_override: dict[str, Any]
) -> None:
    parent.overrides = {
        "memory": {"auto_update": {"effort": "bad"}},
        "policy": {"supervisor": supervisor_override},
        "verification": {"bypass": True},
    }

    with pytest.raises(InvalidDerivedSessionOverridesError) as caught:
        validate_derived_session_overrides(parent)

    assert caught.value.key == "memory.auto_update.effort"
    assert "verification.bypass" not in str(caught.value)


def test_interacting_constructor_values_name_their_supplied_object(parent: SessionState) -> None:
    parent.overrides = {
        "policy": {"supervisor": {"review_trigger": "stop", "cascade": True}},
        "verification": {"bypass": True},
    }

    with pytest.raises(InvalidDerivedSessionOverridesError) as caught:
        validate_derived_session_overrides(parent)

    assert caught.value.key == "policy.supervisor"
    assert "verification.bypass" not in str(caught.value)


def test_malformed_supervisor_requires_remove_when_baseline_exists(parent: SessionState) -> None:
    parent.intent.policy = PolicyIntent(
        supervisor=SupervisorConfig(plan_override_path="/plan", supervisor_model="opus")
    )
    parent.overrides = {"policy": {"supervisor": {"timeout_seconds": "bad"}}}

    with pytest.raises(InvalidDerivedSessionOverridesError) as caught:
        validate_derived_session_overrides(parent)

    assert "forge policy supervisor remove --session parent" in caught.value.recovery
    assert "reconfigure" in caught.value.recovery
    assert "forge session reset" not in caught.value.recovery


def test_malformed_supervisor_without_baseline_requires_manifest_repair(parent: SessionState) -> None:
    parent.overrides = {"policy": {"supervisor": {"timeout_seconds": "bad"}}}

    with pytest.raises(InvalidDerivedSessionOverridesError) as caught:
        validate_derived_session_overrides(parent)

    assert "Repair or restore" in caught.value.recovery
    assert "manifest" in caught.value.recovery
    assert "forge session reset" not in caught.value.recovery
    assert "forge policy supervisor remove" not in caught.value.recovery


@pytest.mark.parametrize("raw_supervisor", ["bad", [1], 1, True])
@pytest.mark.parametrize("has_baseline", [False, True])
def test_malformed_supervisor_container_keeps_recovery_actionable(
    parent: SessionState, raw_supervisor: Any, has_baseline: bool
) -> None:
    if has_baseline:
        parent.intent.policy = PolicyIntent(supervisor=SupervisorConfig(plan_override_path="/plan"))
    parent.overrides = {"policy": {"supervisor": raw_supervisor}}
    before = deepcopy(parent)

    with pytest.raises(InvalidDerivedSessionOverridesError) as caught:
        validate_derived_session_overrides(parent)

    assert caught.value.key == "policy.supervisor"
    assert "forge session reset" not in caught.value.recovery
    if has_baseline:
        assert "forge policy supervisor remove --session parent" in caught.value.recovery
    else:
        assert "Repair or restore" in caught.value.recovery
        assert "forge policy supervisor remove" not in caught.value.recovery
    assert parent == before


def test_native_identity_change_does_not_offer_direct_reset(parent: SessionState) -> None:
    parent.intent.policy = PolicyIntent(
        supervisor=SupervisorConfig(plan_override_path="/plan", supervisor_model="opus")
    )
    source = NativeSupervisorSource(
        "codex", "01a12b5c-ce1a-72c2-ad3f-05d75f3fba00", "/codex", "/codex/log", "/repo", "a" * 64
    )
    parent.overrides = {"policy": {"supervisor": {"native_source": asdict(source)}}}

    with pytest.raises(InvalidDerivedSessionOverridesError) as caught:
        validate_derived_session_overrides(parent)

    assert caught.value.key == "policy.supervisor.native_source"
    assert "forge policy supervisor remove --session parent" in caught.value.recovery
    assert "forge session reset" not in caught.value.recovery


def test_frozen_identity_blocks_reset_all_until_supervisor_removed(parent: SessionState) -> None:
    parent.intent.policy = PolicyIntent(
        supervisor=SupervisorConfig(plan_override_path="/plan", supervisor_model="opus", supervisor_effort="low")
    )
    parent.overrides = {"authority": None, "policy": {"supervisor": {"supervisor_effort": "high"}}}
    ensure_consumer_lane_binding(
        parent, identity.SUPERVISOR_CONSUMER, LaneRecord("claude_code", "anthropic-direct", "opus")
    )
    before = deepcopy(parent)

    with pytest.raises(InvalidDerivedSessionOverridesError) as caught:
        validate_derived_session_overrides(parent)

    assert (
        "Run 'forge policy supervisor remove --session parent', then 'forge session reset --session parent --all'"
        in (caught.value.recovery)
    )
    assert "This clears all live overrides, including unrelated settings." in caught.value.recovery
    assert parent == before


def test_unrelated_invalid_override_cannot_reset_past_malformed_supervisor(parent: SessionState) -> None:
    parent.intent.policy = PolicyIntent(
        supervisor=SupervisorConfig(plan_override_path="/plan", supervisor_model="opus")
    )
    parent.overrides = {"verification": {"bypass": "bad"}, "policy": {"supervisor": {"timeout_seconds": "bad"}}}

    with pytest.raises(InvalidDerivedSessionOverridesError) as caught:
        validate_derived_session_overrides(parent)

    assert (
        "Run 'forge policy supervisor remove --session parent', then 'forge session reset --session parent --all'"
        in (caught.value.recovery)
    )

"""Unit tests for the supervisor lane-degrade overlay (epic consumer_lanes T7)."""

from __future__ import annotations

from forge.core.state import now_iso
from forge.policy.store import build_policy_state_update
from forge.policy.supervisor_lane_degrade import (
    SUPERVISOR_LANE_DEGRADE_KEY,
    clear_supervisor_degrade,
    is_supervisor_degraded,
    read_supervisor_degrade,
    set_supervisor_degrade,
)
from forge.policy.types import CompositeDecision
from forge.session.models import LaneRecord, SessionState

_CODEX = LaneRecord("codex", "chatgpt", "gpt-5-codex")
_CLAUDE = LaneRecord("claude_code", "anthropic-direct", "opus")


def _fresh() -> SessionState:
    return SessionState(schema_version=1, name="t", created_at=now_iso(), last_accessed_at=now_iso())


class TestSupervisorLaneDegrade:
    def test_fresh_state_is_not_degraded(self) -> None:
        state = _fresh()
        assert is_supervisor_degraded(state) is False
        assert read_supervisor_degrade(state) is None

    def test_set_then_read_roundtrips_full_marker(self) -> None:
        state = _fresh()
        set_supervisor_degrade(
            state, from_lane=_CODEX, to_lane=_CLAUDE, reason="subscription_exhausted", at="2026-06-30T00:00:00Z"
        )
        assert is_supervisor_degraded(state) is True
        marker = read_supervisor_degrade(state)
        assert marker is not None
        assert marker["degraded"] is True
        assert marker["from_lane"] == {"runtime_id": "codex", "backend_id": "chatgpt", "model": "gpt-5-codex"}
        assert marker["to_lane"] == {"runtime_id": "claude_code", "backend_id": "anthropic-direct", "model": "opus"}
        assert marker["reason"] == "subscription_exhausted"
        assert marker["at"] == "2026-06-30T00:00:00Z"

    def test_set_creates_policyconfirmed_when_absent(self) -> None:
        state = _fresh()
        assert state.confirmed.policy is None
        set_supervisor_degrade(state, from_lane=_CODEX, to_lane=None, reason="x", at="t")
        assert state.confirmed.policy is not None
        marker = read_supervisor_degrade(state)
        assert marker is not None and marker["to_lane"] is None  # unresolved default stored as None

    def test_clear_removes_marker(self) -> None:
        state = _fresh()
        set_supervisor_degrade(state, from_lane=_CODEX, to_lane=_CLAUDE, reason="x", at="t")
        clear_supervisor_degrade(state)
        assert is_supervisor_degraded(state) is False
        assert read_supervisor_degrade(state) is None

    def test_clear_is_idempotent_and_safe_on_fresh(self) -> None:
        clear_supervisor_degrade(_fresh())  # no PolicyConfirmed -> must not raise
        state = _fresh()
        set_supervisor_degrade(state, from_lane=_CODEX, to_lane=None, reason="x", at="t")
        clear_supervisor_degrade(state)
        clear_supervisor_degrade(state)  # second clear is a no-op
        assert is_supervisor_degraded(state) is False

    def test_overlay_key_is_not_a_policy_id(self) -> None:
        # The `forge.` prefix keeps it out of the policy-id namespace the engine writes.
        assert SUPERVISOR_LANE_DEGRADE_KEY == "forge.supervisor_lane_degrade"
        assert SUPERVISOR_LANE_DEGRADE_KEY.startswith("forge.")

    def test_marker_survives_policy_state_merge(self) -> None:
        # The load-bearing invariant (D3): normal policy persistence must NOT clobber the
        # overlay. build_policy_state_update merges existing policy_states with engine_state
        # (keyed by policy_id); the overlay key is never in engine_state, so it survives.
        state = _fresh()
        set_supervisor_degrade(state, from_lane=_CODEX, to_lane=_CLAUDE, reason="x", at="t")
        assert state.confirmed.policy is not None
        existing = {"policy_states": state.confirmed.policy.policy_states, "decisions": []}

        updated = build_policy_state_update(
            result=CompositeDecision(final_decision="allow"),
            engine_state={"semantic.supervisor": {"throttle": "hash"}},
            existing_state=existing,
        )

        assert SUPERVISOR_LANE_DEGRADE_KEY in updated["policy_states"]
        assert updated["policy_states"]["semantic.supervisor"] == {"throttle": "hash"}
        assert updated["policy_states"][SUPERVISOR_LANE_DEGRADE_KEY]["degraded"] is True

"""Supervisor lane-degrade overlay (epic consumer_lanes T7).

When the supervisor's bound codex subscription lane exhausts mid-session, a sticky marker
in ``confirmed.policy.policy_states`` records the degrade so subsequent checks route to the
default claude lane instead of re-attempting the spent codex lane. The write-once
``confirmed.consumer_lanes`` binding is never rewritten -- this is a separate overlay the
hook consults at lane-injection time, leaving the codex binding frozen and observable.

The marker lives under a dedicated **non-policy-id** key so the engine's
``build_policy_state_update`` merge (keyed by policy_id) never clobbers it. ``from_lane`` /
``to_lane`` are stored as full lane dicts for audit/display only; routing trusts the
``degraded`` flag and injects ``lane_record=None`` -- never the stored ``to_lane``.

These are pure ``SessionState`` mutators (the hook/CLI callers own the store lock), kept in
the policy domain rather than the lane primitives (``session/consumer_lanes.py``) so the
lane layer stays free of policy-overlay knowledge.
"""

from __future__ import annotations

from typing import Any

from forge.session.models import LaneRecord, PolicyConfirmed, SessionState

# Dedicated overlay key. The ``forge.`` prefix marks it as an overlay, not a policy id, so it
# never collides with an engine policy_id (e.g. ``semantic.supervisor``) and the policy_states
# merge in ``policy/store.py`` -- which only ``.update()``s engine state keyed by policy_id --
# cannot overwrite it.
SUPERVISOR_LANE_DEGRADE_KEY = "forge.supervisor_lane_degrade"


def is_supervisor_degraded(state: SessionState) -> bool:
    """Return True iff the supervisor lane is degraded for this session."""
    marker = read_supervisor_degrade(state)
    return bool(marker and marker.get("degraded"))


def read_supervisor_degrade(state: SessionState) -> dict[str, Any] | None:
    """Return the degrade marker dict, or None when absent."""
    policy = state.confirmed.policy
    if policy is None:
        return None
    marker = policy.policy_states.get(SUPERVISOR_LANE_DEGRADE_KEY)
    return marker if isinstance(marker, dict) else None


def set_supervisor_degrade(
    state: SessionState,
    *,
    from_lane: LaneRecord,
    to_lane: LaneRecord | None,
    reason: str,
    at: str,
) -> None:
    """Write the sticky degrade marker. Caller holds the store lock.

    ``from_lane`` is the spent codex lane; ``to_lane`` is the default lane routed to (None
    when the default is unresolvable -- stored for audit only, never for dispatch).
    """
    policy = state.confirmed.policy or PolicyConfirmed()
    policy.policy_states[SUPERVISOR_LANE_DEGRADE_KEY] = {
        "degraded": True,
        "from_lane": _lane_dict(from_lane),
        "to_lane": _lane_dict(to_lane),
        "reason": reason,
        "at": at,
    }
    state.confirmed.policy = policy


def clear_supervisor_degrade(state: SessionState) -> None:
    """Drop the degrade marker. Caller holds the store lock. Idempotent."""
    policy = state.confirmed.policy
    if policy is not None:
        policy.policy_states.pop(SUPERVISOR_LANE_DEGRADE_KEY, None)


def _lane_dict(lane: LaneRecord | None) -> dict[str, str] | None:
    if lane is None:
        return None
    return {"runtime_id": lane.runtime_id, "backend_id": lane.backend_id, "model": lane.model}

"""Regression: a stale supervisor hook must not resurrect a lane after `supervisor remove`.

Bug (consumer_lanes T1b second review, HIGH): the post-eval freeze in
``forge.cli.hooks.policy._persist_policy_state`` gated on the pre-call ``effective`` config and froze
the pre-call ``supervisor_lane``, never consulting the fresh manifest read under the lock. The
supervisor check runs lock-free for seconds, so a concurrent ``forge policy supervisor remove`` (which
clears ``intent.policy.supervisor`` and both consumer-lane slots) could be overwritten: the stale hook
returned and wrote ``confirmed.consumer_lanes.supervisor = codex`` back, leaving ``intent.policy = None``
but a live codex binding. A later ``set planner`` (no ``--runtime``) then resurrected codex via
confirmed-first dispatch.

Root cause: post-eval freeze used pre-call state, not the fresh under-lock manifest.
Affected: ``src/forge/cli/hooks/policy.py`` (the ``_mutate`` freeze guard). The fix freezes only when
``read_bound_lane(m)`` still equals the dispatched lane, so a removed/re-pointed lane is dropped.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from forge.cli.hooks.policy import _persist_policy_state
from forge.core.state import now_iso
from forge.session.models import (
    ConsumerLaneBinding,
    ConsumerLaneConfirmed,
    ConsumerLaneIntent,
    LaneRecord,
    SessionState,
)

pytestmark = pytest.mark.regression

_CODEX = LaneRecord("codex", "chatgpt", "gpt-5-codex")
_BUILD_RETURN = {
    "forge_version": "0.1.0",
    "bundles": [],
    "rules_active": [],
    "decisions": [],
    "policy_states": {},
}


def _effective_supervisor() -> MagicMock:
    """A pre-call effective config with a configured supervisor -- the stale in-flight snapshot."""
    eff = MagicMock()
    eff.policy.bundles = []
    eff.policy.supervisor.resume_id = "planner"
    eff.policy.supervisor.suspended = False
    return eff


def _run_freeze_mutate(state: SessionState, supervisor_lane: LaneRecord | None) -> None:
    """Drive the locked post-eval freeze the way the hook does, against a (fresh) manifest."""
    engine = MagicMock()
    engine.get_collected_state.return_value = {}
    store = MagicMock()
    with patch("forge.policy.store.build_policy_state_update", return_value=_BUILD_RETURN):
        _persist_policy_state(
            store=store,
            engine=engine,
            result=MagicMock(),
            effective=_effective_supervisor(),
            context_summary="ctx",
            supervisor_lane=supervisor_lane,
        )
        store.update.call_args[1]["mutate"](state)


def _bare_state() -> SessionState:
    return SessionState(schema_version=1, name="t", created_at=now_iso(), last_accessed_at=now_iso())


def test_stale_freeze_does_not_resurrect_lane_after_remove() -> None:
    # Fresh manifest = post-remove: no supervisor, no intent lane, no confirmed binding. The stale
    # hook returns and tries to freeze the codex lane it dispatched on -- it must be dropped.
    state = _bare_state()
    _run_freeze_mutate(state, supervisor_lane=_CODEX)
    assert state.confirmed.consumer_lanes is None


def test_stale_freeze_does_not_overwrite_repointed_lane() -> None:
    # Fresh manifest was re-pointed to the default (intent lane cleared) while codex dispatched.
    # The stale codex write must not land; read_bound_lane(default) != codex.
    state = _bare_state()
    state.intent.consumer_lanes = ConsumerLaneIntent(supervisor=None)  # re-pointed to default
    _run_freeze_mutate(state, supervisor_lane=_CODEX)
    assert state.confirmed.consumer_lanes is None or state.confirmed.consumer_lanes.supervisor is None


def test_uncontested_freeze_still_writes() -> None:
    # Control: when nothing changed (fresh manifest still dispatches codex), the freeze lands -- the
    # guard drops only *stale* writes, not legitimate ones.
    state = _bare_state()
    state.intent.consumer_lanes = ConsumerLaneIntent(supervisor=_CODEX)
    _run_freeze_mutate(state, supervisor_lane=_CODEX)
    assert state.confirmed.consumer_lanes is not None
    binding = state.confirmed.consumer_lanes.supervisor
    assert isinstance(binding, ConsumerLaneBinding)
    assert binding.lane == _CODEX
    # And the confirmed section is a real ConsumerLaneConfirmed, not a stray attribute.
    assert isinstance(state.confirmed.consumer_lanes, ConsumerLaneConfirmed)

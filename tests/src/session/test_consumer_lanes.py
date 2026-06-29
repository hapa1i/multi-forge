"""Unit tests for the manifest<->lane binding bridge (epic consumer_lanes, T1b)."""

from __future__ import annotations

import pytest

from forge.core.lanes import Consumer, Lane, LaneError
from forge.core.state import now_iso
from forge.policy.semantic.supervisor import SUPERVISOR_CONSUMER
from forge.session.consumer_lanes import (
    clear_consumer_lane,
    confirmed_lane,
    ensure_consumer_lane_binding,
    lane_record_for_runtime,
    read_bound_lane,
    set_intent_lane,
)
from forge.session.models import (
    ConsumerLaneBinding,
    ConsumerLaneConfirmed,
    ConsumerLaneIntent,
    LaneRecord,
    SessionState,
)

# The codex lane is the one declared override on SUPERVISOR_CONSUMER (T4); a gemini lane
# constructs as a Lane but is NOT a declared candidate, so resolve_lane rejects it.
_CODEX_RECORD = LaneRecord("codex", "chatgpt", "gpt-5-codex")
_DEFAULT = SUPERVISOR_CONSUMER.default_lane
_DEFAULT_RECORD = LaneRecord(_DEFAULT.runtime_id, _DEFAULT.backend_id, _DEFAULT.model)


def _state(*, intent: LaneRecord | None = None, confirmed: ConsumerLaneBinding | None = None) -> SessionState:
    state = SessionState(schema_version=1, name="t", created_at=now_iso(), last_accessed_at=now_iso())
    if intent is not None:
        state.intent.consumer_lanes = ConsumerLaneIntent(supervisor=intent)
    if confirmed is not None:
        state.confirmed.consumer_lanes = ConsumerLaneConfirmed(supervisor=confirmed)
    return state


# --- read_bound_lane ---


class TestReadBoundLane:
    def test_none_when_no_sections(self) -> None:
        assert read_bound_lane(_state(), SUPERVISOR_CONSUMER) is None

    def test_returns_intent_override_before_freeze(self) -> None:
        assert read_bound_lane(_state(intent=_CODEX_RECORD), SUPERVISOR_CONSUMER) == _CODEX_RECORD

    def test_returns_confirmed_binding_lane(self) -> None:
        binding = ConsumerLaneBinding(lane=_CODEX_RECORD, source="intent", resolved_at=now_iso())
        assert read_bound_lane(_state(confirmed=binding), SUPERVISOR_CONSUMER) == _CODEX_RECORD

    def test_confirmed_wins_over_intent(self) -> None:
        # The frozen binding governs dispatch directly: a (drifted/edited) intent must not
        # override a recorded binding. confirmed-first is the "resolved once and frozen" contract.
        frozen = ConsumerLaneBinding(lane=_DEFAULT_RECORD, source="intent", resolved_at=now_iso())
        state = _state(intent=_CODEX_RECORD, confirmed=frozen)
        assert read_bound_lane(state, SUPERVISOR_CONSUMER) == _DEFAULT_RECORD


# --- ensure_consumer_lane_binding ---


class TestEnsureConsumerLaneBinding:
    def test_none_lane_does_not_freeze(self) -> None:
        # The default lane never freezes (MEDIUM contract): lane_record is None means the
        # consumer ran on its default with no explicit choice, so confirmed stays empty and
        # the lane remains re-pinnable via `set --runtime` (no spurious already-bound reject).
        state = _state()
        ensure_consumer_lane_binding(state, SUPERVISOR_CONSUMER, None)
        assert state.confirmed.consumer_lanes is None

    def test_freezes_injected_override(self) -> None:
        state = _state()
        ensure_consumer_lane_binding(state, SUPERVISOR_CONSUMER, _CODEX_RECORD)
        binding = state.confirmed.consumer_lanes.supervisor  # type: ignore[union-attr]
        assert binding is not None
        assert binding.source == "intent"
        assert binding.lane == _CODEX_RECORD

    def test_freezes_dispatched_lane_not_current_intent(self) -> None:
        # P2(a): the freeze records the lane the hook injected at dispatch, NOT a fresh read of the
        # (under-lock) manifest -- so a concurrent intent change during the supervisor call cannot
        # skew the binding away from the lane that actually ran.
        state = _state(intent=_DEFAULT_RECORD)  # manifest intent now says "default"...
        ensure_consumer_lane_binding(state, SUPERVISOR_CONSUMER, _CODEX_RECORD)  # ...but codex dispatched
        binding = state.confirmed.consumer_lanes.supervisor  # type: ignore[union-attr]
        assert binding is not None
        assert binding.lane == _CODEX_RECORD  # froze what dispatched, not the manifest default

    def test_write_if_absent_is_idempotent(self) -> None:
        # A pre-existing binding is the immovable ground truth: a second call never rewrites it.
        frozen = ConsumerLaneBinding(lane=_CODEX_RECORD, source="intent", resolved_at="2020-01-01T00:00:00Z")
        state = _state(confirmed=frozen)
        ensure_consumer_lane_binding(state, SUPERVISOR_CONSUMER, _DEFAULT_RECORD)
        assert state.confirmed.consumer_lanes.supervisor is frozen  # type: ignore[union-attr]

    def test_drift_unknown_runtime_skips_freeze(self) -> None:
        # A dispatched record that no longer builds a Lane (renamed/removed runtime) is NOT frozen
        # as a known-unusable binding; dispatch fails open as a no-call and retries later.
        state = _state()
        ensure_consumer_lane_binding(
            state, SUPERVISOR_CONSUMER, LaneRecord("ghost_runtime", "anthropic-direct", "opus")
        )
        assert state.confirmed.consumer_lanes is None

    def test_not_a_declared_candidate_skips_freeze(self) -> None:
        # A valid Lane that is not one of SUPERVISOR_CONSUMER's declared candidates is rejected by
        # resolve_lane (overrides are an allow-list), so it must not freeze either.
        state = _state()
        ensure_consumer_lane_binding(state, SUPERVISOR_CONSUMER, LaneRecord("gemini", "openrouter", "m"))
        assert state.confirmed.consumer_lanes is None


# --- lane_record_for_runtime (the resolving-command expansion) ---


class TestLaneRecordForRuntime:
    def test_expands_default_runtime_to_full_lane(self) -> None:
        # A runtime id alone is not a lane: expansion recovers the declared (runtime, backend, model).
        assert lane_record_for_runtime(SUPERVISOR_CONSUMER, "claude_code") == _DEFAULT_RECORD

    def test_expands_allowed_runtime_to_full_lane(self) -> None:
        assert lane_record_for_runtime(SUPERVISOR_CONSUMER, "codex") == _CODEX_RECORD

    def test_unknown_runtime_raises(self) -> None:
        # A runtime with no declared candidate lane is a setter bug, not a silent default.
        with pytest.raises(LaneError, match="no valid lane on runtime 'bogus'"):
            lane_record_for_runtime(SUPERVISOR_CONSUMER, "bogus")


# --- set_intent_lane (the resolving-command intent write) ---


class TestSetIntentLane:
    def test_writes_intent_slot_creating_section(self) -> None:
        state = _state()
        set_intent_lane(state, SUPERVISOR_CONSUMER, _CODEX_RECORD)
        assert state.intent.consumer_lanes is not None
        assert state.intent.consumer_lanes.supervisor == _CODEX_RECORD

    def test_overwrites_prior_intent_request(self) -> None:
        # Before the freeze, re-setting the intent lane is allowed (the post-bind reject lives in
        # the CLI, which reads confirmed). set_intent_lane itself is an unconditional write.
        state = _state(intent=_DEFAULT_RECORD)
        set_intent_lane(state, SUPERVISOR_CONSUMER, _CODEX_RECORD)
        assert state.intent.consumer_lanes.supervisor == _CODEX_RECORD  # type: ignore[union-attr]


# --- confirmed_lane (the already-bound reject's reader) ---


class TestConfirmedLane:
    def test_none_when_unbound(self) -> None:
        assert confirmed_lane(_state(intent=_CODEX_RECORD), SUPERVISOR_CONSUMER) is None

    def test_returns_frozen_lane(self) -> None:
        frozen = ConsumerLaneBinding(lane=_CODEX_RECORD, source="intent", resolved_at=now_iso())
        assert confirmed_lane(_state(confirmed=frozen), SUPERVISOR_CONSUMER) == _CODEX_RECORD


# --- clear_consumer_lane (binding teardown on supervisor remove) ---


class TestClearConsumerLane:
    def test_clears_both_intent_and_confirmed(self) -> None:
        # remove orphan-clears the binding: a stale lane in either slot would otherwise be
        # resurrected by read_bound_lane (confirmed-first, else intent) on a re-add.
        frozen = ConsumerLaneBinding(lane=_CODEX_RECORD, source="intent", resolved_at=now_iso())
        state = _state(intent=_CODEX_RECORD, confirmed=frozen)
        clear_consumer_lane(state, SUPERVISOR_CONSUMER)
        assert state.intent.consumer_lanes.supervisor is None  # type: ignore[union-attr]
        assert state.confirmed.consumer_lanes.supervisor is None  # type: ignore[union-attr]
        assert read_bound_lane(state, SUPERVISOR_CONSUMER) is None

    def test_noop_when_unset(self) -> None:
        state = _state()
        clear_consumer_lane(state, SUPERVISOR_CONSUMER)  # no sections -> no error
        assert read_bound_lane(state, SUPERVISOR_CONSUMER) is None


# --- generality / drift guards ---


def test_intent_and_confirmed_slots_match() -> None:
    """Each consumer needs an intent slot and a confirmed slot of the same name (T6 seam guard)."""
    from dataclasses import fields

    intent_slots = {f.name for f in fields(ConsumerLaneIntent)}
    confirmed_slots = {f.name for f in fields(ConsumerLaneConfirmed)}
    assert intent_slots == confirmed_slots


def test_unwired_consumer_rejected() -> None:
    """A consumer with no manifest slot is a wiring bug -- reject, never silently no-op."""
    phantom = Consumer("ghost", "tool_agent", Lane("claude_code", "anthropic-direct", "m"))
    with pytest.raises(ValueError, match="no consumer_lanes manifest slot"):
        ensure_consumer_lane_binding(_state(), phantom, None)

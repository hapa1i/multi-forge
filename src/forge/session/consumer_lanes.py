"""Manifest <-> lane binding bridge (epic consumer_lanes, ticket T1b).

The seam between the catalog-free manifest DTOs (``session.models.LaneRecord`` and
the ``consumer_lanes`` sections) and the validating pure resolver
(``core.lanes``). It deliberately lives in neither: ``session.models`` stays
catalog-free (it must not import ``core.lanes``, card D1), and ``core.lanes``
stays pure/IO-free (no session-model mutation, its purity test forbids it).

Two operations, both keyed by ``consumer.id`` so T6 extends them by adding a
named field per consumer to ``ConsumerLane{Intent,Confirmed}`` -- no edit here:

- ``read_bound_lane`` -- the lane to dispatch on (frozen binding first, then the
  pre-freeze intent override, then the consumer default).
- ``ensure_consumer_lane_binding`` -- freeze that lane into ``confirmed``
  write-if-absent, the single immutability seam (card D2).
"""

from __future__ import annotations

import logging
from dataclasses import fields

from forge.core.lanes import Consumer, Lane, LaneError, resolve_lane, valid_lanes
from forge.core.state import now_iso
from forge.session.models import (
    ConsumerLaneBinding,
    ConsumerLaneConfirmed,
    ConsumerLaneIntent,
    LaneRecord,
    SessionState,
)

_log = logging.getLogger(__name__)

# One named field per consumer on each section; the two must stay in lockstep so a
# consumer's intent slot has a matching confirmed slot. Guarded by
# test_consumer_lanes.test_intent_and_confirmed_slots_match.
_CONSUMER_LANE_SLOTS = frozenset(f.name for f in fields(ConsumerLaneConfirmed))


def read_bound_lane(state: SessionState, consumer: Consumer) -> LaneRecord | None:
    """Return the lane record to dispatch ``consumer`` on, or None for its default.

    Confirmed-first: once a binding is frozen it governs dispatch directly (the
    "resolved once and frozen" contract), so a written binding is followed even if
    ``intent`` later drifts. Before the freeze, the ``intent`` override is the
    source. None means no placement is recorded -- the caller resolves the
    consumer's default lane (the byte-identical pre-T1b path).
    """
    binding = _confirmed_binding(state, consumer)
    if binding is not None:
        return binding.lane
    return _intent_record(state, consumer)


def read_bound_backend_id(state: SessionState, consumer: Consumer) -> str | None:
    """Return the backend id to bill ``consumer``'s run under, or None.

    The billing companion to ``read_bound_lane``. Returns a concrete backend id only for a
    *valid explicit* binding. Returns None when there is no binding -- the consumer ran on its
    default lane, so billing resolves from key/direct alone -- OR when an explicit binding has
    drifted out of the catalog: an honest "don't know" (``unknown`` billing) rather than a silent
    substitution of the default (absence vs. corruption). The drift fail-open mirrors the
    supervisor's posture around invalid lanes (``resolve_lane`` in ``run_supervisor_check``).

    Not a blanket no-raise contract: an *unwired* consumer (no ``consumer_lanes`` manifest slot)
    raises ``ValueError`` from the underlying slot lookup, before the drift guard -- a programmer
    error / internal-boundary rejection (coding_standards §6), not a don't-know. Production call
    sites pass wired consumer constants, so that path is unreachable there.
    """
    record = read_bound_lane(state, consumer)
    if record is None:
        return None
    try:
        return resolve_lane(consumer, override=_record_to_lane(record)).backend_id
    except LaneError:
        return None


def confirmed_lane(state: SessionState, consumer: Consumer) -> LaneRecord | None:
    """Return ``consumer``'s frozen lane record, or None if not yet bound.

    The resolving commands' already-bound reject reads this: a non-None result
    means the lane is frozen, so ``policy supervisor set --runtime`` must refuse to
    change it (the binding is immutable once written, card D2).
    """
    binding = _confirmed_binding(state, consumer)
    return None if binding is None else binding.lane


def intent_lane(state: SessionState, consumer: Consumer) -> LaneRecord | None:
    """Return ``consumer``'s requested (pre-freeze) ``intent`` lane, or None.

    The read companion to ``set_intent_lane`` and the intent-side counterpart of
    ``confirmed_lane``: ``forge session lane show`` reads both to surface drift -- a
    requested lane that differs from the frozen binding (or an intent override that
    has not yet frozen).
    """
    return _intent_record(state, consumer)


def lane_record_for_runtime(consumer: Consumer, runtime_id: str) -> LaneRecord:
    """Expand a runtime id to ``consumer``'s full declared lane on that runtime.

    A runtime alone is not a lane: this recovers the ``(runtime, backend, model)``
    the consumer declares as a valid candidate for ``runtime_id`` (its default or an
    allowed lane). The CLI lane setters call it so they persist a full ``LaneRecord``
    without re-encoding backend/model -- ``SUPERVISOR_CONSUMER`` stays the one place
    that pairs a runtime with its backend/model. Raises ``LaneError`` if the consumer
    has no valid candidate lane on that runtime.
    """
    for lane in valid_lanes(consumer):
        if lane.runtime_id == runtime_id:
            return LaneRecord(lane.runtime_id, lane.backend_id, lane.model)
    raise LaneError(f"Consumer {consumer.id!r} has no valid lane on runtime {runtime_id!r}")


def lane_record_for(consumer: Consumer, *, runtime: str | None = None, backend: str | None = None) -> LaneRecord:
    """Expand a runtime and/or backend constraint to the consumer's unique matching lane.

    Generalizes ``lane_record_for_runtime`` beyond the runtime axis: ``claude-max`` and the
    default ``anthropic-direct`` share the ``claude_code`` runtime, so a *backend* constraint is
    the only way to select the subscription lane. Matches against ``valid_lanes`` (the gated
    default + allowed set). Unlike the runtime-only helper (first match), this requires a *unique*
    match -- a backend id appears in at most one of a consumer's lanes, so a backend constraint is
    unambiguous. Raises ``LaneError`` if no candidate matches, the match is ambiguous, or neither
    constraint is given.
    """
    if runtime is None and backend is None:
        raise LaneError("lane_record_for requires a runtime or backend constraint")
    matches = [
        lane
        for lane in valid_lanes(consumer)
        if (runtime is None or lane.runtime_id == runtime) and (backend is None or lane.backend_id == backend)
    ]
    if not matches:
        raise LaneError(f"Consumer {consumer.id!r} has no valid lane for runtime={runtime!r} backend={backend!r}")
    if len(matches) > 1:
        raise LaneError(
            f"Consumer {consumer.id!r} matches multiple lanes for runtime={runtime!r} backend={backend!r}; "
            "specify both runtime and backend to disambiguate"
        )
    lane = matches[0]
    return LaneRecord(lane.runtime_id, lane.backend_id, lane.model)


def set_intent_lane(state: SessionState, consumer: Consumer, lane_record: LaneRecord) -> None:
    """Record ``consumer``'s requested lane in ``intent`` (the resolving-command setter).

    The write companion to ``read_bound_lane``'s intent branch: resolving commands
    (start/fork ``--supervisor-runtime``, ``policy supervisor set --runtime``) call this
    to record the requested placement. The freeze (``ensure_consumer_lane_binding``) later
    copies the lane that actually dispatched into ``confirmed``. Callers enforce the
    already-bound reject (``confirmed_lane``) before invoking this -- it does not itself
    guard against overwriting a request on an already-frozen session.
    """
    if state.intent.consumer_lanes is None:
        state.intent.consumer_lanes = ConsumerLaneIntent()
    setattr(state.intent.consumer_lanes, _slot(consumer), lane_record)


def clear_consumer_lane(state: SessionState, consumer: Consumer) -> None:
    """Drop ``consumer``'s lane from **both** intent and confirmed (binding teardown).

    Supervisor ``remove`` calls this: the lane binding belongs to the consumer, so removing
    the consumer orphans it. Clearing the pending ``intent`` override **and** any frozen
    ``confirmed`` binding makes a later re-add start from the consumer default -- otherwise
    ``read_bound_lane`` (confirmed-first, else intent) would resurrect the removed lane (e.g.
    ``set --runtime codex`` -> ``remove`` -> ``set planner`` would still dispatch codex).
    """
    slot = _slot(consumer)
    if state.intent.consumer_lanes is not None:
        setattr(state.intent.consumer_lanes, slot, None)
    if state.confirmed.consumer_lanes is not None:
        setattr(state.confirmed.consumer_lanes, slot, None)


def clear_intent_lane(state: SessionState, consumer: Consumer) -> None:
    """Drop ``consumer``'s ``intent`` override only, leaving any frozen ``confirmed`` binding.

    The ``forge session lane clear`` setter. Unlike ``clear_consumer_lane`` (full teardown of
    *both* sections, used by supervisor ``remove``), this preserves an already-frozen binding:
    immutability protects the lane a run committed to for the session. Clearing *before* the
    freeze removes the pending request (back to default); clearing *after* is a no-op for
    dispatch (``read_bound_lane`` is confirmed-first) and surfaces as drift in ``show``, then
    resets on the next session.
    """
    if state.intent.consumer_lanes is not None:
        setattr(state.intent.consumer_lanes, _slot(consumer), None)


def ensure_consumer_lane_binding(state: SessionState, consumer: Consumer, lane_record: LaneRecord | None) -> None:
    """Freeze ``consumer``'s explicitly-chosen lane into ``confirmed``, write-if-absent.

    The single immutability seam (card D2). ``lane_record`` is the lane the hook injected at
    registration (``read_bound_lane`` -- confirmed-first, else the intent override), NOT a fresh
    manifest read, so the freeze records exactly what dispatched even if intent changes during
    the (multi-second) supervisor call.

    **The default lane is never frozen.** ``lane_record is None`` means no explicit choice was
    recorded (neither ``confirmed`` nor ``intent``) and the consumer ran on its default; we leave
    ``confirmed`` empty. That keeps the default re-resolvable and lets the user pin a lane later
    (``set --runtime``) without tripping the already-bound reject -- immutability protects an
    *explicit* choice, not an unconfigured default. Only an explicit lane freezes, always
    ``source="intent"``.

    Idempotent -- a second call is a no-op once the binding exists. A drifted record (a backend
    renamed out of the catalog) fails ``resolve_lane`` and is *skipped*, never frozen as a
    known-unusable lane; dispatch has already failed open as a no-call, so a later valid catalog
    can still freeze it.
    """
    # Reject an unwired consumer up front (internal boundary, never a silent no-op): the no-op
    # branches below (already-bound, or default/None) would otherwise skip slot validation on a
    # fresh manifest, since _confirmed_binding early-returns before reaching _slot.
    _slot(consumer)
    if lane_record is None or _confirmed_binding(state, consumer) is not None:
        return

    try:
        resolved = resolve_lane(consumer, override=_record_to_lane(lane_record))
    except LaneError as e:
        # Best-effort durable write: a drifted/invalid lane must not freeze a binding the
        # dispatch path can't execute. Dispatch already fails open (no-call); leaving
        # confirmed unwritten lets a later, valid catalog freeze it.
        _log.warning("Consumer-lane binding for %r skipped (lane no longer valid): %s", consumer.id, e)
        return

    record = LaneRecord(resolved.runtime_id, resolved.backend_id, resolved.model)
    binding = ConsumerLaneBinding(lane=record, source="intent", resolved_at=now_iso())
    _set_confirmed_binding(state, consumer, binding)


def freeze_bound_lane(state: SessionState, consumer: Consumer) -> None:
    """Freeze ``consumer``'s currently-bound lane into ``confirmed`` (write-if-absent).

    The first-dispatch freeze for the non-supervisor consumers (memory-writer,
    shadow-curation, team-supervisor): they dispatch on whatever ``read_bound_lane``
    resolves, so the lane to freeze *is* that read. Thin wrapper over
    ``ensure_consumer_lane_binding`` -- write-once, the default (None) is never frozen,
    a drifted record is skipped.

    The supervisor does NOT use this. It threads the lane that actually dispatched and
    re-checks equality under lock, because its lane can be re-pinned during the
    multi-second *unlocked* supervisor call (``cli/hooks/policy.py``). These three freeze
    *before* dispatch, so there is no such window and the fresh read is the bound lane.
    """
    ensure_consumer_lane_binding(state, consumer, read_bound_lane(state, consumer))


def _record_to_lane(record: LaneRecord) -> Lane:
    """Validate a stored LaneRecord against today's catalogs (raises LaneError on drift)."""
    # Keyword args, not positional: the LaneRecord/Lane field-parity test guards names, not
    # constructor order, so positional construction would silently swap a reordered field.
    return Lane(runtime_id=record.runtime_id, backend_id=record.backend_id, model=record.model)


def _slot(consumer: Consumer) -> str:
    """Map a consumer to its manifest field name; reject an unwired consumer (internal boundary)."""
    if consumer.id not in _CONSUMER_LANE_SLOTS:
        raise ValueError(f"Consumer {consumer.id!r} has no consumer_lanes manifest slot")
    return consumer.id


def _intent_record(state: SessionState, consumer: Consumer) -> LaneRecord | None:
    section = state.intent.consumer_lanes
    if section is None:
        return None
    record: LaneRecord | None = getattr(section, _slot(consumer))
    return record


def _confirmed_binding(state: SessionState, consumer: Consumer) -> ConsumerLaneBinding | None:
    section = state.confirmed.consumer_lanes
    if section is None:
        return None
    binding: ConsumerLaneBinding | None = getattr(section, _slot(consumer))
    return binding


def _set_confirmed_binding(state: SessionState, consumer: Consumer, binding: ConsumerLaneBinding) -> None:
    if state.confirmed.consumer_lanes is None:
        state.confirmed.consumer_lanes = ConsumerLaneConfirmed()
    setattr(state.confirmed.consumer_lanes, _slot(consumer), binding)

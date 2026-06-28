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

from forge.core.lanes import Consumer, Lane, LaneError, resolve_lane
from forge.core.state import now_iso
from forge.session.models import (
    ConsumerLaneBinding,
    ConsumerLaneConfirmed,
    LaneRecord,
    SessionState,
)

_log = logging.getLogger(__name__)

# One named field per consumer on each section; the two must stay in lockstep so a
# consumer's intent slot has a matching confirmed slot. Guarded by
# test_consumer_lanes.test_intent_confirmed_slots_match.
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


def ensure_consumer_lane_binding(state: SessionState, consumer: Consumer, lane_record: LaneRecord | None) -> None:
    """Freeze ``consumer``'s resolved lane into ``confirmed``, write-if-absent.

    The single immutability seam (card D2): the first policy-check hook that runs a
    configured consumer records the lane **it actually dispatched on** as durable ground
    truth; later dispatches and the "already bound" reject read this. Idempotent -- a
    second call is a no-op once the binding exists.

    ``lane_record`` is the lane the hook injected at registration (``read_bound_lane``),
    NOT a fresh manifest read. Passing it explicitly keeps the freeze consistent with the
    dispatch even if intent changes during the (multi-second) supervisor call: the binding
    records exactly what ran. None => the dispatch used the consumer default
    (``source="default"``); a record => the intent override (``source="intent"``).

    A drifted record (a backend renamed out of the catalog) fails ``resolve_lane``; the
    binding is then *skipped*, never frozen as a known-unusable lane -- dispatch has
    already failed open as a no-call, so the next dispatch retries once the catalog is
    whole again.
    """
    if _confirmed_binding(state, consumer) is not None:
        return

    try:
        override = None if lane_record is None else _record_to_lane(lane_record)
        resolved = resolve_lane(consumer, override=override)
    except LaneError as e:
        # Best-effort durable write: a drifted/invalid lane must not freeze a binding the
        # dispatch path can't execute. Dispatch already fails open (no-call); leaving
        # confirmed unwritten lets a later, valid catalog freeze it.
        _log.warning("Consumer-lane binding for %r skipped (lane no longer valid): %s", consumer.id, e)
        return

    record = LaneRecord(resolved.runtime_id, resolved.backend_id, resolved.model)
    binding = ConsumerLaneBinding(
        lane=record,
        source="default" if lane_record is None else "intent",
        resolved_at=now_iso(),
    )
    _set_confirmed_binding(state, consumer, binding)


def _record_to_lane(record: LaneRecord) -> Lane:
    """Validate a stored LaneRecord against today's catalogs (raises LaneError on drift)."""
    return Lane(record.runtime_id, record.backend_id, record.model)


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

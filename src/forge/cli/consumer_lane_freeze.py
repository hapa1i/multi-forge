"""Best-effort first-dispatch freeze of a consumer's bound lane (epic consumer_lanes T6a).

The non-supervisor consumers -- memory-writer, shadow-curation, team-supervisor --
dispatch on whatever ``read_bound_lane`` resolves, then pin that choice into ``confirmed``
so billing and observability see one stable lane for the rest of the session and a later
re-declaration is rejected (the same write-once contract the supervisor already honors).

This is the CLI/hook-boundary wrapper: per the boundary framework (coding_standards.md
§5), the outermost caller decides whether a persist failure blocks the run. Here it does
not -- the freeze is bookkeeping, and billing still reads the intent lane regardless -- so
a lock/IO failure degrades to "retry on the next dispatch". The pure write-once mutate is
``forge.session.consumer_lanes.freeze_bound_lane``.

The supervisor does NOT use this. It freezes *after* its multi-second unlocked LLM call and
must guard the lane that actually dispatched (``cli/hooks/policy.py``); these sites freeze
*before* dispatch, so the bound lane cannot drift under them.
"""

from __future__ import annotations

import logging

from forge.core.lanes import Consumer
from forge.session.consumer_lanes import (
    confirmed_lane,
    freeze_bound_lane,
    read_bound_lane,
)
from forge.session.models import SessionState
from forge.session.store import SessionStore

logger = logging.getLogger(__name__)


def persist_lane_freeze(
    store: SessionStore, state: SessionState, consumer: Consumer, *, timeout_s: float = 5.0
) -> None:
    """Freeze ``consumer``'s bound lane into ``confirmed`` (write-once), best-effort.

    ``state`` is the caller's already-read manifest; ``store`` must address the same session.
    Skips the write lock on the hot path -- when the lane is already frozen or nothing was
    declared (the default lane is never frozen) -- so a steady-state dispatch pays no lock
    cost. The freeze re-checks under lock, so the skip is an optimization, not the guard. A
    lock or IO failure is swallowed: the freeze is bookkeeping and the next dispatch retries.
    """
    # Cheap pre-check on the already-read manifest: avoid taking the write lock on every
    # dispatch once frozen (the steady state) or when the consumer runs on its default.
    if confirmed_lane(state, consumer) is not None or read_bound_lane(state, consumer) is None:
        return
    try:
        store.update(timeout_s=timeout_s, mutate=lambda m: freeze_bound_lane(m, consumer))
    except Exception:  # best-effort: freeze is bookkeeping; a persist failure must not abort the run
        logger.debug("consumer-lane freeze for %s skipped (persist failed)", consumer.id, exc_info=True)

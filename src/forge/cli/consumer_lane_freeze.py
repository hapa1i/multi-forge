"""Best-effort dispatch-time freeze of a consumer's bound lane (epic consumer_lanes T6a).

The non-supervisor consumers -- memory-writer, shadow-curation, team-supervisor -- dispatch
on the lane ``read_bound_lane`` resolves, then pin that exact lane into ``confirmed`` so a
later re-declaration is rejected and observability sees one stable lane for the session.

This mirrors the supervisor freeze (``cli/hooks/policy.py``) rather than re-reading the
manifest:

- The caller resolves the lane ONCE (the same read ``backend_id`` came from) and threads it
  in as ``dispatched_lane``, so the frozen lane cannot diverge from the billed lane.
- The freeze runs from each consumer's ``on_dispatch`` hook -- at the actual
  ``run_claude_session`` call -- so a skipped/throttled/cached run never freezes a lane it
  never used.
- Under the lock it re-checks ``read_bound_lane(m) == dispatched_lane`` (the supervisor's
  equality guard): a concurrent ``forge session lane set/clear`` between dispatch and this
  write drops the stale freeze instead of recording a lane the run did not bill.

The *timing* differs from the supervisor by design, even though the guard mechanism is shared.
The supervisor is a registered, session-scoped entity (``resume_id``) and freezes eagerly at
the first policy check, because registration is its commitment point (T1b). These consumers are
per-hook invocations with no registration -- a skip means no work ran -- so their only honest
commitment point is the dispatch itself. Same guard, different trigger.

Per the boundary framework (coding_standards.md §5), the persist is the outermost caller's
call to make non-blocking: a lock/IO failure degrades to "retry on the next dispatch" -- the
freeze is bookkeeping and billing reads the lane regardless.
"""

from __future__ import annotations

import logging

from forge.core.lanes import Consumer
from forge.session.consumer_lanes import ensure_consumer_lane_binding, read_bound_lane
from forge.session.models import LaneRecord, SessionState
from forge.session.store import SessionStore

logger = logging.getLogger(__name__)


def persist_lane_freeze(
    store: SessionStore, consumer: Consumer, dispatched_lane: LaneRecord | None, *, timeout_s: float = 5.0
) -> None:
    """Freeze ``dispatched_lane`` into ``consumer``'s ``confirmed`` slot (write-once), best-effort.

    Call from the consumer's ``on_dispatch`` hook so it runs only on a real dispatch.
    ``dispatched_lane`` is the lane the run dispatched on (``read_bound_lane`` at the call site);
    ``None`` (the default lane) is never frozen. ``store`` must address the same session.

    The freeze re-checks the lane under the lock and drops the write if a concurrent edit
    changed it (supervisor parity). A lock/IO failure is swallowed -- the next dispatch retries.
    """
    if dispatched_lane is None:
        return  # the default lane is never frozen

    def _mutate(m: SessionState) -> None:
        # Equality guard (mirrors cli/hooks/policy.py): only freeze if the manifest still
        # dispatches this exact lane. A re-pin/clear between dispatch and here changes
        # read_bound_lane, so the stale write is dropped rather than recording an unused lane.
        if read_bound_lane(m, consumer) == dispatched_lane:
            ensure_consumer_lane_binding(m, consumer, dispatched_lane)

    try:
        store.update(timeout_s=timeout_s, mutate=_mutate)
    except Exception:  # best-effort: freeze is bookkeeping; a persist failure must not abort the run
        logger.debug("consumer-lane freeze for %s skipped (persist failed)", consumer.id, exc_info=True)

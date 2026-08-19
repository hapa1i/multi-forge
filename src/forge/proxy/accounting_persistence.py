"""Ordered off-event-loop persistence for proxy completion accounting."""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from typing import Callable

from forge.core.telemetry.caps import CapState, write_cap_state
from forge.core.telemetry.downstream import DownstreamRecord, write_downstream_record

logger = logging.getLogger(__name__)


class ProxyAccountingPersistence:
    """Serialize downstream records and cap snapshots on one worker thread.

    Callers must hand over complete, detached objects. The worker never reads or
    mutates request/cap-tracker state, so event-loop-owned counters remain safe while
    filesystem I/O is in flight. FIFO executor submission preserves one proxy
    process's completion evidence order.
    """

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="forge-proxy-accounting")
        self._state_lock = threading.Lock()
        self._closed = False

    def submit_downstream_record(self, record: DownstreamRecord) -> None:
        """Queue one already-built downstream record without blocking the caller."""
        self._submit(
            partial(write_downstream_record, record),
            failure_context=f"downstream accounting for request {record.request_id or 'unknown'}",
        )

    def submit_cap_state(self, state: CapState) -> Future[bool] | None:
        """Queue one immutable-by-convention cap snapshot and return its outcome."""
        return self._submit(
            partial(write_cap_state, state),
            failure_context=f"spend-cap state for {state.proxy_id}",
        )

    async def close(self) -> None:
        """Reject later submissions and drain every accepted job off the event loop."""
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        await asyncio.to_thread(self._executor.shutdown, wait=True)

    def _submit(self, operation: Callable[[], None], *, failure_context: str) -> Future[bool] | None:
        with self._state_lock:
            if self._closed:
                logger.warning("Failed to persist %s: accounting persistence is closed", failure_context)
                return None
            return self._executor.submit(self._run, operation, failure_context)

    @staticmethod
    def _run(operation: Callable[[], None], failure_context: str) -> bool:
        try:
            operation()
        except Exception as e:
            logger.warning("Failed to persist %s: %s", failure_context, e)
            return False
        return True

"""Regression: persistent queue residents cannot cycle ahead of valid work.

Root cause: the bounded cursor advanced for unreadable markers but cleared after
an all-skipped unknown-kind window, causing both resident windows to alternate
forever while later actionable work remained pending.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import forge.core.workqueue.queue as workqueue_queue
from forge.core.state import StateUnreadableError
from forge.core.workqueue import enqueue, process_pending_work

pytestmark = pytest.mark.regression


def test_resident_windows_cannot_starve_later_work(monkeypatch: pytest.MonkeyPatch) -> None:
    unreadable = [enqueue(kind="test", marker_id=f"a-unreadable-{i}", payload={}) for i in range(5)]
    unknown = [enqueue(kind="unknown", marker_id=f"m-unknown-{i}", payload={}) for i in range(5)]
    readable = enqueue(kind="test", marker_id="z-readable", payload={})
    assert all(path is not None for path in unreadable + unknown)
    assert readable is not None
    unreadable_paths = {path for path in unreadable if path is not None}
    real_read_json = workqueue_queue.read_json

    def read_with_transient_failure(path: Path) -> dict:
        if path in unreadable_paths:
            raise StateUnreadableError(str(path), "simulated transient read failure")
        return real_read_json(path)

    monkeypatch.setattr(workqueue_queue, "read_json", read_with_transient_failure)
    handler = MagicMock()

    for _ in range(3):
        process_pending_work(max_items=5, handlers={"test": handler})

    handler.assert_called_once()
    assert not readable.exists()

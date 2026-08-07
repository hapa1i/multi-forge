"""D011 regression: a shared JSON read OSError is unreadable state, not corruption.

Root cause: ``read_json`` wrapped ``OSError`` from ``open()`` in
``StateCorruptedError``, allowing callers such as the workqueue to quarantine bytes
whose contents had never been shown to be malformed.
"""

from __future__ import annotations

import builtins
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import forge.core.workqueue.queue as workqueue_queue
from forge.core.state import StateUnreadableError, read_json
from forge.core.workqueue import enqueue, process_pending_work

pytestmark = pytest.mark.regression


def test_read_oserror_is_unreadable_and_preserves_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "state.json"
    original = b'{"schema_version": 1}\n'
    target.write_bytes(original)

    real_open = builtins.open
    failed = False

    def fail_first_target_read(file, *args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal failed
        if Path(file) == target and not failed:
            failed = True
            raise OSError("simulated transient read failure")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fail_first_target_read)

    with pytest.raises(StateUnreadableError, match="simulated transient read failure"):
        read_json(target)

    assert target.read_bytes() == original


def test_unreadable_queue_prefix_cannot_starve_later_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bounded startup scan resumes after an unreadable prefix on its next run."""
    unreadable = [enqueue(kind="test", marker_id=f"a-unreadable-{i}", payload={}) for i in range(5)]
    readable = enqueue(kind="test", marker_id="z-readable", payload={})
    assert all(path is not None for path in unreadable)
    assert readable is not None
    unreadable_paths = {path for path in unreadable if path is not None}
    original_bytes = {path: path.read_bytes() for path in unreadable_paths}
    real_read_json = workqueue_queue.read_json

    def read_with_transient_failure(path: Path) -> dict:
        if path in unreadable_paths:
            raise StateUnreadableError(str(path), "simulated transient read failure")
        return real_read_json(path)

    monkeypatch.setattr(workqueue_queue, "read_json", read_with_transient_failure)
    handler = MagicMock()

    first = process_pending_work(max_items=5, handlers={"test": handler})
    assert first.processed == 0
    assert len(first.diagnostics) == 5
    handler.assert_not_called()

    second = process_pending_work(max_items=5, handlers={"test": handler})
    assert second.processed == 1
    handler.assert_called_once()
    assert not readable.exists()
    assert {path: path.read_bytes() for path in unreadable_paths} == original_bytes

"""Forge async work queue — general-purpose deferred processing primitive.

Provides a file-based queue where producers enqueue markers and CLI startup
processes them opportunistically. Markers are dispatched to handlers by kind.

Quick Start:
    from forge.core.workqueue import enqueue, process_pending_work, enqueue_stop_marker

    # Enqueue a generic marker
    enqueue(kind="index", marker_id="session-123", payload={"path": "..."})

    # Enqueue a stop marker (convenience)
    enqueue_stop_marker(session_id="uuid", worktree_path=Path(...), ...)

    # Process with explicit handlers
    def handle_index(marker):
        index_session(marker.payload["path"])

    process_pending_work(handlers={"index": handle_index})
"""

from .queue import (
    MARKER_LOCK_TIMEOUT_S,
    PROCESSOR_LOCK_TIMEOUT_S,
    SAFE_MARKER_ID,
    enqueue,
    enqueue_handoff_marker,
    enqueue_index_marker,
    enqueue_shadow_marker,
    enqueue_stop_marker,
    marker_path,
    pending_work_dir,
    process_pending_work,
)
from .types import (
    FAILED_WORK_DIR,
    MARKER_SCHEMA_VERSION,
    MAX_ATTEMPTS,
    MAX_ERROR_LENGTH,
    PENDING_WORK_DIR,
    Marker,
    ProcessResult,
    WorkHandler,
)

__all__ = [
    # Queue operations
    "enqueue",
    "enqueue_handoff_marker",
    "enqueue_index_marker",
    "enqueue_shadow_marker",
    "enqueue_stop_marker",
    "marker_path",
    "pending_work_dir",
    "process_pending_work",
    # Types
    "Marker",
    "ProcessResult",
    "WorkHandler",
    # Constants
    "MARKER_SCHEMA_VERSION",
    "MAX_ATTEMPTS",
    "MAX_ERROR_LENGTH",
    "PENDING_WORK_DIR",
    "FAILED_WORK_DIR",
    "MARKER_LOCK_TIMEOUT_S",
    "PROCESSOR_LOCK_TIMEOUT_S",
    "SAFE_MARKER_ID",
]

"""Types for the Forge async work queue.

Defines the marker dataclass, processing result, and handler protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

# Schema versioning
MARKER_SCHEMA_VERSION = 1

# Poison marker limit: after this many failures, move to failed/
MAX_ATTEMPTS = 5

# Queue directory name under FORGE_HOME
PENDING_WORK_DIR = "pending-work"
FAILED_WORK_DIR = "pending-work/failed"

# Maximum error message length stored in markers
MAX_ERROR_LENGTH = 500


@dataclass
class Marker:
    """A work queue marker representing deferred work.

    Each marker is a single work unit identified by (kind, marker_id).
    The kind determines which handler processes it.
    The marker_id determines the filename (must be a safe filename).
    """

    schema_version: int
    kind: str
    marker_id: str
    forge_version: str
    created_at: str
    payload: dict[str, Any]
    attempt_count: int = 0
    last_attempt_at: str | None = None
    last_error: str | None = None


@dataclass
class ProcessResult:
    """Result of processing the work queue."""

    processed: int = 0
    skipped: int = 0
    failed: int = 0  # Markers that exceeded MAX_ATTEMPTS (moved to failed/)
    errors: list[str] = field(default_factory=list)


class WorkHandler(Protocol):
    """Protocol for work queue handlers.

    Handlers are called with a Marker and should raise on failure.
    On success, the marker is deleted. On failure, the marker is kept
    with attempt_count incremented.
    """

    def __call__(self, marker: Marker) -> None: ...

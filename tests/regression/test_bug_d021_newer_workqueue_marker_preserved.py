"""Regression D021: newer workqueue schemas must not enter invalid-marker retries.

Root cause: ``_validate_marker`` collapsed every non-current schema version into the
retryable invalid-marker path, so an older Forge rewrote future fields and eventually
moved the marker to ``failed/``.
"""

from __future__ import annotations

import json

import pytest

from forge.core.workqueue import (
    MARKER_SCHEMA_VERSION,
    pending_work_dir,
    process_pending_work,
)

pytestmark = pytest.mark.regression


def test_newer_schema_marker_stays_byte_identical_across_poison_threshold() -> None:
    queue_dir = pending_work_dir()
    queue_dir.mkdir(parents=True)
    marker = queue_dir / "future-marker.json"
    marker.write_text(
        json.dumps(
            {
                "schema_version": MARKER_SCHEMA_VERSION + 1,
                "kind": "future-kind",
                "marker_id": "future-marker",
                "forge_version": "future",
                "created_at": "2099-01-01T00:00:00Z",
                "payload": {"future_field": {"shape": [1, 2, 3]}},
                "attempt_count": 0,
                "last_attempt_at": None,
                "last_error": None,
                "future_envelope_field": "must-survive",
            },
            indent=4,
        )
        + "\n",
        encoding="utf-8",
    )
    original = marker.read_bytes()

    for _ in range(6):
        result = process_pending_work(handlers={})

        assert result.failed == 0
        assert marker.read_bytes() == original
        assert result.errors == []
        assert not (queue_dir / "failed" / marker.name).exists()

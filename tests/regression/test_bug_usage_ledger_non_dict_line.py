"""Regression: a non-object JSONL line must not abort the usage-ledger read (Phase 4b).

Bug: ``read_usage_events`` called ``record.get(...)`` immediately after ``json.loads``,
assuming every line decodes to a dict. A valid-but-non-object line (``[]``, ``"x"``, ``1``)
raised ``AttributeError`` -- uncaught between the json/dacite ``try`` blocks, so it escaped
past ``except OSError`` and aborted the ENTIRE read, dropping every other shard's events.
The contract is "skip malformed records," so one bad line must not nuke the read.

Root cause / fix: guard with ``isinstance(record, dict)`` before ``.get`` in
``src/forge/core/usage/ledger.py::read_usage_events``.
"""

from __future__ import annotations

import pytest

from forge.core.usage.ledger import UsageEvent, log_usage_event, read_usage_events

pytestmark = pytest.mark.regression


def _shard_path():
    import os
    from datetime import datetime, timezone

    from forge.core.paths import get_forge_home

    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return get_forge_home() / "usage" / "events" / f"{month}_{os.getpid()}.jsonl"


@pytest.mark.parametrize("bad_line", ["[]", '"hello"', "1", "true", "null"])
def test_non_object_line_does_not_abort_read(bad_line: str) -> None:
    """A non-object JSON line is skipped; valid events around it still load (no crash)."""
    log_usage_event(UsageEvent(run_id="r", root_run_id="r", runtime="claude_code", command="keep", status="success"))
    with _shard_path().open("a") as f:
        f.write(bad_line + "\n")

    # Before the fix this raised AttributeError instead of returning the valid event.
    events = read_usage_events()

    assert [e.command for e in events] == ["keep"]

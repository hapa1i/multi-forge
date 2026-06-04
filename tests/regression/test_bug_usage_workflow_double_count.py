"""Regression: workflow usage double-counted across verb + worker events.

Bug: a single workflow verb (e.g. ``panel``) emits one verb-aggregate UsageEvent
(``attribution_granularity="verb"``) plus one per-worker event per worker
(``attribution_granularity="worker"``), all sharing ``command="panel"``. The summary
aggregator counted every event as a ``call`` and derived the session-end "N workflows"
tally from that count, so one 4-worker panel rendered as 5 workflows / 5 calls.

Root cause: ``core/ops/usage_summary._aggregate_ledger`` incremented ``calls`` for every
event regardless of ``attribution_granularity``; ``render_summary_line`` summed those
``calls`` for the workflow tally.

Fix: worker-granularity events are counted in ``CommandUsage.workers``, not ``calls``;
per-command ``calls`` and the workflow tally are one-per-invocation.

Affected: ``src/forge/core/ops/usage_summary.py``.
"""

from __future__ import annotations

import pytest

from forge.core.ops.usage_summary import build_session_activity_summary, render_summary_line
from forge.core.usage.ledger import UsageEvent, log_usage_event

pytestmark = pytest.mark.regression


def _panel_event(granularity: str, **overrides: object) -> UsageEvent:
    base: dict[str, object] = {
        "run_id": "r",
        "root_run_id": "r",
        "runtime": "claude_code",
        "command": "panel",
        "status": "success",
        "session": "planner",
        "attribution_granularity": granularity,
    }
    base.update(overrides)
    return UsageEvent(**base)  # type: ignore[arg-type]


def test_four_worker_panel_is_one_workflow_not_five() -> None:
    # 1 verb-aggregate + 4 worker leaves, all command="panel", one session.
    log_usage_event(_panel_event("verb"))
    for _ in range(4):
        log_usage_event(_panel_event("worker"))

    summary = build_session_activity_summary("planner", forge_root=None)

    panel = next(c for c in summary.commands if c.command == "panel")
    assert panel.calls == 1, "the verb aggregate is the single logical invocation"
    assert panel.workers == 4, "the four claude -p leaves are tracked apart from calls"
    assert summary.total_events == 5  # raw ledger event count is unchanged

    line = render_summary_line(summary)
    assert line is not None
    assert "1 workflow" in line
    assert "5 workflow" not in line


def test_worker_error_does_not_inflate_call_errors() -> None:
    # A failed worker must not be counted as a verb-level error (keep errors <= calls).
    log_usage_event(_panel_event("verb", status="success"))
    log_usage_event(_panel_event("worker", status="error"))

    summary = build_session_activity_summary("planner", forge_root=None)
    panel = next(c for c in summary.commands if c.command == "panel")
    assert panel.calls == 1
    assert panel.workers == 1
    assert panel.errors == 0

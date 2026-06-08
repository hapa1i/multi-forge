"""Regression: 4g read-join must not drop a correctly-unstamped run's snapshot.

Bug (review, 2026-06-08): ``_join_session_cost`` suppressed every
``verb_snapshot_estimated`` event whose ``root_run_id`` had ANY cost-plane record
(whole-root suppression). When two headless verbs share one session root -- the
real topology, since children spawned from the same session run inherit one
``root_run_id`` -- and only some are stamped, the stamped run populated the root's
record set and the *correctly-unstamped* sibling's snapshot was dropped with no exact
figure to replace it. Silent undercount.

Concretely: a stamped memory-writer (exact cost-plane record) plus an opaque/off-Forge
proxied supervisor whose header was correctly NOT stamped (no record) but whose verb
snapshot is its only cost evidence. The supervisor's cost must survive.

Root cause / fix: ``src/forge/core/ops/usage_summary.py::_join_session_cost`` now
suppresses per-run-subtree -- a snapshot is superseded only when its OWN run produced
records, or it is a verb whose DIRECT children did (fan-out, via worker
``parent_run_id``) -- not merely because a sibling under the same root was stamped.
"""

from __future__ import annotations

import pytest

from forge.core.ops.usage_summary import (
    build_session_activity_summary,
    sum_forge_added_cost,
)
from forge.core.usage.ledger import UsageEvent, log_usage_event
from forge.proxy.cost_logger import log_request_cost

pytestmark = pytest.mark.regression

_ROOT = "run_session"  # shared session root: both verbs inherit it


def _verb_event(*, command: str, run: str, snapshot_micros: int) -> None:
    log_usage_event(
        UsageEvent(
            run_id=run,
            parent_run_id=_ROOT,  # spawned from the session run -> shared root
            root_run_id=_ROOT,
            runtime="claude_code",
            command=command,
            status="success",
            session="planner",
            route="claude_p",
            reporter="forge_proxy",
            confidence="reported",
            measurement_source="verb_snapshot_estimated",
            cost_micro_usd=snapshot_micros,
        )
    )


def _stamped_cost_record(*, run: str, micros: int) -> None:
    log_request_cost(
        proxy_id="p1",
        model="gpt-5.5",
        tier="sonnet",
        input_tokens=10,
        output_tokens=5,
        cached_tokens=0,
        cost_micros=micros,
        latency_ms=1.0,
        failed=False,
        request_id="req_" + run,
        reporter="openrouter",
        confidence="reported",
        forge_run_id=run,
        forge_root_run_id=_ROOT,
    )


def test_unstamped_sibling_snapshot_survives_stamped_run() -> None:
    # Stamped memory-writer: exact 30k record supersedes its 50k snapshot.
    _verb_event(command="memory-writer", run="run_mw", snapshot_micros=50_000)
    _stamped_cost_record(run="run_mw", micros=30_000)
    # Unstamped supervisor (off-Forge proxy): NO record; its 40k snapshot is the only
    # evidence. The old whole-root rule dropped it because run_mw populated the root.
    _verb_event(command="supervisor", run="run_sup", snapshot_micros=40_000)

    total = sum_forge_added_cost("planner")
    assert total == 70_000, f"expected 30k exact + 40k snapshot, got {total} (undercount = bug)"
    assert total != 30_000  # the specific failure mode: supervisor's 40k silently dropped


def test_mixed_total_is_estimated_and_breaks_down_per_command() -> None:
    _verb_event(command="memory-writer", run="run_mw", snapshot_micros=50_000)
    _stamped_cost_record(run="run_mw", micros=30_000)
    _verb_event(command="supervisor", run="run_sup", snapshot_micros=40_000)

    summary = build_session_activity_summary("planner", None)
    assert summary.total_cost_micro_usd == 70_000
    # The total mixes an exact cost-plane figure with a snapshot estimate -> approximate.
    assert summary.cost_estimated is True
    by_cmd = {c.command: c for c in summary.commands}
    # memory-writer is exact (cost plane), supervisor is the estimated snapshot fallback.
    assert by_cmd["memory-writer"].cost_micro_usd == 30_000
    assert by_cmd["memory-writer"].cost_estimated is False
    assert by_cmd["supervisor"].cost_micro_usd == 40_000
    assert by_cmd["supervisor"].cost_estimated is True

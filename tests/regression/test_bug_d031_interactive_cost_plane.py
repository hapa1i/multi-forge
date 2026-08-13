"""Regression: exclude interactive harness spend from both cost-join planes.

D031: ``_join_session_cost`` filtered interactive usage events only after querying every event root and summing the
returned per-run cost. Exact interactive proxy records therefore re-entered ``forge +$Y`` through the cost plane, and
presence-only interactive records could falsely mark a mixed result partial.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from forge.core.ops.usage_summary import (
    _join_session_cost,
    build_session_activity_summary,
    sum_forge_added_cost,
)
from forge.core.usage.ledger import UsageEvent, log_usage_event
from forge.core.usage.vocabulary import Route
from forge.proxy import cost_logger
from forge.proxy.cost_logger import log_request_cost

pytestmark = pytest.mark.regression

_ROOT = "run_shared_root"


def _event(*, run: str, route: Route, command: str) -> UsageEvent:
    return UsageEvent(
        run_id=run,
        parent_run_id=_ROOT,
        root_run_id=_ROOT,
        runtime="claude_code",
        command=command,
        status="success",
        session="planner",
        route=route,
    )


def _cost_record(*, run: str, micros: int | None) -> None:
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
        request_id=f"req_{run}",
        reporter="openrouter" if micros is not None else None,
        confidence="reported" if micros is not None else "unavailable",
        forge_run_id=run,
        forge_root_run_id=_ROOT,
    )


def test_all_interactive_root_never_enters_cost_join() -> None:
    log_usage_event(_event(run="run_interactive", route="claude_interactive", command="interactive"))
    _cost_record(run="run_interactive", micros=500_000)

    with patch(
        "forge.proxy.cost_logger.sum_reported_cost_by_root",
        wraps=cost_logger.sum_reported_cost_by_root,
    ) as query:
        assert sum_forge_added_cost("planner") is None

    query.assert_not_called()


def test_mixed_root_excludes_interactive_run_but_keeps_sibling_exact_cost() -> None:
    events = [
        _event(run="run_interactive", route="claude_interactive", command="interactive"),
        _event(run="run_worker", route="claude_p", command="memory-writer"),
    ]
    _cost_record(run="run_interactive", micros=500_000)
    _cost_record(run="run_worker", micros=30_000)

    result = _join_session_cost(events, None, exclude_interactive=True, trusted_only=True)

    assert result.total == 30_000
    assert result.by_command == {"memory-writer": 30_000}
    assert result.partial is False


def test_excluded_presence_only_run_does_not_make_mixed_cost_partial() -> None:
    events = [
        _event(run="run_interactive", route="claude_interactive", command="interactive"),
        _event(run="run_worker", route="claude_p", command="memory-writer"),
    ]
    _cost_record(run="run_interactive", micros=None)
    _cost_record(run="run_worker", micros=30_000)

    result = _join_session_cost(events, None, exclude_interactive=True, trusted_only=True)

    assert result.total == 30_000
    assert result.partial is False


def test_included_root_retains_unobserved_child_cost() -> None:
    log_usage_event(_event(run="run_worker", route="claude_p", command="memory-writer"))
    _cost_record(run="run_worker", micros=30_000)
    _cost_record(run="run_cancelled_orphan", micros=20_000)

    assert sum_forge_added_cost("planner") == 50_000


def test_join_without_exclusion_keeps_interactive_cost() -> None:
    events = [_event(run="run_interactive", route="claude_interactive", command="interactive")]
    _cost_record(run="run_interactive", micros=500_000)

    result = _join_session_cost(events, None, exclude_interactive=False, trusted_only=False)

    assert result.total == 500_000
    assert result.by_command == {"interactive": 500_000}


def test_activity_counts_keep_interactive_event() -> None:
    log_usage_event(_event(run="run_interactive", route="claude_interactive", command="interactive"))
    log_usage_event(_event(run="run_worker", route="claude_p", command="memory-writer"))

    summary = build_session_activity_summary("planner", None)
    calls = {command.command: command.calls for command in summary.commands}

    assert summary.total_events == 2
    assert calls == {"interactive": 1, "memory-writer": 1}

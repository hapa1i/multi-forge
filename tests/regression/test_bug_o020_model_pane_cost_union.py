"""Regression guard for the rejected O020 model-pane cost claim."""

from __future__ import annotations

import pytest

from forge.core.ops import usage_summary
from forge.core.ops.usage_summary import CommandUsage, SessionActivitySummary
from forge.core.run_id import derive_provider_session_id
from forge.core.telemetry.downstream import DownstreamReadResult, DownstreamRecord

pytestmark = pytest.mark.regression


def test_o020_model_pane_keeps_non_proxy_event_cost_with_downstream_rows(monkeypatch) -> None:
    """Adding downstream evidence does not replace event-backed command totals."""
    summary = SessionActivitySummary(
        session="planner",
        commands=[
            CommandUsage(command="direct-supervisor", calls=1, cost_micro_usd=700),
            CommandUsage(command="proxied-panel", calls=1, cost_micro_usd=300),
        ],
        total_cost_micro_usd=1_000,
        cost_estimated=False,
    )

    monkeypatch.setattr(usage_summary, "read_upstream_outcomes", lambda **_kwargs: [])
    monkeypatch.setattr(
        usage_summary,
        "read_downstream_records_with_stats",
        lambda **_kwargs: DownstreamReadResult(
            records=[
                DownstreamRecord(
                    kind="attempt",
                    downstream_event_id="ds_proxy_only",
                    provider_command="proxy-only",
                    provider_session_id=derive_provider_session_id("planner", root_run_id="", role=None),
                    cost_micros=200,
                )
            ]
        ),
    )

    usage_summary._build_activity_panes(summary, "planner", since=None, events=[])

    assert {row.command for row in summary.downstream.rows} == {
        "direct-supervisor",
        "proxied-panel",
        "proxy-only",
    }
    assert summary.downstream.total_cost_micro_usd == 1_200
    assert summary.total_cost_micro_usd == 1_200

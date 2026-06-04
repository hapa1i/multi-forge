"""Tests for the per-session activity summary (forge usage / session-end line).

Two planes are aggregated and kept separate: the usage ledger (supervisor run/error
counts) and ``confirmed.policy.decisions`` (supervisor allow/warn/deny + warnings,
capped). The autouse ``isolate_forge_home`` fixture gives each test a fresh
``FORGE_HOME`` so ledger counts are exact.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from forge.core.ops.usage_summary import (
    CommandUsage,
    PolicyActivity,
    SessionActivitySummary,
    build_session_activity_summary,
    render_summary_line,
)
from forge.core.usage.ledger import UsageEvent, log_usage_event
from forge.session.models import (
    PolicyConfirmed,
    SubagentConfirmed,
    create_session_state,
)
from forge.session.store import SessionStore


def _event(**overrides: object) -> UsageEvent:
    base: dict[str, object] = {
        "run_id": "run_a",
        "root_run_id": "run_a",
        "runtime": "claude_code",
        "command": "supervisor",
        "status": "success",
        "session": "planner",
    }
    base.update(overrides)
    return UsageEvent(**base)  # type: ignore[arg-type]


def _decision(
    *,
    supervisor: str | None = None,
    warnings: list[str] | None = None,
    evaluated_at: str = "2026-06-03T12:00:00Z",
) -> dict:
    entry: dict = {
        "final_decision": supervisor or "allow",
        "context_summary": None,
        "blocking_violations": [],
        "warnings": warnings or [],
        "evaluated_at": evaluated_at,
        "decisions": [],
    }
    if supervisor:
        entry["decisions"].append(
            {
                "decision": supervisor,
                "policy_id": "semantic.supervisor",
                "violations": [],
                "warnings": warnings or [],
                "cached": False,
                "evaluated_at": evaluated_at,
            }
        )
    return entry


def _write_manifest(forge_root: Path, name: str, *, decisions: list[dict] | None = None, subagents: int = 0):
    state = create_session_state(name, worktree_path=str(forge_root))
    if decisions is not None:
        state.confirmed.policy = PolicyConfirmed(decisions=decisions)
    if subagents:
        state.confirmed.subagents = SubagentConfirmed(total_count=subagents)
    SessionStore(str(forge_root), name).write(state)
    return state


class TestLedgerPlane:
    def test_supervisor_runs_and_errors(self) -> None:
        log_usage_event(_event(status="success"))
        log_usage_event(_event(status="success"))
        log_usage_event(_event(status="error"))
        log_usage_event(_event(command="panel", status="success"))

        summary = build_session_activity_summary("planner", forge_root=None)

        assert summary.total_events == 4
        by_cmd = {c.command: c for c in summary.commands}
        assert by_cmd["supervisor"].calls == 3
        assert by_cmd["supervisor"].errors == 1
        assert by_cmd["panel"].calls == 1
        # commands sorted by calls desc -> supervisor first
        assert summary.commands[0].command == "supervisor"

    def test_only_this_session(self) -> None:
        log_usage_event(_event(session="planner", command="supervisor"))
        log_usage_event(_event(session="executor", command="panel"))
        summary = build_session_activity_summary("planner", forge_root=None)
        assert {c.command for c in summary.commands} == {"supervisor"}

    def test_cost_sum_and_partial(self) -> None:
        log_usage_event(_event(cost_micro_usd=20_000, input_tokens=100, output_tokens=50))
        log_usage_event(_event(cost_micro_usd=20_000, input_tokens=100, output_tokens=50))
        log_usage_event(_event(cost_micro_usd=None))  # unmeasured -> partial
        summary = build_session_activity_summary("planner", forge_root=None)
        assert summary.total_cost_micro_usd == 40_000
        assert summary.total_input_tokens == 200
        assert summary.total_output_tokens == 100
        assert summary.cost_partial is True

    def test_cost_none_when_nothing_measured(self) -> None:
        log_usage_event(_event(cost_micro_usd=None))
        summary = build_session_activity_summary("planner", forge_root=None)
        assert summary.total_cost_micro_usd is None
        assert summary.cost_partial is False


class TestPolicyPlane:
    def test_supervisor_breakdown_and_warnings(self, tmp_path: Path) -> None:
        _write_manifest(
            tmp_path,
            "planner",
            decisions=[
                _decision(supervisor="allow"),
                _decision(supervisor="allow"),
                _decision(supervisor="warn", warnings=["Possible divergence: parse failed (0%)"]),
            ],
            subagents=3,
        )
        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))

        assert summary.policy is not None
        assert summary.policy.supervisor_allow == 2
        assert summary.policy.supervisor_warn == 1
        assert summary.policy.supervisor_deny == 0
        assert summary.policy.total_warnings == 1
        assert summary.policy.recent_warnings == ["Possible divergence: parse failed (0%)"]
        assert summary.policy.log_capped is False
        assert summary.subagents == 3

    def test_log_capped_at_max(self, tmp_path: Path) -> None:
        from forge.policy.store import MAX_DECISION_LOG

        _write_manifest(
            tmp_path,
            "planner",
            decisions=[_decision(supervisor="allow") for _ in range(MAX_DECISION_LOG)],
        )
        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))
        assert summary.policy is not None
        assert summary.policy.log_capped is True

    def test_since_window_filters_decisions(self, tmp_path: Path) -> None:
        old = "2026-06-01T00:00:00Z"
        new = "2026-06-03T12:00:00Z"
        _write_manifest(
            tmp_path,
            "planner",
            decisions=[
                _decision(supervisor="warn", evaluated_at=old),
                _decision(supervisor="deny", evaluated_at=new),
            ],
        )
        since = datetime(2026, 6, 2, tzinfo=timezone.utc)
        summary = build_session_activity_summary("planner", forge_root=str(tmp_path), since=since)
        assert summary.policy is not None
        # Only the post-`since` deny is counted.
        assert summary.policy.supervisor_warn == 0
        assert summary.policy.supervisor_deny == 1


class TestBestEffort:
    def test_missing_manifest_does_not_raise(self) -> None:
        log_usage_event(_event(command="supervisor"))
        summary = build_session_activity_summary("ghost", forge_root=None)
        # Ledger still filters by session; this session has no events.
        assert summary.commands == []
        assert summary.policy is None
        assert summary.is_empty is True

    def test_empty_session_is_empty(self) -> None:
        summary = build_session_activity_summary("planner", forge_root=None)
        assert summary.is_empty is True
        assert render_summary_line(summary) is None


class TestRenderLine:
    def test_full_line(self) -> None:
        summary = SessionActivitySummary(
            session="planner",
            commands=[
                CommandUsage(command="supervisor", calls=12, errors=3),
                CommandUsage(command="panel", calls=2),
            ],
            total_cost_micro_usd=40_000,
            total_input_tokens=18_000,
            total_output_tokens=3_000,
            policy=PolicyActivity(supervisor_allow=10, supervisor_warn=2, supervisor_deny=0, total_warnings=2),
            subagents=1,
        )
        line = render_summary_line(summary)
        assert line is not None
        assert "supervisor: 12 checks (2 warn, 0 block, 3 errors)" in line
        assert "~$0.04 est" in line
        assert "21k tok" in line
        assert "2 workflows" in line
        assert "1 subagent" in line

    def test_falls_back_to_ledger_when_no_policy(self) -> None:
        summary = SessionActivitySummary(
            session="planner",
            commands=[CommandUsage(command="supervisor", calls=4, errors=4)],
        )
        line = render_summary_line(summary)
        assert line is not None
        assert "supervisor: 4 runs (4 errors)" in line

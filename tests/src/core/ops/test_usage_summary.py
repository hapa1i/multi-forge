"""Tests for the per-session activity summary (forge telemetry activity / session-end line).

Operation outcomes, downstream/model-call evidence, transitional usage events, and the
manifest fallback are aggregated but kept visibly separate. The autouse
``isolate_forge_home`` fixture gives each test a fresh ``FORGE_HOME`` so ledger counts
are exact.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from forge.core.ops.usage_summary import (
    CommandUsage,
    PolicyActivity,
    SessionActivitySummary,
    SupervisorHealth,
    build_session_activity_summary,
    read_supervisor_health,
    render_summary_line,
    sum_forge_added_cost,
)
from forge.core.paths import get_forge_home
from forge.core.run_id import derive_provider_session_id
from forge.core.telemetry.downstream import (
    DownstreamRecord,
    mint_downstream_event_id,
    write_downstream_record,
)
from forge.core.telemetry.upstream import UpstreamOutcome, write_upstream_outcome
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
    plan_check: str | None = None,
    plan_check_cached: bool = False,
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
    if plan_check:
        entry["decisions"].append(
            {
                "decision": plan_check,
                "policy_id": "semantic.plan_check",
                "violations": (
                    []
                    if plan_check == "allow"
                    else [
                        {
                            "rule_id": "semantic.plan_check.uncertain",
                            "message": "not clearly covered by the plan",
                            "severity": "low",
                            "evidence": None,
                            "suggested_fix": None,
                            "citations": [],
                        }
                    ]
                ),
                "warnings": [],
                "cached": plan_check_cached,
                "evaluated_at": evaluated_at,
            }
        )
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

    def test_error_kinds_breakdown(self) -> None:
        # `errors` is split per display kind; `errors == sum(error_kinds.values())`.
        log_usage_event(_event(status="timeout", failure_type="timeout"))
        log_usage_event(_event(status="timeout", failure_type="timeout"))
        log_usage_event(_event(status="error", failure_type="subprocess_error"))
        summary = build_session_activity_summary("planner", forge_root=None)
        sup = {c.command: c for c in summary.commands}["supervisor"]
        assert sup.errors == 3
        assert sup.error_kinds == {"timeout": 2, "error": 1}

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

    def test_builder_reads_usage_ledger_once(self, monkeypatch) -> None:
        import forge.core.ops.usage_summary as usage_summary

        calls = 0

        def _fake_read_usage_events(**_kwargs: object) -> list[UsageEvent]:
            nonlocal calls
            calls += 1
            return []

        monkeypatch.setattr(usage_summary, "read_usage_events", _fake_read_usage_events)

        usage_summary.build_session_activity_summary("planner", forge_root=None)

        assert calls == 1


class TestActivityPanes:
    def test_upstream_only_operation_is_visible(self, tmp_path: Path) -> None:
        write_upstream_outcome(
            UpstreamOutcome(
                command="memory-writer",
                operation="memory_writer.run",
                status="error",
                session="planner",
                run_id="run_memory",
                root_run_id="run_memory",
                reason_code="transcript_not_found",
            )
        )

        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))

        row = summary.upstream.operations[0]
        assert (row.command, row.operation, row.status, row.join_state) == (
            "memory-writer",
            "memory_writer.run",
            "error",
            "upstream_only",
        )
        assert summary.downstream.rows == []

    def test_operation_rows_roll_up_by_status_and_reason(self, tmp_path: Path) -> None:
        for idx in range(24):
            run_id = f"run_{idx:012x}"
            write_upstream_outcome(
                UpstreamOutcome(
                    command="policy-check",
                    operation="policy.evaluate",
                    policy_id="semantic.supervisor",
                    status="timeout",
                    session="planner",
                    run_id=run_id,
                    root_run_id=run_id,
                    reason_code="timeout",
                    message=f"timeout #{idx}",
                )
            )

        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))

        rows = [
            row
            for row in summary.upstream.operations
            if row.command == "policy-check" and row.policy_id == "semantic.supervisor"
        ]
        assert len(rows) == 1
        assert rows[0].count == 24
        assert rows[0].status == "timeout"
        assert rows[0].reason_code == "timeout"

    def test_matched_operation_and_model_call_share_root(self, tmp_path: Path) -> None:
        log_usage_event(
            _event(
                command="memory-writer",
                run_id="run_memory",
                root_run_id="run_memory",
                cost_micro_usd=10_000,
                confidence="reported",
                measurement_source="runtime_native",
            )
        )
        write_upstream_outcome(
            UpstreamOutcome(
                command="memory-writer",
                operation="memory_writer.run",
                status="error",
                session="planner",
                run_id="run_memory",
                root_run_id="run_memory",
                reason_code="permission_denied",
            )
        )

        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))

        assert summary.upstream.operations[0].join_state == "matched"
        row = next(row for row in summary.downstream.rows if row.command == "memory-writer")
        assert row.join_state == "matched"
        assert row.cost_micro_usd == 10_000

    def test_downstream_only_known_run_tree_is_visible(self, tmp_path: Path) -> None:
        log_usage_event(
            _event(
                command="tagger",
                run_id="run_tag",
                root_run_id="run_tag",
                input_tokens=5,
                output_tokens=2,
            )
        )
        write_downstream_record(
            DownstreamRecord(
                kind="attempt",
                downstream_event_id=mint_downstream_event_id(event_key="tagger:run_tag"),
                forge_run_id="run_tag",
                forge_root_run_id="run_tag",
                provider="openai",
                source_id="openai",
                input_tokens=5,
                output_tokens=2,
                cost_micros=1_200,
            )
        )

        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))

        row = next(row for row in summary.downstream.rows if row.command == "tagger")
        assert row.join_state == "downstream_only"
        assert (row.input_tokens, row.output_tokens) == (5, 2)
        assert summary.downstream.total_cost_micro_usd == 1_200
        assert summary.total_cost_micro_usd == 1_200

    def test_provider_session_prefix_downstream_record_is_visible(self, tmp_path: Path) -> None:
        provider_session_id = derive_provider_session_id("planner", root_run_id="", role="memory_writer")
        write_downstream_record(
            DownstreamRecord(
                kind="attempt",
                downstream_event_id=mint_downstream_event_id(event_key="provider-session-only"),
                provider_session_id=provider_session_id,
                provider_command="memory_writer",
                provider="openrouter",
                input_tokens=11,
                output_tokens=3,
                cost_micros=2_500,
            )
        )

        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))

        assert summary.downstream.downstream_records == 1
        row = summary.downstream.rows[0]
        assert row.command == "memory_writer"
        assert row.join_state == "downstream_only"
        assert (row.input_tokens, row.output_tokens) == (11, 3)
        assert summary.downstream.total_input_tokens == 11
        assert summary.downstream.total_cost_micro_usd == 2_500
        assert summary.total_input_tokens == 11
        assert summary.total_cost_micro_usd == 2_500

    def test_lane_row_carries_runtime_and_billing(self, tmp_path: Path) -> None:
        """T5/WS3: an event-backed model-call row reports the lane its events ran on."""
        log_usage_event(_event(command="supervisor", runtime="codex", billing_mode="subscription_quota"))
        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))
        row = next(r for r in summary.downstream.rows if r.command == "supervisor")
        assert row.runtime == "codex"
        assert row.billing_mode == "subscription_quota"

    def test_lane_mixed_when_command_events_disagree(self, tmp_path: Path) -> None:
        """T5/WS3 (D4): a command whose events span more than one runtime/billing renders 'mixed'."""
        log_usage_event(_event(command="panel", runtime="claude_code", billing_mode="api"))
        log_usage_event(
            _event(
                command="panel",
                run_id="run_b",
                root_run_id="run_b",
                runtime="codex",
                billing_mode="subscription_quota",
            )
        )
        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))
        row = next(r for r in summary.downstream.rows if r.command == "panel")
        assert row.runtime == "mixed"
        assert row.billing_mode == "mixed"

    def test_lane_none_for_downstream_only_row(self, tmp_path: Path) -> None:
        """T5/WS3 (D4): a downstream-only row with no usage-event source carries no lane (renders '-')."""
        provider_session_id = derive_provider_session_id("planner", root_run_id="", role="memory_writer")
        write_downstream_record(
            DownstreamRecord(
                kind="attempt",
                downstream_event_id=mint_downstream_event_id(event_key="lane-downstream-only"),
                provider_session_id=provider_session_id,
                provider_command="memory_writer",
                provider="openrouter",
                input_tokens=4,
                output_tokens=1,
                cost_micros=900,
            )
        )
        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))
        row = summary.downstream.rows[0]
        assert row.join_state == "downstream_only"
        assert row.runtime is None
        assert row.billing_mode is None

    def test_session_unknown_downstream_record_is_excluded(self, tmp_path: Path) -> None:
        write_downstream_record(
            DownstreamRecord(
                kind="attempt",
                downstream_event_id=mint_downstream_event_id(event_key="unknown-session"),
                forge_run_id="run_unknown",
                forge_root_run_id="run_unknown",
                provider_command="memory_writer",
                provider="openrouter",
                input_tokens=11,
                output_tokens=3,
                cost_micros=2_500,
            )
        )

        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))

        assert summary.downstream.rows == []
        assert summary.downstream.downstream_records == 0
        assert summary.total_cost_micro_usd is None


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

    def test_upstream_only_supervisor_fail_open_counts(self, tmp_path: Path) -> None:
        from forge.core.telemetry.upstream import (
            UpstreamOutcome,
            write_upstream_outcome,
        )

        _write_manifest(tmp_path, "planner", decisions=[])
        write_upstream_outcome(
            UpstreamOutcome(
                command="policy-check",
                policy_id="semantic.supervisor",
                session="planner",
                status="fail_open",
                reason_code="configuration_error",
                message="Supervisor error: missing session, failing open",
                ts="2026-06-03T12:00:00Z",
            )
        )

        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))

        assert summary.policy is not None
        assert summary.policy.supervisor_allow == 1
        assert summary.policy.total_warnings == 1
        assert summary.policy.recent_warnings == ["Supervisor error: missing session, failing open"]

    def test_identical_upstream_fail_opens_count_each_occurrence(self, tmp_path: Path) -> None:
        from forge.core.telemetry.upstream import (
            UpstreamOutcome,
            write_upstream_outcome,
        )

        warning = "Supervisor error: proxy unavailable, failing open"
        _write_manifest(tmp_path, "planner", decisions=[])
        for idx in range(3):
            write_upstream_outcome(
                UpstreamOutcome(
                    command="policy-check",
                    policy_id="semantic.supervisor",
                    session="planner",
                    status="fail_open",
                    reason_code="proxy_not_found",
                    message=warning,
                    event_id=f"up_fail_open_{idx}",
                    ts=f"2026-06-03T12:00:0{idx}Z",
                )
            )

        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))

        assert summary.policy is not None
        assert summary.policy.supervisor_allow == 3
        assert summary.policy.total_warnings == 3

    def test_upstream_duplicate_of_manifest_warning_is_not_double_counted(self, tmp_path: Path) -> None:
        from forge.core.telemetry.upstream import (
            UpstreamOutcome,
            write_upstream_outcome,
        )

        warning = "Supervisor error: timed out, failing open"
        _write_manifest(tmp_path, "planner", decisions=[_decision(supervisor="allow", warnings=[warning])])
        write_upstream_outcome(
            UpstreamOutcome(
                command="policy-check",
                policy_id="semantic.supervisor",
                session="planner",
                status="timeout",
                reason_code="timeout",
                message=warning,
                ts="2026-06-03T12:00:00Z",
            )
        )

        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))

        assert summary.policy is not None
        assert summary.policy.supervisor_allow == 1
        assert summary.policy.total_warnings == 1

    def test_manifest_duplicate_suppression_preserves_upstream_siblings(self, tmp_path: Path) -> None:
        from forge.core.telemetry.upstream import (
            UpstreamOutcome,
            write_upstream_outcome,
        )

        warning = "Supervisor error: timed out, failing open"
        _write_manifest(tmp_path, "planner", decisions=[_decision(supervisor="allow", warnings=[warning])])
        for idx in range(3):
            write_upstream_outcome(
                UpstreamOutcome(
                    command="policy-check",
                    policy_id="semantic.supervisor",
                    session="planner",
                    status="timeout",
                    reason_code="timeout",
                    message=warning,
                    event_id=f"up_timeout_{idx}",
                    ts=f"2026-06-03T12:00:0{idx}Z",
                )
            )

        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))

        assert summary.policy is not None
        assert summary.policy.supervisor_allow == 3
        assert summary.policy.total_warnings == 3

    def test_upstream_plan_check_needs_review_counts(self, tmp_path: Path) -> None:
        from forge.core.telemetry.upstream import (
            UpstreamOutcome,
            write_upstream_outcome,
        )

        _write_manifest(tmp_path, "planner", decisions=[])
        write_upstream_outcome(
            UpstreamOutcome(
                command="policy-check",
                policy_id="semantic.plan_check",
                session="planner",
                status="needs_review",
                reason_code="semantic.plan_check.uncertain",
                ts="2026-06-03T12:00:00Z",
            )
        )

        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))

        assert summary.policy is not None
        assert summary.policy.plan_check_needs_review == 1


class TestPlanCheckPlane:
    """Decision-log-derived cascade tier-1 counters (cached allows included)."""

    def test_plan_check_counters(self, tmp_path: Path) -> None:
        _write_manifest(
            tmp_path,
            "planner",
            decisions=[
                _decision(plan_check="allow"),
                _decision(plan_check="allow", plan_check_cached=True),  # cached allow still counts
                _decision(plan_check="needs_review", supervisor="allow"),  # escalation, resolved
            ],
        )
        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))

        assert summary.policy is not None
        assert summary.policy.plan_check_allow == 2
        assert summary.policy.plan_check_needs_review == 1
        # The resolver's resolution counts as supervisor activity (frontier usage).
        assert summary.policy.supervisor_allow == 1

    def test_needs_review_with_deterministic_deny_skips_resolver(self, tmp_path: Path) -> None:
        """A pass-1 deny skips the resolver (engine.py): tier-1 needs_review still counts,
        supervisor counters stay zero — which is why the counter is named needs_review,
        not "escalated"."""
        entry = _decision(plan_check="needs_review")
        entry["final_decision"] = "deny"
        entry["decisions"].append(
            {
                "decision": "deny",
                "policy_id": "tdd.tests_first",
                "violations": [],
                "warnings": [],
                "cached": False,
                "evaluated_at": "2026-06-03T12:00:00Z",
            }
        )
        _write_manifest(tmp_path, "planner", decisions=[entry])
        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))

        assert summary.policy is not None
        assert summary.policy.plan_check_needs_review == 1
        assert summary.policy.supervisor_allow == 0
        assert summary.policy.supervisor_warn == 0
        assert summary.policy.supervisor_deny == 0

    def test_plan_check_only_session_has_content(self, tmp_path: Path) -> None:
        """All-short-circuit sessions still surface policy activity (no phantom None)."""
        _write_manifest(tmp_path, "planner", decisions=[_decision(plan_check="allow")])
        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))

        assert summary.policy is not None
        assert summary.policy.has_content
        assert summary.policy.plan_check_allow == 1
        assert summary.policy.supervisor_allow == 0

    def test_plan_check_does_not_pollute_supervisor_warnings(self, tmp_path: Path) -> None:
        _write_manifest(
            tmp_path,
            "planner",
            decisions=[_decision(plan_check="needs_review", supervisor="allow")],
        )
        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))

        assert summary.policy is not None
        assert summary.policy.total_warnings == 0
        assert summary.policy.recent_warnings == []


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
        # Nothing happened -> nothing to be partial about (was unconditionally True).
        assert summary.session_tagging_partial is False

    def test_session_tagging_partial_true_when_active(self) -> None:
        log_usage_event(_event(command="supervisor"))
        summary = build_session_activity_summary("planner", forge_root=None)
        assert summary.session_tagging_partial is True

    def test_measured_zero_total_cost_is_zero_not_none(self) -> None:
        # A measured 0 is distinct from "unmeasured" (None): keep it 0 so the view
        # reports "$0.00", not "n/a".
        log_usage_event(_event(cost_micro_usd=0))
        summary = build_session_activity_summary("planner", forge_root=None)
        assert summary.total_cost_micro_usd == 0
        assert summary.cost_partial is False


class TestFailureKind:
    def test_failure_kind_mapping(self) -> None:
        from forge.core.ops.usage_summary import _failure_kind

        assert _failure_kind("timeout") == "timeout"
        for ft in ("subprocess_error", "exit_1", "runtime_reported_error", None):
            assert _failure_kind(ft) == "error"

    def test_format_failing_open(self) -> None:
        from forge.core.ops.usage_summary import format_failing_open

        assert format_failing_open(None) is None
        # errors but no kinds (hand-built) -> None, so callers fall back to the count.
        assert format_failing_open(CommandUsage(command="supervisor", errors=3)) is None
        cu = CommandUsage(command="supervisor", errors=3, error_kinds={"timeout": 2, "error": 1})
        assert format_failing_open(cu) == "failing open: 2 timeout, 1 error"
        # timeout-first ordering, only non-zero kinds.
        assert format_failing_open(CommandUsage(command="supervisor", errors=2, error_kinds={"error": 2})) == (
            "failing open: 2 error"
        )
        # A non-empty but all-zero error_kinds yields None, not a content-less "failing
        # open: " -- the value count, not the dict's presence, decides (guards both render
        # surfaces; unreachable from ledger data, which only ever increments).
        assert format_failing_open(CommandUsage(command="supervisor", errors=0, error_kinds={"timeout": 0})) is None


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
        assert "~$0.04" in line
        assert " est" not in line  # the stale ' est' suffix was dropped (Phase 6 label honesty)
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

    def test_failing_open_breakdown_with_policy(self) -> None:
        # Real (kind-bearing) data renders the per-kind fail-open clause inside the
        # decision-log checks segment.
        summary = SessionActivitySummary(
            session="planner",
            commands=[CommandUsage(command="supervisor", calls=24, errors=24, error_kinds={"timeout": 24})],
            policy=PolicyActivity(supervisor_allow=24),
        )
        line = render_summary_line(summary)
        assert line is not None
        assert "supervisor: 24 checks (0 warn, 0 block, failing open: 24 timeout)" in line

    def test_failing_open_breakdown_without_policy(self) -> None:
        summary = SessionActivitySummary(
            session="planner",
            commands=[CommandUsage(command="supervisor", calls=3, errors=3, error_kinds={"timeout": 2, "error": 1})],
        )
        line = render_summary_line(summary)
        assert line is not None
        assert "supervisor: 3 runs (failing open: 2 timeout, 1 error)" in line

    def test_errors_only_falls_back_to_count(self) -> None:
        # error_kinds empty (hand-built/legacy summary) -> plain "N errors" is preserved,
        # never silently dropped, and no fabricated "failing open" clause.
        summary = SessionActivitySummary(
            session="planner",
            commands=[CommandUsage(command="supervisor", calls=5, errors=5)],
            policy=PolicyActivity(supervisor_allow=5),
        )
        line = render_summary_line(summary)
        assert line is not None
        assert "5 errors" in line
        assert "failing open" not in line

    def test_capped_log_marks_checks_as_floor(self) -> None:
        # Capped decision log (checks) vs uncapped ledger (errors): the "+" keeps
        # "100+ checks (... 120 errors)" from reading as a contradiction.
        summary = SessionActivitySummary(
            session="planner",
            commands=[CommandUsage(command="supervisor", calls=100, errors=120)],
            policy=PolicyActivity(supervisor_allow=100, log_capped=True),
        )
        line = render_summary_line(summary)
        assert line is not None
        assert "supervisor: 100+ checks" in line
        assert "120 errors" in line

    def test_uncapped_log_has_no_plus(self) -> None:
        summary = SessionActivitySummary(
            session="planner",
            policy=PolicyActivity(supervisor_allow=3, log_capped=False),
        )
        line = render_summary_line(summary)
        assert line is not None
        assert "supervisor: 3 checks" in line
        assert "3+ checks" not in line

    def test_plan_check_only_skips_supervisor_segment(self) -> None:
        """All-short-circuit cascade session: plan-check segment, no 'supervisor: 0 checks'."""
        summary = SessionActivitySummary(
            session="planner",
            policy=PolicyActivity(plan_check_allow=3, plan_check_needs_review=0),
        )
        line = render_summary_line(summary)
        assert line is not None
        assert "plan-check: 3 allow, 0 needs-review" in line
        assert "supervisor:" not in line

    def test_plan_check_and_supervisor_segments(self) -> None:
        summary = SessionActivitySummary(
            session="planner",
            policy=PolicyActivity(plan_check_allow=8, plan_check_needs_review=2, supervisor_allow=2),
        )
        line = render_summary_line(summary)
        assert line is not None
        assert "plan-check: 8 allow, 2 needs-review" in line
        assert "supervisor: 2 checks" in line

    def test_measured_zero_cost_renders(self) -> None:
        # total_cost_micro_usd == 0 is measured-zero, not unmeasured: it should print.
        summary = SessionActivitySummary(
            session="planner",
            commands=[CommandUsage(command="supervisor", calls=1)],
            total_cost_micro_usd=0,
        )
        line = render_summary_line(summary)
        assert line is not None
        assert "~$0.00" in line

    def test_exact_cost_renders_without_tilde(self) -> None:
        # cost_estimated=False (4g cost-plane-exact total) -> the `~` marker is dropped.
        summary = SessionActivitySummary(
            session="planner",
            commands=[CommandUsage(command="memory-writer", calls=1)],
            total_cost_micro_usd=40_000,
            cost_estimated=False,
        )
        line = render_summary_line(summary)
        assert line is not None
        assert "$0.04" in line
        assert "~$0.04" not in line


class TestSumForgeAddedCost:
    """`sum_forge_added_cost` -- the `forge +$Y` aggregator. "Forge-added" =
    reported LLM cost for the session EXCLUDING the main interactive harness."""

    def test_sums_reported_claude_p_cost(self) -> None:
        log_usage_event(
            _event(
                command="memory-writer",
                route="claude_p",
                reporter="claude_code",
                confidence="reported",
                cost_micro_usd=30_000,
            )
        )
        log_usage_event(
            _event(
                command="supervisor",
                route="claude_p",
                reporter="forge_proxy",
                confidence="reported",
                cost_micro_usd=20_000,
            )
        )
        assert sum_forge_added_cost("planner") == 50_000

    def test_excludes_main_interactive_harness(self) -> None:
        # Load-bearing: the card forbids blending observed main-harness traffic into
        # "Forge additional cost". A claude_interactive event must NOT be summed,
        # even when it carries a reported cost.
        log_usage_event(
            _event(
                command="memory-writer",
                route="claude_p",
                reporter="claude_code",
                confidence="reported",
                cost_micro_usd=30_000,
            )
        )
        log_usage_event(
            _event(
                command="interactive",
                route="claude_interactive",
                reporter="claude_code",
                confidence="reported",
                cost_micro_usd=500_000,
            )
        )
        assert sum_forge_added_cost("planner") == 30_000  # harness 500_000 excluded

    def test_unavailable_rows_contribute_nothing(self) -> None:
        log_usage_event(
            _event(
                command="memory-writer",
                route="claude_p",
                reporter="claude_code",
                confidence="reported",
                cost_micro_usd=12_000,
            )
        )
        log_usage_event(_event(command="supervisor", route="claude_p", confidence="unavailable", cost_micro_usd=None))
        assert sum_forge_added_cost("planner") == 12_000

    def test_no_reported_cost_returns_none_not_zero(self) -> None:
        # No reported-cost event -> None (no cost evidence), distinct from a real $0.
        log_usage_event(_event(command="supervisor", route="claude_p", confidence="unavailable", cost_micro_usd=None))
        assert sum_forge_added_cost("planner") is None

    def test_empty_ledger_returns_none(self) -> None:
        assert sum_forge_added_cost("planner") is None

    def test_since_bounds_the_scan(self) -> None:
        # `since` filters the ledger by event ts so the status-line poll need not
        # re-parse the whole ledger: an event before `since` is excluded; one at/after
        # is summed. The bound is the ONLY difference from an unbounded scan.
        log_usage_event(
            _event(
                command="memory-writer",
                route="claude_p",
                reporter="claude_code",
                confidence="reported",
                cost_micro_usd=10_000,
                ts="2026-06-01T00:00:00+00:00",
            )
        )
        log_usage_event(
            _event(
                command="supervisor",
                route="claude_p",
                reporter="claude_code",
                confidence="reported",
                cost_micro_usd=40_000,
                ts="2026-06-05T00:00:00+00:00",
            )
        )
        since = datetime(2026, 6, 3, tzinfo=timezone.utc)
        assert sum_forge_added_cost("planner", since=since) == 40_000  # 06-01 event excluded
        assert sum_forge_added_cost("planner") == 50_000  # unbounded sums both

    def test_other_sessions_excluded(self) -> None:
        log_usage_event(
            _event(
                session="planner",
                route="claude_p",
                reporter="claude_code",
                confidence="reported",
                cost_micro_usd=10_000,
            )
        )
        log_usage_event(
            _event(
                session="other", route="claude_p", reporter="claude_code", confidence="reported", cost_micro_usd=99_000
            )
        )
        assert sum_forge_added_cost("planner") == 10_000

    def test_includes_gateway_calculated_cost(self) -> None:
        # A gateway-computed figure (e.g. LiteLLM's x-litellm-response-cost) is
        # trustworthy enough to count toward Forge-added spend, like a directly-
        # reported one. Pins the predicate so `forge +$Y` and `forge telemetry activity` agree.
        log_usage_event(
            _event(
                command="panel",
                route="claude_p",
                reporter="litellm",
                confidence="gateway_calculated",
                cost_micro_usd=40_000,
            )
        )
        assert sum_forge_added_cost("planner") == 40_000

    def test_excludes_inferred_and_unknown_cost(self) -> None:
        # Estimates (`inferred`) and un-provenanced (`unknown`) cost never contribute,
        # even with a dollar figure present -- the north star: never sum an estimate.
        log_usage_event(_event(command="panel", route="claude_p", confidence="inferred", cost_micro_usd=70_000))
        log_usage_event(_event(command="panel", route="claude_p", confidence="unknown", cost_micro_usd=80_000))
        assert sum_forge_added_cost("planner") is None


def _cost_record(*, root: str, run: str | None = None, cost_micros: int | None, **overrides: object) -> None:
    """Write one proxy cost record (4g run-tree-stamped) into the isolated FORGE_HOME."""
    from forge.proxy.cost_logger import log_request_cost

    kwargs: dict[str, object] = {
        "proxy_id": "p1",
        "model": "gpt-5.5",
        "tier": "sonnet",
        "input_tokens": 10,
        "output_tokens": 5,
        "cached_tokens": 0,
        "cost_micros": cost_micros,
        "latency_ms": 1.0,
        "failed": False,
        "request_id": "req_" + (run or root),
        "reporter": "openrouter" if cost_micros is not None else None,
        "confidence": "reported" if cost_micros is not None else "unavailable",
        "forge_run_id": run if run is not None else root,
        "forge_root_run_id": root,
    }
    kwargs.update(overrides)
    log_request_cost(**kwargs)  # type: ignore[arg-type]


class TestRootJoin4g:
    """Slice 4g: proxied ``claude -p`` cost comes from the cost plane (exact, by
    ``forge_root_run_id``), superseding the concurrency-fragile verb snapshot."""

    def test_exact_supersedes_snapshot(self) -> None:
        # A proxied verb event carries a SNAPSHOT estimate; the cost plane has the exact
        # per-request cost under the same run tree -> exact wins, snapshot suppressed.
        log_usage_event(
            _event(
                command="memory-writer",
                run_id="run_mw",
                root_run_id="run_mw",
                route="claude_p",
                reporter="forge_proxy",
                confidence="reported",
                measurement_source="verb_snapshot_estimated",
                cost_micro_usd=999_000,  # the (wrong) snapshot estimate
            )
        )
        _cost_record(root="run_mw", cost_micros=120_000)
        _cost_record(root="run_mw", run="run_mw", cost_micros=80_000)
        # 120k + 80k exact, NOT the 999k snapshot.
        assert sum_forge_added_cost("planner") == 200_000

    def test_fanout_no_double_count(self) -> None:
        # A 4-worker panel: ONE verb-aggregate snapshot event (ambient run) + 4 worker
        # leaf events (null cost), all sharing one root. Cost records carry the WORKER
        # run ids. Session cost = sum of the 4 worker records, counted ONCE.
        root = "run_root"
        log_usage_event(
            _event(
                command="panel",
                run_id="run_root",
                root_run_id=root,
                route="claude_p",
                reporter="forge_proxy",
                confidence="reported",
                measurement_source="verb_snapshot_estimated",
                cost_micro_usd=500_000,  # the aggregate snapshot -- must be suppressed
            )
        )
        for i in range(4):
            log_usage_event(
                _event(
                    command="panel",
                    run_id=f"run_w{i}",
                    parent_run_id=root,
                    root_run_id=root,
                    route="claude_p",
                    attribution_granularity="worker",
                    measurement_source="unattributed",
                    confidence="unavailable",
                    cost_micro_usd=None,
                )
            )
            _cost_record(root=root, run=f"run_w{i}", cost_micros=25_000)
        assert sum_forge_added_cost("planner") == 100_000  # 4 x 25k once, not + 500k snapshot

    def test_no_cost_route_unavailable_not_zero(self) -> None:
        # Proxied run whose route reported NO price (anthropic-passthrough): records
        # exist (suppress the snapshot) but no dollars -> total None (unavailable, NOT
        # $0 and NOT the 42k snapshot). With no figure shown at all, cost_partial stays
        # False -- the None itself conveys "unavailable".
        log_usage_event(
            _event(
                command="supervisor",
                run_id="run_sup",
                root_run_id="run_sup",
                route="claude_p",
                measurement_source="verb_snapshot_estimated",
                confidence="reported",
                cost_micro_usd=42_000,  # snapshot -- suppressed because records exist
            )
        )
        _cost_record(root="run_sup", cost_micros=None)  # passthrough: tokens, no dollars
        assert sum_forge_added_cost("planner") is None  # not $0, not the 42k snapshot
        summary = build_session_activity_summary("planner", None)
        assert summary.total_cost_micro_usd is None
        assert summary.cost_partial is False

    def test_mixed_exact_and_no_cost_route_is_partial(self) -> None:
        # One run reports exact dollars, another (passthrough) reports none -> the shown
        # total is real but incomplete: cost_partial True.
        log_usage_event(_event(command="memory-writer", run_id="run_a", root_run_id="run_a", route="claude_p"))
        log_usage_event(_event(command="supervisor", run_id="run_b", root_run_id="run_b", route="claude_p"))
        _cost_record(root="run_a", cost_micros=70_000)  # reported
        _cost_record(root="run_b", cost_micros=None)  # passthrough, no dollars
        summary = build_session_activity_summary("planner", None)
        assert summary.total_cost_micro_usd == 70_000
        assert summary.cost_partial is True

    def test_orphan_cancelled_leaf_captured_by_root(self) -> None:
        # A cancelled worker made a request (cost record under the root) but emitted NO
        # ledger event. The root-join still captures it via forge_root_run_id.
        root = "run_root"
        log_usage_event(_event(command="panel", run_id=root, root_run_id=root, route="claude_p", cost_micro_usd=None))
        _cost_record(root=root, run="run_emitted", cost_micros=30_000)
        _cost_record(root=root, run="run_cancelled_orphan", cost_micros=20_000)  # no ledger event
        assert sum_forge_added_cost("planner") == 50_000

    def test_interactive_isolated_from_forge_added(self) -> None:
        # The interactive harness shares the proxy but never gets the header, so its
        # cost records carry no forge_root_run_id. Only the headless run is summed.
        log_usage_event(
            _event(
                command="memory-writer",
                run_id="run_hl",
                root_run_id="run_hl",
                route="claude_p",
                measurement_source="verb_snapshot_estimated",
                confidence="reported",
                cost_micro_usd=1,
            )
        )
        _cost_record(root="run_hl", cost_micros=15_000)  # headless, stamped
        # interactive harness traffic: no forge_root_run_id on its records (not stamped)
        _cost_record(root="run_hl", run="run_hl", cost_micros=0, forge_root_run_id=None, forge_run_id=None)
        assert sum_forge_added_cost("planner") == 15_000

    def test_direct_runtime_native_kept_alongside_proxied(self) -> None:
        # A session with BOTH a proxied run (cost plane) and a direct runtime_native run
        # (self-reported, no cost record): both contribute, neither double-counted.
        log_usage_event(
            _event(
                command="memory-writer",
                run_id="run_px",
                root_run_id="run_px",
                route="claude_p",
                measurement_source="verb_snapshot_estimated",
                confidence="reported",
                cost_micro_usd=999_000,  # snapshot -- superseded
            )
        )
        _cost_record(root="run_px", cost_micros=60_000)
        log_usage_event(
            _event(
                command="supervisor",
                run_id="run_dir",
                root_run_id="run_dir",
                route="claude_p",
                measurement_source="runtime_native",
                reporter="claude_code",
                confidence="reported",
                cost_micro_usd=40_000,  # direct self-report, no cost record
            )
        )
        assert sum_forge_added_cost("planner") == 100_000  # 60k exact + 40k direct

    def test_pre_4g_snapshot_still_counts(self) -> None:
        # A pre-4g proxied session: snapshot event, but NO cost records carry its root.
        # Nothing to supersede -> the snapshot estimate is kept (graceful fallback).
        log_usage_event(
            _event(
                command="memory-writer",
                run_id="run_old",
                root_run_id="run_old",
                route="claude_p",
                measurement_source="verb_snapshot_estimated",
                confidence="reported",
                cost_micro_usd=33_000,
            )
        )
        assert sum_forge_added_cost("planner") == 33_000

    def test_exact_proxied_cost_is_not_estimated(self) -> None:
        # A fully cost-plane-exact session: the snapshot is superseded by the exact
        # record, so the figure is exact (4g proxy_request_exact) -> NO `~` marker.
        log_usage_event(
            _event(
                command="memory-writer",
                run_id="run_mw",
                root_run_id="run_mw",
                route="claude_p",
                measurement_source="verb_snapshot_estimated",
                confidence="reported",
                cost_micro_usd=999_000,  # snapshot -- superseded by the exact record
            )
        )
        _cost_record(root="run_mw", run="run_mw", cost_micros=120_000)
        summary = build_session_activity_summary("planner", None)
        assert summary.total_cost_micro_usd == 120_000
        assert summary.cost_estimated is False  # exact -> rendered without `~`
        assert summary.cost_partial is False
        mw = next(c for c in summary.commands if c.command == "memory-writer")
        assert mw.cost_micro_usd == 120_000
        assert mw.cost_estimated is False

    def test_exact_plus_snapshot_residual_is_estimated(self) -> None:
        # Exact proxied run + a pre-4g run whose snapshot has no records to supersede it:
        # the total mixes exact dollars with an estimate -> cost_estimated True (`~`).
        log_usage_event(_event(command="memory-writer", run_id="run_px", root_run_id="run_px", route="claude_p"))
        _cost_record(root="run_px", run="run_px", cost_micros=60_000)  # exact
        log_usage_event(
            _event(
                command="supervisor",
                run_id="run_old",
                root_run_id="run_old",
                route="claude_p",
                measurement_source="verb_snapshot_estimated",  # no records -> kept as estimate
                confidence="reported",
                cost_micro_usd=40_000,
            )
        )
        summary = build_session_activity_summary("planner", None)
        assert summary.total_cost_micro_usd == 100_000
        assert summary.cost_estimated is True  # exact + snapshot -> approximate
        sup = next(c for c in summary.commands if c.command == "supervisor")
        assert sup.cost_estimated is True
        mw = next(c for c in summary.commands if c.command == "memory-writer")
        assert mw.cost_estimated is False  # the exact half stays clean per-command


# --- Shadow sampling (Slice 3 read surface) ---------------------------------


def _shadow_dir(forge_root: Path, session: str = "planner") -> Path:
    return forge_root / ".forge" / "artifacts" / session / "shadow"


def _write_shadow(
    forge_root: Path,
    cand_hash: str,
    *,
    session: str = "planner",
    suffix: str = ".done",
    status: str | None = None,
    captured_at: str = "2026-06-03T12:00:00Z",
    frontier_verdict: str | None = None,
    frontier_confidence: float | None = None,
    target_path: str = "src/foo.py",
) -> Path:
    d = _shadow_dir(forge_root, session)
    d.mkdir(parents=True, exist_ok=True)
    record: dict = {
        "schema_version": 1,
        "captured_at": captured_at,
        "tool_name": "Write",
        "target_path": target_path,
    }
    if status is not None:
        record["status"] = status
        record["checked_at"] = "2026-06-03T12:05:00Z"
    if frontier_verdict is not None:
        record["frontier_verdict"] = frontier_verdict
    if frontier_confidence is not None:
        record["frontier_confidence"] = frontier_confidence
    path = d / f"{cand_hash}{suffix}"
    path.write_text(json.dumps(record))
    return path


class TestShadowActivity:
    def test_no_dir_yields_none(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "planner", decisions=[])
        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))
        assert summary.shadow is None

    def test_counts_done_status_breakdown(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "planner", decisions=[])
        _write_shadow(tmp_path, "a1", status="agree")
        _write_shadow(tmp_path, "a2", status="agree")
        _write_shadow(tmp_path, "d1", status="disagree", frontier_verdict="divergent")
        _write_shadow(tmp_path, "i1", status="inconclusive")
        _write_shadow(tmp_path, "e1", status="error")
        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))
        sh = summary.shadow
        assert sh is not None
        assert sh.checked == 5
        assert (sh.agree, sh.disagree, sh.inconclusive, sh.error) == (2, 1, 1, 1)
        assert sh.pending == 0

    def test_pending_counts_json_and_processing(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "planner", decisions=[])
        _write_shadow(tmp_path, "p1", suffix=".json")
        _write_shadow(tmp_path, "p2", suffix=".processing")
        _write_shadow(tmp_path, "done1", status="agree")
        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))
        sh = summary.shadow
        assert sh is not None
        assert sh.pending == 2
        assert sh.checked == 1

    def test_plan_md_sidecar_ignored(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "planner", decisions=[])
        _write_shadow(tmp_path, "x1", status="agree")
        (_shadow_dir(tmp_path) / "x1.plan.md").write_text("# plan")
        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))
        assert summary.shadow is not None
        assert summary.shadow.checked == 1  # sidecar not counted

    def test_since_window_filters_by_captured_at(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "planner", decisions=[])
        _write_shadow(tmp_path, "old", status="disagree", captured_at="2026-06-01T00:00:00Z")
        _write_shadow(tmp_path, "new", status="agree", captured_at="2026-06-10T00:00:00Z")
        since = datetime(2026, 6, 5, tzinfo=timezone.utc)
        summary = build_session_activity_summary("planner", forge_root=str(tmp_path), since=since)
        sh = summary.shadow
        assert sh is not None
        assert sh.checked == 1 and sh.agree == 1 and sh.disagree == 0

    def test_unknown_status_counts_as_error(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "planner", decisions=[])
        _write_shadow(tmp_path, "weird", status="bogus")
        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))
        assert summary.shadow is not None
        assert summary.shadow.error == 1

    def test_shadow_only_session_not_empty(self, tmp_path: Path) -> None:
        # No ledger, no decisions, no subagents -- only a pending shadow candidate.
        _write_manifest(tmp_path, "planner", decisions=[])
        _write_shadow(tmp_path, "p1", suffix=".json")
        summary = build_session_activity_summary("planner", forge_root=str(tmp_path))
        assert summary.is_empty is False

    def test_render_summary_line_audited_segment(self) -> None:
        from forge.core.ops.usage_summary import ShadowActivity

        summary = SessionActivitySummary(session="planner")
        summary.shadow = ShadowActivity(checked=8, agree=5, disagree=2, inconclusive=1, error=0)
        line = render_summary_line(summary)
        assert line is not None
        assert "shadow: 8 audited (2 disagree)" in line

    def test_render_summary_line_queued_segment(self) -> None:
        from forge.core.ops.usage_summary import ShadowActivity

        summary = SessionActivitySummary(session="planner")
        summary.shadow = ShadowActivity(pending=4)
        line = render_summary_line(summary)
        assert line is not None
        assert "shadow: 4 queued" in line


class TestReadSupervisorHealth:
    """`read_supervisor_health` reads the newest-first contiguous fail-open run from the
    usage ledger (`command="supervisor"` only)."""

    def test_consecutive_timeouts_counted(self) -> None:
        for i in (1, 2, 3):
            log_usage_event(_event(status="timeout", failure_type="timeout", ts=f"2026-06-16T12:00:0{i}Z"))
        health = read_supervisor_health("planner")
        assert health.recent_failures == 3
        assert health.last_kind == "timeout"
        assert health.last_seen_at == "2026-06-16T12:00:03Z"  # newest failure's ts

    def test_success_resets_streak(self) -> None:
        for i in (1, 2, 3):
            log_usage_event(_event(status="timeout", failure_type="timeout", ts=f"2026-06-16T12:00:0{i}Z"))
        log_usage_event(_event(status="success", ts="2026-06-16T12:00:04Z"))  # newest
        assert read_supervisor_health("planner") == SupervisorHealth()

    def test_only_newest_contiguous_failures_count(self) -> None:
        log_usage_event(_event(status="success", ts="2026-06-16T12:00:01Z"))  # older success
        log_usage_event(_event(status="timeout", failure_type="timeout", ts="2026-06-16T12:00:02Z"))
        log_usage_event(_event(status="timeout", failure_type="timeout", ts="2026-06-16T12:00:03Z"))
        # Streak starts at the newest event and breaks at the older success.
        assert read_supervisor_health("planner").recent_failures == 2

    def test_subprocess_error_maps_to_error_kind(self) -> None:
        log_usage_event(_event(status="error", failure_type="subprocess_error", ts="2026-06-16T12:00:01Z"))
        health = read_supervisor_health("planner")
        assert health.recent_failures == 1
        assert health.last_kind == "error"  # everything that is not failure_type="timeout"

    def test_upstream_fail_open_without_usage_event_counts(self) -> None:
        from forge.core.telemetry.upstream import (
            UpstreamOutcome,
            write_upstream_outcome,
        )

        write_upstream_outcome(
            UpstreamOutcome(
                command="policy-check",
                policy_id="semantic.supervisor",
                session="planner",
                status="fail_open",
                reason_code="proxy_not_found",
                ts="2026-06-16T12:00:01Z",
            )
        )
        health = read_supervisor_health("planner")
        assert health.recent_failures == 1
        assert health.last_kind == "error"
        assert health.last_seen_at == "2026-06-16T12:00:01Z"

    def test_upstream_skipped_counts_as_fail_open(self) -> None:
        from forge.core.telemetry.upstream import (
            UpstreamOutcome,
            write_upstream_outcome,
        )

        write_upstream_outcome(
            UpstreamOutcome(
                command="policy-check",
                policy_id="semantic.supervisor",
                session="planner",
                status="skipped",
                reason_code="skipped",
                ts="2026-06-16T12:00:01Z",
            )
        )

        health = read_supervisor_health("planner")
        assert health.recent_failures == 1
        assert health.last_kind == "error"

    def test_legacy_and_upstream_same_run_dedupes(self) -> None:
        from forge.core.telemetry.upstream import (
            UpstreamOutcome,
            write_upstream_outcome,
        )

        log_usage_event(
            _event(
                status="timeout",
                failure_type="timeout",
                run_id="run_supervisor_child",
                ts="2026-06-16T12:00:01Z",
            )
        )
        write_upstream_outcome(
            UpstreamOutcome(
                command="policy-check",
                policy_id="semantic.supervisor",
                session="planner",
                status="timeout",
                reason_code="timeout",
                run_id="run_supervisor_child",
                ts="2026-06-16T12:00:02Z",
            )
        )

        health = read_supervisor_health("planner")
        assert health.recent_failures == 1
        assert health.last_kind == "timeout"

    def test_upstream_fail_open_wins_over_legacy_success_for_same_run(self) -> None:
        from forge.core.telemetry.upstream import (
            UpstreamOutcome,
            write_upstream_outcome,
        )

        log_usage_event(
            _event(
                status="success",
                run_id="run_parse_failure",
                root_run_id="root_run",
                ts="2026-06-16T12:00:01Z",
            )
        )
        write_upstream_outcome(
            UpstreamOutcome(
                command="policy-check",
                policy_id="semantic.supervisor",
                session="planner",
                status="fail_open",
                reason_code="parse_failure",
                run_id="run_parse_failure",
                root_run_id="root_run",
                ts="2026-06-16T12:00:01Z",
            )
        )

        health = read_supervisor_health("planner")
        assert health.recent_failures == 1
        assert health.last_kind == "error"
        assert health.last_seen_at == "2026-06-16T12:00:01Z"

    def test_excludes_shadow_command(self) -> None:
        for i in (1, 2):
            log_usage_event(
                _event(
                    command="supervisor-shadow", status="timeout", failure_type="timeout", ts=f"2026-06-16T12:00:0{i}Z"
                )
            )
        # Frontier-only: command="supervisor" exact-match excludes supervisor-shadow.
        assert read_supervisor_health("planner") == SupervisorHealth()

    def test_excludes_plan_check_command(self) -> None:
        for i in (1, 2):
            log_usage_event(
                _event(command="plan-check", status="timeout", failure_type="timeout", ts=f"2026-06-16T12:00:0{i}Z")
            )
        # Frontier-only: the checklist invariant excludes the tier-1 cascade checker too,
        # not only supervisor-shadow. Guards the second MUST-NOT clause against a future
        # filter that loosens read_usage_events's exact command match.
        assert read_supervisor_health("planner") == SupervisorHealth()

    def test_no_events_is_empty(self) -> None:
        assert read_supervisor_health("planner") == SupervisorHealth()

    def test_since_bound_excludes_older_events(self) -> None:
        log_usage_event(_event(status="timeout", failure_type="timeout", ts="2026-06-15T00:00:00Z"))
        since = datetime(2026, 6, 16, tzinfo=timezone.utc)
        assert read_supervisor_health("planner", since=since) == SupervisorHealth()

    def test_malformed_ledger_yields_empty_health_without_raising(self) -> None:
        # read_usage_events skips malformed lines -> empty health, NEVER raises. This is
        # distinct from the throttle's compute-raises -> None fail-open path.
        events_dir = get_forge_home() / "usage" / "events"
        events_dir.mkdir(parents=True, exist_ok=True)
        (events_dir / "2026-06_bad.jsonl").write_text("{ not valid json\n")
        assert read_supervisor_health("planner") == SupervisorHealth()

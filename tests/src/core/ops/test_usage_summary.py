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
    sum_forge_added_cost,
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
        assert summary.policy.plan_check_escalated == 1
        # The resolver's resolution counts as supervisor activity (frontier usage).
        assert summary.policy.supervisor_allow == 1

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
            policy=PolicyActivity(plan_check_allow=3, plan_check_escalated=0),
        )
        line = render_summary_line(summary)
        assert line is not None
        assert "plan-check: 3 allow, 0 escalated" in line
        assert "supervisor:" not in line

    def test_plan_check_and_supervisor_segments(self) -> None:
        summary = SessionActivitySummary(
            session="planner",
            policy=PolicyActivity(plan_check_allow=8, plan_check_escalated=2, supervisor_allow=2),
        )
        line = render_summary_line(summary)
        assert line is not None
        assert "plan-check: 8 allow, 2 escalated" in line
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
        # reported one. Pins the predicate so `forge +$Y` and `forge activity` agree.
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

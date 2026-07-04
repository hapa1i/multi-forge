"""Tests for ``forge telemetry activity``.

Session resolution is exercised by ``test_session_context``; here we monkeypatch the
resolver so the tests focus on the command's rendering / JSON contract / error tip.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone, tzinfo

from click.testing import CliRunner

from forge.cli import activity as activity_module
from forge.cli.main import main
from forge.core.telemetry.downstream import (
    DownstreamRecord,
    mint_downstream_event_id,
    write_downstream_record,
)
from forge.core.telemetry.upstream import UpstreamOutcome, write_upstream_outcome
from forge.core.usage.ledger import UsageEvent, log_usage_event


def _activity_args(*args: str) -> list[str]:
    return ["telemetry", "activity", *args]


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


def _patch_resolver(monkeypatch, name: str = "planner", forge_root: str | None = None) -> None:
    monkeypatch.setattr(
        "forge.cli.activity.resolve_session_identifier",
        lambda _s=None: (name, forge_root),
    )


def test_not_found_prints_tip_and_exits_1(monkeypatch) -> None:
    from forge.core.ops.session_context import SessionContextError

    def _raise(_s=None):  # noqa: ANN001
        raise SessionContextError("No session 'ghost' found")

    monkeypatch.setattr("forge.cli.activity.resolve_session_identifier", _raise)
    result = CliRunner().invoke(main, _activity_args("ghost"))
    assert result.exit_code == 1
    assert "forge session list" in result.output


def test_not_found_json(monkeypatch) -> None:
    from forge.core.ops.session_context import SessionContextError

    def _raise(_s=None):  # noqa: ANN001
        raise SessionContextError("nope")

    monkeypatch.setattr("forge.cli.activity.resolve_session_identifier", _raise)
    result = CliRunner().invoke(main, _activity_args("ghost", "--json"))
    assert result.exit_code == 1
    assert result.stdout == ""
    payload = json.loads(result.stderr)
    assert payload["error"] == "nope"
    assert "forge session list" in payload["tip"]


def test_help_shows_period_clean_break() -> None:
    result = CliRunner().invoke(main, _activity_args("--help"))
    assert result.exit_code == 0
    assert "--period" in result.output
    assert "today" in result.output
    assert "week" in result.output
    assert "month" in result.output
    assert "all" in result.output
    assert "--days" not in result.output
    assert "--all" not in result.output


def test_period_start_uses_local_calendar_boundaries(monkeypatch) -> None:
    fixed_local = datetime(2026, 7, 3, 15, 30, tzinfo=timezone(timedelta(hours=-4)))

    class FrozenDateTime:
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            if tz is None:
                return fixed_local
            return fixed_local.astimezone(tz)

    monkeypatch.setattr(activity_module, "datetime", FrozenDateTime)

    assert activity_module._period_start("all") is None
    assert activity_module._period_start("today") == datetime(2026, 7, 3, 4, tzinfo=timezone.utc)
    assert activity_module._period_start("week") == datetime(2026, 6, 29, 4, tzinfo=timezone.utc)
    assert activity_module._period_start("month") == datetime(2026, 7, 1, 4, tzinfo=timezone.utc)


def test_old_days_flag_is_clean_break() -> None:
    result = CliRunner().invoke(main, _activity_args("planner", "--days", "7"))
    assert result.exit_code == 2
    assert "No such option" in result.output
    assert "--days" in result.output


def test_old_all_flag_is_clean_break() -> None:
    result = CliRunner().invoke(main, _activity_args("planner", "--all"))
    assert result.exit_code == 2
    assert "No such option" in result.output
    assert "--all" in result.output


def test_human_render_shows_supervisor(monkeypatch) -> None:
    _patch_resolver(monkeypatch)
    log_usage_event(_event(status="success"))
    log_usage_event(_event(status="error"))
    result = CliRunner().invoke(main, _activity_args("planner", "--period", "all"))
    assert result.exit_code == 0
    assert "Forge activity" in result.output
    assert "planner" in result.output
    assert "supervisor" in result.output


def test_json_shape(monkeypatch) -> None:
    _patch_resolver(monkeypatch)
    log_usage_event(_event(command="supervisor", status="error"))
    result = CliRunner().invoke(main, _activity_args("planner", "--period", "all", "--json"))
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["session"] == "planner"
    assert set(data) == {"session", "since", "upstream", "downstream", "shadow", "subagents", "notes"}
    assert "session_tagging_partial" in data["notes"]
    rows = {c["command"]: c for c in data["downstream"]["rows"]}
    assert rows["supervisor"]["calls"] == 1
    assert rows["supervisor"]["errors"] == 1


def test_json_carries_runtime_and_billing(monkeypatch) -> None:
    """T5/WS3: --json exposes the per-row runtime/billing_mode lane fields."""
    _patch_resolver(monkeypatch)
    log_usage_event(_event(command="supervisor", runtime="codex", billing_mode="subscription_quota"))
    result = CliRunner().invoke(main, _activity_args("planner", "--period", "all", "--json"))
    assert result.exit_code == 0
    rows = {c["command"]: c for c in json.loads(result.output)["downstream"]["rows"]}
    assert rows["supervisor"]["runtime"] == "codex"
    assert rows["supervisor"]["billing_mode"] == "subscription_quota"


def test_human_render_shows_runtime_billing(monkeypatch) -> None:
    """T5/WS3: the human table has a Runtime/Billing column showing the resolved lane."""
    monkeypatch.setenv("COLUMNS", "200")  # widen so Rich does not truncate the lane cell
    _patch_resolver(monkeypatch)
    log_usage_event(_event(command="supervisor", runtime="codex", billing_mode="subscription_quota"))
    result = CliRunner().invoke(main, _activity_args("planner", "--period", "all"))
    assert result.exit_code == 0
    assert "Runtime/Billing" in result.output
    assert "codex/subscription_quota" in result.output


def test_two_pane_join_renders_upstream_and_downstream(monkeypatch) -> None:
    _patch_resolver(monkeypatch)
    write_upstream_outcome(
        UpstreamOutcome(
            command="memory-writer",
            operation="memory_writer.run",
            status="error",
            session="planner",
            run_id="run_join",
            root_run_id="run_join",
            reason_code="exit_1",
        )
    )
    write_downstream_record(
        DownstreamRecord(
            kind="attempt",
            downstream_event_id=mint_downstream_event_id(event_key="memory-writer:run_join"),
            provider_command="memory-writer",
            forge_run_id="run_join",
            forge_root_run_id="run_join",
            input_tokens=10,
            output_tokens=5,
            cost_micros=10_000,
            failed=True,
        )
    )

    human = CliRunner().invoke(main, _activity_args("planner", "--period", "all"))
    assert human.exit_code == 0
    assert "Operation outcomes" in human.output
    assert "Model calls" in human.output
    assert "memory-writer" in human.output
    assert "memory_writer.run" in human.output
    assert "matched" in human.output

    machine = CliRunner().invoke(main, _activity_args("planner", "--period", "all", "--json"))
    assert machine.exit_code == 0
    data = json.loads(machine.output)
    operation = data["upstream"]["operations"][0]
    row = data["downstream"]["rows"][0]
    assert operation["join_state"] == "matched"
    assert row["join_state"] == "matched"
    assert row["attempts"] == 1
    assert row["errors"] == 1


def test_human_render_shows_failing_open(monkeypatch) -> None:
    # Acceptance: a supervisor failing open is visible with a per-kind breakdown, even
    # with no decision log (pol is None here -- the resolver returns no forge_root).
    _patch_resolver(monkeypatch)
    log_usage_event(_event(status="timeout", failure_type="timeout"))
    log_usage_event(_event(status="timeout", failure_type="timeout"))
    log_usage_event(_event(status="error", failure_type="subprocess_error"))
    result = CliRunner().invoke(main, _activity_args("planner", "--period", "all"))
    assert result.exit_code == 0
    assert "failing open: 2 timeout, 1 error" in result.output


def test_json_includes_error_kinds(monkeypatch) -> None:
    _patch_resolver(monkeypatch)
    log_usage_event(_event(status="timeout", failure_type="timeout"))
    log_usage_event(_event(status="timeout", failure_type="timeout"))
    log_usage_event(_event(status="error", failure_type="subprocess_error"))
    result = CliRunner().invoke(main, _activity_args("planner", "--period", "all", "--json"))
    assert result.exit_code == 0
    rows = {c["command"]: c for c in json.loads(result.output)["downstream"]["rows"]}
    assert rows["supervisor"]["error_kinds"] == {"timeout": 2, "error": 1}
    assert rows["supervisor"]["errors"] == 3


def test_empty_session_message(monkeypatch) -> None:
    _patch_resolver(monkeypatch, name="quiet")
    result = CliRunner().invoke(main, _activity_args("quiet"))
    assert result.exit_code == 0
    assert "No Forge activity" in result.output


def test_human_render_shows_subagents(monkeypatch, tmp_path) -> None:
    # Subagent count is collected and JSON-exposed; it must also appear in the human view.
    from forge.session.models import SubagentConfirmed, create_session_state
    from forge.session.store import SessionStore

    state = create_session_state("planner", worktree_path=str(tmp_path))
    state.confirmed.subagents = SubagentConfirmed(total_count=3)
    SessionStore(str(tmp_path), "planner").write(state)
    _patch_resolver(monkeypatch, name="planner", forge_root=str(tmp_path))
    log_usage_event(_event(command="supervisor"))

    result = CliRunner().invoke(main, _activity_args("planner", "--period", "all"))
    assert result.exit_code == 0
    assert "Subagents" in result.output
    assert "3" in result.output


def test_human_render_shows_plan_check_counters(monkeypatch, tmp_path) -> None:
    # Cascade tier-1 activity comes from the decision log; an all-short-circuit
    # session shows the plan-check line and NO "Supervisor: 0 allow" noise.
    from forge.session.models import PolicyConfirmed, create_session_state
    from forge.session.store import SessionStore

    state = create_session_state("planner", worktree_path=str(tmp_path))
    state.confirmed.policy = PolicyConfirmed(
        decisions=[
            {
                "final_decision": "allow",
                "warnings": [],
                "evaluated_at": "2026-06-10T12:00:00Z",
                "decisions": [
                    {
                        "decision": "allow",
                        "policy_id": "semantic.plan_check",
                        "violations": [],
                        "warnings": [],
                        "cached": False,
                        "evaluated_at": "2026-06-10T12:00:00Z",
                    }
                ],
            }
        ]
    )
    SessionStore(str(tmp_path), "planner").write(state)
    _patch_resolver(monkeypatch, name="planner", forge_root=str(tmp_path))
    log_usage_event(_event(command="plan-check"))

    result = CliRunner().invoke(main, _activity_args("planner", "--period", "all"))
    assert result.exit_code == 0
    assert "Plan check (tier-1)" in result.output
    assert "1 allow" in result.output
    assert "Supervisor" not in result.output


def test_json_includes_plan_check_counters(monkeypatch, tmp_path) -> None:
    from forge.session.models import PolicyConfirmed, create_session_state
    from forge.session.store import SessionStore

    state = create_session_state("planner", worktree_path=str(tmp_path))
    state.confirmed.policy = PolicyConfirmed(
        decisions=[
            {
                "final_decision": "allow",
                "warnings": [],
                "evaluated_at": "2026-06-10T12:00:00Z",
                "decisions": [
                    {
                        "decision": "needs_review",
                        "policy_id": "semantic.plan_check",
                        "violations": [],
                        "warnings": [],
                        "cached": False,
                        "evaluated_at": "2026-06-10T12:00:00Z",
                    },
                    {
                        "decision": "allow",
                        "policy_id": "semantic.supervisor",
                        "violations": [],
                        "warnings": [],
                        "cached": False,
                        "evaluated_at": "2026-06-10T12:00:00Z",
                    },
                ],
            }
        ]
    )
    SessionStore(str(tmp_path), "planner").write(state)
    _patch_resolver(monkeypatch, name="planner", forge_root=str(tmp_path))
    log_usage_event(_event(command="plan-check"))

    result = CliRunner().invoke(main, _activity_args("planner", "--period", "all", "--json"))
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["upstream"]["policy"]["plan_check_needs_review"] == 1
    assert data["upstream"]["policy"]["plan_check_allow"] == 0
    assert data["upstream"]["policy"]["supervisor_allow"] == 1
    assert data["upstream"]["manifest_fallback_used"] is True


def test_period_week_excludes_nothing_recent(monkeypatch) -> None:
    _patch_resolver(monkeypatch)
    log_usage_event(_event(command="supervisor"))
    result = CliRunner().invoke(main, _activity_args("planner", "--period", "week", "--json"))
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["downstream"]["rows"][0]["attempts"] == 1


def test_exact_proxied_cost_renders_without_tilde(monkeypatch) -> None:
    # 4g: a proxied run whose exact cost-plane record supersedes its snapshot renders the
    # total WITHOUT the `~` estimate marker, and the footnote reports no-estimates-mixed-in.
    from forge.proxy.cost_logger import log_request_cost

    _patch_resolver(monkeypatch)
    log_usage_event(
        _event(
            command="memory-writer",
            run_id="run_mw",
            root_run_id="run_mw",
            route="claude_p",
            measurement_source="verb_snapshot_estimated",
            confidence="reported",
            cost_micro_usd=999_000,  # snapshot -- superseded
        )
    )
    log_request_cost(
        proxy_id="p1",
        model="gpt-5.5",
        tier="sonnet",
        input_tokens=10,
        output_tokens=5,
        cached_tokens=0,
        cost_micros=120_000,
        latency_ms=1.0,
        failed=False,
        request_id="req_mw",
        reporter="openrouter",
        confidence="reported",
        forge_run_id="run_mw",
        forge_root_run_id="run_mw",
    )
    result = CliRunner().invoke(main, _activity_args("planner", "--period", "all"))
    assert result.exit_code == 0
    assert "$0.12" in result.output
    assert "~$0.12" not in result.output  # exact -> no estimate marker
    assert "no snapshot estimates mixed in" in result.output


def _write_shadow_done(forge_root, cand_hash: str, *, status: str, session: str = "planner", **extra) -> None:
    import json as _json
    from pathlib import Path as _Path

    d = _Path(forge_root) / ".forge" / "artifacts" / session / "shadow"
    d.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "captured_at": "2026-06-10T12:00:00Z",
        "checked_at": "2026-06-10T12:05:00Z",
        "tool_name": "Write",
        "target_path": "src/foo.py",
        "status": status,
    }
    record.update(extra)
    (d / f"{cand_hash}.done").write_text(_json.dumps(record))


def test_human_render_shows_shadow_section(monkeypatch, tmp_path) -> None:
    from forge.session.models import create_session_state
    from forge.session.store import SessionStore

    SessionStore(str(tmp_path), "planner").write(create_session_state("planner", worktree_path=str(tmp_path)))
    _write_shadow_done(tmp_path, "a1", status="agree")
    _write_shadow_done(tmp_path, "d1", status="disagree", frontier_verdict="divergent", frontier_confidence=0.9)
    _patch_resolver(monkeypatch, name="planner", forge_root=str(tmp_path))

    result = CliRunner().invoke(main, _activity_args("planner", "--period", "all"))
    assert result.exit_code == 0
    assert "Shadow (audit)" in result.output
    assert "2 checked" in result.output
    assert "1 disagree" in result.output


def test_json_includes_shadow(monkeypatch, tmp_path) -> None:
    from forge.session.models import create_session_state
    from forge.session.store import SessionStore

    SessionStore(str(tmp_path), "planner").write(create_session_state("planner", worktree_path=str(tmp_path)))
    _write_shadow_done(tmp_path, "d1", status="disagree")
    _patch_resolver(monkeypatch, name="planner", forge_root=str(tmp_path))

    result = CliRunner().invoke(main, _activity_args("planner", "--period", "all", "--json"))
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["shadow"]["checked"] == 1
    assert data["shadow"]["disagree"] == 1

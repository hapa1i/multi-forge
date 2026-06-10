"""Tests for ``forge activity``.

Session resolution is exercised by ``test_session_context``; here we monkeypatch the
resolver so the tests focus on the command's rendering / JSON contract / error tip.
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from forge.cli.activity import activity_cmd
from forge.core.usage.ledger import UsageEvent, log_usage_event


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
    result = CliRunner().invoke(activity_cmd, ["ghost"])
    assert result.exit_code == 1
    assert "forge session list" in result.output


def test_not_found_json(monkeypatch) -> None:
    from forge.core.ops.session_context import SessionContextError

    def _raise(_s=None):  # noqa: ANN001
        raise SessionContextError("nope")

    monkeypatch.setattr("forge.cli.activity.resolve_session_identifier", _raise)
    result = CliRunner().invoke(activity_cmd, ["ghost", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error"] == "nope"


def test_human_render_shows_supervisor(monkeypatch) -> None:
    _patch_resolver(monkeypatch)
    log_usage_event(_event(status="success"))
    log_usage_event(_event(status="error"))
    result = CliRunner().invoke(activity_cmd, ["planner", "--all"])
    assert result.exit_code == 0
    assert "Forge activity" in result.output
    assert "planner" in result.output
    assert "supervisor" in result.output


def test_json_shape(monkeypatch) -> None:
    _patch_resolver(monkeypatch)
    log_usage_event(_event(command="supervisor", status="error"))
    result = CliRunner().invoke(activity_cmd, ["planner", "--all", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["session"] == "planner"
    assert data["session_tagging_partial"] is True
    cmds = {c["command"]: c for c in data["commands"]}
    assert cmds["supervisor"]["calls"] == 1
    assert cmds["supervisor"]["errors"] == 1


def test_empty_session_message(monkeypatch) -> None:
    _patch_resolver(monkeypatch, name="quiet")
    result = CliRunner().invoke(activity_cmd, ["quiet"])
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

    result = CliRunner().invoke(activity_cmd, ["planner", "--all"])
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

    result = CliRunner().invoke(activity_cmd, ["planner", "--all"])
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

    result = CliRunner().invoke(activity_cmd, ["planner", "--all", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["policy"]["plan_check_escalated"] == 1
    assert data["policy"]["plan_check_allow"] == 0
    assert data["policy"]["supervisor_allow"] == 1


def test_days_window_excludes_nothing_recent(monkeypatch) -> None:
    _patch_resolver(monkeypatch)
    log_usage_event(_event(command="supervisor"))
    result = CliRunner().invoke(activity_cmd, ["planner", "--days", "7", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["total_events"] == 1


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
    result = CliRunner().invoke(activity_cmd, ["planner", "--all"])
    assert result.exit_code == 0
    assert "$0.12" in result.output
    assert "~$0.12" not in result.output  # exact -> no estimate marker
    assert "no snapshot estimates mixed in" in result.output

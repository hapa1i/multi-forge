"""Hook-level wiring tests for the supervisor cascade (policy-check command).

Covers the registration branch in cli/hooks/commands.py: cascade on registers
PlanCheckPolicy as a regular policy and the supervisor as the needs_review
resolver (frontier runs only on escalation); cascade off registers the
supervisor as a regular policy exactly as before.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from forge.cli.hooks.commands import hooks
from forge.policy.semantic.plan_check import PlanCheckVerdict
from forge.policy.types import PolicyDecision, Violation
from forge.session import SessionStore, create_session_state
from forge.session.models import PolicyIntent, SupervisorConfig


def _make_cascade_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    cascade: bool = True,
) -> SessionStore:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_SESSION", "test-session")
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))

    plan = tmp_path / "plan.md"
    plan.write_text("# Approved Plan\nImplement the widget.")

    store = SessionStore(str(tmp_path), "test-session")
    manifest = create_session_state("test-session", worktree_path=str(tmp_path))
    manifest.forge_root = str(tmp_path)
    manifest.intent.policy = PolicyIntent(
        enabled=True,
        supervisor=SupervisorConfig(
            resume_id="planner",
            direct=True,
            cascade=cascade,
            plan_override_path=str(plan),
        ),
    )
    store.write(manifest)
    return store


def _write_payload() -> str:
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": "src/widget.py", "content": "def widget(): pass"},
        }
    )


def _supervisor_allow() -> PolicyDecision:
    return PolicyDecision(decision="allow", policy_id="semantic.supervisor")


def _supervisor_deny() -> PolicyDecision:
    return PolicyDecision(
        decision="deny",
        policy_id="semantic.supervisor",
        violations=[
            Violation(
                rule_id="semantic.supervisor.alignment",
                message="Divergent from plan",
                severity="high",
                citations=["Plan section 1"],
            )
        ],
    )


class TestCascadeHookWiring:
    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_short_circuit_skips_supervisor(
        self, mock_check: MagicMock, mock_invoke: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tier-1 aligned -> allow without ever invoking the frontier supervisor."""
        _make_cascade_session(tmp_path, monkeypatch)
        mock_check.return_value = PlanCheckVerdict(aligned=True, reason="covered")

        result = CliRunner().invoke(hooks, ["policy-check"], input=_write_payload())

        assert result.exit_code == 0, result.output
        assert mock_check.call_count == 1
        mock_invoke.assert_not_called()

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_escalation_invokes_supervisor_once(
        self, mock_check: MagicMock, mock_invoke: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tier-1 failure escalates; the supervisor resolves to allow."""
        _make_cascade_session(tmp_path, monkeypatch)
        mock_check.return_value = None  # checker error -> needs_review
        mock_invoke.return_value = _supervisor_allow()

        result = CliRunner().invoke(hooks, ["policy-check"], input=_write_payload())

        assert result.exit_code == 0, result.output
        assert mock_invoke.call_count == 1

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_escalation_supervisor_deny_blocks(
        self, mock_check: MagicMock, mock_invoke: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An escalated check the supervisor denies blocks the tool (exit 2)."""
        _make_cascade_session(tmp_path, monkeypatch)
        mock_check.return_value = PlanCheckVerdict(aligned=False, reason="touches unplanned files")
        mock_invoke.return_value = _supervisor_deny()

        result = CliRunner().invoke(hooks, ["policy-check"], input=_write_payload())

        assert result.exit_code == 2
        assert "Policy violation" in result.output

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_resolved_escalation_prints_no_tier1_noise(
        self, mock_check: MagicMock, mock_invoke: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A tier-1 error resolved to allow must not leak '[forge] Policy warning' lines."""
        _make_cascade_session(tmp_path, monkeypatch)
        mock_check.return_value = None  # checker error path
        mock_invoke.return_value = _supervisor_allow()

        result = CliRunner().invoke(hooks, ["policy-check"], input=_write_payload())

        assert result.exit_code == 0, result.output
        assert "Policy warning" not in result.output

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_cascade_off_runs_supervisor_directly(
        self, mock_check: MagicMock, mock_invoke: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cascade=False is exactly today's path: supervisor every event, no tier-1."""
        _make_cascade_session(tmp_path, monkeypatch, cascade=False)
        mock_invoke.return_value = _supervisor_allow()

        result = CliRunner().invoke(hooks, ["policy-check"], input=_write_payload())

        assert result.exit_code == 0, result.output
        assert mock_invoke.call_count == 1
        mock_check.assert_not_called()

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_decision_log_records_both_tiers(
        self, mock_check: MagicMock, mock_invoke: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Escalation persists both the tier-1 needs_review and the resolution."""
        store = _make_cascade_session(tmp_path, monkeypatch)
        mock_check.return_value = PlanCheckVerdict(aligned=False, reason="unsure")
        mock_invoke.return_value = _supervisor_allow()

        result = CliRunner().invoke(hooks, ["policy-check"], input=_write_payload())
        assert result.exit_code == 0, result.output

        manifest = store.read()
        assert manifest.confirmed.policy is not None
        entry = manifest.confirmed.policy.decisions[-1]
        by_policy = {d["policy_id"]: d for d in entry["decisions"]}
        assert by_policy["semantic.plan_check"]["decision"] == "needs_review"
        assert by_policy["semantic.plan_check"]["violations"][0]["rule_id"] == "semantic.plan_check.uncertain"
        assert by_policy["semantic.supervisor"]["decision"] == "allow"
        # rules_active provenance includes the resolver
        assert "semantic.supervisor" in manifest.confirmed.policy.rules_active
        assert "semantic.plan_check" in manifest.confirmed.policy.rules_active

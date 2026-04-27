"""Tests for policy check feedback (stderr summary + additionalContext).

Covers: _derive_policy_source_label, policy_check stderr/stdout output,
additionalContext JSON shape, config knob gating.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from forge.cli.hooks._group import hooks
from forge.cli.hooks.policy import _derive_policy_source_label

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_decision(
    policy_id: str = "semantic.supervisor",
    decision: str = "allow",
    cached: bool = False,
    violations: list | None = None,
    intent: str | None = None,
) -> MagicMock:
    d = MagicMock()
    d.policy_id = policy_id
    d.decision = decision
    d.cached = cached
    d.violations = violations or []
    d.intent = intent
    return d


def _make_violation(rule_id: str = "semantic.supervisor.alignment", message: str = "diverged") -> MagicMock:
    v = MagicMock()
    v.rule_id = rule_id
    v.message = message
    v.suggested_fix = None
    return v


def _make_result(
    final_decision: str = "allow",
    decisions: list | None = None,
    all_warnings: list | None = None,
) -> MagicMock:
    r = MagicMock()
    r.final_decision = final_decision
    r.decisions = decisions or []
    r.all_warnings = all_warnings or []
    r.blocking_violations = []
    return r


def _make_effective(supervisor_resume_id: str | None = "planner") -> MagicMock:
    eff = MagicMock()
    if supervisor_resume_id:
        eff.policy.supervisor.resume_id = supervisor_resume_id
        eff.policy.supervisor.suspended = False
    else:
        eff.policy.supervisor = None
    eff.policy.enabled = True
    eff.policy.fail_mode = "open"
    eff.policy.bundles = []
    eff.policy.bundle_config = {}
    return eff


def _hook_input(tool_name: str = "Edit", target_path: str = "src/foo.py") -> str:
    """Build minimal PreToolUse hook stdin JSON."""
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "session_id": "test-uuid",
            "tool_input": {"file_path": target_path, "new_string": "x = 1"},
        }
    )


# ---------------------------------------------------------------------------
# _derive_policy_source_label
# ---------------------------------------------------------------------------


class TestDerivePolicySourceLabel:
    def test_supervisor_allow_returns_resume_id(self) -> None:
        result = _make_result(
            final_decision="allow",
            decisions=[_make_decision("semantic.supervisor", "allow")],
        )
        effective = _make_effective("planner")
        assert _derive_policy_source_label(result, effective) == "'planner'"

    def test_supervisor_deny_returns_resume_id(self) -> None:
        result = _make_result(
            final_decision="deny",
            decisions=[_make_decision("semantic.supervisor", "deny")],
        )
        effective = _make_effective("planner")
        assert _derive_policy_source_label(result, effective) == "'planner'"

    def test_tdd_deny_returns_policy_id(self) -> None:
        result = _make_result(
            final_decision="deny",
            decisions=[
                _make_decision("tdd.tests-before-impl", "deny"),
                _make_decision("semantic.supervisor", "allow"),
            ],
        )
        effective = _make_effective("planner")
        assert _derive_policy_source_label(result, effective) == "tdd.tests-before-impl"

    def test_coding_standards_warn_returns_policy_id(self) -> None:
        result = _make_result(
            final_decision="warn",
            decisions=[_make_decision("coding_standards.no-bsd-sed", "warn")],
        )
        effective = _make_effective(None)
        assert _derive_policy_source_label(result, effective) == "coding_standards.no-bsd-sed"

    def test_no_matching_decision_returns_fallback(self) -> None:
        result = _make_result(final_decision="allow", decisions=[])
        effective = _make_effective(None)
        assert _derive_policy_source_label(result, effective) == "policy"

    def test_supervisor_without_resume_id_returns_policy_id(self) -> None:
        result = _make_result(
            final_decision="allow",
            decisions=[_make_decision("semantic.supervisor", "allow")],
        )
        effective = _make_effective(None)
        assert _derive_policy_source_label(result, effective) == "semantic.supervisor"

    def test_mixed_bundle_and_supervisor_deny_picks_first_deny(self) -> None:
        """When both TDD and supervisor deny, the first deny in the list wins."""
        result = _make_result(
            final_decision="deny",
            decisions=[
                _make_decision("tdd.tests-before-impl", "deny"),
                _make_decision("semantic.supervisor", "deny"),
            ],
        )
        effective = _make_effective("planner")
        assert _derive_policy_source_label(result, effective) == "tdd.tests-before-impl"

    def test_bundle_allow_plus_supervisor_allow_prefers_supervisor(self) -> None:
        """P1 regression: when both allow, supervisor is the interesting check."""
        result = _make_result(
            final_decision="allow",
            decisions=[
                _make_decision("tdd.tests-before-impl", "allow"),
                _make_decision("semantic.supervisor", "allow"),
            ],
        )
        effective = _make_effective("planner")
        assert _derive_policy_source_label(result, effective) == "'planner'"

    def test_bundle_only_allow_returns_bundle_id(self) -> None:
        """No supervisor — falls back to first matching deterministic policy."""
        result = _make_result(
            final_decision="allow",
            decisions=[_make_decision("tdd.tests-before-impl", "allow")],
        )
        effective = _make_effective(None)
        assert _derive_policy_source_label(result, effective) == "tdd.tests-before-impl"


# ---------------------------------------------------------------------------
# Config knob validation
# ---------------------------------------------------------------------------


class TestPolicySummaryFeedbackConfig:
    def test_on_accepted(self) -> None:
        from forge.runtime_config import RuntimeConfig

        rc = RuntimeConfig(policy_summary_feedback="on")
        assert rc.policy_summary_feedback == "on"

    def test_off_accepted(self) -> None:
        from forge.runtime_config import RuntimeConfig

        rc = RuntimeConfig(policy_summary_feedback="off")
        assert rc.policy_summary_feedback == "off"

    def test_invalid_rejected(self) -> None:
        from forge.runtime_config import RuntimeConfig

        with pytest.raises(ValueError, match="Invalid policy_summary_feedback"):
            RuntimeConfig(policy_summary_feedback="verbose")

    def test_default_is_on(self) -> None:
        from forge.runtime_config import RuntimeConfig

        rc = RuntimeConfig()
        assert rc.policy_summary_feedback == "on"

    def test_default_config_content_mentions_field(self) -> None:
        from forge.runtime_config import get_default_config_content

        content = get_default_config_content()
        assert "policy_summary_feedback" in content


# ---------------------------------------------------------------------------
# Hook-level tests: policy_check stderr/stdout behavior
# ---------------------------------------------------------------------------


def _run_policy_check(
    result: MagicMock,
    effective: MagicMock | None = None,
    feedback: str = "on",
    tool_name: str = "Edit",
    target_path: str = "src/foo.py",
) -> tuple[str, int]:
    """Invoke policy_check via CliRunner, return (combined_output, exit_code).

    Click 8.x merges stderr into output. The combined output contains both
    JSON (from _output_json to stdout) and stderr lines (from print to sys.stderr).
    """
    if effective is None:
        effective = _make_effective("planner")

    mock_store = MagicMock()
    mock_store.read.return_value = MagicMock(confirmed=MagicMock(policy=None))

    mock_engine = MagicMock()
    mock_engine.evaluate.return_value = result
    mock_engine.policies = []
    mock_engine.get_collected_state.return_value = {}

    from forge.runtime_config import RuntimeConfig

    rc = RuntimeConfig(policy_summary_feedback=feedback)

    with (
        patch("forge.cli.hooks.commands.resolve_session_store", return_value=mock_store),
        patch("forge.cli.hooks.commands.compute_effective_intent", return_value=effective),
        patch("forge.guard.engine.build_engine", return_value=mock_engine),
        patch("forge.cli.hooks.commands._persist_policy_state"),
        patch("forge.runtime_config.get_runtime_config", return_value=rc),
    ):
        runner = CliRunner()
        out = runner.invoke(hooks, ["policy-check"], input=_hook_input(tool_name, target_path))

    return out.output, out.exit_code


def _extract_json(output: str) -> dict | None:
    """Extract the first JSON object from combined Click output."""
    brace = output.find("{")
    if brace == -1:
        return None
    depth = 0
    for i in range(brace, len(output)):
        if output[i] == "{":
            depth += 1
        elif output[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(output[brace : i + 1])
    return None


class TestPolicyCheckFeedback:
    """Test the actual policy_check hook command output.

    Click 8.x merges stderr into output, so all assertions use combined output.
    """

    def test_allow_prints_aligned_summary(self) -> None:
        result = _make_result(
            final_decision="allow",
            decisions=[_make_decision("semantic.supervisor", "allow")],
        )
        output, code = _run_policy_check(result)

        assert code == 0
        assert "[forge] Policy: checked" in output
        assert "aligned" in output
        assert "'planner'" in output

    def test_allow_outputs_additional_context_json(self) -> None:
        result = _make_result(
            final_decision="allow",
            decisions=[_make_decision("semantic.supervisor", "allow")],
        )
        output, _code = _run_policy_check(result)

        data = _extract_json(output)
        assert data is not None
        assert "hookSpecificOutput" in data
        assert data["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert "additionalContext" in data["hookSpecificOutput"]
        assert "aligned" in data["hookSpecificOutput"]["additionalContext"]

    def test_allow_with_warnings_not_labeled_aligned(self) -> None:
        """P2 regression: fail-open warnings must not be called 'aligned'."""
        result = _make_result(
            final_decision="allow",
            decisions=[_make_decision("semantic.supervisor", "allow")],
            all_warnings=["Supervisor verdict could not be parsed"],
        )
        output, _code = _run_policy_check(result)

        summary_parts = output.split("[forge] Policy: checked")
        assert len(summary_parts) >= 2, "Summary line must appear"
        assert "aligned" not in summary_parts[1]
        assert "1 warning" in output

    def test_deny_prints_violations_then_summary(self) -> None:
        v = _make_violation()
        result = _make_result(
            final_decision="deny",
            decisions=[_make_decision("semantic.supervisor", "deny", violations=[v])],
        )
        output, code = _run_policy_check(result)

        assert code == 2
        violation_pos = output.find("Policy violation(s):")
        summary_pos = output.find("[forge] Policy: checked")
        assert violation_pos >= 0
        assert summary_pos >= 0
        assert violation_pos < summary_pos, "Summary must appear after violations"

    def test_deny_no_additional_context_json(self) -> None:
        v = _make_violation()
        result = _make_result(
            final_decision="deny",
            decisions=[_make_decision("semantic.supervisor", "deny", violations=[v])],
        )
        output, _code = _run_policy_check(result)

        assert "hookSpecificOutput" not in output

    def test_unresolved_needs_review_blocks(self) -> None:
        """needs_review without a supervisor resolution must block instead of allowing."""
        effective = _make_effective(None)
        effective.policy.bundles = ["coding_standards"]
        result = _make_result(
            final_decision="needs_review",
            decisions=[
                _make_decision(
                    "coding_standards.some-rule",
                    "needs_review",
                    intent="check this change",
                )
            ],
        )

        output, code = _run_policy_check(result, effective=effective)

        assert code == 2
        assert "Policy review required" in output
        assert "coding_standards.some-rule" in output
        assert "hookSpecificOutput" not in output

    def test_feedback_off_suppresses_summary(self) -> None:
        result = _make_result(
            final_decision="allow",
            decisions=[_make_decision("semantic.supervisor", "allow")],
        )
        output, _code = _run_policy_check(result, feedback="off")

        assert "[forge] Policy: checked" not in output
        assert "hookSpecificOutput" not in output

    def test_feedback_off_preserves_deny_output(self) -> None:
        """Deny violation lines must appear even with feedback=off."""
        v = _make_violation()
        result = _make_result(
            final_decision="deny",
            decisions=[_make_decision("semantic.supervisor", "deny", violations=[v])],
        )
        output, code = _run_policy_check(result, feedback="off")

        assert code == 2
        assert "Policy violation(s):" in output
        assert "[forge] Policy: checked" not in output

    def test_feedback_off_preserves_warning_lines(self) -> None:
        """Substantive warning lines must appear even with feedback=off."""
        result = _make_result(
            final_decision="allow",
            decisions=[_make_decision("semantic.supervisor", "allow")],
            all_warnings=["Possible divergence: unparseable"],
        )
        output, _code = _run_policy_check(result, feedback="off")

        assert "[forge] Policy warning:" in output
        assert "[forge] Policy: checked" not in output

    def test_cached_verdict_label(self) -> None:
        result = _make_result(
            final_decision="allow",
            decisions=[_make_decision("semantic.supervisor", "allow", cached=True)],
        )
        output, _code = _run_policy_check(result)

        assert "cached" in output

    def test_supervisor_allow_with_bundles_labels_supervisor(self) -> None:
        """P1 regression: bundles before supervisor must not steal the label."""
        result = _make_result(
            final_decision="allow",
            decisions=[
                _make_decision("tdd.tests-before-impl", "allow"),
                _make_decision("semantic.supervisor", "allow"),
            ],
        )
        output, _code = _run_policy_check(result)

        summary_parts = output.split("[forge] Policy: checked")
        assert len(summary_parts) >= 2
        assert "'planner'" in summary_parts[1]
        assert "tdd" not in summary_parts[1]

    def test_zero_violation_deny_says_evaluation_error(self) -> None:
        result = _make_result(
            final_decision="deny",
            decisions=[_make_decision("semantic.supervisor", "deny", violations=[])],
        )
        output, _code = _run_policy_check(result)

        assert "evaluation error" in output

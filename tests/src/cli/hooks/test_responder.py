"""Tests for the Claude hook adapter + responder seam (Phase 4f).

``ClaudeHookResponder`` owns Claude Code's PreToolUse wire contract: the block
message (deny / needs_review), the allow ``hookSpecificOutput`` JSON, and the
exit codes. These lock that contract directly (the ``policy_check`` command tests
cover the end-to-end integration). ``ClaudeHookAdapter``/``ClaudeHookResponder``
must also structurally satisfy the runtime-neutral ``HookAdapter``/``HookResponder``
protocols so a Codex equivalent (Phase 6) can sit beside them.
"""

from __future__ import annotations

from forge.cli.hooks.policy import ClaudeHookAdapter, ClaudeHookResponder
from forge.cli.hooks.protocols import HookAdapter, HookResponder
from forge.policy.types import CompositeDecision, PolicyDecision, Violation


def _deny(policy_id: str, *violations: Violation, intent: str | None = None) -> PolicyDecision:
    return PolicyDecision(decision="deny", policy_id=policy_id, violations=list(violations), intent=intent)


class TestFormatDeny:
    def test_violation_lines_with_intent_and_fix(self) -> None:
        result = CompositeDecision(
            final_decision="deny",
            decisions=[
                _deny(
                    "tdd",
                    Violation(
                        rule_id="tdd.tests-first",
                        message="write a test first",
                        severity="high",
                        suggested_fix="add a test",
                    ),
                    intent="enforce TDD",
                )
            ],
        )
        msg = ClaudeHookResponder().format_deny(result)
        assert msg.startswith("Policy violation(s):")
        assert "  [tdd.tests-first] write a test first" in msg
        assert "    Intent: enforce TDD" in msg
        assert "    Fix: add a test" in msg
        assert "Note: This policy was configured by the project owner." in msg

    def test_intent_only_on_first_violation(self) -> None:
        result = CompositeDecision(
            final_decision="deny",
            decisions=[
                _deny(
                    "std",
                    Violation(rule_id="r1", message="m1", severity="high"),
                    Violation(rule_id="r2", message="m2", severity="low"),
                    intent="keep it clean",
                )
            ],
        )
        msg = ClaudeHookResponder().format_deny(result)
        # Intent is printed once (after the first violation), not per violation.
        assert msg.count("    Intent: keep it clean") == 1

    def test_one_note_per_denying_decision(self) -> None:
        result = CompositeDecision(
            final_decision="deny",
            decisions=[
                _deny("a", Violation(rule_id="r1", message="m1", severity="high")),
                PolicyDecision(decision="allow", policy_id="b"),  # non-deny: skipped
                _deny("c", Violation(rule_id="r2", message="m2", severity="high")),
            ],
        )
        msg = ClaudeHookResponder().format_deny(result)
        assert msg.count("Note: This policy was configured") == 2  # one per denying policy, allow skipped


class TestFormatNeedsReview:
    def test_review_lines(self) -> None:
        result = CompositeDecision(
            final_decision="needs_review",
            decisions=[
                PolicyDecision(decision="needs_review", policy_id="semantic.supervisor", intent="check the plan")
            ],
        )
        msg = ClaudeHookResponder().format_needs_review(result)
        assert msg.startswith("Policy review required but no semantic supervisor resolved it:")
        assert "  [semantic.supervisor] requested review" in msg
        assert "    Intent: check the plan" in msg
        assert "Configure a supervisor for this session" in msg


class TestAllowFeedback:
    def test_hook_specific_output_shape(self) -> None:
        out = ClaudeHookResponder().allow_feedback("Forge policy: ok")
        assert out == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "additionalContext": "Forge policy: ok",
            }
        }


class TestExitCodes:
    def test_block_and_allow_exit_codes(self) -> None:
        # Claude's PreToolUse contract: 2 blocks (stderr shown), 0 allows.
        assert ClaudeHookResponder.BLOCK_EXIT == 2
        assert ClaudeHookResponder.ALLOW_EXIT == 0


def test_claude_impls_satisfy_protocols() -> None:
    """Static + runtime check that the Claude impls match the runtime-neutral seam."""
    adapter: HookAdapter = ClaudeHookAdapter()  # type-checked structural conformance
    responder: HookResponder = ClaudeHookResponder()
    assert adapter is not None and responder is not None

"""Allowed Codex findings must survive conversion and use the deliverable wire."""

import pytest

from forge.cli.hooks.codex_policy import CodexHookResponder
from forge.policy.semantic.verdict import SupervisorVerdict, verdict_to_decision

pytestmark = pytest.mark.regression


def test_allowed_context_does_not_explicitly_allow() -> None:
    wire = CodexHookResponder().allow_feedback("warning nonce")
    assert wire == {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "warning nonce"}}


def test_low_confidence_finding_retains_citation_without_becoming_a_violation() -> None:
    decision = verdict_to_decision(
        SupervisorVerdict(
            verdict="divergent",
            confidence=0.5,
            violations=[{"evidence": "reviewer explanation", "citations": ["Use the approved interface."]}],
        )
    )
    assert decision.decision == "warn"
    assert decision.violations == []
    assert decision.warnings == ["Possible divergence: reviewer explanation (confidence: 50%)"]
    assert decision.warning_findings[0].citations == ["Use the approved interface."]

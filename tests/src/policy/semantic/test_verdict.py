"""Tests for policy/semantic/verdict.py."""

from forge.policy.semantic.verdict import (
    SupervisorVerdict,
    parse_supervisor_verdict,
    verdict_to_decision,
)


class TestParseSupervisorVerdict:
    """Tests for parse_supervisor_verdict function."""

    def test_parse_aligned_verdict(self) -> None:
        """Parse aligned verdict from JSON code fence."""
        response = """Here is my analysis:
```json
{"verdict": "aligned", "confidence": 0.95, "violations": []}
```
"""
        verdict = parse_supervisor_verdict(response)
        assert verdict.verdict == "aligned"
        assert verdict.confidence == 0.95
        assert verdict.violations == []

    def test_parse_divergent_verdict(self) -> None:
        """Parse divergent verdict with violations."""
        response = """Analysis complete:
```json
{
  "verdict": "divergent",
  "confidence": 0.85,
  "violations": [
    {
      "severity": "high",
      "evidence": "Added unplanned feature",
      "citations": ["Plan says: implement only X"]
    }
  ]
}
```
"""
        verdict = parse_supervisor_verdict(response)
        assert verdict.verdict == "divergent"
        assert verdict.confidence == 0.85
        assert len(verdict.violations) == 1
        assert verdict.violations[0]["severity"] == "high"

    def test_parse_no_json_fence(self) -> None:
        """Fails open with warning (divergent+0.0) when no JSON fence found."""
        response = "This action looks fine to me."
        verdict = parse_supervisor_verdict(response)
        assert verdict.verdict == "divergent"
        assert verdict.confidence == 0.0
        assert len(verdict.violations) == 1

    def test_parse_malformed_json(self) -> None:
        """Fails open with warning (divergent+0.0) on malformed JSON."""
        response = """```json
{"verdict": "aligned", confidence: broken}
```"""
        verdict = parse_supervisor_verdict(response)
        assert verdict.verdict == "divergent"
        assert verdict.confidence == 0.0
        assert len(verdict.violations) == 1

    def test_parse_empty_response(self) -> None:
        """Fails open with warning (divergent+0.0) on empty response."""
        verdict = parse_supervisor_verdict("")
        assert verdict.verdict == "divergent"
        assert verdict.confidence == 0.0
        assert len(verdict.violations) == 1

    def test_parse_confidence_clamped(self) -> None:
        """Confidence is clamped to 0.0-1.0."""
        response = """```json
{"verdict": "aligned", "confidence": 1.5}
```"""
        verdict = parse_supervisor_verdict(response)
        assert verdict.confidence == 1.0

        response2 = """```json
{"verdict": "aligned", "confidence": -0.5}
```"""
        verdict2 = parse_supervisor_verdict(response2)
        assert verdict2.confidence == 0.0


class TestVerdictToDecision:
    """Tests for verdict_to_decision function."""

    def test_aligned_allows(self) -> None:
        """Aligned verdict returns allow decision."""
        verdict = SupervisorVerdict(verdict="aligned", confidence=0.9)
        decision = verdict_to_decision(verdict)
        assert decision.decision == "allow"
        assert decision.policy_id == "semantic.supervisor"

    def test_divergent_high_confidence_with_citations_denies(self) -> None:
        """Divergent with high confidence and citations denies."""
        verdict = SupervisorVerdict(
            verdict="divergent",
            confidence=0.85,
            violations=[
                {
                    "severity": "high",
                    "evidence": "Wrong approach",
                    "citations": ["Plan says X"],
                }
            ],
        )
        decision = verdict_to_decision(verdict)
        assert decision.decision == "deny"
        assert len(decision.violations) == 1

    def test_divergent_low_confidence_warns(self) -> None:
        """Divergent with low confidence warns instead of denying."""
        verdict = SupervisorVerdict(
            verdict="divergent",
            confidence=0.6,  # Below 0.8 threshold
            violations=[
                {
                    "severity": "medium",
                    "evidence": "Might be wrong",
                    "citations": ["Maybe plan says X"],
                }
            ],
        )
        decision = verdict_to_decision(verdict)
        assert decision.decision == "warn"
        assert len(decision.warnings) == 1

    def test_divergent_no_citations_warns(self) -> None:
        """Divergent without citations warns even with high confidence."""
        verdict = SupervisorVerdict(
            verdict="divergent",
            confidence=0.95,
            violations=[
                {
                    "severity": "high",
                    "evidence": "Wrong approach",
                    "citations": [],  # No citations
                }
            ],
        )
        decision = verdict_to_decision(verdict)
        assert decision.decision == "warn"

    def test_divergent_mixed_violations(self) -> None:
        """Some violations with citations block, others warn."""
        verdict = SupervisorVerdict(
            verdict="divergent",
            confidence=0.9,
            violations=[
                {
                    "severity": "high",
                    "evidence": "Cited violation",
                    "citations": ["Plan says X"],
                },
                {
                    "severity": "medium",
                    "evidence": "Uncited violation",
                    "citations": [],
                },
            ],
        )
        decision = verdict_to_decision(verdict)
        assert decision.decision == "deny"
        assert len(decision.violations) == 1  # Only cited one blocks
        assert len(decision.warnings) == 1  # Uncited one warns

    def test_deny_includes_intent_when_provided(self) -> None:
        """Deny decision carries intent when caller passes it."""
        verdict = SupervisorVerdict(
            verdict="divergent",
            confidence=0.9,
            violations=[
                {
                    "severity": "high",
                    "evidence": "Wrong approach",
                    "citations": ["Plan says X"],
                }
            ],
        )
        decision = verdict_to_decision(verdict, intent="Stay aligned with plan")
        assert decision.decision == "deny"
        assert decision.intent == "Stay aligned with plan"

    def test_allow_does_not_carry_intent(self) -> None:
        """Allow decisions don't carry intent (only shown on deny)."""
        verdict = SupervisorVerdict(verdict="aligned", confidence=0.9)
        decision = verdict_to_decision(verdict, intent="Some intent")
        assert decision.decision == "allow"
        assert decision.intent is None

    def test_deny_without_intent_defaults_to_none(self) -> None:
        """Deny decision has None intent when caller omits it."""
        verdict = SupervisorVerdict(
            verdict="divergent",
            confidence=0.9,
            violations=[
                {
                    "severity": "high",
                    "evidence": "Wrong approach",
                    "citations": ["Plan says X"],
                }
            ],
        )
        decision = verdict_to_decision(verdict)
        assert decision.decision == "deny"
        assert decision.intent is None

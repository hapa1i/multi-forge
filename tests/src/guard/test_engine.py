"""Tests for guard/engine.py."""

from forge.guard.engine import PolicyEngine, build_engine
from forge.guard.types import ActionContext, PolicyDecision, Violation


class MockPolicy:
    """Mock policy for testing."""

    def __init__(
        self,
        policy_id: str = "mock",
        decision: str = "allow",
        applies: bool = True,
        violations: list | None = None,
    ) -> None:
        self._policy_id = policy_id
        self._decision = decision
        self._applies = applies
        self._violations = violations or []

    @property
    def policy_id(self) -> str:
        return self._policy_id

    @property
    def description(self) -> str:
        return f"Mock policy: {self._policy_id}"

    def applies_to(self, context: ActionContext) -> bool:
        return self._applies

    def evaluate(self, context: ActionContext) -> PolicyDecision:
        return PolicyDecision(
            decision=self._decision,  # type: ignore
            policy_id=self._policy_id,
            violations=self._violations,
        )


class TestPolicyEngine:
    """Tests for PolicyEngine composition."""

    def test_empty_engine_allows(self, write_context: ActionContext) -> None:
        """An engine with no policies should allow all actions."""
        engine = PolicyEngine()
        result = engine.evaluate(write_context)
        assert result.final_decision == "allow"
        assert len(result.decisions) == 0

    def test_single_allow_policy(self, write_context: ActionContext) -> None:
        """Single allow policy passes through."""
        engine = PolicyEngine()
        engine.register(MockPolicy(decision="allow"))

        result = engine.evaluate(write_context)
        assert result.final_decision == "allow"
        assert len(result.decisions) == 1

    def test_single_deny_policy(self, write_context: ActionContext) -> None:
        """Single deny policy blocks."""
        v = Violation(rule_id="test", message="blocked", severity="high")
        engine = PolicyEngine()
        engine.register(MockPolicy(decision="deny", violations=[v]))

        result = engine.evaluate(write_context)
        assert result.final_decision == "deny"
        assert len(result.blocking_violations) == 1

    def test_any_deny_blocks(self, write_context: ActionContext) -> None:
        """Any deny policy blocks, even with other allows."""
        v = Violation(rule_id="test", message="blocked", severity="high")
        engine = PolicyEngine()
        engine.register(MockPolicy(policy_id="allow1", decision="allow"))
        engine.register(MockPolicy(policy_id="deny1", decision="deny", violations=[v]))
        engine.register(MockPolicy(policy_id="allow2", decision="allow"))

        result = engine.evaluate(write_context)
        assert result.final_decision == "deny"
        assert len(result.decisions) == 3

    def test_non_applicable_policy_skipped(self, write_context: ActionContext) -> None:
        """Policies that don't apply are skipped."""
        v = Violation(rule_id="test", message="blocked", severity="high")
        engine = PolicyEngine()
        engine.register(MockPolicy(policy_id="skip", decision="deny", applies=False, violations=[v]))
        engine.register(MockPolicy(policy_id="apply", decision="allow"))

        result = engine.evaluate(write_context)
        assert result.final_decision == "allow"
        # Only the applicable policy should be in decisions
        assert len(result.decisions) == 1
        assert result.decisions[0].policy_id == "apply"

    def test_warn_decision(self, write_context: ActionContext) -> None:
        """Warn decision when no deny."""
        engine = PolicyEngine()
        engine.register(MockPolicy(decision="warn"))

        result = engine.evaluate(write_context)
        assert result.final_decision == "warn"

    def test_needs_review_escalation(self, write_context: ActionContext) -> None:
        """needs_review escalates when no deny."""
        engine = PolicyEngine()
        engine.register(MockPolicy(policy_id="allow", decision="allow"))
        engine.register(MockPolicy(policy_id="review", decision="needs_review"))

        result = engine.evaluate(write_context)
        assert result.final_decision == "needs_review"

    def test_needs_review_resolved_by_semantic_supervisor_allow(self, write_context: ActionContext) -> None:
        """A supervisor allow decision resolves an earlier review request."""
        engine = PolicyEngine()
        engine.register(MockPolicy(policy_id="review", decision="needs_review"))
        engine.register(MockPolicy(policy_id="semantic.supervisor", decision="allow"))

        result = engine.evaluate(write_context)
        assert result.final_decision == "allow"

    def test_needs_review_resolved_by_semantic_supervisor_warn(self, write_context: ActionContext) -> None:
        """A supervisor warn decision resolves review while preserving the warning verdict."""
        engine = PolicyEngine()
        engine.register(MockPolicy(policy_id="review", decision="needs_review"))
        engine.register(MockPolicy(policy_id="semantic.supervisor", decision="warn"))

        result = engine.evaluate(write_context)
        assert result.final_decision == "warn"

    def test_fail_open_on_error(self, write_context: ActionContext) -> None:
        """Fail-open mode allows on policy errors."""

        class ErrorPolicy:
            @property
            def policy_id(self) -> str:
                return "error"

            @property
            def description(self) -> str:
                return "Error policy"

            def applies_to(self, context: ActionContext) -> bool:
                return True

            def evaluate(self, context: ActionContext) -> PolicyDecision:
                raise RuntimeError("Boom!")

        engine = PolicyEngine(fail_mode="open")
        engine.register(ErrorPolicy())

        result = engine.evaluate(write_context)
        assert result.final_decision == "allow"
        assert any("fail-open" in w for w in result.all_warnings)

    def test_fail_closed_on_error(self, write_context: ActionContext) -> None:
        """Fail-closed mode denies on policy errors."""

        class ErrorPolicy:
            @property
            def policy_id(self) -> str:
                return "error"

            @property
            def description(self) -> str:
                return "Error policy"

            def applies_to(self, context: ActionContext) -> bool:
                return True

            def evaluate(self, context: ActionContext) -> PolicyDecision:
                raise RuntimeError("Boom!")

        engine = PolicyEngine(fail_mode="closed")
        engine.register(ErrorPolicy())

        result = engine.evaluate(write_context)
        assert result.final_decision == "deny"


class TestBuildEngine:
    """Tests for build_engine function."""

    def test_build_tdd_bundle(self) -> None:
        """Build engine with TDD bundle."""
        engine = build_engine(["tdd"])
        assert len(engine.policies) == 2

        policy_ids = [p.policy_id for p in engine.policies]
        assert "tdd.tests-before-impl" in policy_ids
        assert "tdd.no-skip-tests" in policy_ids

    def test_build_coding_standards_bundle(self) -> None:
        """Build engine with coding standards bundle."""
        engine = build_engine(["coding_standards"])
        assert len(engine.policies) == 3

        policy_ids = [p.policy_id for p in engine.policies]
        assert "coding_standards.no-type-checking" in policy_ids
        assert "coding_standards.no-backward-compat" in policy_ids
        assert "coding_standards.no-emoji" in policy_ids

    def test_build_multiple_bundles(self) -> None:
        """Build engine with multiple bundles."""
        engine = build_engine(["tdd", "coding_standards"])
        assert len(engine.policies) == 5

    def test_build_unknown_bundle(self) -> None:
        """Unknown bundle is ignored (returns no policies)."""
        engine = build_engine(["unknown"])
        assert len(engine.policies) == 0

    def test_build_tdd_with_bundle_config_permissive(self) -> None:
        """bundle_config passes per-bundle config to get_bundle_policies."""
        engine = build_engine(["tdd"], bundle_config={"tdd": {"strict": False}})
        assert len(engine.policies) == 2

        # TDDEnforcementPolicy should be non-strict (permissive)
        from forge.guard.deterministic.tdd import TDDEnforcementPolicy

        tdd_policy = next(p for p in engine.policies if isinstance(p, TDDEnforcementPolicy))
        assert tdd_policy.strict is False

    def test_build_tdd_without_bundle_config(self) -> None:
        """Default TDD is strict when no bundle_config provided."""
        engine = build_engine(["tdd"])

        from forge.guard.deterministic.tdd import TDDEnforcementPolicy

        tdd_policy = next(p for p in engine.policies if isinstance(p, TDDEnforcementPolicy))
        assert tdd_policy.strict is True

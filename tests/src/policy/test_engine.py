"""Tests for policy/engine.py."""

from forge.core.telemetry.upstream import read_upstream_outcomes
from forge.policy.engine import PolicyEngine, build_engine
from forge.policy.types import ActionContext, PolicyDecision, Violation


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
        self.evaluate_calls = 0

    @property
    def policy_id(self) -> str:
        return self._policy_id

    @property
    def description(self) -> str:
        return f"Mock policy: {self._policy_id}"

    def applies_to(self, context: ActionContext) -> bool:
        return self._applies

    def evaluate(self, context: ActionContext) -> PolicyDecision:
        self.evaluate_calls += 1
        return PolicyDecision(
            decision=self._decision,  # type: ignore
            policy_id=self._policy_id,
            violations=self._violations,
        )


class StatefulMockPolicy(MockPolicy):
    """Mock policy implementing the StatefulPolicy protocol."""

    def __init__(self, policy_id: str = "stateful", decision: str = "allow") -> None:
        super().__init__(policy_id=policy_id, decision=decision)
        self.state: dict = {"count": 0}

    def evaluate(self, context: ActionContext) -> PolicyDecision:
        self.state["count"] += 1
        return super().evaluate(context)

    def get_state(self) -> dict:
        return dict(self.state)

    def set_state(self, state: dict) -> None:
        self.state = dict(state)


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

    def test_fail_open_records_upstream_outcome_by_default(self, write_context: ActionContext) -> None:
        """Default upstream volume records non-success no-call outcomes."""

        class ErrorPolicy:
            @property
            def policy_id(self) -> str:
                return "semantic.supervisor"

            @property
            def description(self) -> str:
                return "Error policy"

            def applies_to(self, context: ActionContext) -> bool:
                return True

            def evaluate(self, context: ActionContext) -> PolicyDecision:
                raise RuntimeError("Boom!")

        engine = PolicyEngine(fail_mode="open")
        engine.register(ErrorPolicy())

        engine.evaluate(write_context)

        outcomes = read_upstream_outcomes(session="test-session", policy_id="semantic.supervisor")
        assert len(outcomes) == 1
        assert outcomes[0].command == "policy-check"
        assert outcomes[0].status == "fail_open"
        assert outcomes[0].reason_code == "evaluate_fail_open"

    def test_structural_supervisor_timeout_records_timeout(self, write_context: ActionContext) -> None:
        """Supervisor fail-open telemetry uses structured fields, not warning text."""

        class TimeoutPolicy:
            @property
            def policy_id(self) -> str:
                return "semantic.supervisor"

            @property
            def description(self) -> str:
                return "Supervisor"

            def applies_to(self, context: ActionContext) -> bool:
                return True

            def evaluate(self, context: ActionContext) -> PolicyDecision:
                return PolicyDecision(
                    decision="allow",
                    policy_id="semantic.supervisor",
                    warnings=["Supervisor error: timed out, failing open"],
                    fail_open=True,
                    failure_type="timeout",
                    telemetry_run_id="run_supervisor_child",
                )

        engine = PolicyEngine(fail_mode="open")
        engine.register(TimeoutPolicy())

        engine.evaluate(write_context)

        outcomes = read_upstream_outcomes(session="test-session", policy_id="semantic.supervisor")
        assert len(outcomes) == 1
        assert outcomes[0].status == "timeout"
        assert outcomes[0].reason_code == "timeout"
        assert outcomes[0].run_id == "run_supervisor_child"

    def test_success_not_recorded_at_default_upstream_volume(self, write_context: ActionContext) -> None:
        """Default upstream volume is a non-success log, not a complete operation log."""
        engine = PolicyEngine()
        engine.register(MockPolicy(policy_id="semantic.supervisor", decision="allow"))

        engine.evaluate(write_context)

        assert read_upstream_outcomes(session="test-session", policy_id="semantic.supervisor") == []

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


class TestResolver:
    """Tests for the needs_review resolver hop."""

    def test_resolver_resolves_allow(self, write_context: ActionContext) -> None:
        """Resolver allow resolves an escalated review."""
        engine = PolicyEngine()
        engine.register(MockPolicy(policy_id="checker", decision="needs_review"))
        resolver = MockPolicy(policy_id="semantic.supervisor", decision="allow")
        engine.register_resolver(resolver)

        result = engine.evaluate(write_context)
        assert result.final_decision == "allow"
        assert resolver.evaluate_calls == 1
        assert any(d.policy_id == "semantic.supervisor" for d in result.decisions)

    def test_resolver_resolves_warn(self, write_context: ActionContext) -> None:
        """Resolver warn resolves review while preserving the warning verdict."""
        engine = PolicyEngine()
        engine.register(MockPolicy(policy_id="checker", decision="needs_review"))
        engine.register_resolver(MockPolicy(policy_id="semantic.supervisor", decision="warn"))

        result = engine.evaluate(write_context)
        assert result.final_decision == "warn"

    def test_resolver_resolves_deny(self, write_context: ActionContext) -> None:
        """Resolver deny blocks with its violations."""
        v = Violation(rule_id="sup", message="divergent", severity="high")
        engine = PolicyEngine()
        engine.register(MockPolicy(policy_id="checker", decision="needs_review"))
        engine.register_resolver(MockPolicy(policy_id="semantic.supervisor", decision="deny", violations=[v]))

        result = engine.evaluate(write_context)
        assert result.final_decision == "deny"
        assert result.blocking_violations == [v]

    def test_resolver_with_custom_policy_id_resolves(self, write_context: ActionContext) -> None:
        """Resolution keys off the registered resolver's id, not a hardcoded literal."""
        engine = PolicyEngine()
        engine.register(MockPolicy(policy_id="checker", decision="needs_review"))
        engine.register_resolver(MockPolicy(policy_id="custom.resolver", decision="allow"))

        result = engine.evaluate(write_context)
        assert result.final_decision == "allow"

    def test_deny_in_pass_one_skips_resolver(self, write_context: ActionContext) -> None:
        """A deny already blocks; the resolver is never invoked."""
        v = Violation(rule_id="det", message="blocked", severity="high")
        engine = PolicyEngine()
        engine.register(MockPolicy(policy_id="checker", decision="needs_review"))
        engine.register(MockPolicy(policy_id="det", decision="deny", violations=[v]))
        resolver = MockPolicy(policy_id="semantic.supervisor", decision="allow")
        engine.register_resolver(resolver)

        result = engine.evaluate(write_context)
        assert result.final_decision == "deny"
        assert resolver.evaluate_calls == 0

    def test_no_needs_review_skips_resolver(self, write_context: ActionContext) -> None:
        """No escalation -> the resolver never runs (the whole point of the hop)."""
        engine = PolicyEngine()
        engine.register(MockPolicy(policy_id="checker", decision="allow"))
        resolver = MockPolicy(policy_id="semantic.supervisor", decision="allow")
        engine.register_resolver(resolver)

        result = engine.evaluate(write_context)
        assert result.final_decision == "allow"
        assert resolver.evaluate_calls == 0

    def test_needs_review_without_resolver_blocks(self, write_context: ActionContext) -> None:
        """No resolver registered -> review stays unresolved (existing contract)."""
        engine = PolicyEngine()
        engine.register(MockPolicy(policy_id="checker", decision="needs_review"))

        result = engine.evaluate(write_context)
        assert result.final_decision == "needs_review"

    def test_resolver_returning_needs_review_blocks(self, write_context: ActionContext) -> None:
        """A resolver that itself returns needs_review composes to an unresolved block."""
        engine = PolicyEngine()
        engine.register(MockPolicy(policy_id="checker", decision="needs_review"))
        resolver = MockPolicy(policy_id="semantic.supervisor", decision="needs_review")
        engine.register_resolver(resolver)

        result = engine.evaluate(write_context)
        assert result.final_decision == "needs_review"
        assert resolver.evaluate_calls == 1  # ran once; no infinite hop

    def test_resolver_not_applicable_blocks_unresolved(self, write_context: ActionContext) -> None:
        """A non-applicable resolver appends no decision; review stays unresolved."""
        engine = PolicyEngine()
        engine.register(MockPolicy(policy_id="checker", decision="needs_review"))
        engine.register_resolver(MockPolicy(policy_id="semantic.supervisor", decision="allow", applies=False))

        result = engine.evaluate(write_context)
        assert result.final_decision == "needs_review"

    def test_resolver_error_fail_open_resolves_with_warning(self, write_context: ActionContext) -> None:
        """Resolver raise under fail-open -> allow-with-warning under the resolver's id resolves review."""

        class ErrorResolver(MockPolicy):
            def evaluate(self, context: ActionContext) -> PolicyDecision:
                raise RuntimeError("Boom!")

        engine = PolicyEngine(fail_mode="open")
        engine.register(MockPolicy(policy_id="checker", decision="needs_review"))
        engine.register_resolver(ErrorResolver(policy_id="semantic.supervisor"))

        result = engine.evaluate(write_context)
        assert result.final_decision == "allow"
        assert any("fail-open" in w for w in result.all_warnings)

    def test_resolver_error_fail_closed_denies(self, write_context: ActionContext) -> None:
        """Resolver raise under fail-closed -> deny."""

        class ErrorResolver(MockPolicy):
            def evaluate(self, context: ActionContext) -> PolicyDecision:
                raise RuntimeError("Boom!")

        engine = PolicyEngine(fail_mode="closed")
        engine.register(MockPolicy(policy_id="checker", decision="needs_review"))
        engine.register_resolver(ErrorResolver(policy_id="semantic.supervisor"))

        result = engine.evaluate(write_context)
        assert result.final_decision == "deny"

    def test_resolver_state_collected_and_restored(self, write_context: ActionContext) -> None:
        """A stateful resolver participates in state collection and restore."""
        engine = PolicyEngine()
        engine.register(MockPolicy(policy_id="checker", decision="needs_review"))
        resolver = StatefulMockPolicy(policy_id="semantic.supervisor", decision="allow")
        engine.register_resolver(resolver)

        engine.restore_state({"semantic.supervisor": {"count": 7}})
        assert resolver.state == {"count": 7}

        result = engine.evaluate(write_context)
        assert result.final_decision == "allow"
        assert engine.get_collected_state()["semantic.supervisor"] == {"count": 8}

    def test_short_circuit_does_not_repersist_stale_resolver_state(self, write_context: ActionContext) -> None:
        """Eval 2 without escalation must not carry eval 1's resolver state snapshot."""
        checker = MockPolicy(policy_id="checker", decision="needs_review")
        engine = PolicyEngine()
        engine.register(checker)
        resolver = StatefulMockPolicy(policy_id="semantic.supervisor", decision="allow")
        engine.register_resolver(resolver)

        engine.evaluate(write_context)
        assert "semantic.supervisor" in engine.get_collected_state()

        checker._decision = "allow"  # eval 2 short-circuits
        engine.evaluate(write_context)
        assert "semantic.supervisor" not in engine.get_collected_state()

    def test_registered_policy_ids_includes_resolver(self) -> None:
        """registered_policy_ids lists regular policies plus the resolver."""
        engine = PolicyEngine()
        engine.register(MockPolicy(policy_id="checker"))
        assert engine.registered_policy_ids == ["checker"]

        engine.register_resolver(MockPolicy(policy_id="semantic.supervisor"))
        assert engine.registered_policy_ids == ["checker", "semantic.supervisor"]


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
        from forge.policy.deterministic.tdd import TDDEnforcementPolicy

        tdd_policy = next(p for p in engine.policies if isinstance(p, TDDEnforcementPolicy))
        assert tdd_policy.strict is False

    def test_build_tdd_without_bundle_config(self) -> None:
        """Default TDD is strict when no bundle_config provided."""
        engine = build_engine(["tdd"])

        from forge.policy.deterministic.tdd import TDDEnforcementPolicy

        tdd_policy = next(p for p in engine.policies if isinstance(p, TDDEnforcementPolicy))
        assert tdd_policy.strict is True

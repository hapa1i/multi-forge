"""Policy composition engine.

The PolicyEngine evaluates multiple policies against an action and
composes their decisions using the "any deny blocks" rule.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from forge.core.state import now_iso
from forge.guard.protocols import Policy, StatefulPolicy
from forge.guard.types import (
    ActionContext,
    CompositeDecision,
    DecisionType,
    FailMode,
    PolicyDecision,
)

_log = logging.getLogger(__name__)


@dataclass
class PolicyEngine:
    """Composes multiple policies and produces a unified decision.

    Composition rules:
    - Policies are evaluated in registration order
    - Any deny blocks the action (unless fail_mode is "open" and it's an error)
    - needs_review is resolved by semantic supervisor when it participates
    - Warnings accumulate from all policies
    - State is collected from stateful policies for persistence

    Attributes:
        policies: List of registered policies
        fail_mode: Default behavior on policy errors ("open" = allow, "closed" = deny)
    """

    policies: list[Policy] = field(default_factory=list)
    fail_mode: FailMode = "open"

    # Collected state from stateful policies (for persistence)
    _collected_state: dict[str, dict[str, Any]] = field(default_factory=dict)

    def register(self, policy: Policy) -> None:
        """Register a policy with the engine."""
        self.policies.append(policy)
        _log.debug("Registered policy: %s", policy.policy_id)

    def restore_state(self, persisted_state: dict[str, Any] | None) -> None:
        """Restore state to all stateful policies.

        Called at the start of evaluation to restore state from the session manifest.

        Args:
            persisted_state: Dict mapping policy_id to state dict
        """
        if persisted_state is None:
            return

        for policy in self.policies:
            if isinstance(policy, StatefulPolicy):
                policy_state = persisted_state.get(policy.policy_id)
                if policy_state is not None:
                    try:
                        policy.set_state(policy_state)
                        _log.debug("Restored state for %s", policy.policy_id)
                    except Exception as e:
                        _log.warning("Failed to restore state for %s: %s", policy.policy_id, e)

    def get_collected_state(self) -> dict[str, dict[str, Any]]:
        """Get collected state from all stateful policies.

        Called after evaluation to persist state to the session manifest.

        Returns:
            Dict mapping policy_id to state dict
        """
        return self._collected_state.copy()

    def evaluate(self, context: ActionContext) -> CompositeDecision:
        """Evaluate all applicable policies and compose results.

        Args:
            context: The action being evaluated

        Returns:
            CompositeDecision with:
            - final_decision: allow/deny/warn/needs_review based on composition
            - decisions: individual policy decisions for debugging
            - blocking_violations: violations that caused deny
            - all_warnings: accumulated warnings
        """
        decisions: list[PolicyDecision] = []
        blocking_violations: list = []
        all_warnings: list[str] = []
        needs_review = False

        for policy in self.policies:
            # Check if policy applies
            try:
                if not policy.applies_to(context):
                    _log.debug(
                        "Policy %s does not apply to %s",
                        policy.policy_id,
                        context.tool_name,
                    )
                    continue
            except Exception as e:
                _log.warning("Policy %s.applies_to() failed: %s", policy.policy_id, e)
                if self.fail_mode == "closed":
                    decisions.append(
                        PolicyDecision(
                            decision="deny",
                            policy_id=policy.policy_id,
                            warnings=[f"Policy applies_to() failed (fail-closed): {e}"],
                        )
                    )
                continue

            # Evaluate policy
            try:
                decision = policy.evaluate(context)
                decision.evaluated_at = now_iso()
                decisions.append(decision)

                _log.debug(
                    "Policy %s evaluated: %s (%d violations)",
                    policy.policy_id,
                    decision.decision,
                    len(decision.violations),
                )

            except Exception as e:
                _log.warning("Policy %s.evaluate() failed: %s", policy.policy_id, e)
                if self.fail_mode == "open":
                    decisions.append(
                        PolicyDecision(
                            decision="allow",
                            policy_id=policy.policy_id,
                            warnings=[f"Policy evaluation failed (fail-open): {e}"],
                        )
                    )
                else:
                    decisions.append(
                        PolicyDecision(
                            decision="deny",
                            policy_id=policy.policy_id,
                            warnings=[f"Policy evaluation failed (fail-closed): {e}"],
                        )
                    )
                continue

            # Collect state from stateful policies
            if isinstance(policy, StatefulPolicy):
                try:
                    self._collected_state[policy.policy_id] = policy.get_state()
                except Exception as e:
                    _log.warning("Failed to get state from %s: %s", policy.policy_id, e)

        # Compose decisions
        final_decision: DecisionType = "allow"

        for d in decisions:
            all_warnings.extend(d.warnings)

            if d.decision == "deny":
                final_decision = "deny"
                blocking_violations.extend(d.violations)
            elif d.decision == "needs_review":
                needs_review = True
            elif d.decision == "warn" and final_decision == "allow":
                final_decision = "warn"

        review_resolved = any(d.policy_id == "semantic.supervisor" and d.decision != "needs_review" for d in decisions)

        # If any policy needs review and no supervisor resolved it, escalate.
        if needs_review and not review_resolved and final_decision not in ("deny",):
            final_decision = "needs_review"

        return CompositeDecision(
            final_decision=final_decision,
            decisions=decisions,
            blocking_violations=blocking_violations,
            all_warnings=all_warnings,
        )


def build_engine(
    bundles: list[str],
    fail_mode: FailMode = "open",
    bundle_config: dict[str, dict[str, Any]] | None = None,
) -> PolicyEngine:
    """Build a PolicyEngine with policies from the specified bundles.

    Args:
        bundles: List of bundle names (e.g., ["tdd", "coding_standards"])
        fail_mode: Behavior on policy errors
        bundle_config: Per-bundle configuration (e.g., {"tdd": {"strict": False}}).

    Returns:
        Configured PolicyEngine
    """
    from forge.guard.deterministic.registry import get_bundle_policies

    engine = PolicyEngine(fail_mode=fail_mode)

    for bundle in bundles:
        config = bundle_config.get(bundle) if bundle_config else None
        for policy in get_bundle_policies(bundle, config=config):
            engine.register(policy)

    return engine

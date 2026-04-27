"""Policy protocol definitions.

All policies (deterministic and semantic) implement these protocols,
enabling uniform composition in the PolicyEngine.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from forge.guard.types import ActionContext, PolicyDecision


@runtime_checkable
class Policy(Protocol):
    """Interface all policies must implement.

    Policies are evaluated against an ActionContext and return a PolicyDecision.
    The `applies_to` method enables filtering/short-circuiting before evaluation.

    Example:
        class MyPolicy:
            @property
            def policy_id(self) -> str:
                return "my-bundle.my-rule"

            def applies_to(self, context: ActionContext) -> bool:
                return context.tool_name == "Write"

            def evaluate(self, context: ActionContext) -> PolicyDecision:
                # Check something and return decision
                return PolicyDecision(decision="allow", policy_id=self.policy_id)
    """

    @property
    def policy_id(self) -> str:
        """Unique identifier for this policy (e.g., 'tdd.tests-before-impl')."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description of what this policy enforces."""
        ...

    def applies_to(self, context: ActionContext) -> bool:
        """Return True if this policy should evaluate the given action.

        Used for filtering/throttling before full evaluation. Policies that
        don't apply to the action should return False to skip evaluation.
        """
        ...

    def evaluate(self, context: ActionContext) -> PolicyDecision:
        """Evaluate the action and return a decision.

        For deterministic policies: synchronous, fast.
        For semantic policies: may invoke LLM (should be throttled).
        """
        ...


@runtime_checkable
class StatefulPolicy(Policy, Protocol):
    """Protocol for policies that track state across actions.

    Stateful policies (e.g., TDD's "tests touched before impl") need to
    persist state across hook invocations. Since hooks are short-lived
    processes, state is persisted to the session manifest.

    The PolicyEngine calls get_state() after evaluation to persist state,
    and set_state() at the start to restore it.

    Example:
        class TDDEnforcementPolicy:
            def __init__(self):
                self._tests_touched: set[str] = set()

            def get_state(self) -> dict[str, Any]:
                return {"tests_touched": list(self._tests_touched)}

            def set_state(self, state: dict[str, Any]) -> None:
                self._tests_touched = set(state.get("tests_touched", []))
    """

    def get_state(self) -> dict[str, Any]:
        """Return current policy state for persistence."""
        ...

    def set_state(self, state: dict[str, Any]) -> None:
        """Restore policy state from persisted data."""
        ...

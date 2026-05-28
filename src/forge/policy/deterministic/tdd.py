"""TDD bundle policies.

Enforces test-driven development workflow:
- tests-before-impl: Must touch tests before implementing in src/
- no-skip-tests: Blocks adding pytest.skip or similar patterns
"""

from __future__ import annotations

from typing import Any

from forge.policy.deterministic.base import (
    DeterministicPolicy,
    StatefulDeterministicPolicy,
)
from forge.policy.types import ActionContext, PolicyDecision, Violation

# Patterns that indicate test skipping
SKIP_PATTERNS = [
    r"pytest\.skip\(",
    r"@pytest\.mark\.skip\b",
    r"@pytest\.mark\.skipif\b",
    r"unittest\.skip\b",
    r"@unittest\.skip\b",
]


class TDDEnforcementPolicy(StatefulDeterministicPolicy):
    """Enforce that tests are touched before implementation code.

    State tracking:
    - When Write/Edit targets tests/, record path in tests_touched
    - When Write/Edit targets src/ and tests_touched is empty, deny (or warn)

    This policy is stateful because it needs to remember across hook invocations
    which test files have been touched in the current session.
    """

    def __init__(self, *, strict: bool = True) -> None:
        """Initialize the policy.

        Args:
            strict: If True, deny impl without tests. If False, warn only.
        """
        self.strict = strict
        self._tests_touched: set[str] = set()

    @property
    def policy_id(self) -> str:
        return "tdd.tests-before-impl"

    @property
    def description(self) -> str:
        mode = "strict" if self.strict else "permissive"
        return f"Require test changes before implementation changes ({mode} mode)"

    @property
    def intent(self) -> str:
        return (
            "Test-driven development: write tests first to define expected behavior, "
            "then implement. This catches design issues early and ensures every change "
            "has test coverage from the start."
        )

    def applies_to(self, context: ActionContext) -> bool:
        """Apply to Write/Edit on tests/ or src/ paths."""
        if context.tool_name not in ("Write", "Edit"):
            return False

        path = context.target_path
        if path is None:
            return False

        # Only care about tests/ and src/ directories
        return self._is_under_directory(path, "tests") or self._is_under_directory(path, "src")

    def _evaluate(self, context: ActionContext) -> PolicyDecision:
        """Evaluate the TDD workflow.

        Logic:
        1. If writing to tests/, record the path and allow
        2. If writing to src/ and no tests touched, deny (strict) or warn (permissive)
        3. Otherwise, allow
        """
        path = context.target_path
        if path is None:
            return self._allow()

        # Touching a test file - record it and allow
        if self._is_under_directory(path, "tests"):
            self._tests_touched.add(path)
            return self._allow()

        # Touching implementation - check if tests were touched first
        if self._is_under_directory(path, "src"):
            if not self._tests_touched:
                violation = Violation(
                    rule_id=self.policy_id,
                    message="Implementation changes require test changes first",
                    severity="high",
                    evidence=f"Writing to {path} without touching any test files",
                    suggested_fix="Write or update tests in tests/ directory before modifying src/ code",
                )

                if self.strict:
                    return self._deny([violation])
                else:
                    return self._warn([violation.message])

        return self._allow()

    def get_state(self) -> dict[str, Any]:
        """Return current state for persistence."""
        return {"tests_touched": list(self._tests_touched)}

    def set_state(self, state: dict[str, Any]) -> None:
        """Restore state from persisted data."""
        self._tests_touched = set(state.get("tests_touched", []))


class NoSkipTestsPolicy(DeterministicPolicy):
    """Block adding test skip patterns.

    Prevents:
    - pytest.skip()
    - @pytest.mark.skip
    - @pytest.mark.skipif
    - unittest.skip
    """

    @property
    def policy_id(self) -> str:
        return "tdd.no-skip-tests"

    @property
    def description(self) -> str:
        return "Block adding pytest.skip or similar test-skipping patterns"

    @property
    def intent(self) -> str:
        return (
            "Skipped tests hide broken functionality. Every test should either pass or "
            "be deleted. If a test cannot run, fix the environment or the code rather "
            "than skipping it."
        )

    def applies_to(self, context: ActionContext) -> bool:
        """Apply to Write/Edit with content that might contain skip patterns."""
        if context.tool_name not in ("Write", "Edit"):
            return False

        # Only check if there's content to analyze
        return context.new_content is not None

    def _evaluate(self, context: ActionContext) -> PolicyDecision:
        """Check for skip patterns in content."""
        matched = self._matches_any_pattern(context.new_content, SKIP_PATTERNS)

        if matched:
            violations = [
                Violation(
                    rule_id=self.policy_id,
                    message="Test skip patterns are not allowed",
                    severity="high",
                    evidence=f"Found skip pattern(s): {', '.join(matched)}",
                    suggested_fix="Remove the skip pattern and fix the underlying issue",
                )
            ]
            return self._deny(violations)

        return self._allow()

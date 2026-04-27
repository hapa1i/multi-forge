"""Base class for deterministic policies."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from forge.guard.types import ActionContext, PolicyDecision, Violation


class DeterministicPolicy(ABC):
    """Base class for deterministic (non-LLM) policies.

    Subclasses implement:
    - policy_id: Unique identifier (e.g., "tdd.tests-before-impl")
    - description: Human-readable description
    - intent: Why this policy exists (shown to models on deny so they
      understand the goal and surface conflicts instead of working around them)
    - _evaluate: The actual evaluation logic

    The base class provides:
    - Default applies_to() for Write/Edit filtering
    - Path normalization helpers
    - Common pattern matching utilities
    """

    @property
    @abstractmethod
    def policy_id(self) -> str:
        """Unique identifier for this policy."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description."""
        ...

    @property
    @abstractmethod
    def intent(self) -> str:
        """Why this policy exists.

        Shown to models on deny so they understand the goal behind the rule.
        This helps models surface conflicts to the user instead of finding
        creative workarounds that satisfy the letter but not the spirit.
        """
        ...

    def applies_to(self, context: ActionContext) -> bool:
        """Return True if this policy should evaluate the action.

        Default: applies to Write and Edit tools only.
        Override for more specific filtering.
        """
        return context.tool_name in ("Write", "Edit")

    def evaluate(self, context: ActionContext) -> PolicyDecision:
        """Evaluate the action and return a decision.

        Wraps _evaluate() with common setup. Subclasses override _evaluate().
        """
        return self._evaluate(context)

    @abstractmethod
    def _evaluate(self, context: ActionContext) -> PolicyDecision:
        """Implement policy-specific evaluation logic."""
        ...

    # --- Helper methods ---

    def _normalize_path(self, path: str | None, repo_root: str) -> str | None:
        """Normalize a path relative to repo root.

        Returns the path relative to repo_root, or None if path is None.
        """
        if path is None:
            return None

        try:
            abs_path = Path(path).resolve()
            root = Path(repo_root).resolve()
            return str(abs_path.relative_to(root))
        except (ValueError, RuntimeError):
            # Path not under repo root, return as-is
            return path

    def _is_under_directory(self, path: str | None, directory: str) -> bool:
        """Check if path is under a directory (e.g., 'tests/' or 'src/')."""
        if path is None:
            return False

        # Normalize separators and ensure consistent format
        normalized = path.replace("\\", "/")

        # Check if path starts with directory or contains /directory/
        return normalized.startswith(f"{directory}/") or f"/{directory}/" in normalized

    def _matches_any_pattern(self, content: str | None, patterns: list[str]) -> list[str]:
        """Return list of matched patterns from content.

        Args:
            content: Text to search
            patterns: List of regex patterns

        Returns:
            List of patterns that matched (empty if none)
        """
        if content is None:
            return []

        matched = []
        for pattern in patterns:
            if re.search(pattern, content, re.MULTILINE):
                matched.append(pattern)

        return matched

    def _allow(self) -> PolicyDecision:
        """Return an allow decision."""
        return PolicyDecision(decision="allow", policy_id=self.policy_id)

    def _deny(self, violations: list[Violation]) -> PolicyDecision:
        """Return a deny decision with violations and policy intent."""
        return PolicyDecision(
            decision="deny",
            policy_id=self.policy_id,
            violations=violations,
            intent=self.intent,
        )

    def _warn(self, warnings: list[str]) -> PolicyDecision:
        """Return a warn decision."""
        return PolicyDecision(
            decision="warn",
            policy_id=self.policy_id,
            warnings=warnings,
        )


class StatefulDeterministicPolicy(DeterministicPolicy):
    """Base class for deterministic policies that track state.

    State is persisted to the session manifest between hook invocations.
    Subclasses implement get_state() and set_state() for their specific state.
    """

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        """Return current state for persistence."""
        ...

    @abstractmethod
    def set_state(self, state: dict[str, Any]) -> None:
        """Restore state from persisted data."""
        ...

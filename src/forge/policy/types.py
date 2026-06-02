"""Type definitions for the Policy Engine.

All types are dataclasses for easy serialization and dacite compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Type aliases for clarity
DecisionType = Literal["allow", "deny", "warn", "needs_review"]
Severity = Literal["critical", "high", "medium", "low"]
FailMode = Literal["open", "closed"]


def extract_added_lines(diff_chunk: str) -> str:
    """Extract only the added lines from a unified diff chunk.

    Strips diff headers, context lines, and removed lines, returning only
    the content of ``+`` lines (with the ``+`` prefix removed). This makes
    on-demand diff content semantically consistent with hook-provided content
    (i.e., "what's being introduced", not "what's being removed").
    """
    lines = []
    for line in diff_chunk.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
    return "\n".join(lines)


@dataclass(frozen=True)
class ActionContext:
    """Normalized view of what a runtime is about to do.

    This is the input to all policy evaluations. A runtime's hook adapter (e.g.
    ``ClaudeHookAdapter``) normalizes that runtime's hook payload into this shape;
    ``PolicyEngine.evaluate`` is runtime-agnostic and does not branch on ``runtime``.

    Attributes:
        runtime: Which agent runtime produced this action ("claude_code" today;
            "codex"/"gemini" later). Required so the origin runtime is explicit at
            the adapter boundary, never silently assumed; flows into attribution.
        event: Hook event type (e.g., "PreToolUse.Write")
        tool_name: Tool being invoked (e.g., "Write", "Edit")
        tool_args: Raw tool input arguments from the runtime's hook payload
        repo_root: Absolute path to repository root
        session_name: Current Forge session name
        target_path: Normalized file path being modified (if applicable)
        new_content: Content being introduced — new file content (Write), new_string
            (Edit), or added lines extracted from a unified diff (on-demand check).
            Regex policies match against this field.
        raw_diff: Full unified diff chunk (on-demand checks only). Provides richer
            context for LLM-based policies. None for hook-triggered evaluations.
    """

    runtime: str
    event: str
    tool_name: str
    tool_args: dict[str, Any]
    repo_root: str
    session_name: str
    target_path: str | None = None
    new_content: str | None = None
    raw_diff: str | None = None


@dataclass
class Violation:
    """A single policy violation.

    Attributes:
        rule_id: Unique identifier (e.g., "tdd.tests-before-impl")
        message: Human-readable explanation
        severity: How serious this violation is
        evidence: What triggered this violation (code snippet, etc.)
        suggested_fix: How to resolve the violation
        citations: For semantic policies, quoted plan sections that were violated
    """

    rule_id: str
    message: str
    severity: Severity
    evidence: str | None = None
    suggested_fix: str | None = None
    citations: list[str] = field(default_factory=list)


@dataclass
class PolicyDecision:
    """Result of a single policy evaluation.

    Attributes:
        decision: The policy's verdict. ``needs_review`` must be resolved by
            semantic supervision before a hook allows the action.
        policy_id: Which policy made this decision
        violations: List of violations found (for deny/warn decisions)
        warnings: Non-blocking warnings to display
        intent: Why the policy exists (shown on deny to help models understand
            the goal and surface conflicts instead of working around them)
        cached: Whether this was a cached verdict (for debugging)
        evaluated_at: ISO8601 timestamp when evaluated (for logging)
    """

    decision: DecisionType
    policy_id: str
    violations: list[Violation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    intent: str | None = None
    cached: bool = False
    evaluated_at: str | None = None


@dataclass
class CompositeDecision:
    """Result of composing multiple policies.

    The PolicyEngine evaluates all applicable policies and composes
    their decisions using the "any deny blocks" rule.

    Attributes:
        final_decision: Composed result (any deny → deny)
        decisions: Individual policy decisions for debugging
        blocking_violations: Violations that caused the deny
        all_warnings: Accumulated warnings from all policies
    """

    final_decision: DecisionType
    decisions: list[PolicyDecision] = field(default_factory=list)
    blocking_violations: list[Violation] = field(default_factory=list)
    all_warnings: list[str] = field(default_factory=list)

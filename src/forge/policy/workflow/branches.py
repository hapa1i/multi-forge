"""Branch routing for WorkflowPolicy.

A branch is a routing target selected by tag match. It contains
optional stages (filter → checker → reviewer) that execute in order.
"""

from __future__ import annotations

from dataclasses import dataclass

from forge.policy.types import ActionContext, PolicyDecision
from forge.policy.workflow.config import BranchConfig
from forge.policy.workflow.stages import CheckerStage, FilterStage, ReviewerStage


@dataclass
class Branch:
    """A routing target selected by tag match."""

    name: str
    match_tags: list[str]
    match_mode: str
    filter: FilterStage | None
    checker: CheckerStage | None
    reviewer: ReviewerStage | None

    @classmethod
    def from_config(cls, config: BranchConfig) -> Branch:
        """Instantiate stages from config."""
        return cls(
            name=config.name,
            match_tags=config.match_tags,
            match_mode=config.match_mode,
            filter=FilterStage(config.filter) if config.filter else None,
            checker=CheckerStage(config.checker) if config.checker else None,
            reviewer=ReviewerStage(config.reviewer) if config.reviewer else None,
        )

    def matches(self, tags: list[str]) -> bool:
        """Return True if tags match this branch."""
        if not self.match_tags:
            return False
        if self.match_mode == "all":
            return all(t in tags for t in self.match_tags)
        return any(t in tags for t in self.match_tags)

    def execute(self, context: ActionContext, tags: list[str], policy_id: str) -> PolicyDecision:
        """Run stages in order: filter → checker → reviewer.

        - filter fails (passes()=False) → allow
        - checker returns allow → short-circuit
        - checker returns None → continue to reviewer
        - reviewer returns final decision
        - No stages configured → allow
        """
        if self.filter and not self.filter.passes(context):
            return PolicyDecision(decision="allow", policy_id=policy_id)

        if self.checker:
            result = self.checker.check(context, tags, policy_id)
            if result is not None:
                return result

        if self.reviewer:
            return self.reviewer.review(context, tags, policy_id)

        return PolicyDecision(decision="allow", policy_id=policy_id)

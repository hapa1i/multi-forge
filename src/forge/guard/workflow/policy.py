"""WorkflowPolicy — composable tagger → branch → stage pipeline.

Plugs into the existing PolicyEngine via bundle registration.
Zero engine changes required.
"""

from __future__ import annotations

import logging
from typing import Any

from forge.core.reactive import ThrottleCache, compute_cache_key, tag_action
from forge.guard.deterministic.base import StatefulDeterministicPolicy
from forge.guard.types import ActionContext, PolicyDecision
from forge.guard.workflow.branches import Branch
from forge.guard.workflow.config import WorkflowConfig

_log = logging.getLogger(__name__)


class WorkflowPolicy(StatefulDeterministicPolicy):
    """Composable tagger → branch → stage pipeline.

    Pipeline:
    1. Cache check (ThrottleCache) — reuse recent verdicts
    2. Tag (tag_action) — classify action via cheap LLM
    3. Route (Branch.matches) — first-match by tags
    4. Execute (Branch.execute) — filter → checker → reviewer
    5. Cache result (clean allows only)
    """

    def __init__(self, config: WorkflowConfig) -> None:
        self._config = config
        self._cache = ThrottleCache(
            ttl_seconds=config.throttle_seconds,
            max_entries=config.max_cache_entries,
        )
        self._branches = [Branch.from_config(b) for b in config.branches]

    @property
    def policy_id(self) -> str:
        return f"workflow.{self._config.name}"

    @property
    def description(self) -> str:
        return self._config.description

    @property
    def intent(self) -> str:
        return self._config.intent

    def applies_to(self, context: ActionContext) -> bool:
        return context.tool_name in self._config.tool_names

    def _evaluate(self, context: ActionContext) -> PolicyDecision:
        cache_key = compute_cache_key(context.tool_name, context.target_path, context.new_content)

        cached = self._cache.check(cache_key)
        if cached is not None:
            decision = self._allow()
            decision.cached = True
            return decision

        tags = tag_action(
            context,
            model=self._config.tagger_model,
            prompt_template=self._config.tagger_prompt,
        )

        for branch in self._branches:
            if branch.matches(tags):
                decision = branch.execute(context, tags, self.policy_id)
                if decision.decision == "deny":
                    decision.intent = self.intent
                if decision.decision == "allow" and not decision.warnings:
                    self._cache.update(cache_key, decision="allow", tags=tags)
                return decision

        # No branch matched → allow (not cached: tagger may have transiently
        # failed, and caching would suppress re-evaluation after recovery)
        return self._allow()

    def get_state(self) -> dict[str, Any]:
        return {"cache": self._cache.get_state()}

    def set_state(self, state: dict[str, Any]) -> None:
        self._cache.set_state(state.get("cache", {}))

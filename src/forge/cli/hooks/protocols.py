"""Runtime hook seam: adapter (payload -> ActionContext) + responder (decision -> wire).

Phase 4f makes the two Claude-specific halves of the policy-check hook explicit so a
future Codex equivalent can sit beside them, sharing the runtime-agnostic policy core
(``PolicyEngine.evaluate``):

- A :class:`HookAdapter` normalizes a runtime's hook payload into an ``ActionContext``
  (the engine input). ``ClaudeHookAdapter`` is the only implementation today;
  ``CodexHookAdapter`` is Phase 6.
- A :class:`HookResponder` serializes a composed ``CompositeDecision`` back into that
  runtime's hook wire contract (exit codes, block message, allow output).

These are structural ``Protocol``s -- adapters/responders need only match the shape, not
inherit. They are forward-looking: the second implementation lands with Codex (Phase 6).
"""

from __future__ import annotations

from typing import Any, Protocol

from forge.policy.types import ActionContext, CompositeDecision


class HookAdapter(Protocol):
    """Normalizes a runtime's hook payload into a policy-engine ``ActionContext``.

    The input shape is runtime-specific (Claude's ``tool_input`` keys differ from
    Codex's); the output is the normalized, runtime-tagged context the engine consumes.
    """

    def build_context(self, payload: dict[str, Any], tool_name: str, manifest: Any) -> ActionContext | None:
        """Build an ``ActionContext`` from a hook ``payload``, or None if unbuildable."""
        ...


class HookResponder(Protocol):
    """Serializes a composed policy decision into a runtime's hook wire response.

    The Claude contract is exit-code + stderr (block) / optional stdout JSON (allow);
    a Codex responder would map the same ``CompositeDecision`` onto Codex's wire shape.
    """

    def format_deny(self, result: CompositeDecision) -> str:
        """Render the block message shown to the agent on a deny."""
        ...

    def format_needs_review(self, result: CompositeDecision) -> str:
        """Render the block message for an unresolved ``needs_review``."""
        ...

    def allow_feedback(self, additional_context: str) -> dict[str, Any]:
        """Build the allow-path feedback payload carrying ``additional_context``."""
        ...

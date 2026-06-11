"""Runtime hook seam: adapter (payload -> ActionContexts) + responder (decision -> wire).

The two runtime-specific halves of a policy-check hook are explicit so each runtime's
pair sits beside the others, sharing the runtime-agnostic policy core
(``PolicyEngine.evaluate``):

- A :class:`HookAdapter` normalizes a runtime's hook payload into ``ActionContext``s
  (the engine input). ``ClaudeHookAdapter`` (cli/hooks/policy.py) and
  ``CodexHookAdapter`` (cli/hooks/codex_policy.py) are the implementations.
- A :class:`HookResponder` serializes a composed ``CompositeDecision`` back into that
  runtime's hook wire contract. Claude blocks via exit 2 + stderr;
  Codex blocks via a ``hookSpecificOutput`` JSON on stdout with exit 0.

These are structural ``Protocol``s -- adapters/responders need only match the shape,
not inherit.
"""

from __future__ import annotations

from typing import Any, Protocol

from forge.policy.types import ActionContext, CompositeDecision


class HookAdapter(Protocol):
    """Normalizes a runtime's hook payload into policy-engine ``ActionContext``s.

    The input shape is runtime-specific (Claude's ``tool_input`` keys differ from
    Codex's); the output is the normalized, origin-tagged contexts the engine
    consumes. Returns a list because one runtime action can carry several file
    operations (a Codex apply_patch envelope); Claude tools yield at most one.
    An empty list means "nothing evaluable" -- the hook command fails open.
    """

    def build_contexts(self, payload: dict[str, Any], tool_name: str, manifest: Any) -> list[ActionContext]:
        """Build ``ActionContext``s from a hook ``payload`` ([] if unbuildable)."""
        ...


class HookResponder(Protocol):
    """Serializes a composed policy decision into a runtime's hook wire response.

    The Claude contract is exit-code + stderr (block) / optional stdout JSON (allow);
    the Codex contract is strict stdout JSON (block) with exit 0.
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

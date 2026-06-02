"""Policy check helpers for the PreToolUse policy-check hook."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.core.state import now_iso
from forge.policy.types import ActionContext, CompositeDecision
from forge.session import SessionStore
from forge.session.models import SessionState
from forge.session.store import HOOK_LOCK_TIMEOUT_S


class ClaudeHookAdapter:
    """Normalize a Claude Code hook payload into an ``ActionContext`` (runtime="claude_code").

    The Claude-specific half of the hook seam (see ``protocols.HookAdapter``): it knows
    Claude's ``tool_input`` keys (``file_path``/``path``, ``content``/``new_string``) and
    tags every context ``runtime="claude_code"``. The policy engine consumes the
    normalized result with no Claude knowledge -- a ``CodexHookAdapter`` (Phase 6) sits
    beside this one, producing the same ``ActionContext`` from Codex's payload shape.
    """

    RUNTIME = "claude_code"

    def build_context(self, payload: dict[str, Any], tool_name: str, manifest: Any) -> ActionContext | None:
        """Build an ``ActionContext`` from a Claude PreToolUse payload, or None if unbuildable."""
        tool_input = payload.get("tool_input", {})
        if not isinstance(tool_input, dict):
            return None

        target_path = tool_input.get("file_path") or tool_input.get("path")
        if not isinstance(target_path, str):
            target_path = None

        cwd = Path.cwd().resolve()
        if target_path:
            try:
                p = Path(target_path)
                if p.is_absolute():
                    target_path = str(p.relative_to(cwd))
            except (ValueError, RuntimeError):
                # Keep as-is if can't make relative
                pass

        new_content = None
        if tool_name == "Write":
            new_content = tool_input.get("content")
        elif tool_name == "Edit":
            new_content = tool_input.get("new_string")

        if new_content and len(new_content) > 5000:
            new_content = new_content[:5000] + "\n... (truncated)"

        return ActionContext(
            runtime=self.RUNTIME,
            event=f"PreToolUse.{tool_name}",
            tool_name=tool_name,
            tool_args=tool_input,
            repo_root=str(cwd),
            session_name=manifest.name,
            target_path=target_path,
            new_content=new_content,
        )


class ClaudeHookResponder:
    """Serialize a composed policy decision into Claude Code's PreToolUse wire contract.

    Claude reads a block reason from stderr on exit :attr:`BLOCK_EXIT` (2) and continues
    on :attr:`ALLOW_EXIT` (0); the allow path may emit a ``hookSpecificOutput`` JSON. This
    responder owns ONLY that runtime wire shape (see ``protocols.HookResponder``) -- the
    Forge summary/warning overlay (telemetry) stays in the hook command. A
    ``CodexHookResponder`` (Phase 6) maps the same ``CompositeDecision`` onto Codex's wire.
    """

    BLOCK_EXIT = 2
    ALLOW_EXIT = 0

    # Appended once per denying policy so the agent satisfies the intent instead of
    # bypassing the check.
    _DENY_NOTE = (
        "    Note: This policy was configured by the project owner. First"
        " try a compliant approach that satisfies the intent above. If the"
        " user's request cannot be fulfilled without violating the intent,"
        " explain the conflict and ask how to proceed. Do not attempt"
        " bypasses that pass the check but defeat the goal."
    )

    def format_deny(self, result: CompositeDecision) -> str:
        """Render the stderr block message for a deny (violations + intent + fix + note)."""
        lines = ["Policy violation(s):"]
        for d in result.decisions:
            if d.decision != "deny":
                continue
            for i, v in enumerate(d.violations):
                lines.append(f"  [{v.rule_id}] {v.message}")
                if d.intent and i == 0:
                    lines.append(f"    Intent: {d.intent}")
                if v.suggested_fix:
                    lines.append(f"    Fix: {v.suggested_fix}")
            lines.append(self._DENY_NOTE)
        return "\n".join(lines)

    def format_needs_review(self, result: CompositeDecision) -> str:
        """Render the stderr block message for an unresolved ``needs_review``."""
        lines = ["Policy review required but no semantic supervisor resolved it:"]
        for d in result.decisions:
            if d.decision == "needs_review":
                lines.append(f"  [{d.policy_id}] requested review")
                if d.intent:
                    lines.append(f"    Intent: {d.intent}")
        lines.append(
            "    Configure a supervisor for this session or ask the user how to proceed before making this change."
        )
        return "\n".join(lines)

    def allow_feedback(self, additional_context: str) -> dict[str, Any]:
        """Build the allow-path ``hookSpecificOutput`` JSON carrying ``additional_context``."""
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "additionalContext": additional_context,
            }
        }


def _persist_policy_state(
    *,
    store: SessionStore,
    engine: Any,
    result: Any,
    effective: Any,
    context_summary: str,
) -> None:
    """Persist policy state updates to session manifest.

    Updates decision log and generic policy_states from stateful policies.
    """
    from forge.policy.store import build_policy_state_update
    from forge.session.models import PolicyConfirmed

    collected_state = engine.get_collected_state()

    def _mutate(m: object) -> None:
        if not isinstance(m, SessionState):
            raise TypeError(f"Expected SessionState, got {type(m)}")

        existing = None
        if m.confirmed.policy:
            existing = {
                "decisions": m.confirmed.policy.decisions,
                "policy_states": m.confirmed.policy.policy_states,
                "forge_version": m.confirmed.policy.forge_version,
                "bundles": m.confirmed.policy.bundles,
                "rules_active": m.confirmed.policy.rules_active,
            }

        updated = build_policy_state_update(
            result=result,
            engine_state=collected_state,
            existing_state=existing,
            bundles=effective.policy.bundles if effective.policy else [],
            rules_active=[p.policy_id for p in engine.policies],
            context_summary=context_summary,
        )

        m.confirmed.policy = PolicyConfirmed(
            forge_version=updated.get("forge_version"),
            bundles=updated.get("bundles", []),
            rules_active=updated.get("rules_active", []),
            decisions=updated.get("decisions", []),
            policy_states=updated.get("policy_states", {}),
        )

        m.confirmed.confirmed_at = now_iso()
        m.confirmed.confirmed_by = "hook:policy-check"

    store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=_mutate)


def _derive_policy_source_label(result: Any, effective: Any) -> str:
    """Derive source label from the most relevant policy for the outcome.

    For deny: the first denying policy (the blocker).
    For non-deny: prefer the supervisor if it participated (the expensive check),
    fall back to the first matching deterministic policy.
    """
    sup = effective.policy.supervisor if effective.policy else None
    sup_resume_id = sup.resume_id if sup else None

    if result.final_decision == "deny":
        for d in result.decisions:
            if d.decision == "deny":
                if d.policy_id == "semantic.supervisor" and sup_resume_id:
                    return f"'{sup_resume_id}'"
                return d.policy_id
    else:
        # Non-deny: prefer supervisor if it evaluated
        for d in result.decisions:
            if d.policy_id == "semantic.supervisor":
                if sup_resume_id:
                    return f"'{sup_resume_id}'"
                return d.policy_id
        # No supervisor — use first decision with matching outcome
        for d in result.decisions:
            if d.decision == result.final_decision:
                return d.policy_id

    return "policy"

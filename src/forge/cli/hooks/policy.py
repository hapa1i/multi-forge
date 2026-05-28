"""Policy check helpers for the PreToolUse policy-check hook."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.core.state import now_iso
from forge.session import SessionStore
from forge.session.models import SessionState
from forge.session.store import HOOK_LOCK_TIMEOUT_S


def _build_action_context(
    data: dict[str, Any],
    tool_name: str,
    manifest: Any,
) -> Any | None:
    """Build ActionContext from hook payload.

    Args:
        data: Hook JSON payload
        tool_name: "Write" or "Edit"
        manifest: Session manifest

    Returns:
        ActionContext or None if required fields missing
    """
    from forge.policy.types import ActionContext

    tool_input = data.get("tool_input", {})
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
        event=f"PreToolUse.{tool_name}",
        tool_name=tool_name,
        tool_args=tool_input,
        repo_root=str(cwd),
        session_name=manifest.name,
        target_path=target_path,
        new_content=new_content,
    )


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

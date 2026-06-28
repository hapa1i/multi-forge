"""Policy check helpers for the PreToolUse policy-check hook."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.core.state import now_iso
from forge.policy.types import ActionContext, CompositeDecision
from forge.session import SessionStore
from forge.session.models import LaneRecord, SessionState
from forge.session.store import HOOK_LOCK_TIMEOUT_S


class ClaudeHookAdapter:
    """Normalize a Claude Code hook payload into ``ActionContext``s (origin="claude_code").

    The Claude-specific half of the hook seam (see ``protocols.HookAdapter``): it knows
    Claude's ``tool_input`` keys (``file_path``/``path``, ``content``/``new_string``) and
    tags every context ``origin="claude_code"``. The policy engine consumes the
    normalized result with no Claude knowledge -- ``CodexHookAdapter``
    (cli/hooks/codex_policy.py) sits beside this one, producing the same shape from
    Codex's payload. Claude tools are single-file, so the list carries at most one
    context (the list cardinality exists for multi-file apply_patch envelopes).
    """

    ORIGIN = "claude_code"

    def build_contexts(self, payload: dict[str, Any], tool_name: str, manifest: Any) -> list[ActionContext]:
        """Build ``ActionContext``s from a Claude PreToolUse payload ([] if unbuildable)."""
        tool_input = payload.get("tool_input", {})
        if not isinstance(tool_input, dict):
            return []

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

        return [
            ActionContext(
                origin=self.ORIGIN,
                event=f"PreToolUse.{tool_name}",
                tool_name=tool_name,
                tool_args=tool_input,
                repo_root=str(cwd),
                session_name=manifest.name,
                target_path=target_path,
                new_content=new_content,
            )
        ]


# Appended once per denying policy so the agent satisfies the intent instead of
# bypassing the check.
_DENY_NOTE = (
    "    Note: This policy was configured by the project owner. First"
    " try a compliant approach that satisfies the intent above. If the"
    " user's request cannot be fulfilled without violating the intent,"
    " explain the conflict and ask how to proceed. Do not attempt"
    " bypasses that pass the check but defeat the goal."
)


def format_deny_text(result: CompositeDecision) -> str:
    """Compose the deny reason text (violations + intent + fix + note).

    Runtime-neutral: Claude delivers it via stderr, Codex inside the deny JSON's
    ``permissionDecisionReason``. Each responder owns only the wire framing.
    """
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
        lines.append(_DENY_NOTE)
    return "\n".join(lines)


def format_needs_review_text(result: CompositeDecision) -> str:
    """Compose the unresolved-``needs_review`` reason text (runtime-neutral)."""
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


class ClaudeHookResponder:
    """Serialize a composed policy decision into Claude Code's PreToolUse wire contract.

    Claude reads a block reason from stderr on exit :attr:`BLOCK_EXIT` (2) and continues
    on :attr:`ALLOW_EXIT` (0); the allow path may emit a ``hookSpecificOutput`` JSON. This
    responder owns ONLY that runtime wire shape (see ``protocols.HookResponder``) -- the
    Forge summary/warning overlay (telemetry) stays in the hook command.
    ``CodexHookResponder`` (cli/hooks/codex_policy.py) maps the same
    ``CompositeDecision`` onto Codex's stdout-JSON wire.
    """

    BLOCK_EXIT = 2
    ALLOW_EXIT = 0

    def format_deny(self, result: CompositeDecision) -> str:
        """Render the stderr block message for a deny (violations + intent + fix + note)."""
        return format_deny_text(result)

    def format_needs_review(self, result: CompositeDecision) -> str:
        """Render the stderr block message for an unresolved ``needs_review``."""
        return format_needs_review_text(result)

    def allow_feedback(self, additional_context: str) -> dict[str, Any]:
        """Build the allow-path ``hookSpecificOutput`` JSON carrying ``additional_context``."""
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "additionalContext": additional_context,
            }
        }


def build_hook_engine(effective: Any) -> Any:
    """Build the policy engine from effective intent (bundles, fail_mode, bundle_config).

    Raises on any build failure; hook commands catch and fail open with their own
    stderr note. Supervisor registration is separate (``register_supervisor_and_restore``).
    """
    from forge.policy.engine import build_engine
    from forge.policy.types import FailMode

    fail_mode: FailMode = effective.policy.fail_mode or "open"
    bundles = effective.policy.bundles or []
    bundle_config: dict[str, dict[str, Any]] = {}
    if effective.policy and effective.policy.bundle_config:
        bundle_config = effective.policy.bundle_config
    return build_engine(bundles, fail_mode=fail_mode, bundle_config=bundle_config or None)


def register_supervisor_and_restore(engine: Any, effective: Any, manifest: Any) -> LaneRecord | None:
    """Register the semantic supervisor (cascade-aware) and restore persisted state.

    Registration precedes ``restore_state`` so cached supervisor/plan-check state is
    restored into the registered policy instances.

    Returns the supervisor's injected consumer-lane binding (None when no supervisor is
    configured, or when it resolves to the default lane). The caller threads this same
    value into the post-eval freeze so the binding records the lane that actually
    dispatched -- not a fresh manifest read that could race a concurrent intent change.
    """
    sup = effective.policy.supervisor if effective.policy else None
    has_supervisor = bool(sup and sup.resume_id and not sup.suspended)
    lane_record: LaneRecord | None = None
    if has_supervisor:
        from forge.policy.semantic.supervisor import (
            SUPERVISOR_CONSUMER,
            SemanticSupervisorPolicy,
        )
        from forge.session.consumer_lanes import read_bound_lane

        sup_cfg = effective.policy.supervisor
        # Inject the supervisor's consumer-lane binding (epic consumer_lanes, T1b). The hook holds
        # the manifest; the semantic module never reads the store. None => the default lane.
        lane_record = read_bound_lane(manifest, SUPERVISOR_CONSUMER)
        if sup_cfg and sup_cfg.cascade:
            # Cascade: the cheap tier-1 plan check runs on every event; the frontier
            # supervisor becomes the needs_review resolver (invoked only on escalation).
            from forge.policy.semantic.plan_check import PlanCheckPolicy

            engine.register(PlanCheckPolicy(config=sup_cfg, lane_record=lane_record))
            engine.register_resolver(SemanticSupervisorPolicy(config=sup_cfg, lane_record=lane_record))
        else:
            engine.register(SemanticSupervisorPolicy(config=sup_cfg, lane_record=lane_record))

    existing_policy_state = None
    if manifest.confirmed.policy:
        existing_policy_state = manifest.confirmed.policy.policy_states
    engine.restore_state(existing_policy_state)
    return lane_record


def _persist_policy_decisions(
    *,
    store: SessionStore,
    engine: Any,
    engine_state: dict[str, dict[str, Any]],
    entries: list[tuple[Any, str]],
    effective: Any,
    confirmed_by: str = "hook:policy-check",
    supervisor_lane: LaneRecord | None = None,
) -> None:
    """Persist one decision-log entry per (result, context_summary) pair in one write.

    ``engine_state`` is explicit because ``PolicyEngine.evaluate`` clears its
    collected state per call: a multi-file loop must aggregate across evaluations
    and pass the aggregate here (reading the engine at persist time would keep only
    the last file's state and drop e.g. TDD ``tests_touched`` from earlier files).
    The state merge is per-entry idempotent (same aggregate each iteration); the
    decision log grows by one entry per pair.

    Caller contract: pass ``engine_state={}`` when the evaluated action was BLOCKED
    (deny / unresolved needs_review) -- a blocked action never lands, so state
    collected from it (e.g. ``tests_touched`` from a test file riding in a denied
    patch) must not persist as if it did. ``build_policy_state_update`` merges
    per-policy-id, so ``{}`` preserves prior state while the decision-log entries
    (the audit trail of evaluations) still persist.
    """
    from forge.policy.store import build_policy_state_update
    from forge.session.models import PolicyConfirmed

    def _mutate(m: object) -> None:
        if not isinstance(m, SessionState):
            raise TypeError(f"Expected SessionState, got {type(m)}")

        state: dict[str, Any] | None = None
        if m.confirmed.policy:
            state = {
                "decisions": m.confirmed.policy.decisions,
                "policy_states": m.confirmed.policy.policy_states,
                "forge_version": m.confirmed.policy.forge_version,
                "bundles": m.confirmed.policy.bundles,
                "rules_active": m.confirmed.policy.rules_active,
            }

        for result, context_summary in entries:
            state = build_policy_state_update(
                result=result,
                engine_state=engine_state,
                existing_state=state,
                bundles=effective.policy.bundles if effective.policy else [],
                rules_active=engine.registered_policy_ids,
                context_summary=context_summary,
            )

        updated = state or {}
        m.confirmed.policy = PolicyConfirmed(
            forge_version=updated.get("forge_version"),
            bundles=updated.get("bundles", []),
            rules_active=updated.get("rules_active", []),
            decisions=updated.get("decisions", []),
            policy_states=updated.get("policy_states", {}),
        )

        m.confirmed.confirmed_at = now_iso()
        m.confirmed.confirmed_by = confirmed_by

        # Freeze the supervisor's consumer-lane binding write-if-absent (epic consumer_lanes, T1b):
        # the first policy-check hook that runs a configured supervisor records the lane it dispatched
        # as durable ground truth (the anchor the "already bound" reject checks). Folded into this
        # existing locked post-eval write -- no second lock. ``supervisor_lane`` is the lane the hook
        # injected at registration, so the freeze records exactly what dispatched even if intent
        # changed during the supervisor call (not a fresh read of this under-lock manifest).
        sup = effective.policy.supervisor if effective.policy else None
        if sup and sup.resume_id and not sup.suspended:
            from forge.policy.semantic.supervisor import SUPERVISOR_CONSUMER
            from forge.session.consumer_lanes import ensure_consumer_lane_binding

            ensure_consumer_lane_binding(m, SUPERVISOR_CONSUMER, supervisor_lane)

    store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=_mutate)


def _persist_policy_state(
    *,
    store: SessionStore,
    engine: Any,
    result: Any,
    effective: Any,
    context_summary: str,
    supervisor_lane: LaneRecord | None = None,
) -> None:
    """Persist policy state updates to session manifest (single-entry wrapper).

    A blocked action never lands (the hook denies the Write/Edit), so its collected
    policy state is dropped: e.g. a test write denied by tdd.no-skip-tests must not
    record ``tests_touched``, or a later impl-only write would wrongly pass
    tests-before-impl. The decision-log entry persists either way.
    """
    blocked = result.final_decision in ("deny", "needs_review")
    _persist_policy_decisions(
        store=store,
        engine=engine,
        engine_state={} if blocked else engine.get_collected_state(),
        entries=[(result, context_summary)],
        effective=effective,
        supervisor_lane=supervisor_lane,
    )


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

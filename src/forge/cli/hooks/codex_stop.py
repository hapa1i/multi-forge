"""Codex turn hooks, separate from Claude's Stop lifecycle.

Only a verified managed executor may create operational review state. A reviewer
or nested runtime inheriting FORGE_SESSION is not an executor admission proof.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from forge.cli.hooks._group import hooks
from forge.cli.hooks.codex_patch import parse_apply_patch
from forge.core.reactive.watchdog import exit_on_parent_death
from forge.core.runtime import codex_turn_enrollment
from forge.core.runtime.codex_feedback import (
    CODEX_EXECUTOR_IDENTITY_VAR,
    stop_review_supported,
)
from forge.policy.semantic import stop_review, turn_evidence
from forge.policy.semantic.deadline import stop_review_budget
from forge.policy.semantic.identity import validate_stop_executor
from forge.policy.semantic.supervisor import SUPERVISOR_CONSUMER
from forge.session.consumer_lanes import ensure_consumer_lane_binding, read_bound_lane
from forge.session.effective import compute_effective_intent
from forge.session.hooks.session_start import resolve_session_store
from forge.session.models import SessionState, session_runtime
from forge.session.store import SessionStore
from forge.session.workers import SESSION_INSTANCE_ENV, capture_session_instance

_log = logging.getLogger(__name__)
INPUT_BYTES = 512_000


@hooks.command("codex-turn-start", hidden=True)
def codex_turn_start() -> None:
    """Observe UserPromptSubmit before tool mutations."""
    _handle("UserPromptSubmit")


@hooks.command("codex-turn-tool", hidden=True)
def codex_turn_tool() -> None:
    """Observe tool outcomes, including shell writes and edit/revert actions."""
    _handle("PostToolUse")


@hooks.command("codex-stop", hidden=True)
@stop_review_budget
def codex_stop() -> None:
    """Review one frozen aggregate at most once per explicit turn."""
    _handle("Stop")


def observe_request(data: dict[str, Any] | None, *, denied: bool = False) -> None:
    """Add evidence to the turn without changing any deterministic policy decision."""
    if not data or data.get("hook_event_name") != "PreToolUse":
        return
    try:
        if codex_turn_enrollment.observe(data):
            return
        resolved = resolve_context(data)
        if resolved:
            context, _store = resolved
            stop_review.record_action(context, _action(data, "denied" if denied else "request", context))
    except Exception as exc:
        # Incomplete request/outcome coverage prevents a later clean review.
        _log.warning("Stop request evidence unavailable (%s)", type(exc).__name__)


def resolve_context(data: dict[str, Any]) -> tuple[stop_review.TurnContext, SessionStore] | None:
    """Resolve only the admitted executor, matching native thread and checkout."""
    if not stop_review_supported(os.environ):
        return None
    cwd = data.get("cwd")
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        raise ValueError("Missing executor checkout identity")
    checkout = Path(cwd).resolve(strict=True)
    store = resolve_session_store(checkout, session_id=None)
    if store is None:
        return None
    state = store.read()
    effective = compute_effective_intent(state)
    policy = effective.policy
    sup = policy.supervisor if policy else None
    if not policy or not policy.enabled or not sup or not sup.active or sup.review_trigger != "stop":
        return None
    identity = json.loads(os.environ[CODEX_EXECUTOR_IDENTITY_VAR])
    if not codex_turn_enrollment.verified(identity):
        raise ValueError("Stop hook enrollment is unverified; sync, trust and verify enrollment")
    validate_stop_executor(sup, runtime=session_runtime(state), sidecar=os.environ.get("FORGE_SIDECAR") == "1")
    expected = Path(state.worktree.path if state.worktree else state.forge_root or store.forge_root).resolve(
        strict=True
    )
    if checkout != expected:
        raise ValueError("Executor checkout does not match the managed session")
    confirmed = state.confirmed.codex
    if confirmed and confirmed.thread_id and confirmed.thread_id != data.get("session_id"):
        raise ValueError("Executor thread does not match the managed session")
    from forge.core.runtime.codex_review_source import boundary_from_hook

    context = stop_review.TurnContext(
        Path(store.forge_root),
        state.name,
        checkout,
        data.get("session_id", ""),
        data.get("turn_id", ""),
        sup,
        read_bound_lane(state, SUPERVISOR_CONSUMER),
        os.environ.get(SESSION_INSTANCE_ENV) or capture_session_instance(store.forge_root, state.name),
        native_boundary=boundary_from_hook(data, admitted=True) if sup.native_source else None,
    )
    return context, store


def _handle(event: str) -> None:
    expires = time.monotonic() + 55
    invoking_parent = os.getppid()
    try:
        raw = sys.stdin.read(INPUT_BYTES + 1)
        if len(raw.encode()) > INPUT_BYTES:
            raise ValueError("Unbounded hook input")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("hook_event_name") != event:
            return
        if codex_turn_enrollment.observe(data):
            return
        resolved = resolve_context(data)
        if resolved is None:
            return
        context, store = resolved
        if event == "UserPromptSubmit":
            stop_review.begin_turn(context, deadline=expires)
        elif event == "PostToolUse":
            stop_review.record_action(context, _action(data, "outcome", context))
        else:
            if type(data.get("stop_hook_active")) is not bool:
                raise ValueError("Unverified Stop continuation identity")

            def current_config() -> str:
                fresh = resolve_context(data)
                return fresh[0].config_digest if fresh else "inactive"

            with exit_on_parent_death(invoking_parent):
                outcome = stop_review.review_stop(context, deadline=expires, current_config=current_config)
            if outcome.decision is not None:
                _freeze_lane(store, context)
            from forge.cli.hooks.codex_policy_feedback import render_stop_feedback
            from forge.runtime_config import get_runtime_config

            config = get_runtime_config()
            wire = render_stop_feedback(
                outcome,
                source_only=config.codex_policy_feedback_format == "source-only",
                model_feedback=config.policy_summary_feedback == "on",
            )
            if wire:
                print(wire)
    except Exception as exc:
        # Arbitrary provider/path errors never enter a Stop block's user authority.
        _log.warning("Stop review hook unavailable (%s)", type(exc).__name__)
        if event == "Stop" and os.environ.get("FORGE_SESSION"):
            print(
                json.dumps(
                    {
                        "systemMessage": "Forge Stop review unavailable. Inspect forge policy supervisor status --json. No correction was requested."
                    }
                )
            )


def _action(data: dict[str, Any], phase: str, context: stop_review.TurnContext) -> dict[str, Any]:
    identity, tool = data.get("tool_use_id"), data.get("tool_name")
    if not isinstance(identity, str) or not identity or len(identity) > 200 or not isinstance(tool, str):
        raise ValueError("Missing bounded tool identity")
    action: dict[str, Any] = {"id": identity, "phase": phase, "turn_id": context.turn_id, "tool": tool}
    values = {"input": data.get("tool_input"), "response": data.get("tool_response") if phase == "outcome" else None}
    encoded = json.dumps(values, sort_keys=True)
    if len(encoded.encode()) > 6_000:
        action.update(evidence_sha256=turn_evidence.digest(values), coverage_issue="tool_evidence_byte_limit")
    else:
        action.update(values)
    if tool == "apply_patch":
        tool_input = data.get("tool_input")
        patch = tool_input.get("command") if isinstance(tool_input, dict) else None
        ops = parse_apply_patch(patch) if isinstance(patch, str) else None
        if not ops:
            action["coverage_issue"] = "malformed_patch_evidence"
        else:
            paths = [value for op in ops for value in (op.source_path, op.path) if value is not None]
            action["paths"] = []
            for value in paths:
                path = (context.checkout / value).resolve()
                if not path.is_relative_to(context.checkout) or ".forge" in path.relative_to(context.checkout).parts:
                    action["coverage_issue"] = "patch_outside_review_scope"
                else:
                    action["paths"].append(path.relative_to(context.checkout).as_posix())
    if len(json.dumps(action).encode()) > stop_review.MAX_ACTION_BYTES:
        action = {
            "id": identity,
            "phase": phase,
            "turn_id": context.turn_id,
            "tool": tool,
            "evidence_sha256": turn_evidence.digest(action),
            "coverage_issue": "tool_evidence_byte_limit",
        }
    return action


def _freeze_lane(store: SessionStore, context: stop_review.TurnContext) -> None:
    def mutate(state: SessionState) -> None:
        effective = compute_effective_intent(state)
        sup = effective.policy.supervisor if effective.policy else None
        if sup == context.config and read_bound_lane(state, SUPERVISOR_CONSUMER) == context.lane:
            ensure_consumer_lane_binding(state, SUPERVISOR_CONSUMER, context.lane)

    try:
        store.update(timeout_s=1, mutate=mutate, expected_instance_id=context.session_identity)
    except Exception as exc:
        _log.warning("Stop reviewer lane could not be frozen (%s)", type(exc).__name__)

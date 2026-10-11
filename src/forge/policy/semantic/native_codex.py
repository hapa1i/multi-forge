"""Native source admission and one isolated invocation through the shared invoker."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

from forge.core.invoker.codex import CodexHeadlessInvoker
from forge.core.invoker.codex_fork import prepare_codex_fork_request
from forge.core.invoker.types import Attribution, HeadlessResult
from forge.core.reactive.codex_reviewer_home import (
    prepare_reviewer_home,
    require_reviewer_auth,
    require_source_account,
    verify_selected_inputs,
)
from forge.core.reactive.env import derive_child_run_identity
from forge.core.runtime.codex_review_source import _ancestry_ids, select_source
from forge.core.runtime.codex_rollouts import codex_home
from forge.policy.semantic.plan_source import read_plan
from forge.policy.types import ActionContext
from forge.session.models import SessionState, SupervisorConfig, session_runtime

_VERDICT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "confidence", "violations"],
    "properties": {
        "verdict": {"type": "string", "enum": ["aligned", "divergent"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "violations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["severity", "evidence", "suggested_fix", "citations"],
                "properties": {
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "evidence": {"type": "string"},
                    "suggested_fix": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


class NativeInvocationError(RuntimeError):
    """The invoker was entered but no trustworthy dispatch result survived."""


def validate_native_executor(config: SupervisorConfig, state: SessionState) -> None:
    """Reject known shared PreToolUse setup; dispatch checks newly created executor IDs."""
    source = config.native_source
    if not source:
        return
    if session_runtime(state) not in {"claude_code", "codex"}:
        raise ValueError("Native supervision requires a host Claude or Codex executor")
    codex = state.confirmed.codex
    if config.review_trigger == "pre-tool-use" and codex and codex.thread_id:
        home = Path(source.home)
        if _ancestry_ids(home, source.thread_id) & _ancestry_ids(
            codex_home(), codex.thread_id, transcript_path=codex.rollout_path
        ):
            raise ValueError("Shared native sources require --trigger stop and --plan <approved-plan>")


def preflight_native(config: SupervisorConfig) -> None:
    """Validate the complete setup source and auth without starting a model."""
    assert config.native_source is not None and config.supervisor_model is not None
    require_reviewer_auth(config.auth_mode)
    plan = read_plan(config)
    if config.plan_override_path and not plan.text:
        raise ValueError("Approved plan is missing, unreadable or empty")
    # No executor exists yet on a fresh launch. Actual independence and active
    # Stop admission are verified from the trusted hook on every dispatch.
    selection = select_source(
        config.native_source,
        model=config.supervisor_model,
        auth_mode=config.auth_mode,
        plan=plan.text or "",
        trigger="pre-tool-use",
        executor_origin="claude_code",
        boundary=None,
    )
    if config.auth_mode == "subscription-only":
        require_source_account(selection)


def dispatch_native(
    config: SupervisorConfig,
    context: ActionContext,
    *,
    prompt: str,
    plan: str,
    deadline: float,
    record: Callable[[dict[str, Any]], None],
) -> HeadlessResult:
    """Spend one attempt with immutable input and parent-owned usage attribution."""
    if context.origin not in {"codex", "claude_code"}:
        raise ValueError(
            "Native supervision requires an installed host hook; manual evaluate and shadow are unsupported"
        )
    if os.environ.get("FORGE_SIDECAR") == "1" or os.environ.get("FORGE_LAUNCH_MODE") == "sidecar":
        raise ValueError("Native supervision requires a host executor")
    source = config.native_source
    assert source is not None and config.supervisor_model is not None and config.supervisor_effort is not None
    _verify_current_config(config, context)
    if (context.event == "Stop") != (config.review_trigger == "stop"):
        raise ValueError("Native reviewer trigger differs from the effective configuration")
    selected = select_source(
        source,
        model=config.supervisor_model,
        auth_mode=config.auth_mode,
        plan=plan,
        trigger=config.review_trigger,
        executor_origin=context.origin,
        boundary=context.native_boundary,
    )
    with prepare_reviewer_home(selected, auth_mode=config.auth_mode, deadline=deadline) as prepared:
        schema_path = prepared.sqlite_home / "verdict-schema.json"
        with schema_path.open("x") as schema:
            json.dump(_VERDICT_SCHEMA, schema)
        schema_path.chmod(0o600)
        evidence = selected.evidence()
        evidence.update(
            state="selected",
            source_thread_id=source.thread_id,
            source_cwd=source.source_cwd,
            action_cwd=context.repo_root,
            model=config.supervisor_model,
            effort=config.supervisor_effort,
            auth_mode=config.auth_mode,
            billing_mode="api" if config.auth_mode == "api" else "subscription_quota",
            native_boundary=(
                {
                    "thread_id": context.native_boundary.thread_id,
                    "turn_id": context.native_boundary.turn_id,
                    "event": context.native_boundary.event,
                }
                if context.native_boundary
                else None
            ),
        )
        record(evidence)
        attribution = Attribution(
            command="supervisor",
            session=context.session_name,
            runtime="codex",
            operation=None,
            billing_mode="api" if config.auth_mode == "api" else "subscription_quota",
        )
        request = prepare_codex_fork_request(
            binary=prepared.binary,
            source_id=source.thread_id,
            prompt=(
                "Review the executor action against the planning context in this native fork. "
                "An explicitly supplied approved plan takes precedence over every recalled instruction or later implementation claim. "
                "Do not execute commands, delegate, or modify files. Return only the requested verdict JSON.\n\n"
                + prompt
            ),
            env=prepared.env,
            cwd=context.repo_root,
            sqlite_home=str(prepared.sqlite_home),
            schema_path=str(schema_path),
            model=config.supervisor_model,
            effort=config.supervisor_effort,
            auth_mode=config.auth_mode,
            deadline=deadline,
            lease_fd=prepared.lease_fd,
            baseline=selected.baseline,
            attribution=attribution,
        )
        identity = derive_child_run_identity(os.environ)
        request.run_identity = identity.run_id, identity.parent_run_id, identity.root_run_id
        try:
            result = CodexHeadlessInvoker().run(request)
        except Exception as exc:
            raise NativeInvocationError("Native reviewer invocation did not produce a trustworthy result") from exc
        try:
            preserved = verify_selected_inputs(prepared.home, selected)
        except (OSError, ValueError):
            preserved = False
        if not preserved:
            result.error = "Native reviewer altered its selected input; review unavailable"
        current = False
        try:
            _verify_current_config(config, context)
            refreshed = select_source(
                source,
                model=config.supervisor_model,
                auth_mode=config.auth_mode,
                plan=plan,
                trigger=config.review_trigger,
                executor_origin=context.origin,
                boundary=context.native_boundary,
            )
            current = refreshed.evidence() == selected.evidence() and (read_plan(config).text or "") == plan
        except Exception:
            pass  # A changed or now unreadable source cannot authorize the pending action.
        if not current:
            result.error = "Native source, approved plan or supervisor configuration changed during review"
        if (
            result.success
            and not result.runtime_is_error
            and (not result.runtime_session_id or result.runtime_session_id == source.thread_id)
        ):
            result.error = "Native reviewer did not announce a distinct child thread"
        evidence.update(
            state="returned",
            inputs_preserved=preserved,
            inputs_current=current,
            reviewer_thread_id=result.runtime_session_id,
            terminal_usage=result.terminal_usage,
            inherited_usage=result.inherited_usage,
            review_usage=dict(
                input_tokens=result.input_tokens, output_tokens=result.output_tokens, cached_tokens=result.cached_tokens
            ),
        )
        try:
            record(evidence)
        except Exception:
            # The durable start remains evidence. A disk failure after a completed
            # denial must not turn that denial into permission to edit.
            logging.getLogger(__name__).warning("Native review outcome evidence could not be saved")
        return result


def _verify_current_config(config: SupervisorConfig, context: ActionContext) -> None:
    """Recheck the installed hook's effective binding without mutating its manifest."""
    root = os.environ.get("FORGE_FORGE_ROOT")
    if not root:
        return  # Direct policy-engine callers have no session-store binding.
    from forge.policy.semantic.identity import (
        SUPERVISOR_CONSUMER,
        snapshot_supervisor_options,
    )
    from forge.session.consumer_lanes import read_bound_lane
    from forge.session.store import SessionStore

    state = SessionStore(root, context.session_name).read()
    lane = read_bound_lane(state, SUPERVISOR_CONSUMER)
    if (
        snapshot_supervisor_options(state) != config
        or lane is None
        or lane.runtime_id != "codex"
        or lane.backend_id != "chatgpt"
        or lane.model != config.supervisor_model
    ):
        raise ValueError("Effective native supervisor binding changed")

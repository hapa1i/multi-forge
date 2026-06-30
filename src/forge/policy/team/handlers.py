"""Team hook handler logic for TeammateIdle and TaskCompleted.

Handlers return ``(exit_code, stderr_message)``:
- ``(0, "")`` = allow (teammate goes idle / task marked completed)
- ``(2, "feedback")`` = block (teammate continues / task stays open)

All errors fail-open (return 0). Uses file-backed cache at
``~/.forge/team-hooks/<session_id>.json`` for throttle + escape hatch.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from forge.core.lanes import Consumer, Lane
from forge.core.reactive.proxy import lookup_proxy_base_url
from forge.core.reactive.session_runner import run_claude_session
from forge.core.reactive.structured_output import extract_json_from_response
from forge.core.state import now_iso
from forge.policy.team.config import TeamSupervisorConfig
from forge.policy.team.prompts import (
    IDLE_TAGGER_PROMPT,
    TASK_TAGGER_PROMPT,
    TEAM_SUPERVISOR_PROMPT,
)

_log = logging.getLogger(__name__)


# Consumer-lane identity (epic consumer_lanes, T0): the team supervisor is a DISTINCT consumer
# from the semantic supervisor (different config/contract). claude-max is its only non-default
# lane (claude_code runtime, subscription posture); backend_id is load-bearing for billing only.
TEAM_SUPERVISOR_CONSUMER = Consumer(
    id="team_supervisor",
    capability_floor="tool_agent",
    default_lane=Lane(runtime_id="claude_code", backend_id="anthropic-direct", model="opus"),
    allowed_lanes=(Lane(runtime_id="claude_code", backend_id="claude-max", model="opus"),),
)


def handle_teammate_idle(
    data: dict[str, Any],
    config: TeamSupervisorConfig,
    cache: dict[str, Any],
    backend_id: str | None = None,
) -> tuple[int, str]:
    """Handle TeammateIdle event.

    Args:
        data: Raw hook event payload from Claude Code.
        config: Team supervisor configuration.
        cache: File-backed dict (loaded/saved by caller).

    Returns:
        ``(exit_code, stderr_feedback)``.
    """
    teammate = data.get("teammate_name") or "unknown"
    team = data.get("team_name") or "unknown"
    cache_key = f"{teammate}:idle"

    cached = cache.get(cache_key)
    if cached and _is_fresh(cached, config.throttle_seconds):
        return cached.get("exit_code", 0), cached.get("feedback", "")

    tag = _classify_event(config.tagger_model, IDLE_TAGGER_PROMPT, teammate, team)
    if tag != "needs-review":
        cache[cache_key] = {"checked_at": now_iso(), "exit_code": 0, "feedback": ""}
        return 0, ""

    if not config.resume_id:
        return 0, ""

    exit_code, feedback = _run_supervisor(config, teammate, team, "idle", "", backend_id=backend_id)
    cache[cache_key] = {
        "checked_at": now_iso(),
        "exit_code": exit_code,
        "feedback": feedback,
    }
    return exit_code, feedback


def handle_task_completed(
    data: dict[str, Any],
    config: TeamSupervisorConfig,
    cache: dict[str, Any],
    backend_id: str | None = None,
) -> tuple[int, str]:
    """Handle TaskCompleted event.

    Args:
        data: Raw hook event payload from Claude Code.
        config: Team supervisor configuration.
        cache: File-backed dict (loaded/saved by caller).

    Returns:
        ``(exit_code, stderr_feedback)``.
    """
    teammate = data.get("teammate_name") or "unknown"
    team = data.get("team_name") or "unknown"
    task_id = data.get("task_id") or "unknown"
    task_subject = data.get("task_subject")
    cache_key = f"{teammate}:{task_id}"

    cached = cache.get(cache_key, {})

    # Escape hatch: auto-allow after max_blocks_per_task
    if cached.get("block_count", 0) >= config.max_blocks_per_task:
        _log.info(
            "Escape hatch: auto-allowing %s after %d blocks",
            cache_key,
            config.max_blocks_per_task,
        )
        return 0, ""

    if _is_fresh(cached, config.throttle_seconds):
        return cached.get("exit_code", 0), cached.get("feedback", "")

    tag = _classify_event(config.tagger_model, TASK_TAGGER_PROMPT, teammate, team, task_subject)
    if tag != "needs-review":
        cache[cache_key] = {"checked_at": now_iso(), "exit_code": 0, "feedback": ""}
        return 0, ""

    if not config.resume_id:
        return 0, ""

    task_context = f"Task: {task_subject or 'unknown'} (id: {task_id})"
    exit_code, feedback = _run_supervisor(config, teammate, team, "task-completed", task_context, backend_id=backend_id)

    block_count = cached.get("block_count", 0) + (1 if exit_code == 2 else 0)
    cache[cache_key] = {
        "checked_at": now_iso(),
        "exit_code": exit_code,
        "feedback": feedback,
        "block_count": block_count,
    }
    return exit_code, feedback


def _is_fresh(entry: dict[str, Any], throttle_seconds: int) -> bool:
    """Return True if the cache entry is within the throttle window."""
    checked_at = entry.get("checked_at")
    if not checked_at:
        return False
    try:
        checked_time = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - checked_time).total_seconds()
        return age < throttle_seconds
    except (ValueError, TypeError):
        return False


def _classify_event(
    model: str,
    prompt_template: str,
    teammate: str,
    team: str,
    task_subject: str | None = None,
) -> str:
    """Classify event via cheap LLM call. Returns single tag string."""
    # The handler carries no Forge session, so attribute to FORGE_SESSION when the hook set
    # it, else emit ambient/global (emit_direct_llm_usage no-ops without a run identity).
    session = os.environ.get("FORGE_SESSION") or None
    try:
        from forge.core.llm import Message, SyncAdapter, get_client
        from forge.core.usage import (
            emit_direct_llm_usage,
            mint_request_id,
            resolve_client_base_url,
            target_is_forge_proxy,
            with_forge_request_id,
        )

        prompt = prompt_template.format(
            teammate_name=teammate,
            team_name=team,
            task_subject=task_subject or "",
        )
        adapter = SyncAdapter(get_client(model))
        # Exact-cost join only when the client provably targets a Forge proxy (same gate as
        # the action tagger / WorkflowPolicy stages); else no header and no cost_request_id.
        request_id = mint_request_id() if target_is_forge_proxy(resolve_client_base_url(model)) else None
        hp = with_forge_request_id(None, request_id) if request_id else None
        start = time.monotonic()
        response = adapter.complete([Message(role="user", content=prompt)], hyperparams=hp)
        latency_ms = (time.monotonic() - start) * 1000
        emit_direct_llm_usage(
            command="team-tagger",
            model=model,
            provider=model.split("/", 1)[0] if "/" in model else None,
            usage=response.usage,
            cost_request_id=request_id,
            latency_ms=latency_ms,
            session=session,
            provider_meta=response.provider_meta,
        )
        words = response.text.strip().lower().split()
        return words[0] if words else "routine"
    except Exception as e:
        _log.warning("Team tagger failed: %s", e)
        from forge.core.usage import emit_direct_llm_usage

        emit_direct_llm_usage(
            command="team-tagger",
            model=model,
            provider=model.split("/", 1)[0] if "/" in model else None,
            status="error",
            failure_type="exception",
            session=session,
        )
        return "routine"


def _run_supervisor(
    config: TeamSupervisorConfig,
    teammate: str,
    team: str,
    event_type: str,
    task_context: str,
    backend_id: str | None = None,
) -> tuple[int, str]:
    """Run cross-team supervisor. Returns ``(exit_code, feedback)``.

    Fail-open on: subprocess failure, parse failure, missing "verdict",
    non-dict extraction, verdict != "divergent", or FORGE_DEPTH limit.
    """
    from forge.core.reactive.env import should_spawn_subprocesses

    if not should_spawn_subprocesses():
        _log.debug("Skipping team supervisor at FORGE_DEPTH limit")
        return 0, ""

    try:
        base_url = None if config.direct else (config.base_url or lookup_proxy_base_url(config.proxy))
    except Exception as e:
        _log.warning("Team supervisor proxy '%s' not found: %s", config.proxy, e)
        return 0, ""
    prompt = TEAM_SUPERVISOR_PROMPT.format(
        teammate_name=teammate,
        team_name=team,
        event_type=event_type,
        task_context=task_context,
    )
    # Instrument like the semantic supervisor (Phase 5): snapshot proxy cost around the
    # run, then emit one verb-level UsageEvent so the team supervisor's claude -p spend is
    # attributed too (direct -> claude_code self-report; proxied -> forge_proxy snapshot).
    from forge.core.reactive.cost_tracking import track_verb_cost
    from forge.core.usage import emit_usage_for_session_result

    with track_verb_cost("team-supervisor", [base_url] if base_url else []) as cost:
        result = run_claude_session(
            prompt,
            resume_id=config.resume_id,
            base_url=base_url,
            direct=config.direct,
            timeout_seconds=config.timeout_seconds,
            reasoning_effort=config.effort,
        )
    # Emit before the success gate so failures/timeouts are attributed too (the emit
    # helper maps status itself and is best-effort -- it never raises).
    emit_usage_for_session_result(
        result,
        command="team-supervisor",
        cost=cost,
        base_url=base_url,
        direct=config.direct,
        backend_id=backend_id,
    )
    if not result.success:
        _log.warning("Team supervisor failed: %s", result.error)
        return 0, ""

    verdict = extract_json_from_response(result.stdout)
    if not isinstance(verdict, dict) or verdict.get("verdict") != "divergent":
        return 0, ""

    feedback = verdict.get("feedback", "Supervisor flagged work as divergent")
    return 2, feedback

"""Team hook handler logic for TeammateIdle and TaskCompleted.

Handlers return ``(exit_code, stderr_message)``:
- ``(0, "")`` = allow (teammate goes idle / task marked completed)
- ``(2, "feedback")`` = block (teammate continues / task stays open)

All errors fail-open (return 0). Uses file-backed cache at
``~/.forge/team-hooks/<session_id>.json`` for throttle + escape hatch.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

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


def handle_teammate_idle(
    data: dict[str, Any],
    config: TeamSupervisorConfig,
    cache: dict[str, Any],
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

    exit_code, feedback = _run_supervisor(config, teammate, team, "idle", "")
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
    exit_code, feedback = _run_supervisor(config, teammate, team, "task-completed", task_context)

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
    try:
        from forge.core.llm import SyncAdapter, get_client

        prompt = prompt_template.format(
            teammate_name=teammate,
            team_name=team,
            task_subject=task_subject or "",
        )
        adapter = SyncAdapter(get_client(model))
        response = adapter.ask(prompt)
        words = response.strip().lower().split()
        return words[0] if words else "routine"
    except Exception as e:
        _log.warning("Team tagger failed: %s", e)
        return "routine"


def _run_supervisor(
    config: TeamSupervisorConfig,
    teammate: str,
    team: str,
    event_type: str,
    task_context: str,
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
    result = run_claude_session(
        prompt,
        resume_id=config.resume_id,
        base_url=base_url,
        timeout_seconds=config.timeout_seconds,
    )
    if not result.success:
        _log.warning("Team supervisor failed: %s", result.error)
        return 0, ""

    verdict = extract_json_from_response(result.stdout)
    if not isinstance(verdict, dict) or verdict.get("verdict") != "divergent":
        return 0, ""

    feedback = verdict.get("feedback", "Supervisor flagged work as divergent")
    return 2, feedback

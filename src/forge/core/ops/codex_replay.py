"""Reconcile the bound native rollout with per-turn Responses dispatch evidence."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID

from forge.core.invoker.types import HeadlessResult
from forge.core.runtime.codex_proxy_launch import CodexProxyLaunch
from forge.core.runtime.codex_review_source import directory_fd
from forge.core.runtime.codex_rollouts import codex_home, find_rollouts_by_thread_id
from forge.core.runtime.codex_turn import turn_reference
from forge.core.runtime.codex_usage import CodexUsageBaseline
from forge.core.telemetry.downstream import read_downstream_records
from forge.session.events import SessionEventError
from forge.session.models import CodexCompletedTurn, CodexConfirmed, SessionState
from forge.session.routing import codex_proxy_commits

from .session import ForgeOpError


def replay_snapshot(
    state: SessionState, forge_root: str | Path, instance_id: str
) -> tuple[tuple[str, str], CodexUsageBaseline | None]:
    """Refuse history delivery unless the latest launch and native completion agree."""
    try:
        commits = codex_proxy_commits(forge_root, state, instance_id)
        codex = state.confirmed.codex
        if codex is None or codex.reconciled_run_id != commits[-1].run_id:
            raise ValueError("the latest launch has no verified turn outcome")
        latest, baseline = _rollout_selection(codex)
        completed = codex.completed_turn
        if completed:
            if completed.thread_id != codex.thread_id or latest != (
                completed.turn_id,
                completed.requested_model,
            ):
                raise ValueError("the bound rollout differs from the last verified foreground turn")
            return (completed.requested_model, completed.dispatched_model), baseline
        if latest is not None:
            raise ValueError("the rollout contains an unverified completed turn")
        initial = commits[0].payload["codex_proxy"]
        return (initial["requested_model"], initial["dispatched_model"]), baseline
    except (SessionEventError, OSError, ValueError) as exc:
        raise ForgeOpError(
            f"Cannot establish the completed Codex model for '{state.name}': {exc}. "
            "Restore the original evidence or start a fresh session."
        ) from exc


def reconcile_proxy_turn(
    state: SessionState,
    *,
    run_id: str,
    launch: CodexProxyLaunch,
    headless: HeadlessResult | None,
) -> None:
    """Project only a proven completion, inside the session's guarded post-launch update."""
    projection = state.confirmed.route_commit
    codex = state.confirmed.codex
    if not projection or projection.run_id != run_id or codex is None or not codex.thread_id:
        return
    try:
        latest, _ = _rollout_selection(codex)
        previous = codex.completed_turn
        if previous and previous.thread_id != codex.thread_id:
            return
        unchanged = latest == ((previous.turn_id, previous.requested_model) if previous else None)
        if headless is not None:
            if headless.runtime_session_id != codex.thread_id:
                return
            if not (headless.success and not headless.runtime_is_error and headless.codex_turn_completed):
                if unchanged and headless.runtime_is_error and not headless.codex_turn_completed:
                    codex.reconciled_run_id = run_id
                return
            if unchanged or latest is None or latest[1] != launch.requested_model:
                return
        if not unchanged and latest is not None:
            turn, model = latest
            ref = turn_reference(run_id, codex.thread_id, turn)
            attempts = read_downstream_records(
                kind="attempt",
                proxy_id=launch.proxy_id,
                backend_id=launch.backend_id,
                forge_run_id=run_id,
                forge_root_run_id=run_id,
            )
            dispatches = {
                (row.model, row.mapped_model) for row in attempts if row.codex_turn_ref == ref and row.failed is False
            }
            if len(dispatches) != 1:
                return
            requested, dispatched = dispatches.pop()
            if requested != model or not dispatched or (headless is not None and dispatched != launch.dispatched_model):
                return
            codex.completed_turn = CodexCompletedTurn(codex.thread_id, model, dispatched, turn)
        elif not unchanged:
            return
        codex.reconciled_run_id = run_id
    except (OSError, ValueError):
        # Keeping the old marker makes an incomplete or ambiguous observation fail closed on resume.
        return


def _rollout_selection(codex: CodexConfirmed) -> tuple[tuple[str, str] | None, CodexUsageBaseline | None]:
    """Read the last completed user turn, preserving an explicit no-answer terminal."""
    thread = codex.thread_id
    if not thread or not codex.rollout_path:
        raise ValueError("the native thread or its rollout is missing")
    UUID(thread)
    home = codex_home().expanduser().resolve(strict=True)
    paths = find_rollouts_by_thread_id(thread, home=home)
    if len(paths) != 1 or paths[0] != Path(codex.rollout_path).resolve(strict=True):
        raise ValueError("the bound rollout is missing or ambiguous")
    path = paths[0]
    with directory_fd(path.parent) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError("the bound rollout is not an ordinary file")
            latest = _read_turns(stream, thread)
            after = os.fstat(fd)
            if (before.st_size, before.st_mtime_ns) != (
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError("the bound rollout changed during reconciliation")
            return latest


def _row(line: bytes) -> tuple[str, dict[str, Any]]:
    if not line.endswith(b"\n"):
        raise ValueError("the native rollout is incomplete")
    row = json.loads(line)
    if not isinstance(row, dict) or not isinstance(row.get("payload"), dict) or not isinstance(row.get("type"), str):
        raise ValueError("unrecognized native rollout record")
    return row["type"], row["payload"]


def _read_turns(stream: BinaryIO, thread: str) -> tuple[tuple[str, str] | None, CodexUsageBaseline | None]:
    kind, header = _row(stream.readline())
    if kind != "session_meta" or header.get("id") != thread or header.get("model_provider") != "forge_proxy":
        raise ValueError("native identity or provider differs from the bound proxy thread")
    active = model = None
    user = False
    latest = None
    baseline = None
    previous_total = None
    for line in stream:
        kind, payload = _row(line)
        event = payload.get("type") if kind == "event_msg" else None
        turn = payload.get("turn_id")
        if event == "task_started":
            if active or not isinstance(turn, str):
                raise ValueError("ambiguous native turn start")
            UUID(turn)
            active, model, user = turn, None, False
            previous_total, baseline = baseline, None
        elif event == "token_count" and payload.get("info") is not None:
            previous_total = None
            info = payload["info"]
            baseline = CodexUsageBaseline.from_total_usage(
                info.get("total_token_usage") if isinstance(info, dict) else None
            )
        elif kind == "turn_context":
            if (
                not active
                or turn != active
                or not isinstance(payload.get("model"), str)
                or (model and model != payload["model"])
            ):
                raise ValueError("ambiguous native turn context")
            model = payload["model"]
        elif event == "user_message" or (
            event == "item_completed"
            and isinstance(payload.get("item"), dict)
            and payload["item"].get("type") == "UserMessage"
        ):
            if not active or (turn and turn != active):
                raise ValueError("ambiguous native user message")
            user = True
        elif event == "item_completed" or (
            kind == "response_item"
            and not (payload.get("type") == "message" and payload.get("role") in {"user", "developer", "system"})
        ):
            # Wait for the corresponding counters after output, reasoning or tool activity.
            previous_total = baseline = None
        elif event in {"task_complete", "turn_aborted"}:
            if not active or turn != active:
                raise ValueError("ambiguous native turn terminal")
            if event == "task_complete":
                if not user or not model or "last_agent_message" not in payload:
                    raise ValueError("unrecognized native completion")
                if payload["last_agent_message"] is not None:
                    if not isinstance(payload["last_agent_message"], str) or not payload["last_agent_message"]:
                        raise ValueError("unrecognized native final message")
                    latest = (active, model)
                elif previous_total is not None:
                    # A request rejected before native generation leaves its prior thread counters intact.
                    baseline = previous_total
            active = None
        elif kind == "session_meta" or event == "thread_rolled_back":
            raise ValueError("native thread history was replaced")
    if active is not None:
        raise ValueError("the last native turn has no terminal record")
    return latest, baseline

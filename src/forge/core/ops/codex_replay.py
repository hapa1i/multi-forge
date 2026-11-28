"""Reconcile the bound native rollout with per-turn Responses dispatch evidence."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import replace
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID

from forge.core.invoker.types import HeadlessResult
from forge.core.runtime.codex_review_source import directory_fd
from forge.core.runtime.codex_rollouts import codex_home, find_rollouts_by_thread_id
from forge.core.runtime.codex_turn import turn_reference
from forge.core.runtime.codex_usage import CodexUsageBaseline
from forge.core.state import FileLockTimeoutError, parse_iso
from forge.core.telemetry.downstream import read_downstream_records
from forge.core.usage.ledger import read_usage_events
from forge.session.events import SessionEvent
from forge.session.exceptions import ForgeSessionError
from forge.session.index import IndexStore
from forge.session.models import (
    CodexCompletedTurn,
    CodexConfirmed,
    CodexExitOutcome,
    CodexProxyExit,
    SessionState,
)
from forge.session.routing import codex_proxy_commits
from forge.session.store import SessionStore

from .session import ForgeOpError


def record_proxy_exit(
    codex: CodexConfirmed,
    run_id: str,
    *,
    headless: HeadlessResult | None,
    thread_drift: bool = False,
) -> None:
    """Preserve the child's observed outcome before attempting the asynchronous dispatch join."""
    outcome: CodexExitOutcome
    if thread_drift or (headless and headless.runtime_session_id and headless.runtime_session_id != codex.thread_id):
        outcome = "conflict"
    elif headless is None:
        outcome = "interactive"
    elif headless.codex_turn_completed:
        if headless.runtime_session_id and headless.success and not headless.runtime_is_error:
            outcome = "completed"
        else:
            outcome = "conflict"
    else:
        outcome = "incomplete"
    codex.pending_exit = CodexProxyExit(run_id=run_id, outcome=outcome)


def replay_snapshot(
    state: SessionState, forge_root: str | Path, instance_id: str
) -> tuple[tuple[str, str], CodexUsageBaseline | None]:
    """Join the bound rollout with its dispatch and publish a recovered turn before resume."""
    try:
        commits = codex_proxy_commits(forge_root, state, instance_id)
        commit = commits[-1]
        codex = state.confirmed.codex
        if not commit.run_id or codex is None or not codex.thread_id:
            raise ValueError("the latest launch has no bound Codex thread")
        outcome = None
        if codex.reconciled_run_id != commit.run_id:
            if codex.pending_exit is None:
                outcome = _legacy_exit(state, codex, commit, instance_id)
            elif codex.pending_exit.run_id == commit.run_id:
                outcome = codex.pending_exit.outcome
            else:
                raise ValueError("the latest launch has no matching post-exit evidence")
            if outcome == "conflict":
                raise ValueError("the native exit disagrees with the bound thread or completed turn")

        latest, baseline, rollout_path = _rollout_selection(codex)
        completed = codex.completed_turn
        if completed is not None and completed.thread_id != codex.thread_id:
            raise ValueError("the last verified foreground turn belongs to a different thread")
        previous = (completed.turn_id, completed.requested_model) if completed else None
        if outcome is None:
            if latest != previous:
                raise ValueError("the bound rollout differs from the last verified foreground turn")
        else:
            if latest != previous:
                if latest is None or outcome == "incomplete":
                    raise ValueError("the native completion disagrees with the recorded exit")
                completed = _matched_dispatch(commit, codex.thread_id, latest, headless=outcome == "completed")
            elif outcome == "completed":
                raise ValueError("the completed native launch has no new foreground turn")
            recovered = replace(
                codex,
                completed_turn=completed,
                reconciled_run_id=commit.run_id,
                pending_exit=None,
                rollout_path=codex.rollout_path or str(rollout_path),
                rollout_source=(codex.rollout_source if codex.rollout_path else "discovered_by_thread_id"),
            )
            _publish_recovery(state, forge_root, instance_id, recovered)

        if completed:
            return (completed.requested_model, completed.dispatched_model), baseline
        initial = commits[0].payload["codex_proxy"]
        return (initial["requested_model"], initial["dispatched_model"]), baseline
    except (ForgeSessionError, FileLockTimeoutError, OSError, ValueError) as exc:
        raise ForgeOpError(
            f"Cannot establish the completed Codex model for '{state.name}': {exc}. "
            "Retry after the launch exits and its telemetry is available. "
            "If the evidence still disagrees, restore it or start a fresh session."
        ) from exc


def _legacy_exit(
    state: SessionState, codex: CodexConfirmed, commit: SessionEvent, instance_id: str
) -> CodexExitOutcome:
    """Earlier v6 manifests need independent headless exit evidence to distinguish a pending or live launch."""
    started_at = parse_iso(commit.timestamp)
    last_run_at = parse_iso(codex.last_run_at) if codex.last_run_at else None
    if last_run_at and last_run_at >= started_at:
        events = read_usage_events(
            period_start=started_at,
            run_id=commit.run_id,
            root_run_id=commit.run_id,
            runtime="codex",
            session=state.name,
        )
        expected = commit.payload["codex_proxy"]["dispatched_model"]
        if len(events) == 1:
            event = events[0]
            if (
                event.command in {"codex-bridge", "codex-resume"}
                and event.route == "codex_exec"
                and event.reporter == "codex_jsonl"
                and event.session_instance_id == instance_id
                and event.proxy_id == commit.payload["route"]["proxy_id"]
                and event.model == expected
            ):
                if event.status == "success" and event.input_tokens is not None and event.output_tokens is not None:
                    return "completed"
                if (
                    event.status == "timeout"
                    and last_run_at > started_at
                    and event.input_tokens is None
                    and event.output_tokens is None
                ):
                    return "incomplete"
    raise ValueError("the latest launch has no verified post-exit evidence")


def _matched_dispatch(
    commit: SessionEvent, thread: str, latest: tuple[str, str], *, headless: bool
) -> CodexCompletedTurn:
    turn, model = latest
    assert commit.run_id
    ref = turn_reference(commit.run_id, thread, turn)
    route = commit.payload["route"]
    attempts = read_downstream_records(
        period_start=parse_iso(commit.timestamp),
        kind="attempt",
        proxy_id=route["proxy_id"],
        backend_id=route["backend_id"],
        forge_run_id=commit.run_id,
        forge_root_run_id=commit.run_id,
    )
    dispatches = {
        (row.model, row.mapped_model) for row in attempts if row.codex_turn_ref == ref and row.failed is False
    }
    if not dispatches:
        raise ValueError("the completed foreground turn has no recorded successful proxy dispatch yet")
    if len(dispatches) != 1:
        raise ValueError("the proxy recorded conflicting dispatches for the completed foreground turn")
    requested, dispatched = dispatches.pop()
    facts = commit.payload["codex_proxy"]
    if (
        requested != model
        or not dispatched
        or (headless and (requested, dispatched) != (facts["requested_model"], facts["dispatched_model"]))
    ):
        raise ValueError("the foreground model and proxy dispatch disagree")
    return CodexCompletedTurn(thread, model, dispatched, turn)


def _publish_recovery(
    state: SessionState,
    forge_root: str | Path,
    instance_id: str,
    recovered: CodexConfirmed,
) -> None:
    """Perform only a guarded compare-and-write under the manifest lock."""

    def publish(current: SessionState) -> None:
        if (
            current.confirmed.route_commit != state.confirmed.route_commit
            or current.intent.proxy != state.intent.proxy
            or current.confirmed.codex not in (state.confirmed.codex, recovered)
        ):
            raise ValueError("the session changed during reconciliation")
        current.confirmed.codex = recovered

    store = SessionStore(str(forge_root), state.name)

    def persist() -> None:
        store.update(timeout_s=5.0, mutate=publish, expected_instance_id=instance_id)

    if not IndexStore().run_session_instance_txn(
        state.name,
        str(store.forge_root),
        expected_instance_id=instance_id,
        callback=persist,
    ):
        raise ValueError("the session was deleted, replaced, or entered cleanup during reconciliation")
    state.confirmed.codex = recovered


def _rollout_selection(
    codex: CodexConfirmed,
) -> tuple[tuple[str, str] | None, CodexUsageBaseline | None, Path]:
    """Read the last completed user turn, preserving an explicit no-answer terminal."""
    thread = codex.thread_id
    if not thread:
        raise ValueError("the native thread is missing")
    UUID(thread)
    home = codex_home().expanduser().resolve(strict=True)
    if (home / "sessions").is_symlink():
        raise ValueError("the Codex sessions directory is a symbolic link")
    paths = find_rollouts_by_thread_id(thread, home=home)
    if len(paths) != 1 or (codex.rollout_path and paths[0] != Path(codex.rollout_path).resolve(strict=True)):
        raise ValueError("the bound rollout is missing or ambiguous")
    path = paths[0]
    with directory_fd(path.parent) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError("the bound rollout is not an ordinary file")
            latest, baseline = _read_turns(stream, thread)
            after = os.fstat(fd)
            if (before.st_size, before.st_mtime_ns) != (
                after.st_size,
                after.st_mtime_ns,
            ):
                raise ValueError("the bound rollout changed during reconciliation")
            return latest, baseline, path


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

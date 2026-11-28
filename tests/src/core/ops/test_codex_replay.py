from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from forge.core.invoker.types import HeadlessResult
from forge.core.ops import codex_replay
from forge.core.ops.codex_replay import record_proxy_exit, replay_snapshot
from forge.core.ops.codex_session import _update_manifest_if_present
from forge.core.ops.session import ForgeOpError
from forge.core.ops.session_routing import (
    build_codex_proxy_routing_payload,
    commit_launch_routing,
)
from forge.core.reactive.env import new_root_run_identity
from forge.core.runtime.codex_proxy_launch import CodexProxyLaunch
from forge.core.runtime.codex_turn import request_turn_reference
from forge.core.state import file_lock_for_target, parse_iso
from forge.core.telemetry.downstream import DownstreamRecord, write_downstream_record
from forge.core.usage.ledger import UsageEvent, log_usage_event
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.cleanup_state import cleanup_state_path
from forge.session.models import CodexConfirmed, SessionState
from forge.session.routing import read_routing_events
from tests.fixtures.session_state import publish_session

INITIAL = "Acme/initial:free"
SWITCH = "Other/Model@testing"
LAUNCH = CodexProxyLaunch(
    "edge",
    "responses",
    "http://127.0.0.1:4011",
    "openrouter",
    "openrouter",
    INITIAL,
    "target-a",
    True,
)


def _append(path: Path, kind: str, **payload: object) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"type": kind, "payload": payload}) + "\n")


class Session:
    def __init__(self, home: Path):
        self.root = home / "work"
        self.thread = str(uuid4())
        self.path = home / "sessions/2026/01/01" / f"rollout-2026-01-01T12-00-00-{self.thread}.jsonl"
        self.path.parent.mkdir(parents=True)
        _append(self.path, "session_meta", id=self.thread, model_provider="forge_proxy")
        state = create_session_state(
            "codex-session",
            runtime="codex",
            proxy_template=LAUNCH.template,
            proxy_base_url=LAUNCH.base_url,
            proxy_id=LAUNCH.proxy_id,
        )
        self.store = SessionStore(str(self.root), state.name)
        state.confirmed.codex = CodexConfirmed(thread_id=self.thread, rollout_path=str(self.path))
        self.instance = publish_session(IndexStore(), state, self.root, forge_root=self.root).instance_id
        assert self.instance
        self.run = self.commit(LAUNCH, "start")

    def commit(self, launch: CodexProxyLaunch, operation: str) -> str:
        assert self.instance
        identity = new_root_run_identity()
        commit_launch_routing(
            store=self.store,
            state=self.store.read(),
            root=identity,
            operation=operation,
            payload=build_codex_proxy_routing_payload(launch, self.instance),
            authority_attempt=None,
        )
        return identity.run_id

    def turn(self, model: str, *, answer: str | None = "reply", terminal: bool = True) -> str:
        turn = str(uuid4())
        _append(self.path, "event_msg", type="task_started", turn_id=turn)
        _append(self.path, "turn_context", model=model, turn_id=turn)
        _append(
            self.path,
            "event_msg",
            type="item_completed",
            item={"type": "UserMessage"},
            turn_id=turn,
        )
        if terminal:
            _append(
                self.path,
                "event_msg",
                type="task_complete",
                turn_id=turn,
                last_agent_message=answer,
            )
        return turn

    def attempt(self, turn: str, requested: str, mapped: str, *, failed: bool = False) -> None:
        meta = {"thread_id": self.thread, "turn_id": turn}
        ref = request_turn_reference(
            {
                "client_metadata": {
                    **meta,
                    "x-codex-turn-metadata": json.dumps({**meta, "request_kind": "turn"}),
                }
            },
            self.run,
        )
        assert ref is not None and self.thread not in ref and turn not in ref
        write_downstream_record(
            DownstreamRecord(
                kind="attempt",
                downstream_event_id=str(uuid4()),
                proxy_id=LAUNCH.proxy_id,
                backend_id=LAUNCH.backend_id,
                forge_run_id=self.run,
                forge_root_run_id=self.run,
                model=requested,
                mapped_model=mapped,
                failed=failed,
                codex_turn_ref=ref,
            )
        )

    def finish(self, headless: HeadlessResult | None = None) -> list[str]:
        def mutate(state: SessionState) -> None:
            assert state.confirmed.codex
            record_proxy_exit(state.confirmed.codex, self.run, headless=headless)

        warnings: list[str] = []
        assert self.instance
        _update_manifest_if_present(
            self.store,
            mutate=mutate,
            warnings=warnings,
            session=self.store.session_name,
            expected_proxy_run_id=self.run,
            expected_instance_id=self.instance,
        )
        return warnings

    def replay(self) -> tuple[str, str]:
        assert self.instance
        return replay_snapshot(self.store.read(), self.root, self.instance)[0]


@pytest.fixture
def session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    return Session(tmp_path)


def test_tui_switch_and_failed_turn_keep_last_foreground_selection(
    session: Session,
) -> None:
    first = session.turn(INITIAL)
    session.attempt(first, INITIAL, "target-a")
    switched = session.turn(SWITCH)
    session.attempt(switched, SWITCH, "target-b")
    session.attempt(str(uuid4()), INITIAL, "title-model")
    failed = session.turn("unavailable", answer=None)
    session.attempt(failed, "unavailable", "failed-target", failed=True)
    session.finish()
    assert session.replay() == (SWITCH, "target-b")
    assert session.store.read().schema_version == 6


def test_no_completed_turn_replays_start_even_after_failed_resume(
    session: Session,
) -> None:
    session.finish()
    changed = replace(LAUNCH, requested_model=SWITCH, dispatched_model="other")
    session.run = session.commit(changed, "resume")
    with pytest.raises(ForgeOpError, match="fresh"):
        session.replay()
    session.turn(SWITCH, answer=None)
    session.finish(
        HeadlessResult(None, "", "", 1, 0, runtime_session_id=session.thread, runtime_is_error=True),
    )
    assert session.replay() == (INITIAL, "target-a")


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "wrong_turn",
        "failed",
        "conflict",
        "no_terminal",
        "headless_incomplete",
        "wrong_thread",
    ],
)
def test_unproven_completion_refuses_resume(session: Session, fault: str) -> None:
    turn = session.turn(INITIAL, terminal=fault != "no_terminal")
    if fault != "missing":
        session.attempt(
            str(uuid4()) if fault == "wrong_turn" else turn,
            INITIAL,
            "target-a",
            failed=fault == "failed",
        )
    if fault == "conflict":
        session.attempt(turn, INITIAL, "target-b")
    headless = HeadlessResult(
        None,
        "",
        "",
        0,
        0,
        runtime_session_id=(str(uuid4()) if fault == "wrong_thread" else session.thread),
        codex_turn_completed=fault != "headless_incomplete",
    )
    session.finish(headless)
    with pytest.raises(ForgeOpError, match="fresh"):
        session.replay()


def test_headless_completed_stream_and_bound_dispatch_then_external_turn(
    session: Session,
) -> None:
    turn = session.turn(INITIAL)
    session.attempt(turn, INITIAL, "target-a")
    session.finish(
        HeadlessResult(
            None,
            "",
            "",
            0,
            0,
            runtime_session_id=session.thread,
            codex_turn_completed=True,
        )
    )
    assert session.replay() == (INITIAL, "target-a")
    session.turn(SWITCH)
    with pytest.raises(ForgeOpError, match="differs"):
        session.replay()


def test_native_join_requires_consistent_ids_and_a_managed_run() -> None:
    metadata = {"thread_id": str(uuid4()), "turn_id": str(uuid4())}

    def body(**overrides: str) -> dict[str, object]:
        native = {**metadata, "request_kind": "turn", **overrides}
        return {"client_metadata": {**metadata, "x-codex-turn-metadata": json.dumps(native)}}

    assert request_turn_reference(body(), None) is None
    assert request_turn_reference(body(), "wrong") is None
    first = request_turn_reference(body(), "run_aaaaaaaaaaaa")
    assert first is not None and first != request_turn_reference(body(), "run_bbbbbbbbbbbb")
    assert request_turn_reference(body(thread_id=str(uuid4())), "run_aaaaaaaaaaaa") is None
    assert request_turn_reference(body(request_kind="compact"), "run_aaaaaaaaaaaa") is None


def test_superseded_post_exit_keeps_newer_commit_unreconciled(session: Session) -> None:
    winning_run = session.commit(LAUNCH, "resume")
    session.finish()
    state = session.store.read()
    assert state.confirmed.route_commit is not None and state.confirmed.route_commit.run_id == winning_run
    assert state.confirmed.codex is not None and state.confirmed.codex.reconciled_run_id is None
    with pytest.raises(ForgeOpError, match="fresh"):
        session.replay()


@pytest.mark.parametrize("partial", ["none", "reasoning", "malformed-usage"])
def test_resume_counter_after_refused_switch(session: Session, partial: str) -> None:
    first = session.turn(INITIAL, terminal=False)
    usage = {"input_tokens": 32, "output_tokens": 4, "cached_input_tokens": 0}
    _append(session.path, "event_msg", type="token_count", info={"total_token_usage": usage})
    _append(session.path, "event_msg", type="task_complete", turn_id=first, last_agent_message="first")
    session.attempt(first, INITIAL, "target-a")
    failed = session.turn(SWITCH, terminal=False)
    if partial == "reasoning":
        _append(session.path, "response_item", type="reasoning", summary=[])
    elif partial == "malformed-usage":
        _append(session.path, "event_msg", type="token_count", info={"total_token_usage": {}})
    _append(session.path, "event_msg", type="task_complete", turn_id=failed, last_agent_message=None)
    session.finish()
    assert session.instance
    _, baseline = replay_snapshot(session.store.read(), session.root, session.instance)
    if partial == "none":
        assert baseline and baseline.as_dict() == {"input_tokens": 32, "output_tokens": 4, "cached_tokens": 0}
    else:
        assert baseline is None


@pytest.mark.parametrize("frontend", ["interactive", "headless"])
def test_resume_retries_missing_dispatch_and_publishes_proof(session: Session, frontend: str) -> None:
    first = session.turn(INITIAL)
    result = (
        HeadlessResult(
            None,
            "",
            "",
            0,
            0,
            runtime_session_id=session.thread,
            codex_turn_completed=True,
        )
        if frontend == "headless"
        else None
    )
    session.finish(result)
    with pytest.raises(ForgeOpError, match="no recorded successful proxy dispatch yet"):
        session.replay()
    pending = session.store.read().confirmed.codex
    assert pending and pending.pending_exit and pending.pending_exit.run_id == session.run
    session.attempt(first, INITIAL, "target-a")
    assert session.replay() == (INITIAL, "target-a")
    settled = session.store.read().confirmed.codex
    assert settled and settled.completed_turn and settled.completed_turn.turn_id == first
    assert settled.reconciled_run_id == session.run and settled.pending_exit is None


@pytest.mark.parametrize("clean_abort", [False, True])
def test_failed_or_aborted_headless_turn_needs_no_stream_error(session: Session, clean_abort: bool) -> None:
    first = session.turn(INITIAL)
    session.attempt(first, INITIAL, "target-a")
    session.finish()
    session.run = session.commit(replace(LAUNCH, requested_model=SWITCH), "resume")
    if clean_abort:
        aborted = session.turn(SWITCH, terminal=False)
        _append(session.path, "event_msg", type="turn_aborted", turn_id=aborted)
    session.finish(
        HeadlessResult(
            None,
            "",
            "",
            130,
            0,
            runtime_session_id=session.thread if clean_abort else None,
            timed_out=not clean_abort,
        )
    )
    assert session.replay() == (INITIAL, "target-a")
    settled = session.store.read().confirmed.codex
    assert settled and settled.reconciled_run_id == session.run


def test_new_commit_with_unchanged_rollout_cannot_recover_an_in_flight_launch(
    session: Session,
) -> None:
    session.finish()
    previous_run = session.run
    session.run = session.commit(LAUNCH, "resume")
    with pytest.raises(ForgeOpError, match="no verified post-exit evidence"):
        session.replay()
    codex = session.store.read().confirmed.codex
    assert codex and codex.reconciled_run_id == previous_run


def test_legacy_same_second_headless_success_recovers_only_a_verified_new_dispatch(
    session: Session,
) -> None:
    state = session.store.read()
    assert state.confirmed.codex
    commit = read_routing_events(session.root, state)[-1]
    state.confirmed.codex.last_run_at = commit.timestamp
    session.store.write(state)
    first = session.turn(INITIAL)
    session.attempt(first, INITIAL, "target-a")
    event = UsageEvent(
        run_id=session.run,
        root_run_id=session.run,
        runtime="codex",
        command="codex-bridge",
        status="success",
        session=state.name,
        session_instance_id=session.instance,
        model="target-a",
        proxy_id=LAUNCH.proxy_id,
        reporter="codex_jsonl",
        route="codex_exec",
        input_tokens=7,
        output_tokens=3,
    )
    with pytest.raises(ForgeOpError, match="post-exit evidence"):
        session.replay()
    log_usage_event(event)
    assert session.replay() == (INITIAL, "target-a")
    codex = session.store.read().confirmed.codex
    assert codex and codex.completed_turn and codex.completed_turn.turn_id == first


@pytest.mark.parametrize(
    ("status", "later", "recovers"),
    [("error", True, False), ("timeout", False, False), ("timeout", True, True)],
)
def test_historical_no_turn_requires_unambiguous_exit_evidence(
    session: Session, status: str, later: bool, recovers: bool
) -> None:
    session.finish()
    session.run = session.commit(LAUNCH, "resume")
    state = session.store.read()
    assert state.confirmed.codex
    commit = read_routing_events(session.root, state)[-1]
    state.confirmed.codex.last_run_at = (parse_iso(commit.timestamp) + timedelta(seconds=int(later))).isoformat()
    session.store.write(state)
    # A historical thread mismatch could emit the same generic error without storing the reported thread.
    log_usage_event(
        UsageEvent(
            run_id=session.run,
            root_run_id=session.run,
            runtime="codex",
            command="codex-resume",
            status=status,
            session=state.name,
            session_instance_id=session.instance,
            model="target-a",
            proxy_id=LAUNCH.proxy_id,
            reporter="codex_jsonl",
            route="codex_exec",
        )
    )
    if recovers:
        assert session.replay() == (INITIAL, "target-a")
    else:
        with pytest.raises(ForgeOpError, match="no verified post-exit evidence"):
            session.replay()


def test_cleanup_during_evidence_read_prevents_publication(session: Session) -> None:
    first = session.turn(INITIAL)
    session.attempt(first, INITIAL, "target-a")

    def verify_unlocked() -> None:
        with (
            file_lock_for_target(target_path=IndexStore().index_path, timeout_s=0),
            file_lock_for_target(target_path=session.store.manifest_path, timeout_s=0),
        ):
            pass

    read_rollout = codex_replay._rollout_selection
    read_dispatch = codex_replay._matched_dispatch

    def read_without_locks(codex):
        verify_unlocked()
        return read_rollout(codex)

    def cleanup_after_read(*args, **kwargs):
        verify_unlocked()
        matched = read_dispatch(*args, **kwargs)
        retry = cleanup_state_path(session.root, session.store.session_name)
        retry.parent.mkdir(parents=True, exist_ok=True)
        retry.write_text("{}")
        return matched

    with (
        patch.object(codex_replay, "_rollout_selection", side_effect=read_without_locks) as rollout,
        patch.object(codex_replay, "_matched_dispatch", side_effect=cleanup_after_read) as dispatch,
    ):
        warnings = session.finish()
    rollout.assert_called_once()
    dispatch.assert_called_once()
    assert any("entered cleanup during reconciliation" in warning for warning in warnings)
    codex = session.store.read().confirmed.codex
    assert codex and codex.pending_exit and codex.pending_exit.run_id == session.run
    assert codex.reconciled_run_id is None and codex.completed_turn is None


def test_symlinked_sessions_directory_is_refused_without_reading_external_content(
    session: Session,
) -> None:
    sessions = session.path.parents[3]
    moved = sessions.rename(sessions.with_name("external"))
    sessions.symlink_to(moved, target_is_directory=True)
    session.finish()
    with pytest.raises(ForgeOpError, match="sessions directory is a symbolic link"):
        session.replay()

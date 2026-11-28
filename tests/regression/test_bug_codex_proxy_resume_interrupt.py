"""An interrupted proxy resume may reuse the previous turn once its child has stopped."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.core.invoker.types import HeadlessRequest
from forge.core.ops.codex_session import continue_codex_session
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import ForgeOpError
from forge.session import SessionStore
from tests.src.core.ops.test_codex_replay import INITIAL, LAUNCH, Session
from tests.src.core.ops.test_codex_session import _preflight

pytestmark = pytest.mark.regression


@pytest.fixture
def settled_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Session:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    session = Session(tmp_path)
    turn = session.turn(INITIAL)
    session.attempt(turn, INITIAL, "target-a")
    assert session.finish() == []
    monkeypatch.setattr("forge.core.ops.codex_session.resolve_codex_proxy_launch", lambda **kw: (_preflight(), LAUNCH))
    return session


@pytest.mark.parametrize("stage", ["before-spawn", "child-reaped", "child-alive"])
def test_resume_after_interrupt(settled_session: Session, monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    session = settled_session
    ctx = ExecutionContext(session.root, session.root, session.root, session.root)
    request = HeadlessRequest(
        argv=[sys.executable, "-c", "import time; time.sleep(10)"],
        prompt="continue",
        env=os.environ.copy(),
    )
    monkeypatch.setattr("forge.core.ops.codex_session.prepare_codex_request", lambda **kw: request)
    child_pids: list[int] = []

    def interrupt(proc, *args, **kwargs):
        child_pids.append(proc.pid)
        raise KeyboardInterrupt

    with monkeypatch.context() as child:
        if stage == "before-spawn":
            child.setattr("forge.core.invoker.CodexHeadlessInvoker._prepare_argv", Mock(side_effect=KeyboardInterrupt))
        else:
            child.setattr(subprocess.Popen, "communicate", interrupt)
        if stage == "child-alive":
            # Model a failed teardown. The test owns the child and reaps it below.
            child.setattr("forge.core.invoker._lifecycle._terminate_and_reap", lambda procs: None)
        try:
            with pytest.raises(KeyboardInterrupt):
                continue_codex_session(ctx=ctx, name=session.store.session_name, task="continue")
        finally:
            if child_pids and stage == "child-alive":
                os.killpg(child_pids[0], signal.SIGKILL)
                os.waitpid(child_pids[0], 0)
    assert len(child_pids) == (0 if stage == "before-spawn" else 1)
    if stage == "child-reaped":
        with pytest.raises(ProcessLookupError):
            os.killpg(child_pids[0], 0)
    if stage == "child-alive":
        with pytest.raises(ForgeOpError, match="no verified post-exit evidence"):
            session.replay()
    else:
        assert session.replay() == (INITIAL, "target-a")


@pytest.mark.parametrize(
    ("stage", "completed", "group_exists"),
    [
        ("parse", False, False),
        ("parse", True, False),
        ("parse", False, True),
        ("emit", False, False),
        ("emit", True, False),
        ("emit", True, True),
        ("after-return", False, False),
        ("after-return", True, False),
        ("after-return", False, True),
    ],
)
def test_interrupt_after_native_exit(
    settled_session: Session, monkeypatch: pytest.MonkeyPatch, stage: str, completed: bool, group_exists: bool
) -> None:
    session = settled_session
    ctx = ExecutionContext(session.root, session.root, session.root, session.root)
    output = json.dumps({"type": "thread.started", "thread_id": session.thread})
    if completed:
        output += "\n" + json.dumps({"type": "turn.completed"})
    request = HeadlessRequest(
        argv=[sys.executable, "-c", f"print({output!r})"], prompt="continue", env=os.environ.copy()
    )
    monkeypatch.setattr("forge.core.ops.codex_session.prepare_codex_request", lambda **kw: request)
    monkeypatch.setattr("forge.core.invoker._lifecycle._process_group_exists", lambda pid: group_exists)
    teardown = Mock()
    monkeypatch.setattr("forge.core.invoker._lifecycle._terminate_and_reap", teardown)
    turn = None

    def interrupt(*args, **kwargs):
        nonlocal turn
        if completed:
            commit = session.store.read().confirmed.route_commit
            assert commit is not None
            session.run = commit.run_id
            turn = session.turn(INITIAL)
            session.attempt(turn, INITIAL, "target-a")
        raise KeyboardInterrupt

    if stage == "after-return":
        monkeypatch.setattr("forge.core.ops.codex_session.find_rollout_path", interrupt)
    else:
        hook = "_build_result" if stage == "parse" else "_emit"
        monkeypatch.setattr(f"forge.core.invoker.CodexHeadlessInvoker.{hook}", interrupt)
    with pytest.raises(KeyboardInterrupt):
        continue_codex_session(ctx=ctx, name=session.store.session_name, task="continue")
    teardown.assert_not_called()
    if group_exists:
        with pytest.raises(ForgeOpError, match="no verified post-exit evidence"):
            session.replay()
    elif stage == "parse" and completed:
        with pytest.raises(ForgeOpError, match="disagrees with the recorded exit"):
            session.replay()
    else:
        assert session.replay() == (INITIAL, "target-a")
        if completed:
            codex = session.store.read().confirmed.codex
            assert codex and codex.completed_turn and codex.completed_turn.turn_id == turn


def test_post_run_update_keeps_a_concurrent_reconciliation(
    settled_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = settled_session
    ctx = ExecutionContext(session.root, session.root, session.root, session.root)
    request = HeadlessRequest(argv=[sys.executable, "-c", "pass"], prompt="continue", env=os.environ.copy())
    monkeypatch.setattr("forge.core.ops.codex_session.prepare_codex_request", lambda **kw: request)

    def reconcile_before_rollout_lookup(thread_id: str) -> Path:
        assert thread_id == session.thread
        assert session.replay() == (INITIAL, "target-a")
        return session.path

    monkeypatch.setattr("forge.core.ops.codex_session.find_rollout_path", reconcile_before_rollout_lookup)
    resume = continue_codex_session(ctx=ctx, name=session.store.session_name, task="continue")
    codex = session.store.read().confirmed.codex
    assert codex and codex.reconciled_run_id == resume.root_run_id and codex.pending_exit is None


@pytest.mark.parametrize("retry_fails", [False, True])
def test_interrupt_during_exit_receipt_write(
    settled_session: Session, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, retry_fails: bool
) -> None:
    session = settled_session
    ctx = ExecutionContext(session.root, session.root, session.root, session.root)
    request = HeadlessRequest(argv=[sys.executable, "-c", "pass"], prompt="continue", env=os.environ.copy())
    monkeypatch.setattr("forge.core.ops.codex_session.prepare_codex_request", lambda **kw: request)
    interrupt = KeyboardInterrupt()
    writes = []
    update = SessionStore.update

    def interrupted_update(store, **kwargs):
        writes.append((store, kwargs))
        if len(writes) == 1:
            raise interrupt
        if retry_fails:
            raise OSError("receipt unavailable")
        return update(store, **kwargs)

    with monkeypatch.context() as child:
        # Let the launch commit normally. Interrupt its first manifest write after the native exit.
        child.setattr(
            "forge.core.invoker.CodexHeadlessInvoker._emit",
            lambda *args: child.setattr(SessionStore, "update", interrupted_update),
        )
        with pytest.raises(KeyboardInterrupt) as caught:
            continue_codex_session(ctx=ctx, name=session.store.session_name, task="continue")
    assert caught.value is interrupt
    if retry_fails:
        assert "Could not record Codex resume exit" in caplog.text
        with pytest.raises(ForgeOpError, match="no verified post-exit evidence"):
            session.replay()
    else:
        assert session.replay() == (INITIAL, "target-a")
    assert len(writes) == 2 and writes[0] == writes[1]
    assert writes[0][1]["expected_instance_id"] == session.instance

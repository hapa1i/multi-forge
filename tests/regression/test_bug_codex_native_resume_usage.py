"""A direct resume must never charge an inherited thread total as this launch's usage."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from forge.core.ops.codex_adopt import adopt_codex_session, plan_codex_adoption
from forge.core.ops.codex_session import (
    CodexSessionResumeResult,
    continue_codex_session,
)
from forge.core.ops.context import ExecutionContext
from forge.core.runtime.codex_rollouts import codex_home
from forge.core.telemetry.downstream import read_downstream_records
from forge.core.usage.ledger import read_usage_events
from forge.session import SessionManager
from tests.src.core.ops.test_codex_adopt import _make_project
from tests.src.core.ops.test_codex_session import _SUCCESS_TID, _preflight

pytestmark = pytest.mark.regression

_BASE = (100, 20, 10)
_UNKNOWN = (None, None, None)
_TokenCounts = tuple[int, int, int]


def _usage(counts: _TokenCounts) -> dict[str, int]:
    tokens_in, cached, tokens_out = counts
    return {"input_tokens": tokens_in, "cached_input_tokens": cached, "output_tokens": tokens_out}


def _row(kind: str, **payload: object) -> str:
    return json.dumps({"type": kind, "payload": payload}) + "\n"


def _sample(total: _TokenCounts, last: _TokenCounts) -> str:
    return _row(
        "event_msg",
        type="token_count",
        info={"total_token_usage": _usage(total), "last_token_usage": _usage(last)},
    )


def _turn(total: _TokenCounts, request: _TokenCounts, *, failed: bool = False) -> str:
    turn = str(uuid4())
    end = {"type": "turn_aborted"} if failed else {"type": "task_complete", "last_agent_message": "OK"}
    user = {"type": "UserMessage", "content": [{"type": "text", "text": "Continue", "text_elements": []}]}
    agent = {"type": "AgentMessage", "content": [{"type": "Text", "text": "partial" if failed else "OK"}]}
    return "".join(
        [
            _row("event_msg", type="task_started", turn_id=turn, root_turn_id=turn),
            _row("turn_context", turn_id=turn, root_turn_id=turn, model="gpt-6.1-sol"),
            _row("event_msg", type="item_completed", thread_id=_SUCCESS_TID, turn_id=turn, item=user),
            _row("event_msg", type="item_completed", thread_id=_SUCCESS_TID, turn_id=turn, item=agent),
            _row(
                "token_usage_record",
                session_id=_SUCCESS_TID,
                thread_id=_SUCCESS_TID,
                root_turn_id=turn,
                turn_id=turn,
                usage=_usage(request),
                turn_token_usage=_usage(request),
                thread_token_usage=_usage(total),
            ),
            _sample(total, request),
            _row("event_msg", turn_id=turn, root_turn_id=turn, **end),
        ]
    )


@pytest.fixture
def adopted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ExecutionContext, Path]:
    project = _make_project(tmp_path)
    monkeypatch.chdir(project)
    ctx = ExecutionContext(cwd=project, worktree_root=project, project_root=project, forge_root=project)
    monkeypatch.setattr("forge.core.ops.codex_adopt.assert_codex_ready", _preflight)
    monkeypatch.setattr("forge.core.ops.codex_session.assert_codex_ready", _preflight)

    directory = codex_home() / "sessions/2026/10/01"
    directory.mkdir(parents=True)
    path = directory / f"rollout-2026-10-01T00-00-00-{_SUCCESS_TID}.jsonl"
    header = _row(
        "session_meta",
        id=_SUCCESS_TID,
        cwd=str(project),
        originator="Codex Desktop",
        source="vscode",
        model_provider="openai",
    )
    # An adopted Desktop history can have usage samples without the proxy's task lifecycle.
    path.write_text(header + _sample(_BASE, _BASE), encoding="utf-8")
    adopt_codex_session(ctx, plan_codex_adoption(ctx, _SUCCESS_TID), name="impl")
    return ctx, path


def _resume(
    ctx: ExecutionContext,
    path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    append: str,
    terminal: _TokenCounts | None,
    thread_id: str = _SUCCESS_TID,
) -> CodexSessionResumeResult:
    end = (
        {"type": "turn.completed", "usage": _usage(terminal)}
        if terminal is not None
        else {"type": "turn.failed", "error": {"message": "interrupted"}}
    )
    events = [
        {"type": "thread.started", "thread_id": thread_id},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "OK" if terminal is not None else "partial"},
        },
        end,
    ]
    stream = "\n".join(json.dumps(event) for event in events)
    # The child mutates the rollout only after spawn, between Forge's two observations.
    script = """
import sys
path, appended, stream, status = sys.argv[1:]
if appended:
    with open(path, "a", encoding="utf-8") as rollout:
        rollout.write(appended)
print(stream)
sys.exit(int(status))
"""

    def scripted_launch(argv, env, *, cwd):
        assert argv[-2:] == ["resume", _SUCCESS_TID]
        return [sys.executable, "-c", script, str(path), append, stream, str(int(terminal is None))]

    monkeypatch.setattr("forge.core.invoker.codex.prepare_executor_launch", scripted_launch)
    return continue_codex_session(ctx=ctx, name="impl", task="Continue")


def _assert_accounting(
    result: CodexSessionResumeResult, expected: tuple[int | None, ...], *, failed: bool = False
) -> None:
    (event,) = read_usage_events(root_run_id=result.root_run_id)
    (attempt,) = read_downstream_records(kind="attempt", forge_run_id=event.run_id)
    assert result.codex.success is (not failed)
    assert event.status == ("error" if failed else "success")
    assert attempt.failed is failed
    for record in (result.codex, event, attempt):
        assert (record.input_tokens, record.cached_tokens, record.output_tokens) == expected


def test_partial_failure_excluded_from_next_launch(adopted, monkeypatch):
    ctx, path = adopted
    failed = _resume(ctx, path, monkeypatch, append=_turn((130, 25, 12), (30, 5, 2), failed=True), terminal=None)
    _assert_accounting(failed, _UNKNOWN, failed=True)

    succeeded = _resume(ctx, path, monkeypatch, append=_turn((160, 35, 16), (30, 10, 4)), terminal=(160, 35, 16))
    _assert_accounting(succeeded, (30, 10, 4))


def test_new_zero_delta_requires_a_fresh_sample(adopted, monkeypatch):
    ctx, path = adopted
    _assert_accounting(_resume(ctx, path, monkeypatch, append="", terminal=_BASE), _UNKNOWN)
    _assert_accounting(
        _resume(ctx, path, monkeypatch, append=_turn(_BASE, (0, 0, 0)), terminal=_BASE),
        (0, 0, 0),
    )


@pytest.mark.parametrize("condition", ["missing", "corrupt", "per-launch", "drift"])
def test_uncertain_accounting_preserves_the_resume(adopted, monkeypatch, condition):
    ctx, path = adopted
    total = (230, 45, 22)
    # All three exceed the baseline, so subtraction alone accepts the wrong values.
    delta = (130, 25, 12)
    if condition == "missing":
        path.unlink()
    elif condition == "corrupt":
        with path.open("a", encoding="utf-8") as rollout:
            rollout.write('{"type":\n')
    thread = str(uuid4()) if condition == "drift" else _SUCCESS_TID
    result = _resume(
        ctx,
        path,
        monkeypatch,
        append=_turn(total, delta),
        terminal=delta if condition == "per-launch" else total,
        thread_id=thread,
    )
    _assert_accounting(result, _UNKNOWN)
    if condition == "drift":
        assert any("drifted" in message for message in result.warnings)
        manager = SessionManager()
        state = manager.get_session("impl", forge_root=str(ctx.forge_root))
        assert state.confirmed.codex is not None and state.confirmed.codex.thread_id == thread
        assert manager.get_session_entry("impl", forge_root=str(ctx.forge_root)).codex_thread_id == thread

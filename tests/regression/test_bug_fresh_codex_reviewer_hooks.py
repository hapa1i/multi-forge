"""A fresh reviewer must not publish its SessionStart as the managed executor."""

import os
from unittest.mock import patch

import pytest

from forge.cli.hooks.codex_transfer import run_codex_session_start
from forge.core.invoker.types import HeadlessResult
from forge.core.ops.codex_interactive import reattach_codex_session
from forge.policy.semantic.supervisor import _dispatch_codex_supervisor
from forge.policy.types import ActionContext
from forge.session import SessionManager
from forge.session.models import SupervisorConfig
from tests.src.core.ops.test_codex_interactive import (
    _TID,
    _TID_B,
    _interactive_mocks,
    _make_project,
    _preflight,
    _seed_codex_session,
)

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("effort", [None, "low"])
def test_fresh_reviewer_keeps_the_executor_thread_receipt(tmp_path, monkeypatch, effort):
    for key in list(os.environ):
        if key.startswith("FORGE_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge-home"))
    proj, ctx = _make_project(tmp_path, monkeypatch)
    _seed_codex_session(proj)
    requests = []

    def hook(thread):
        run_codex_session_start(
            {
                "hook_event_name": "SessionStart",
                "session_id": thread,
                "cwd": str(proj),
                "transcript_path": str(tmp_path / (thread + ".jsonl")),
                "source": "startup",
            }
        )

    def review_run(self, request):
        requests.append(request)
        # Replay the registered hook only when the actual request leaves it enabled.
        disabled = any(left == "--disable" and right == "hooks" for left, right in zip(request.argv, request.argv[1:]))
        if not disabled:
            with patch.dict(os.environ, request.env, clear=True):
                hook(_TID_B)
        return HeadlessResult(
            label="supervisor",
            stdout="{}",
            stderr="",
            returncode=0,
            duration_seconds=0,
            runtime_session_id=_TID_B,
        )

    def invoke(**kwargs):
        with patch.dict(
            os.environ,
            {
                "FORGE_SESSION": kwargs["session_name"],
                "FORGE_FORGE_ROOT": kwargs["forge_root"],
                "FORGE_DEPTH": "1",
            },
        ):
            hook(_TID)
            _dispatch_codex_supervisor(
                prompt="review",
                config=SupervisorConfig(supervisor_effort=effort),
                context=ActionContext(
                    origin="codex",
                    event="PreToolUse.Edit",
                    tool_name="Edit",
                    tool_args={},
                    repo_root=str(proj),
                    session_name="impl",
                ),
                usage_command="supervisor",
            )
        return 0

    monkeypatch.setattr(
        "forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight",
        _preflight,
    )
    monkeypatch.setattr("forge.core.invoker.codex.CodexHeadlessInvoker.run", review_run)
    with _interactive_mocks():
        result = reattach_codex_session(ctx=ctx, name="impl", invoke=invoke)

    assert result.thread_id == _TID
    assert SessionManager().get_session("impl", forge_root=str(proj)).confirmed.codex.thread_id == _TID
    assert len(requests) == 1
    if effort:
        assert f'model_reasoning_effort="{effort}"' in requests[0].argv

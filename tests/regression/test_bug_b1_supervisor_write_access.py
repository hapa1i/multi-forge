"""B1: resumed supervisors inherited writable Claude capabilities."""

from unittest.mock import patch

import pytest

from forge.core.reactive.session_runner import SessionResult
from forge.policy.semantic.supervisor import (
    _dispatch_claude_supervisor,
    _ResolvedTarget,
)
from forge.policy.types import ActionContext
from forge.session.models import SupervisorConfig

pytestmark = pytest.mark.regression


def test_resumed_supervisor_requests_enforced_read_only_access(tmp_path):
    context = ActionContext(
        origin="codex",
        event="PreToolUse.Edit",
        tool_name="Edit",
        tool_args={},
        repo_root=str(tmp_path / "executor"),
        session_name="executor",
    )
    with patch("forge.policy.semantic.supervisor.run_claude_session") as run:
        run.return_value = SessionResult(stdout="", stderr="", returncode=0)
        _dispatch_claude_supervisor(
            prompt="Review the proposed edit",
            config=SupervisorConfig(resume_id="planning-history", direct=True),
            context=context,
            resolved=_ResolvedTarget(resume_id="planning-history", source_cwd=str(tmp_path / "planner")),
            usage_command="supervisor",
            backend_id="anthropic-direct",
        )
    assert run.call_args.kwargs.get("read_only") is True
    assert run.call_args.kwargs["additional_dirs"] == (str(tmp_path / "executor"),)

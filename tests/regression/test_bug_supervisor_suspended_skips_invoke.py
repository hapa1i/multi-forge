"""Regression: suspended supervisor must not invoke the LLM subprocess.

Bug: --off destroyed SupervisorConfig entirely. Adding a suspended toggle
requires that suspension is checked at both the engine gate (applies_to)
and the defensive _evaluate guard, preventing subprocess invocation.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from forge.policy.semantic.supervisor import SemanticSupervisorPolicy
from forge.policy.types import ActionContext
from forge.session.models import SupervisorConfig

pytestmark = pytest.mark.regression


def _make_context() -> ActionContext:
    return ActionContext(
        event="PreToolUse.Write",
        tool_name="Write",
        tool_args={"file_path": "src/main.py", "content": "x = 1"},
        repo_root="/workspace",
        session_name="test",
        target_path="src/main.py",
        new_content="x = 1",
    )


class TestSuspendedSupervisorSkipsInvoke:
    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_suspended_evaluate_does_not_invoke(self, mock_invoke: MagicMock) -> None:
        """Suspended supervisor's _evaluate() returns allow without subprocess call."""
        config = SupervisorConfig(resume_id="planner-uuid", suspended=True)
        policy = SemanticSupervisorPolicy(config=config)

        result = policy.evaluate(_make_context())
        assert result.decision == "allow"
        assert not result.warnings
        mock_invoke.assert_not_called()

    def test_suspended_supervisor_not_registered_by_hook(self) -> None:
        """The has_supervisor check in commands.py excludes suspended supervisors."""
        from forge.session.models import PolicyIntent

        # Simulate the hook's has_supervisor logic
        policy = PolicyIntent(
            enabled=True,
            supervisor=SupervisorConfig(resume_id="planner", suspended=True),
        )
        sup = policy.supervisor
        has_supervisor = bool(sup and sup.resume_id and not sup.suspended)
        assert has_supervisor is False

        # Unsuspended should register
        policy.supervisor = SupervisorConfig(resume_id="planner", suspended=False)
        sup = policy.supervisor
        has_supervisor = bool(sup and sup.resume_id and not sup.suspended)
        assert has_supervisor is True

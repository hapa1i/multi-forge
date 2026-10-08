"""B1: restoring a plan's mtime and size retained a cached verdict for different bytes."""

import os
from unittest.mock import patch

import pytest

from forge.policy.semantic.supervisor import SemanticSupervisorPolicy
from forge.policy.types import ActionContext, PolicyDecision
from forge.session.models import SupervisorConfig

pytestmark = pytest.mark.regression


def test_equal_size_plan_replacement_invalidates_persisted_supervisor_cache(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text("allow A\n")
    before = plan.stat()
    config = SupervisorConfig(resume_id="planner", plan_override_path=str(plan))
    action = ActionContext("codex", "PreToolUse.Write", "Write", {}, str(tmp_path), "worker", "f.py", "A")
    with patch(
        "forge.policy.semantic.supervisor.invoke_supervisor",
        return_value=PolicyDecision("allow", "semantic.supervisor"),
    ) as review:
        first = SemanticSupervisorPolicy(config)
        first.evaluate(action)
        plan.write_text("allow B\n")
        os.utime(plan, ns=(before.st_atime_ns, before.st_mtime_ns))
        resumed = SemanticSupervisorPolicy(config)
        resumed.set_state(first.get_state())
        assert not resumed.evaluate(action).cached
        assert review.call_count == 2

"""B1: review evidence grew without bounds and every session read decoded all files."""

import pytest

from forge.policy.semantic import attempts
from forge.policy.semantic.plan_source import PlanSnapshot
from forge.policy.types import ActionContext, PolicyDecision
from forge.session.models import SupervisorConfig

pytestmark = pytest.mark.regression


def test_retention_bounds_completed_records_and_preserves_live_writer(tmp_path, monkeypatch):
    monkeypatch.setattr(attempts, "MAX_SESSION_ATTEMPTS", 2)
    context = ActionContext("codex", "PreToolUse.Write", "Write", {}, str(tmp_path), "worker")
    config = SupervisorConfig(plan_override_path="/plan")
    snapshot = PlanSnapshot("/plan", "plan", "digest")
    pending = attempts.ReviewAttempt(config, context, snapshot, None, budget=60)
    try:
        for _ in range(4):
            attempt = attempts.ReviewAttempt(config, context, snapshot, None, budget=5)
            attempt.finish(PolicyDecision("allow", "semantic.supervisor"))
        rows = attempts.read_attempts("worker")
        assert len(rows) == 3
        assert sum(row["state"] == "pending" for row in rows) == 1
        assert pending.path.exists()
        assert len(list(pending.path.parent.glob("*.lock"))) == 3
    finally:
        pending.close()

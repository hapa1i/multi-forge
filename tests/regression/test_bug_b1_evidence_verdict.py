"""B1: failing the terminal evidence write discarded an already computed verdict."""

from unittest.mock import patch

import pytest

from forge.policy.semantic import attempts
from forge.policy.semantic.plan_check import PlanCheckPolicy
from forge.policy.semantic.supervisor import SupervisorRun, run_supervisor_check
from forge.policy.types import ActionContext, PolicyDecision, Violation
from forge.session.models import SupervisorConfig

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("stage", ["frontier", "checker"])
@pytest.mark.parametrize("verdict", ["deny", "allow", "needs_review"])
def test_final_evidence_failure_preserves_verdict(tmp_path, stage, verdict):
    config = SupervisorConfig(plan_override_path=str(tmp_path / "plan"), cascade=stage == "checker")
    (tmp_path / "plan").write_text("approved plan")
    context = ActionContext("codex", "PreToolUse.Write", "Write", {}, str(tmp_path), "worker")
    decision = PolicyDecision(
        decision=verdict,
        policy_id="semantic.supervisor",
        violations=[Violation("divergence", "Violates approved plan", "high", citations=["approved plan"])],
    )
    write = attempts.atomic_write_json
    writes = 0

    def fail_final(path, data):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("disk full")
        return write(path, data)

    with patch.object(attempts, "atomic_write_json", side_effect=fail_final):
        if stage == "frontier":
            with patch("forge.policy.semantic.supervisor._run_supervisor_check", return_value=SupervisorRun(decision)):
                actual = run_supervisor_check(config, context).decision
        else:
            policy = PlanCheckPolicy(config)
            with patch.object(policy, "_check", return_value=decision):
                actual = policy.evaluate(context)
    assert actual is decision
    assert actual.decision == verdict
    assert not actual.fail_open
    assert actual.violations[0].citations == ["approved plan"]
    assert any("evidence" in warning.lower() for warning in actual.warnings)
    assert attempts.read_attempts("worker")[0]["state"] == "incomplete"


def test_recorder_exception_cannot_enter_the_frontier_fail_open_handler(tmp_path):
    config = SupervisorConfig(resume_id="planner")
    context = ActionContext("codex", "PreToolUse.Write", "Write", {}, str(tmp_path), "worker")
    decision = PolicyDecision(decision="deny", policy_id="semantic.supervisor")
    with (
        patch("forge.policy.semantic.supervisor._run_supervisor_check", return_value=SupervisorRun(decision)),
        patch.object(attempts.ReviewAttempt, "finish", side_effect=OSError("recorder failure")),
    ):
        assert run_supervisor_check(config, context).decision is decision
    assert decision.decision == "deny" and not decision.fail_open

"""Regression for D003: malformed violation entries must not escape evaluation.

Root cause: the parser validated only the ``violations`` container, while the
converter called ``.get`` on every list element. A string element raised
``AttributeError`` and the policy engine converted that exception to a denial
when configured fail closed.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from unittest.mock import patch

import pytest

from forge.core.reactive.session_runner import SessionResult
from forge.policy.engine import PolicyEngine
from forge.policy.semantic.supervisor import SemanticSupervisorPolicy
from forge.policy.semantic.verdict import parse_supervisor_verdict, verdict_to_decision
from forge.policy.types import ActionContext
from forge.session.models import SupervisorConfig

pytestmark = pytest.mark.regression

_SUPERVISOR_UUID = "12345678-1234-1234-1234-123456789abc"


def _response(violations: Any) -> str:
    return json.dumps({"verdict": "divergent", "confidence": 0.95, "violations": violations})


def _context() -> ActionContext:
    return ActionContext(
        origin="claude_code",
        event="PreToolUse.Edit",
        tool_name="Edit",
        tool_args={"file_path": "src/app.py"},
        repo_root="/workspace",
        session_name="worker",
        target_path="src/app.py",
        new_content="changed",
    )


@pytest.mark.parametrize("fail_mode", ["open", "closed"])
@patch("forge.policy.semantic.supervisor.run_claude_session")
def test_non_mapping_violation_cannot_become_policy_error_denial(
    mock_run: Any, fail_mode: Literal["open", "closed"]
) -> None:
    mock_run.return_value = SessionResult(stdout=_response(["bad"]), stderr="", returncode=0)
    policy = SemanticSupervisorPolicy(
        SupervisorConfig(resume_id=_SUPERVISOR_UUID, direct=True, throttle_seconds=0)
    )
    engine = PolicyEngine(policies=[policy], fail_mode=fail_mode)

    result = engine.evaluate(_context())

    assert result.final_decision == "warn"
    assert result.decisions[0].failure_type is None


@pytest.mark.parametrize("violations", [None, "bad", {"evidence": "bad"}, 7])
def test_non_list_violation_container_normalizes_to_no_specific_violations(violations: Any) -> None:
    decision = verdict_to_decision(parse_supervisor_verdict(_response(violations)))

    assert decision.decision == "warn"
    assert decision.violations == []


def test_non_mapping_entries_are_ignored_without_hiding_valid_violations() -> None:
    verdict = parse_supervisor_verdict(
        _response(["bad", {"evidence": "Changed the plan", "citations": ["Plan section 2"]}])
    )

    decision = verdict_to_decision(verdict)

    assert decision.decision == "deny"
    assert len(decision.violations) == 1
    assert decision.violations[0].message == "Changed the plan"

"""Regression for O028: unknown supervisor verdicts must remain parse failures.

Root cause: the parser rewrote every unknown or case-mismatched verdict literal
to ``aligned`` while reporting ``parsed=True``. Enforcement treated malformed
output as a clean cacheable allow and shadow auditing classified it as agreement.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from forge.core.reactive.session_runner import SessionResult
from forge.core.reactive.throttle import compute_cache_key
from forge.core.state import now_iso
from forge.policy.engine import PolicyEngine
from forge.policy.semantic.shadow_runner import STATUS_ERROR, classify_shadow
from forge.policy.semantic.supervisor import (
    SemanticSupervisorPolicy,
    run_supervisor_check,
)
from forge.policy.semantic.verdict import parse_supervisor_verdict_with_status
from forge.policy.types import ActionContext, PolicyDecision
from forge.session.models import SupervisorConfig

pytestmark = pytest.mark.regression

_SUPERVISOR_UUID = "12345678-1234-1234-1234-123456789abc"
_UNKNOWN_RESPONSE = json.dumps({"verdict": "DIVERGENT", "confidence": 0.95, "violations": []})


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


def _config() -> SupervisorConfig:
    return SupervisorConfig(resume_id=_SUPERVISOR_UUID, direct=True, throttle_seconds=60)


@pytest.mark.parametrize("verdict_value", ["DIVERGENT", "unknown", "", None])
def test_unknown_or_case_mismatched_literal_is_not_a_parsed_alignment(verdict_value: Any) -> None:
    response = json.dumps({"verdict": verdict_value, "confidence": 0.95, "violations": []})

    verdict, parsed = parse_supervisor_verdict_with_status(response)

    assert parsed is False
    assert verdict.verdict == "divergent"
    assert verdict.confidence == 0.0


def test_missing_verdict_is_a_schema_parse_failure() -> None:
    verdict, parsed = parse_supervisor_verdict_with_status(json.dumps({"confidence": 0.95, "violations": []}))

    assert parsed is False
    assert verdict.verdict == "divergent"
    assert verdict.confidence == 0.0


@patch("forge.policy.semantic.supervisor.run_claude_session")
def test_unknown_verdict_is_structural_fail_open_and_shadow_error(mock_run: Any) -> None:
    mock_run.return_value = SessionResult(stdout=_UNKNOWN_RESPONSE, stderr="", returncode=0)

    run = run_supervisor_check(_config(), _context())

    assert run.run_ok is True
    assert run.parsed is False
    assert run.decision.decision == "allow"
    assert run.decision.fail_open is True
    assert run.decision.failure_type == "parse_failure"
    assert classify_shadow(run) == STATUS_ERROR


@patch("forge.policy.engine.record_upstream_operation")
@patch("forge.policy.semantic.supervisor.run_claude_session")
def test_unknown_verdict_is_not_cached_and_emits_fail_open_telemetry(mock_run: Any, mock_record: Any) -> None:
    mock_run.return_value = SessionResult(stdout=_UNKNOWN_RESPONSE, stderr="", returncode=0)
    policy = SemanticSupervisorPolicy(_config())
    engine = PolicyEngine(policies=[policy], fail_mode="closed")

    first = engine.evaluate(_context())
    second = engine.evaluate(_context())

    assert first.final_decision == "allow"
    assert second.final_decision == "allow"
    assert all(decision.fail_open for result in (first, second) for decision in result.decisions)
    assert mock_run.call_count == 2
    assert policy.get_state()["cache"] == {}
    assert mock_record.call_count == 2
    assert all(call.kwargs["status"] == "fail_open" for call in mock_record.call_args_list)
    assert all(call.kwargs["reason_code"] == "parse_failure" for call in mock_record.call_args_list)


@patch("forge.policy.semantic.supervisor.invoke_supervisor")
def test_unknown_restored_cache_verdict_is_a_miss(mock_invoke: Any) -> None:
    context = _context()
    cache_key = compute_cache_key(context.tool_name, context.target_path, context.new_content)
    policy = SemanticSupervisorPolicy(_config())
    policy.set_state(
        {
            "cache": {
                cache_key: {
                    "checked_at": now_iso(),
                    "verdict": "DIVERGENT",
                    "confidence": 0.95,
                }
            }
        }
    )
    mock_invoke.return_value = PolicyDecision(
        decision="warn",
        policy_id="semantic.supervisor",
        warnings=["Fresh supervisor result"],
    )

    result = policy.evaluate(context)

    assert result.decision == "warn"
    assert result.cached is False
    mock_invoke.assert_called_once()

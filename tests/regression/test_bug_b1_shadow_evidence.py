"""B1: shadow audits appeared as live enforcement and inherited models could not replay."""

import json
from unittest.mock import patch

import pytest

from forge.policy.semantic.attempts import read_attempts
from forge.policy.semantic.shadow import capture_candidate, count_existing_candidates
from forge.policy.semantic.shadow_runner import reconstruct_config, run_shadow_candidate
from forge.policy.semantic.supervisor import (
    SupervisorRun,
    _ResolvedTarget,
    run_supervisor_check,
)
from forge.policy.types import ActionContext, PolicyDecision
from forge.session.claude.paths import get_transcript_path
from forge.session.models import SupervisorConfig

pytestmark = pytest.mark.regression


def test_shadow_deny_does_not_replace_latest_live_allow(tmp_path):
    config = SupervisorConfig(plan_override_path=str(tmp_path / "plan"))
    context = ActionContext("codex", "PreToolUse.Write", "Write", {}, str(tmp_path), "worker")
    with patch(
        "forge.policy.semantic.supervisor._run_supervisor_check",
        return_value=SupervisorRun(PolicyDecision("allow", "semantic.supervisor")),
    ):
        run_supervisor_check(config, context)
    with patch(
        "forge.policy.semantic.supervisor._run_supervisor_check",
        return_value=SupervisorRun(PolicyDecision("deny", "semantic.supervisor")),
    ):
        run_supervisor_check(config, context, usage_command="supervisor-shadow")
    assert len(read_attempts("worker")) == 1
    assert read_attempts("worker")[0]["verdict"] == "allow"
    assert read_attempts("worker", purpose="shadow")[0]["verdict"] == "deny"


def test_default_legacy_supervisor_freezes_restored_model_and_replays(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_DEFAULT_SONNET_MODEL", raising=False)
    uuid = "12345678-1234-1234-1234-123456789abc"
    transcript = get_transcript_path(str(tmp_path), uuid)
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-5-5", "role": "assistant"}}) + "\n"
    )
    plan = tmp_path / "plan.md"
    plan.write_text("approved plan")
    config = SupervisorConfig(resume_id=uuid, direct=True, forge_root=str(tmp_path), plan_override_path=str(plan))
    context = ActionContext("claude_code", "PreToolUse.Write", "Write", {}, str(tmp_path), "worker")
    with patch(
        "forge.policy.semantic.supervisor._resolve_resume_target", return_value=_ResolvedTarget(uuid, str(tmp_path))
    ):
        path = capture_candidate(
            config,
            context,
            cache_key="test",
            tier1_reason="ok",
            checker_model="checker",
            checker_provider="openrouter",
            checker_budget_tokens=1000,
            checker_prompt_version=1,
        )
    assert path is not None
    candidate = json.loads(path.read_text())
    assert candidate["model_source"] == "conversation"
    assert candidate["supervisor_model"] == candidate["lane"]["model"] == "claude-sonnet-5-5"
    assert reconstruct_config(candidate, path.parent).supervisor_model == "claude-sonnet-5-5"
    with patch(
        "forge.policy.semantic.shadow_runner.run_supervisor_check",
        return_value=SupervisorRun(PolicyDecision("allow", "semantic.supervisor")),
    ) as review:
        run_shadow_candidate(path)
    review.assert_called_once()


def test_unavailable_reconstruction_does_not_consume_shadow_spend_cap(tmp_path):
    failed = tmp_path / "failed.done"
    failed.write_text(json.dumps({"status": "error", "review_state": "unavailable", "error": "unverified model"}))
    assert count_existing_candidates(tmp_path) == 0
    failed.write_text(json.dumps({"status": "error", "run_ok": False}))
    assert count_existing_candidates(tmp_path) == 1

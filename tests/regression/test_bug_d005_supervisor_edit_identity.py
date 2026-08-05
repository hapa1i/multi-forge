"""Regression for D005: supervision must identify the complete edit.

Root cause: Claude and Codex hook adapters truncated presentation fields before
the semantic supervisor and plan checker built cache keys. Both caches hashed
only ``tool_name``, path, and truncated ``new_content``; Claude's frontier
prompt also omitted ``old_string``. Distinct removals and changes beyond the
5,000-character presentation boundary could therefore reuse a clean allow.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from unittest.mock import MagicMock, patch

import pytest

from forge.cli.hooks.codex_policy import CodexHookAdapter
from forge.cli.hooks.policy import ClaudeHookAdapter
from forge.core.reactive.session_runner import SessionResult
from forge.policy.deterministic.base import DeterministicPolicy
from forge.policy.semantic.plan_check import PlanCheckPolicy, PlanCheckVerdict
from forge.policy.semantic.supervisor import SemanticSupervisorPolicy, invoke_supervisor
from forge.policy.types import ActionContext, PolicyDecision
from forge.session.models import SupervisorConfig

pytestmark = pytest.mark.regression

_SUPERVISOR_UUID = "12345678-1234-1234-1234-123456789abc"
_ALIGNED_RESPONSE = '{"verdict":"aligned","confidence":0.95,"violations":[]}'
CacheLayer = Literal["supervisor", "plan_check"]


def _manifest() -> SimpleNamespace:
    return SimpleNamespace(name="worker")


def _claude_edit(tmp_path: Path, *, old_string: str, new_string: str = "replacement()") -> ActionContext:
    payload = {
        "tool_input": {
            "file_path": str(tmp_path / "src" / "app.py"),
            "old_string": old_string,
            "new_string": new_string,
        }
    }
    contexts = ClaudeHookAdapter().build_contexts(payload, "Edit", _manifest())
    assert len(contexts) == 1
    return contexts[0]


def _claude_write(tmp_path: Path, *, content: str) -> ActionContext:
    payload = {"tool_input": {"file_path": str(tmp_path / "src" / "app.py"), "content": content}}
    contexts = ClaudeHookAdapter().build_contexts(payload, "Write", _manifest())
    assert len(contexts) == 1
    return contexts[0]


def _codex_delete_only_update(tmp_path: Path, *, removed: str) -> ActionContext:
    command = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: src/app.py",
            "@@",
            f"-{removed}",
            "*** End Patch",
        ]
    )
    payload = {"cwd": str(tmp_path), "tool_input": {"command": command}}
    contexts = CodexHookAdapter().build_contexts(payload, "apply_patch", _manifest())
    assert len(contexts) == 1
    return contexts[0]


def _exercise_cache_layer(layer: CacheLayer, contexts: list[ActionContext], tmp_path: Path) -> MagicMock:
    policy: DeterministicPolicy
    if layer == "supervisor":
        policy = SemanticSupervisorPolicy(
            SupervisorConfig(resume_id=_SUPERVISOR_UUID, direct=True, throttle_seconds=60)
        )
        mock = MagicMock(
            side_effect=lambda *_args, **_kwargs: PolicyDecision(
                decision="allow",
                policy_id="semantic.supervisor",
            )
        )
        patcher = patch("forge.policy.semantic.supervisor.invoke_supervisor", mock)
    else:
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan\nPreserve behavior.")
        policy = PlanCheckPolicy(
            SupervisorConfig(
                resume_id=_SUPERVISOR_UUID,
                direct=True,
                cascade=True,
                plan_override_path=str(plan),
                throttle_seconds=60,
            )
        )
        mock = MagicMock(return_value=PlanCheckVerdict(aligned=True, reason="aligned"))
        patcher = patch("forge.policy.semantic.plan_check.run_plan_check", mock)

    with patcher:
        for context in contexts:
            assert policy.evaluate(context).decision == "allow"
    return mock


@pytest.mark.parametrize("layer", ["supervisor", "plan_check"])
def test_claude_removed_text_distinguishes_cache_identity(
    layer: CacheLayer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    contexts = [
        _claude_edit(tmp_path, old_string="remove_first()"),
        _claude_edit(tmp_path, old_string="remove_second()"),
    ]

    mock = _exercise_cache_layer(layer, contexts, tmp_path)

    assert mock.call_count == 2


@pytest.mark.parametrize("layer", ["supervisor", "plan_check"])
def test_codex_delete_only_hunks_distinguish_cache_identity(layer: CacheLayer, tmp_path: Path) -> None:
    contexts = [
        _codex_delete_only_update(tmp_path, removed="remove_first()"),
        _codex_delete_only_update(tmp_path, removed="remove_second()"),
    ]
    assert contexts[0].new_content is None and contexts[1].new_content is None

    mock = _exercise_cache_layer(layer, contexts, tmp_path)

    assert mock.call_count == 2


@pytest.mark.parametrize("layer", ["supervisor", "plan_check"])
@pytest.mark.parametrize("runtime", ["claude", "codex"])
def test_post_truncation_tail_distinguishes_cache_identity(
    layer: CacheLayer,
    runtime: Literal["claude", "codex"],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    common = "x" * 5_100
    if runtime == "claude":
        monkeypatch.chdir(tmp_path)
        contexts = [
            _claude_write(tmp_path, content=common + "first-tail"),
            _claude_write(tmp_path, content=common + "second-tail"),
        ]
        assert contexts[0].new_content == contexts[1].new_content
    else:
        contexts = [
            _codex_delete_only_update(tmp_path, removed=common + "first-tail"),
            _codex_delete_only_update(tmp_path, removed=common + "second-tail"),
        ]
        assert contexts[0].raw_diff == contexts[1].raw_diff

    mock = _exercise_cache_layer(layer, contexts, tmp_path)

    assert mock.call_count == 2


@patch("forge.policy.semantic.supervisor.run_claude_session")
def test_claude_frontier_prompt_includes_matched_and_replacement_fragments(
    mock_run: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    context = _claude_edit(
        tmp_path,
        old_string="dangerous_call()",
        new_string="safe_call()",
    )
    mock_run.return_value = SessionResult(stdout=_ALIGNED_RESPONSE, stderr="", returncode=0)

    decision = invoke_supervisor(
        SupervisorConfig(resume_id=_SUPERVISOR_UUID, direct=True, throttle_seconds=0),
        context,
    )

    assert decision.decision == "allow"
    prompt = mock_run.call_args.args[0] if mock_run.call_args.args else mock_run.call_args.kwargs["prompt"]
    assert "Matched/replaced fragment (old_string)" in prompt
    assert "dangerous_call()" in prompt
    assert "Replacement fragment (new_string)" in prompt
    assert "safe_call()" in prompt

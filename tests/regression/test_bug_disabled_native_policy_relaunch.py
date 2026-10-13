"""Disabled native policy must not require reviewer readiness when a relaunch copies its overrides."""

from pathlib import Path

import pytest

from forge.session import IndexStore, SessionManager, create_session_state
from forge.session.effective import compute_effective_intent
from forge.session.models import (
    ConsumerLaneIntent,
    LaneRecord,
    NativeSupervisorSource,
    PolicyIntent,
    SupervisorConfig,
)
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("disabled_in_intent", [False, True])
def test_disabled_native_policy_relaunch_preserves_disabled_child_without_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, disabled_in_intent: bool
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    state = create_session_state("executor", worktree_path=str(project))
    state.intent.policy = PolicyIntent(
        enabled=not disabled_in_intent,
        supervisor=SupervisorConfig(
            native_source=NativeSupervisorSource(
                runtime="codex",
                thread_id="01a12b5c-ce1a-72c2-ad3f-05d75f3fba00",
                home=str(tmp_path / "codex"),
                rollout_path=str(tmp_path / "codex" / "missing.jsonl"),
                source_cwd=str(project),
                header_digest="a" * 64,
            ),
            auth_mode="subscription-only",
            supervisor_model="gpt-6.1-sol",
            supervisor_effort="low",
        ),
    )
    state.intent.consumer_lanes = ConsumerLaneIntent(supervisor=LaneRecord("codex", "chatgpt", "gpt-6.1-sol"))
    if not disabled_in_intent:
        state.overrides = {"policy": {"enabled": False}}
    index = IndexStore(tmp_path / "forge" / "sessions" / "index.json")
    publish_session(index, state, project)

    def unavailable_reviewer(_supervisor: SupervisorConfig) -> None:
        raise AssertionError("disabled inherited policy must not check reviewer readiness")

    monkeypatch.setattr("forge.policy.semantic.native_codex.preflight_native", unavailable_reviewer)

    _, child = SessionManager(index).relaunch_session("executor", child_name="child", forge_root=str(project))

    child_policy = compute_effective_intent(child).policy
    assert child_policy is not None
    assert not child_policy.enabled
    assert child.overrides == state.overrides

"""B1: supervisor admission changed unrelated state and rejected legacy sessions."""

import json
from unittest.mock import patch

import pytest

from forge.core.ops.policy import (
    SupervisorInputError,
    supervisor_cascade,
    supervisor_set,
)
from forge.policy.semantic.identity import (
    SUPERVISOR_CONSUMER,
    select_supervisor_lane,
    validate_reviewer,
)
from forge.policy.semantic.supervisor import (
    apply_supervisor_and_lane,
    apply_supervisor_to_intent,
)
from forge.session import SessionStore, create_session_state
from forge.session.launch import get_launch_preferences
from forge.session.models import PolicyIntent, SupervisorConfig

pytestmark = pytest.mark.regression


def test_setting_supervisor_preserves_tuning_overrides():
    state = create_session_state("worker")
    tuning = {
        "shadow_sample_rate": 0.25,
        "shadow_max_per_session": 7,
        "throttle_seconds": 15,
        "checker_model": "custom",
    }
    state.overrides = {"policy": {"enabled": False, "supervisor": {**tuning, "resume_id": "stale"}}}
    apply_supervisor_to_intent(state, SupervisorConfig(resume_id="planner"))
    assert state.overrides["policy"]["supervisor"] == tuning
    assert state.intent.policy.supervisor.resume_id == "planner"


@pytest.mark.parametrize("supervised", [False, True])
def test_launch_preferences_ignore_incomplete_unrelated_proxy_override(tmp_path, supervised):
    state = create_session_state("worker", worktree_path=str(tmp_path))
    state.overrides = {"proxy": {"template": "litellm-other"}}
    if supervised:
        state.intent.policy = PolicyIntent(supervisor=SupervisorConfig(resume_id="planner"))
    assert get_launch_preferences(state)[0] is False


def test_sidecar_preferences_remain_readable_for_old_plan_override(tmp_path):
    state = create_session_state("worker", worktree_path=str(tmp_path), launch_mode="sidecar")
    state.intent.policy = PolicyIntent(
        supervisor=SupervisorConfig(resume_id="planner", plan_override_path="/host/plan")
    )
    assert get_launch_preferences(state)[0] is True


def test_cascade_refuses_sidecar_before_plan_resolution_or_write(tmp_path):
    state = create_session_state("worker", worktree_path=str(tmp_path), launch_mode="sidecar")
    state.intent.policy = PolicyIntent(supervisor=SupervisorConfig(resume_id="planner"))
    store = SessionStore(str(tmp_path), "worker")
    store.write(state)
    before = store.manifest_path.read_bytes()
    with patch("forge.policy.semantic.supervisor.resolve_supervisor_reload_plan_path") as resolve:
        with pytest.raises(SupervisorInputError, match="host executor"):
            supervisor_cascade(store=store, manifest=state, state="on")
    resolve.assert_not_called()
    assert store.manifest_path.read_bytes() == before


def test_v2_timeout_and_codex_proxy_migrate_in_memory(tmp_path):
    state = create_session_state("worker", worktree_path=str(tmp_path))
    sup = SupervisorConfig(resume_id="planner", timeout_seconds=90, proxy="old-claude-proxy", base_url="http://old")
    from forge.session.consumer_lanes import set_intent_lane

    lane = select_supervisor_lane(runtime="codex")
    state.intent.policy = PolicyIntent(supervisor=sup)
    set_intent_lane(state, SUPERVISOR_CONSUMER, lane)
    state.overrides = {"policy": {"supervisor": {"timeout_seconds": 80}}}
    store = SessionStore(str(tmp_path), "worker")
    store.write(state)
    raw = json.loads(store.manifest_path.read_text())
    raw["schema_version"] = 2
    for field in ("auth_mode", "supervisor_model"):
        raw["intent"]["policy"]["supervisor"].pop(field, None)
    store.manifest_path.write_text(json.dumps(raw))
    before = store.manifest_path.read_bytes()
    migrated = store.read()
    assert migrated.intent.policy.supervisor.timeout_seconds == 45
    assert migrated.overrides["policy"]["supervisor"]["timeout_seconds"] == 45
    validate_reviewer(migrated.intent.policy.supervisor, lane)
    assert migrated.intent.policy.supervisor.proxy is None
    assert migrated.intent.policy.supervisor.base_url is None
    assert store.manifest_path.read_bytes() == before


def test_codex_setup_does_not_inherit_planner_claude_proxy(tmp_path):
    state = create_session_state("worker", worktree_path=str(tmp_path))
    state.overrides = {"proxy": {"template": "incomplete-unrelated-override"}}
    store = SessionStore(str(tmp_path), "worker")
    store.write(state)
    with (
        patch("forge.policy.semantic.supervisor.validate_supervisor_target", return_value=state),
        patch("forge.policy.semantic.supervisor.auto_seed_supervisor_proxy", return_value="planner-claude-proxy"),
    ):
        result = supervisor_set(
            store=store, manifest=state, target="planner", policy_forge_root=str(tmp_path), runtime="codex"
        )
    assert result.config.proxy is None
    validate_reviewer(result.config, result.lane_record)


def test_start_fork_wiring_validates_before_changing_manifest():
    state = create_session_state("worker")
    with pytest.raises(ValueError, match="model"):
        apply_supervisor_and_lane(
            state,
            SupervisorConfig(resume_id="planner", supervisor_model="opus"),
            select_supervisor_lane(runtime="codex"),
        )
    assert state.intent.policy is None

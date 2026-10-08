"""B1: ordinary host writes made old sidecar hooks reject every manifest."""

import json
import subprocess
from unittest.mock import patch

import pytest

from forge.session import SessionStore, create_session_state
from forge.session.models import PolicyIntent, SupervisorConfig
from forge.sidecar.docker import require_sidecar_contract

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("supervisor", [None, SupervisorConfig(resume_id="planner")])
def test_ordinary_writes_remain_readable_by_v2_sidecar(tmp_path, supervisor):
    state = create_session_state("worker", worktree_path=str(tmp_path), launch_mode="sidecar")
    state.intent.policy = PolicyIntent(enabled=True, supervisor=supervisor)
    store = SessionStore(str(tmp_path), "worker")
    store.write(state)
    store.update_last_accessed()
    data = json.loads(store.manifest_path.read_text())
    assert data["schema_version"] == 2
    if supervisor:
        assert "auth_mode" not in data["intent"]["policy"]["supervisor"]
        assert "supervisor_model" not in data["intent"]["policy"]["supervisor"]


def test_new_model_contract_requires_v3(tmp_path):
    state = create_session_state("worker", worktree_path=str(tmp_path))
    state.intent.policy = PolicyIntent(supervisor=SupervisorConfig(resume_id="planner", supervisor_model="opus"))
    store = SessionStore(str(tmp_path), "worker")
    store.write(state)
    assert json.loads(store.manifest_path.read_text())["schema_version"] == 3


def test_stale_image_refuses_without_launching_or_mounting_user_state():
    with patch(
        "forge.sidecar.docker.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "old image")
    ) as probe:
        with pytest.raises(ValueError, match="Rebuild the image"):
            require_sidecar_contract("old-sidecar", schema_version=3, reviewer=True)
    args = probe.call_args.args[0]
    assert "--network" in args and "none" in args
    assert not any(arg in args for arg in ("-v", "--mount", "--env-file"))

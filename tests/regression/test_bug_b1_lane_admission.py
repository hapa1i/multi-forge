"""B1: lane set saved a model/auth mismatch and the next hook froze it."""

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.models import PolicyIntent, SupervisorConfig
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("auth_mode", ["inherit", "subscription-only"])
def test_lane_change_cannot_break_stored_reviewer_identity(tmp_path, monkeypatch, auth_mode):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".forge").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_SESSION", "worker")
    state = create_session_state("worker", worktree_path=str(tmp_path))
    state.forge_root = str(tmp_path)
    state.intent.policy = PolicyIntent(
        supervisor=SupervisorConfig(
            plan_override_path="/plan", supervisor_model="opus", auth_mode=auth_mode, direct=True
        )
    )
    publish_session(IndexStore(), state, str(tmp_path))
    store = SessionStore(str(tmp_path), "worker")
    before = store.manifest_path.read_bytes()
    result = CliRunner().invoke(main, ["session", "lane", "set", "--consumer", "supervisor", "--runtime", "codex"])
    assert result.exit_code == 1
    assert "Supervisor model differs" in result.output
    assert store.manifest_path.read_bytes() == before

"""Regression for D001: policy enable must preserve supervisor intent.

Root cause: the terminal command rebuilt ``PolicyIntent`` from its bundle-owned
fields, silently replacing ``supervisor`` and ``team_supervisor`` with their
``None`` defaults.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.policy.team.config import TeamSupervisorConfig
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.models import PolicyIntent, SupervisorConfig
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


def test_policy_enable_preserves_supervisor_intent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)

    supervisor = SupervisorConfig(resume_id="planner")
    team_supervisor = TeamSupervisorConfig(enabled=True, resume_id="team-planner")
    state = create_session_state("worker", worktree_path=str(project))
    state.forge_root = str(project)
    state.intent.policy = PolicyIntent(
        enabled=False,
        bundles=["coding_standards"],
        supervisor=supervisor,
        team_supervisor=team_supervisor,
    )
    store = SessionStore(str(project), "worker")
    publish_session(
        IndexStore(),
        state,
        project,
        forge_root=str(project),
        checkout_root=str(project),
        relative_path=".",
    )

    result = CliRunner().invoke(main, ["policy", "enable", "--bundle", "tdd", "--session", "worker"])

    assert result.exit_code == 0, result.output
    policy = store.read().intent.policy
    assert policy is not None
    assert policy.bundles == ["tdd"]
    assert policy.supervisor == supervisor
    assert policy.team_supervisor == team_supervisor

"""An executor's Responses listener does not supply the Claude reviewer's Messages route."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.models import StartedWithProxy
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


def test_claude_reviewer_selects_planner_route_despite_shared_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    (project / ".forge").mkdir(parents=True)
    (project / ".git").mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setattr(
        "forge.core.reactive.reviewer_runtime.preflight_supervisor_runtime", lambda *args, **kwargs: None
    )
    planner = create_session_state("planner", worktree_path=str(project))
    planner.confirmed.claude_session_id = "fcf2b264-178d-4c73-adf3-b0707496e0cd"
    planner.confirmed.confirmed_by = "hook:SessionStart:startup"
    # Older Claude planners recorded a template and URL without an instance ID.
    planner.confirmed.started_with_proxy = StartedWithProxy(
        template="openrouter-anthropic", base_url="http://localhost:8123"
    )
    executor = create_session_state(
        "executor",
        runtime="codex",
        worktree_path=str(project),
        proxy_template="openrouter-anthropic",
        proxy_base_url="http://localhost:8300",
        proxy_id="responses-instance",
    )
    for state in (planner, executor):
        state.forge_root = str(project)
        publish_session(IndexStore(), state, project, forge_root=project)
    result = CliRunner().invoke(main, ["policy", "supervisor", "set", "planner", "--session", "executor"])
    assert result.exit_code == 0, (result.output, result.exception)
    policy = SessionStore(str(project), executor.name).read().intent.policy
    assert policy and policy.supervisor
    assert policy.supervisor.proxy == planner.confirmed.started_with_proxy.template
    assert not policy.supervisor.direct

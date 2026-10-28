"""Characterize public configuration commands across child derivation paths."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import (
    IndexStore,
    SessionManager,
    SessionStore,
    compute_effective_intent,
    create_session_state,
)
from forge.session.models import PolicyIntent, SupervisorConfig
from tests.fixtures.session_state import publish_session


@pytest.mark.parametrize("operation", ["fork", "fresh", "relaunch"])
def test_supervisor_off_and_verification_setup_inheritance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    project = (tmp_path / "project").resolve()
    project.mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)
    state = create_session_state("parent", worktree_path=str(project))
    state.intent.policy = PolicyIntent(supervisor=SupervisorConfig(plan_override_path="/plan", supervisor_model="opus"))
    publish_session(IndexStore(), state, project)
    runner = CliRunner()
    suspended = runner.invoke(main, ["policy", "supervisor", "off", "--session", "parent"])
    assert suspended.exit_code == 0, suspended.output
    configured = runner.invoke(
        main, ["session", "set", "--session", "parent", "verification.type", "completion_promise"]
    )
    assert configured.exit_code == 0, configured.output
    parent_store = SessionStore(str(project), "parent")
    parent_before = parent_store.manifest_path.read_bytes()
    assert parent_store.read().intent.verification is None

    manager = SessionManager()
    if operation == "fork":
        _, child = manager.fork_session("parent", "child")
    elif operation == "fresh":
        child, _ = manager.resume_session("parent", child_name="child")
    else:
        _, child = manager.relaunch_session("parent", child_name="child")

    effective = compute_effective_intent(child)
    assert effective.policy is not None and effective.policy.supervisor is not None
    assert effective.policy.supervisor.suspended
    assert (effective.verification is not None) == (operation == "relaunch")
    reset = runner.invoke(main, ["session", "reset", "--session", "child", "--all"])
    assert reset.exit_code == 0, reset.output
    after = compute_effective_intent(SessionStore(str(project), "child").read())
    assert after.policy is not None and after.policy.supervisor is not None
    assert after.policy.supervisor.suspended
    assert after.verification is None
    assert parent_store.manifest_path.read_bytes() == parent_before

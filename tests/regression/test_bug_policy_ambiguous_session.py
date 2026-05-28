"""Regression: `forge policy` terminal session resolution must distinguish zero vs many.

Bug: `_resolve_session_name` returned None for BOTH "zero local sessions" and "multiple
local sessions, none selected", so `forge policy status`/`enable`/`disable` printed
"No session found in <path>" even when several sessions existed. From a plain terminal
(no FORGE_SESSION) in a project with >1 session, policy appeared broken.

Fix (src/forge/cli/policy.py, `_resolve_policy_session`): ambiguity now reports the candidate
session names and points to `--session`; the true zero-session case keeps "No session found".
`enable`/`disable` gained the `--session/-s` flag (previously only `status` had it).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.models import PolicyIntent

pytestmark = pytest.mark.regression


def _project_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # This regression targets the "plain terminal, no FORGE_SESSION" path. The autouse
    # isolate_forge_home fixture already clears it; re-clear locally so the precondition is
    # explicit and holds even if the suite runs from inside a Forge-managed session.
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)
    return project


def _seed_session(forge_root: str, name: str, *, policy: PolicyIntent | None = None) -> None:
    state = create_session_state(name, worktree_path=forge_root)
    state.forge_root = forge_root
    if policy:
        state.intent.policy = policy
    SessionStore(forge_root, name).write(state)
    IndexStore().add_session(
        name=name,
        worktree_path=forge_root,
        project_root=forge_root,
        forge_root=forge_root,
        checkout_root=forge_root,
        relative_path=".",
    )


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return _project_env(tmp_path, monkeypatch)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_status_ambiguous_is_not_no_session_found(runner: CliRunner, env: Path) -> None:
    """Multiple local sessions, no FORGE_SESSION: report ambiguity + candidates, not 'No session found'."""
    _seed_session(str(env), "planner")
    _seed_session(str(env), "executor")

    result = runner.invoke(main, ["policy", "status"])

    assert result.exit_code != 0
    assert "Multiple sessions" in result.output
    assert "planner" in result.output and "executor" in result.output
    assert "--session" in result.output
    # The exact bug: this message must NOT appear when sessions exist.
    assert "No session found" not in result.output


def test_status_zero_sessions_still_says_no_session_found(runner: CliRunner, env: Path) -> None:
    """The genuine empty case keeps the original message (distinct from ambiguity)."""
    result = runner.invoke(main, ["policy", "status"])

    assert result.exit_code != 0
    assert "No session found" in result.output


def test_enable_session_flag_targets_named_session(runner: CliRunner, env: Path) -> None:
    """`enable --session` mutates the named session's intent and leaves others untouched."""
    _seed_session(str(env), "planner")
    _seed_session(str(env), "executor")

    result = runner.invoke(main, ["policy", "enable", "--bundle", "tdd", "--session", "executor"])

    assert result.exit_code == 0, result.output
    executor = SessionStore(str(env), "executor").read()
    assert executor.intent.policy is not None
    assert executor.intent.policy.enabled is True
    assert "tdd" in executor.intent.policy.bundles
    planner = SessionStore(str(env), "planner").read()
    assert planner.intent.policy is None or planner.intent.policy.enabled is False


def test_disable_session_flag_targets_named_session(runner: CliRunner, env: Path) -> None:
    """`disable --session` flips the named session's policy off."""
    _seed_session(str(env), "planner")
    _seed_session(str(env), "executor", policy=PolicyIntent(enabled=True, bundles=["tdd"]))

    result = runner.invoke(main, ["policy", "disable", "--session", "executor"])

    assert result.exit_code == 0, result.output
    executor = SessionStore(str(env), "executor").read()
    assert executor.intent.policy is not None
    assert executor.intent.policy.enabled is False


def test_enable_without_flag_reports_ambiguity(runner: CliRunner, env: Path) -> None:
    """`enable` (no --session) with multiple sessions errors with the ambiguity message."""
    _seed_session(str(env), "planner")
    _seed_session(str(env), "executor")

    result = runner.invoke(main, ["policy", "enable", "--bundle", "tdd"])

    assert result.exit_code != 0
    assert "Multiple sessions" in result.output
    assert "No session found" not in result.output

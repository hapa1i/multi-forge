"""Tests for forge policy status command."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
from pytest import fixture

from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.models import PolicyIntent, SupervisorConfig


def _project_env(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)
    return project


def _seed_session(
    forge_root: str,
    name: str,
    *,
    project_root: str | None = None,
    policy: PolicyIntent | None = None,
    claude_session_id: str | None = None,
):
    state = create_session_state(name, worktree_path=forge_root)
    state.forge_root = forge_root
    if policy:
        state.intent.policy = policy
    if claude_session_id:
        state.confirmed.claude_session_id = claude_session_id
    SessionStore(forge_root, name).write(state)
    IndexStore().add_session(
        name=name,
        worktree_path=forge_root,
        project_root=project_root or forge_root,
        forge_root=forge_root,
        checkout_root=forge_root,
        relative_path=".",
    )
    return state


@fixture
def env(tmp_path, monkeypatch):
    return _project_env(tmp_path, monkeypatch)


@fixture
def runner():
    return CliRunner()


class TestStatusBasic:
    def test_help(self, runner: CliRunner):
        result = runner.invoke(main, ["policy", "status", "--help"])
        assert result.exit_code == 0
        assert "--session" in result.output

    def test_no_session_error(self, runner: CliRunner, env: Path):
        result = runner.invoke(main, ["policy", "status"])
        assert result.exit_code == 1
        assert "No session found" in result.output

    def test_no_policy(self, runner: CliRunner, env: Path):
        _seed_session(str(env), "test-session")
        result = runner.invoke(main, ["policy", "status"])
        assert result.exit_code == 0
        assert "No (not configured)" in result.output

    def test_with_bundles(self, runner: CliRunner, env: Path):
        policy = PolicyIntent(enabled=True, bundles=["tdd"])
        _seed_session(str(env), "test-session", policy=policy)
        result = runner.invoke(main, ["policy", "status"])
        assert result.exit_code == 0
        assert "tdd" in result.output


class TestStatusSessionFlag:
    def test_resolves_same_forge_root(self, runner: CliRunner, env: Path):
        policy = PolicyIntent(enabled=True, bundles=["tdd"])
        _seed_session(str(env), "planner")
        _seed_session(str(env), "executor", policy=policy)
        result = runner.invoke(main, ["policy", "status", "--session", "executor"])
        assert result.exit_code == 0
        assert "tdd" in result.output

    def test_resolves_cross_worktree(self, runner: CliRunner, env: Path):
        """Session in different forge_root but same project_root."""
        project_root = str(env)
        other_root = env / "other-worktree"
        other_root.mkdir()
        (other_root / ".forge").mkdir()

        _seed_session(project_root, "planner", project_root=project_root)
        policy = PolicyIntent(enabled=True, bundles=["coding_standards"])
        _seed_session(str(other_root), "executor", project_root=project_root, policy=policy)

        result = runner.invoke(main, ["policy", "status", "--session", "executor"])
        assert result.exit_code == 0
        assert "coding_standards" in result.output

    def test_not_found(self, runner: CliRunner, env: Path):
        _seed_session(str(env), "planner")
        result = runner.invoke(main, ["policy", "status", "--session", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_duplicate_names_prefers_current(self, runner: CliRunner, env: Path):
        """When same name exists in multiple forge_roots, prefer current."""
        project_root = str(env)
        other_root = env / "other-worktree"
        other_root.mkdir()
        (other_root / ".forge").mkdir()

        policy_a = PolicyIntent(enabled=True, bundles=["tdd"])
        policy_b = PolicyIntent(enabled=True, bundles=["coding_standards"])
        _seed_session(str(env), "shared", project_root=project_root, policy=policy_a)
        _seed_session(str(other_root), "shared", project_root=project_root, policy=policy_b)

        result = runner.invoke(main, ["policy", "status", "--session", "shared"])
        assert result.exit_code == 0
        assert "tdd" in result.output

    def test_no_cross_repo_leak(self, runner: CliRunner, env: Path):
        """Session in a different repo is not found."""
        other_project = env.parent / "other-repo"
        other_project.mkdir()
        (other_project / ".forge").mkdir()
        _seed_session(str(other_project), "foreign", project_root=str(other_project))

        result = runner.invoke(main, ["policy", "status", "--session", "foreign"])
        assert result.exit_code == 1

    def test_json_output(self, runner: CliRunner, env: Path):
        policy = PolicyIntent(enabled=True, bundles=["tdd"])
        _seed_session(str(env), "target", policy=policy)
        result = runner.invoke(main, ["policy", "status", "--session", "target", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["session_name"] == "target"
        assert data["policy"]["bundles"] == ["tdd"]


class TestSupervisedTip:
    def test_tip_shown(self, runner: CliRunner, env: Path, monkeypatch):
        project_root = str(env)
        _seed_session(project_root, "planner", project_root=project_root)
        policy = PolicyIntent(
            enabled=True,
            supervisor=SupervisorConfig(resume_id="planner", forge_root=project_root),
        )
        _seed_session(project_root, "executor", project_root=project_root, policy=policy)

        monkeypatch.setenv("FORGE_SESSION", "planner")
        result = runner.invoke(main, ["policy", "status"])
        assert result.exit_code == 0
        assert "This session supervises: executor" in result.output

    def test_tip_shown_even_when_supervised(self, runner: CliRunner, env: Path, monkeypatch):
        """A session in a chain (both supervised and supervising) shows the tip."""
        project_root = str(env)
        _seed_session(project_root, "planner", project_root=project_root, claude_session_id="uuid-plan")
        middle_policy = PolicyIntent(
            enabled=True,
            supervisor=SupervisorConfig(resume_id="planner", forge_root=project_root),
        )
        _seed_session(project_root, "middle", project_root=project_root, policy=middle_policy)
        leaf_policy = PolicyIntent(
            enabled=True,
            supervisor=SupervisorConfig(resume_id="middle", forge_root=project_root),
        )
        _seed_session(project_root, "leaf", project_root=project_root, policy=leaf_policy)

        monkeypatch.setenv("FORGE_SESSION", "middle")
        result = runner.invoke(main, ["policy", "status"])
        assert result.exit_code == 0
        assert "This session supervises: leaf" in result.output

    def test_tip_uuid_match(self, runner: CliRunner, env: Path, monkeypatch):
        """Supervisor wired by UUID is matched."""
        project_root = str(env)
        _seed_session(project_root, "planner", project_root=project_root, claude_session_id="abc-123")
        policy = PolicyIntent(
            enabled=True,
            supervisor=SupervisorConfig(resume_id="abc-123", forge_root=project_root),
        )
        _seed_session(project_root, "executor", project_root=project_root, policy=policy)

        monkeypatch.setenv("FORGE_SESSION", "planner")
        result = runner.invoke(main, ["policy", "status"])
        assert result.exit_code == 0
        assert "This session supervises: executor" in result.output

    def test_tip_scoped_by_forge_root(self, runner: CliRunner, env: Path, monkeypatch):
        """No false match when supervisor.forge_root doesn't align."""
        project_root = str(env)
        other_root = env / "other"
        other_root.mkdir()
        (other_root / ".forge").mkdir()

        _seed_session(project_root, "planner", project_root=project_root)
        policy = PolicyIntent(
            enabled=True,
            supervisor=SupervisorConfig(resume_id="planner", forge_root=str(other_root)),
        )
        _seed_session(project_root, "executor", project_root=project_root, policy=policy)

        monkeypatch.setenv("FORGE_SESSION", "planner")
        result = runner.invoke(main, ["policy", "status"])
        assert result.exit_code == 0
        assert "This session supervises" not in result.output

    def test_tip_multiple(self, runner: CliRunner, env: Path, monkeypatch):
        project_root = str(env)
        _seed_session(project_root, "planner", project_root=project_root)
        for name in ["exec-1", "exec-2"]:
            policy = PolicyIntent(
                enabled=True,
                supervisor=SupervisorConfig(resume_id="planner", forge_root=project_root),
            )
            _seed_session(project_root, name, project_root=project_root, policy=policy)

        monkeypatch.setenv("FORGE_SESSION", "planner")
        result = runner.invoke(main, ["policy", "status"])
        assert result.exit_code == 0
        assert "exec-1" in result.output
        assert "exec-2" in result.output

    def test_json_has_supervised_sessions(self, runner: CliRunner, env: Path, monkeypatch):
        project_root = str(env)
        _seed_session(project_root, "planner", project_root=project_root)
        policy = PolicyIntent(
            enabled=True,
            supervisor=SupervisorConfig(resume_id="planner", forge_root=project_root),
        )
        _seed_session(project_root, "executor", project_root=project_root, policy=policy)

        monkeypatch.setenv("FORGE_SESSION", "planner")
        result = runner.invoke(main, ["policy", "status", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "supervised_sessions" in data
        assert data["supervised_sessions"] == ["executor"]

    def test_skips_broken_manifests(self, runner: CliRunner, env: Path, monkeypatch):
        """Corrupted sibling manifest doesn't crash the tip scan."""
        project_root = str(env)
        _seed_session(project_root, "planner", project_root=project_root)

        broken_dir = Path(project_root) / ".forge" / "sessions" / "broken"
        broken_dir.mkdir(parents=True)
        (broken_dir / "forge.session.json").write_text("{invalid json")
        IndexStore().add_session(
            name="broken",
            worktree_path=project_root,
            project_root=project_root,
            forge_root=project_root,
            checkout_root=project_root,
            relative_path=".",
        )

        monkeypatch.setenv("FORGE_SESSION", "planner")
        result = runner.invoke(main, ["policy", "status"])
        assert result.exit_code == 0

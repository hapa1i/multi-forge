"""Tests for hook-missing warnings in CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def temp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Project dir with .git (no hooks installed)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)
    return project


def _install_hook(project: Path, hook_type: str, command: str) -> None:
    """Write a settings.local.json with a single forge hook."""
    settings_dir = project / ".claude"
    settings_dir.mkdir(exist_ok=True)
    data = {"hooks": {hook_type: [{"hooks": [{"type": "command", "command": command}]}]}}
    (settings_dir / "settings.local.json").write_text(json.dumps(data))


class TestSessionStartWarning:
    def test_start_warns_when_no_hooks(self, runner: CliRunner, temp_env: Path) -> None:
        with patch("forge.core.ops.claude_session.invoke_claude", return_value=0):
            result = runner.invoke(main, ["session", "start", "warn-test"])

        assert result.exit_code == 0
        assert "Forge hooks are not installed" in result.output
        assert "forge extension enable --scope user" in result.output

    def test_start_no_warning_when_hooks_present(self, runner: CliRunner, temp_env: Path) -> None:
        _install_hook(temp_env, "SessionStart", "/tmp/forge-home/bin/forge-hook session-start")

        with patch("forge.core.ops.claude_session.invoke_claude", return_value=0):
            result = runner.invoke(main, ["session", "start", "clean-test"])

        assert result.exit_code == 0
        assert "hooks are not installed" not in result.output

    def test_start_no_warning_on_no_launch(self, runner: CliRunner, temp_env: Path) -> None:
        result = runner.invoke(main, ["session", "start", "nol-test", "--no-launch"])

        assert result.exit_code == 0
        assert "hooks are not installed" not in result.output


class TestHookDetectionFromSubdirectory:
    def test_detects_hooks_from_subdirectory(self, tmp_path: Path) -> None:
        """Hooks installed at project root should be found from a subdirectory."""
        from forge.install.hooks import has_forge_hooks

        project = tmp_path / "project"
        project.mkdir()
        _install_hook(project, "SessionStart", "forge hook session-start")

        subdir = project / "src" / "module"
        subdir.mkdir(parents=True)

        assert has_forge_hooks(subdir) is True

    def test_no_false_warn_from_subdirectory(self, tmp_path: Path) -> None:
        """Should NOT warn about missing hooks when called from a subdirectory."""
        from forge.install.hooks import has_forge_hooks

        project = tmp_path / "project"
        project.mkdir()
        _install_hook(project, "SessionStart", "forge hook session-start")

        subdir = project / "deep" / "nested" / "dir"
        subdir.mkdir(parents=True)

        # Without the walk-up fix, this would return False (false warn)
        assert has_forge_hooks(subdir) is True

    def test_returns_false_when_truly_missing(self, tmp_path: Path) -> None:
        """Should correctly return False when no hooks are installed anywhere."""
        from forge.install.hooks import has_forge_hooks

        project = tmp_path / "project"
        project.mkdir()
        (project / ".claude").mkdir()
        # No hooks installed

        assert has_forge_hooks(project) is False


class TestHookDetectionFromForgeRoot:
    """Hooks check must use forge_root, not worktree/checkout root."""

    def test_detects_hooks_at_nested_forge_root(self, tmp_path: Path) -> None:
        """Hooks at nested forge_root found when checking from forge_root."""
        from forge.install.hooks import has_forge_hooks

        # Worktree root has no .claude/
        worktree = tmp_path / "repo-executor"
        worktree.mkdir()

        # Forge project is nested inside worktree
        forge_root = worktree / "packages" / "app"
        forge_root.mkdir(parents=True)
        _install_hook(forge_root, "SessionStart", "forge hook session-start")

        # Checking from forge_root works
        assert has_forge_hooks(forge_root) is True
        # Checking from worktree root fails (no .claude/ there)
        assert has_forge_hooks(worktree) is False

    def test_detects_hooks_with_trailing_dot_path(self, tmp_path: Path) -> None:
        """forge_root computed as Path(wt) / '.' still finds hooks."""
        from forge.install.hooks import has_forge_hooks

        worktree = tmp_path / "repo-executor"
        worktree.mkdir()
        _install_hook(worktree, "SessionStart", "forge hook session-start")

        # Path with trailing dot (as fork_session computes for relative_path=".")
        dot_path = worktree / "."
        assert has_forge_hooks(dot_path) is True


class TestGuardEnableWarning:
    def test_guard_enable_warns_when_no_hook(self, runner: CliRunner, temp_env: Path) -> None:
        runner.invoke(main, ["session", "start", "policy-warn", "--no-launch"])

        result = runner.invoke(main, ["policy", "enable", "--bundle", "tdd"])

        assert result.exit_code == 0
        assert "Policy enabled" in result.output
        assert "PreToolUse hook is not installed" in result.output
        assert "forge extension enable --scope user" in result.output

    def test_guard_enable_no_warning_when_hooks_present(self, runner: CliRunner, temp_env: Path) -> None:
        _install_hook(temp_env, "PreToolUse", "/tmp/forge-home/bin/forge-hook policy-check")
        runner.invoke(main, ["session", "start", "policy-clean", "--no-launch"])

        result = runner.invoke(main, ["policy", "enable", "--bundle", "tdd"])

        assert result.exit_code == 0
        assert "hook is not installed" not in result.output


class TestVerificationSetWarning:
    def test_set_verification_warns_when_no_hook(self, runner: CliRunner, temp_env: Path) -> None:
        runner.invoke(main, ["session", "start", "ver-warn", "--no-launch"])

        result = runner.invoke(
            main,
            [
                "session",
                "set",
                "--session",
                "ver-warn",
                "verification.type",
                "completion_promise",
            ],
        )

        assert result.exit_code == 0
        assert "Stop hook is not installed" in result.output
        assert "forge extension enable --scope user" in result.output

    def test_set_non_verification_key_no_warning(self, runner: CliRunner, temp_env: Path) -> None:
        runner.invoke(main, ["session", "start", "ver-clean", "--no-launch"])

        result = runner.invoke(main, ["session", "set", "--session", "ver-clean", "agent", "custom"])

        assert result.exit_code == 0
        assert "hook is not installed" not in result.output

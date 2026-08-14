"""Tests for extension enable: scope/root resolution, anchor validation, Rule 4."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import pytest
from click.testing import CliRunner

from forge.cli.extensions import (
    _create_claude_dir,
    _detect_git_project_root,
    _resolve_project_root,
    _validate_anchor,
)
from forge.cli.extensions import console as extensions_console
from forge.cli.extensions import extensions
from forge.core.paths import get_forge_home
from forge.install.exceptions import NoClaudeDirectoryError
from forge.install.models import InstallModule, InstallScope
from forge.install.ownership import attributed
from forge.install.project_registry import ProjectRegistryStore


def _normalize_forge_home(command: str) -> str:
    return command.replace(str(get_forge_home()), "$FORGE_HOME")


def _make_executable_forge(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _make_venv_forge(checkout: Path) -> Path:
    (checkout / ".venv" / "pyvenv.cfg").parent.mkdir(parents=True, exist_ok=True)
    (checkout / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    return _make_executable_forge(checkout / ".venv" / "bin" / "forge")


def test_scope_help_is_shared_across_extension_commands() -> None:
    expected = "Installation scope: local (gitignored), project (committed), user (global)"
    runner = CliRunner()

    for command in ("enable", "sync", "disable", "status"):
        result = runner.invoke(extensions, [command, "--help"])
        output = " ".join(result.output.split())
        assert result.exit_code == 0, result.output
        assert expected in output


@pytest.mark.parametrize("command", ["sync", "disable", "status"])
def test_lifecycle_help_describes_sidecar_and_tracking_row_discovery(command: str) -> None:
    result = CliRunner().invoke(extensions, [command, "--help"])

    output = " ".join(result.output.split())
    assert result.exit_code == 0, result.output
    assert ".claude/ ownership sidecars" in output
    assert "exact scope/path tracking rows" in output
    assert "~/.forge/installed.json" in output


@pytest.mark.parametrize("scope", ["local", "project"])
def test_project_enable_preserves_recorded_global_launcher_when_run_from_venv(
    scope: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from forge.install.hook_dispatcher import (
        install_hook_dispatcher,
        read_runtime_metadata,
    )

    stable_forge = _make_executable_forge(tmp_path / "global-a" / "bin" / "forge")
    venv_forge = _make_venv_forge(tmp_path / "checkout-b")
    install_hook_dispatcher(forge_binary_path=stable_forge)
    monkeypatch.setattr(
        "forge.install.hook_dispatcher.find_current_forge_binary",
        lambda **_kwargs: venv_forge,
    )
    monkeypatch.setattr(
        "forge.install.version.check_minimum_version",
        lambda: type("Check", (), {"ok": True})(),
    )
    monkeypatch.setattr("forge.install.installer._codex_available", lambda: False)
    project = tmp_path / f"{scope}-repo"
    project.mkdir()

    result = CliRunner().invoke(
        extensions,
        ["enable", "--scope", scope, "--root", str(project), "--profile", "minimal"],
    )

    assert result.exit_code == 0, result.output
    metadata = read_runtime_metadata()
    assert metadata is not None
    assert metadata["forge_binary_path"] == str(stable_forge)


def test_user_sync_preserves_recorded_global_launcher_when_run_from_venv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from forge.install.hook_dispatcher import read_runtime_metadata

    stable_forge = _make_executable_forge(tmp_path / "global-a" / "bin" / "forge")
    venv_forge = _make_venv_forge(tmp_path / "checkout-b")
    monkeypatch.setattr(
        "forge.install.version.check_minimum_version",
        lambda: type("Check", (), {"ok": True})(),
    )
    monkeypatch.setattr("forge.install.installer._codex_available", lambda: False)
    monkeypatch.setattr(
        "forge.install.hook_dispatcher.find_current_forge_binary",
        lambda **_kwargs: stable_forge,
    )
    runner = CliRunner()
    enabled = runner.invoke(
        extensions,
        ["enable", "--scope", "user", "--profile", "minimal"],
    )
    assert enabled.exit_code == 0, enabled.output
    initial = read_runtime_metadata()
    assert initial is not None
    assert initial["forge_binary_path"] == str(stable_forge)

    monkeypatch.setattr(
        "forge.install.hook_dispatcher.find_current_forge_binary",
        lambda **_kwargs: venv_forge,
    )
    synced = runner.invoke(extensions, ["sync", "--scope", "user"])

    assert synced.exit_code == 0, synced.output
    metadata = read_runtime_metadata()
    assert metadata is not None
    assert metadata["forge_binary_path"] == str(stable_forge)


class TestDetectGitProjectRoot:
    """Tests for _detect_git_project_root (Rule 4 detector)."""

    def test_detects_git_repo(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        subdir = tmp_path / "src"
        subdir.mkdir()

        result = _detect_git_project_root(start=subdir)
        assert result == tmp_path.resolve()

    def test_returns_none_outside_git(self, tmp_path: Path) -> None:
        result = _detect_git_project_root(start=tmp_path)
        assert result is None

    def test_returns_none_at_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Does not return home directory even if it has .git."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        (fake_home / ".git").mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        result = _detect_git_project_root(start=fake_home)
        assert result is None


class TestCreateClaudeDir:
    """Tests for _create_claude_dir."""

    def test_creates_claude_dir(self, tmp_path: Path) -> None:
        _create_claude_dir(tmp_path)
        assert (tmp_path / ".claude").is_dir()

    def test_idempotent(self, tmp_path: Path) -> None:
        (tmp_path / ".claude").mkdir()
        _create_claude_dir(tmp_path)
        assert (tmp_path / ".claude").is_dir()


class TestResolveProjectRootAutoCreate:
    """Tests for _resolve_project_root with Rule 4 auto-create."""

    def test_user_scope_returns_none(self) -> None:
        assert _resolve_project_root(InstallScope.USER) is None

    def test_project_scope_detects_git_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--project in a git repo without .claude/ returns git root (no auto_create)."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        repo = tmp_path / "my-repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        monkeypatch.chdir(repo)

        result = _resolve_project_root(InstallScope.PROJECT, auto_create=False)

        assert result == repo.resolve()
        # .claude/ NOT created when auto_create=False
        assert not (repo / ".claude").is_dir()

    def test_project_scope_auto_creates_claude(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--project with auto_create=True creates .claude/ at git root."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        repo = tmp_path / "my-repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        monkeypatch.chdir(repo)

        result = _resolve_project_root(InstallScope.PROJECT, auto_create=True)

        assert result == repo.resolve()
        assert (repo / ".claude").is_dir()

    def test_local_scope_auto_creates_claude(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--local with auto_create=True creates .claude/ at git root."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        repo = tmp_path / "my-repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        monkeypatch.chdir(repo)

        result = _resolve_project_root(InstallScope.LOCAL, auto_create=True)

        assert result == repo.resolve()
        assert (repo / ".claude").is_dir()

    def test_project_scope_raises_outside_git(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--project outside a git repo raises NoClaudeDirectoryError."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        no_git = tmp_path / "random-dir"
        no_git.mkdir()
        monkeypatch.chdir(no_git)

        with pytest.raises(NoClaudeDirectoryError):
            _resolve_project_root(InstallScope.PROJECT)

    def test_existing_claude_not_recreated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When .claude/ already exists, returns it without auto-create."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        repo = tmp_path / "my-repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".claude").mkdir()
        monkeypatch.chdir(repo)

        result = _resolve_project_root(InstallScope.LOCAL)

        assert result == repo.resolve()


class TestEnableFailureCleanup:
    """Verify .forge/ is not created when enable fails."""

    def test_enable_failure_does_not_leave_forge_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A failed enable should not leave an orphaned .forge/ directory."""
        from unittest.mock import MagicMock, patch

        from click.testing import CliRunner

        from forge.cli.extensions import enable_cmd

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".claude").mkdir()

        monkeypatch.chdir(repo)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        # Mock installer to return a plan with conflicts
        mock_plan = MagicMock()
        mock_plan.has_conflicts = True
        mock_plan.files = []
        mock_plan.codex = None
        mock_plan.settings_entries = []

        with (
            patch("forge.cli.extensions.Installer") as MockInstaller,
            patch("forge.install.version.check_minimum_version") as mock_ver,
        ):
            mock_instance = MockInstaller.return_value
            mock_instance.plan.return_value = mock_plan
            mock_instance.init.return_value = mock_plan
            mock_ver.return_value = MagicMock(ok=True)
            runner = CliRunner()
            result = runner.invoke(enable_cmd, ["--scope", "local"])

        assert result.exit_code != 0
        assert not (repo / ".forge").is_dir()


@pytest.mark.parametrize(
    "runtime_args",
    [(), ("--runtime", "codex")],
    ids=["automatic", "explicit-codex"],
)
def test_missing_claude_names_full_codex_only_skill_recovery(
    runtime_args: tuple[str, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one-flag Codex selection is the complete no-Claude recovery."""
    from unittest.mock import patch

    from forge.core.runtime import get_runtime

    home = tmp_path / "home"
    outside = tmp_path / "outside"
    home.mkdir()
    outside.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge-home"))
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / "claude-home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.chdir(outside)
    missing = type(
        "VersionCheck",
        (),
        {
            "ok": False,
            "version": None,
            "reason": "Claude Code not found. Install it first.",
        },
    )()
    recovery = "forge extension enable --scope user --runtime codex"

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=[get_runtime("codex")],
        ),
        patch(
            "forge.install.version.check_minimum_version",
            return_value=missing,
        ) as version_check,
    ):
        blocked = CliRunner().invoke(
            extensions,
            ["enable", "--scope", "user", *runtime_args],
        )
        installed = CliRunner().invoke(extensions, recovery.split()[2:])

    if runtime_args:
        assert blocked.exit_code == 0, blocked.output
        assert version_check.call_count == 0
    else:
        assert blocked.exit_code == 1, blocked.output
        assert recovery in " ".join(blocked.output.split())
        assert version_check.call_count == 1
    assert installed.exit_code == 0, installed.output
    assert not (tmp_path / "claude-home").exists()
    assert (home / ".agents" / "skills" / "smoke-test" / "SKILL.md").is_file()


class TestRuntimeScopedModuleSelection:
    """CLI acceptance rows for the shared runtime/module filter."""

    @staticmethod
    def _select_codex(monkeypatch: pytest.MonkeyPatch) -> None:
        from forge.core.runtime import get_runtime

        monkeypatch.setattr(
            "forge.install.installer.installed_runtimes",
            lambda: [get_runtime("codex")],
        )
        monkeypatch.setattr("forge.install.installer._codex_available", lambda: True)

    def test_local_codex_is_a_conflict_not_a_silent_noop(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        self._select_codex(monkeypatch)

        result = CliRunner().invoke(
            extensions,
            [
                "enable",
                "--scope",
                "local",
                "--root",
                str(project),
                "--runtime",
                "codex",
                "--force",
                "--dry-run",
            ],
        )

        assert result.exit_code == 1, result.output
        output = " ".join(result.output.split())
        assert "Conflicts detected" in output
        assert "scope_unsupported" in output

    def test_bare_codex_in_repo_conflicts_and_names_user_scope_recovery(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)
        self._select_codex(monkeypatch)

        result = CliRunner().invoke(
            extensions,
            ["enable", "--runtime", "codex", "--dry-run"],
        )

        assert result.exit_code == 1, result.output
        output = " ".join(result.output.split())
        assert "Auto-detected scope: local" in output
        assert "scope_unsupported" in output
        assert "forge extension enable --scope user" in output

    def test_minimal_codex_conflicts_when_runtime_filter_empties_profile(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._select_codex(monkeypatch)

        result = CliRunner().invoke(
            extensions,
            [
                "enable",
                "--scope",
                "user",
                "--profile",
                "minimal",
                "--runtime",
                "codex",
                "--force",
                "--dry-run",
            ],
        )

        assert result.exit_code == 1, result.output
        output = " ".join(result.output.split())
        assert "commands" in output
        assert "no modules remain after profile, scope, and runtime filtering" in output
        assert "--force does not override" in output
        assert "Use --force to override" not in output

    def test_explicit_wrong_owner_module_conflicts(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._select_codex(monkeypatch)

        result = CliRunner().invoke(
            extensions,
            [
                "enable",
                "--scope",
                "user",
                "--runtime",
                "codex",
                "--with",
                "commands",
                "--dry-run",
            ],
        )

        assert result.exit_code == 1, result.output
        output = " ".join(result.output.split())
        assert "Module: commands" in output
        assert "not owned by selected runtime(s): codex" in output

    def test_minimal_plus_skills_allows_codex(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        self._select_codex(monkeypatch)

        result = CliRunner().invoke(
            extensions,
            [
                "enable",
                "--scope",
                "user",
                "--profile",
                "minimal",
                "--with",
                "skills",
                "--runtime",
                "codex",
                "--dry-run",
            ],
        )

        assert result.exit_code == 0, result.output
        output = " ".join(result.output.split())
        assert "Skill packages:" in output
        assert "codex" in output
        assert "Conflicts detected" not in output

    def test_force_cannot_cross_module_conflict_preflight(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from unittest.mock import MagicMock, patch

        from forge.install.models import (
            FilePlan,
            InstallMode,
            InstallPlan,
            ModulePlan,
        )

        plan = InstallPlan(
            scope="user",
            mode="copy",
            profile="standard",
            modules=["hooks", "skills"],
            module_outcomes=[ModulePlan(module="commands", action="conflict", reason="runtime_excluded")],
            files=[
                FilePlan(
                    action="conflict",
                    target_path="/managed/conflict.md",
                    effective_mode=InstallMode.COPY,
                    reason="file exists and is not Forge-managed",
                    module="skills",
                    runtime="codex",
                )
            ],
            has_conflicts=True,
            conflicts=[
                "Module: commands - module is not owned by selected runtime(s): codex",
                "File: /managed/conflict.md - file exists and is not Forge-managed",
            ],
        )
        self._select_codex(monkeypatch)

        with patch("forge.cli.extensions.Installer") as installer_type:
            installer = installer_type.return_value
            installer.plan.return_value = plan
            installer.init.return_value = MagicMock()
            result = CliRunner().invoke(
                extensions,
                [
                    "enable",
                    "--scope",
                    "user",
                    "--runtime",
                    "codex",
                    "--with",
                    "commands",
                    "--force",
                ],
            )

        assert result.exit_code == 1, result.output
        installer.init.assert_not_called()
        output = " ".join(result.output.split())
        assert "Use --force only for file or settings conflicts" in output


class TestEnableProjectRegistry:
    """Tests for trusted-project enrollment during extension enable."""

    def _successful_plan(self) -> Any:
        from unittest.mock import MagicMock

        plan = MagicMock()
        plan.has_conflicts = False
        plan.conflicts = []
        plan.files = []
        plan.settings = []
        plan.codex = None
        plan.modules = []
        plan.profile = "minimal"
        return plan

    def test_local_enable_enrolls_project_root(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock, patch

        from forge.cli.extensions import enable_cmd

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".claude").mkdir()

        with (
            patch("forge.cli.extensions.Installer") as MockInstaller,
            patch("forge.install.version.check_minimum_version") as mock_ver,
        ):
            plan = self._successful_plan()
            MockInstaller.return_value.plan.return_value = plan
            MockInstaller.return_value.init.return_value = plan
            mock_ver.return_value = MagicMock(ok=True)
            result = CliRunner().invoke(enable_cmd, ["--scope", "local", "--root", str(repo)])

        assert result.exit_code == 0, result.output
        assert (repo / ".forge").is_dir()
        assert ProjectRegistryStore().contains_root(repo)

    def test_user_enable_does_not_enroll_project_root(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock, patch

        from forge.cli.extensions import enable_cmd

        with (
            patch("forge.cli.extensions.Installer") as MockInstaller,
            patch("forge.install.version.check_minimum_version") as mock_ver,
        ):
            plan = self._successful_plan()
            MockInstaller.return_value.plan.return_value = plan
            MockInstaller.return_value.init.return_value = plan
            mock_ver.return_value = MagicMock(ok=True)
            result = CliRunner().invoke(enable_cmd, ["--scope", "user"])

        assert result.exit_code == 0, result.output
        assert not ProjectRegistryStore().path.exists()

    def test_incompatible_project_pin_blocks_enable_before_install(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock, patch

        from forge.cli.extensions import enable_cmd

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".claude").mkdir()
        (repo / ".forge").mkdir()
        (repo / ".forge" / "project.toml").write_text(
            'schema_version = 1\nrequired_forge = ">=9999"\n',
            encoding="utf-8",
        )

        with (
            patch("forge.cli.extensions.Installer") as MockInstaller,
            patch("forge.install.version.check_minimum_version") as mock_ver,
        ):
            mock_ver.return_value = MagicMock(ok=True)
            result = CliRunner().invoke(enable_cmd, ["--scope", "local", "--root", str(repo)])

        assert result.exit_code == 1
        assert "requires Forge >=9999" in result.output
        assert "satisfying required_forge" in result.output
        assert "global Forge" not in result.output
        MockInstaller.assert_not_called()


class TestEmptyModuleWarning:
    """Tests for the 0-file sanity warning (catches broken installs)."""

    def _make_plan(self, modules: list[str], file_paths: list[str]) -> Any:
        from unittest.mock import MagicMock

        plan = MagicMock()
        plan.modules = modules
        plan.files = [MagicMock(target_path=p, action="install") for p in file_paths]
        plan.settings = []
        return plan

    def test_warns_when_file_module_has_no_files_anywhere(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        from forge.cli.extensions import _warn_if_modules_have_no_files
        from forge.install.tracking import TrackingStore

        plan = self._make_plan(modules=["skills", "hooks"], file_paths=[])
        tracking = MagicMock(spec=TrackingStore)
        tracking.get_installation.return_value = None  # no prior install

        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("forge.cli.extensions.console", Console(file=buf, width=200))
            _warn_if_modules_have_no_files(plan, InstallScope.USER, None, tracking)

        output = buf.getvalue()
        assert "Warning" in output
        assert "skills" in output

    def test_no_warn_when_files_in_plan(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        from forge.cli.extensions import _warn_if_modules_have_no_files
        from forge.install.tracking import TrackingStore

        plan = self._make_plan(
            modules=["skills"],
            file_paths=["/some/path/.claude/skills/foo/SKILL.md"],
        )
        tracking = MagicMock(spec=TrackingStore)
        tracking.get_installation.return_value = None

        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("forge.cli.extensions.console", Console(file=buf, width=200))
            _warn_if_modules_have_no_files(plan, InstallScope.USER, None, tracking)

        assert "Warning" not in buf.getvalue()

    def test_no_warn_when_files_in_existing_install(self, tmp_path: Path) -> None:
        """Up-to-date install: 0 plan files but tracking has files → no warning."""
        from unittest.mock import MagicMock

        from forge.cli.extensions import _warn_if_modules_have_no_files
        from forge.install.tracking import TrackingStore

        plan = self._make_plan(modules=["skills"], file_paths=[])
        tracking = MagicMock(spec=TrackingStore)
        existing = MagicMock()
        existing.files = [MagicMock(target_path="/some/path/.claude/skills/foo/SKILL.md")]
        tracking.get_installation.return_value = existing

        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("forge.cli.extensions.console", Console(file=buf, width=200))
            _warn_if_modules_have_no_files(plan, InstallScope.USER, None, tracking)

        assert "Warning" not in buf.getvalue()

    def test_no_warn_for_intentionally_empty_modules(self, tmp_path: Path) -> None:
        """Allowlisted empty modules (agents, commands) should not warn."""
        from unittest.mock import MagicMock

        from forge.cli.extensions import _warn_if_modules_have_no_files
        from forge.install.tracking import TrackingStore

        plan = self._make_plan(modules=["agents", "commands", "skills"], file_paths=[])
        tracking = MagicMock(spec=TrackingStore)
        tracking.get_installation.return_value = None

        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("forge.cli.extensions.console", Console(file=buf, width=200))
            _warn_if_modules_have_no_files(plan, InstallScope.USER, None, tracking)

        output = buf.getvalue()
        # Should warn about skills (not allowlisted, 0 files), not agents/commands
        assert "Warning" in output
        assert "skills" in output
        assert "agents" not in output
        assert "commands" not in output

    def test_no_warn_for_settings_only_modules(self, tmp_path: Path) -> None:
        """Settings-only modules (hooks, permissions) should never trigger the warning."""
        from unittest.mock import MagicMock

        from forge.cli.extensions import _warn_if_modules_have_no_files
        from forge.install.tracking import TrackingStore

        plan = self._make_plan(modules=["hooks", "permissions", "status-line"], file_paths=[])
        tracking = MagicMock(spec=TrackingStore)
        tracking.get_installation.return_value = None

        from io import StringIO

        from rich.console import Console

        buf = StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("forge.cli.extensions.console", Console(file=buf, width=200))
            _warn_if_modules_have_no_files(plan, InstallScope.USER, None, tracking)

        assert "Warning" not in buf.getvalue()


class TestValidateAnchor:
    """Tests for _validate_anchor (inside-.claude guard)."""

    def test_rejects_path_inside_claude_dir(self, tmp_path: Path) -> None:
        claude_dir = tmp_path / "repo" / ".claude"
        claude_dir.mkdir(parents=True)
        with pytest.raises(click.UsageError, match="inside a .claude directory"):
            _validate_anchor(claude_dir)

    def test_rejects_nested_claude_path(self, tmp_path: Path) -> None:
        nested = tmp_path / "repo" / ".claude" / "sub" / "deep"
        nested.mkdir(parents=True)
        with pytest.raises(click.UsageError, match="inside a .claude directory"):
            _validate_anchor(nested)

    def test_accepts_normal_project_root(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _validate_anchor(repo)

    def test_accepts_path_containing_claude_in_name(self, tmp_path: Path) -> None:
        """A directory named 'multi-forge' should not be rejected."""
        repo = tmp_path / "multi-forge"
        repo.mkdir()
        _validate_anchor(repo)


class TestResolveProjectRootAnchor:
    """Tests for _resolve_project_root with explicit anchor."""

    def test_anchor_bypasses_walk_up(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Anchor should return that path directly, not walk up."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        target = tmp_path / "target"
        target.mkdir()
        (target / ".claude").mkdir()

        other = tmp_path / "other"
        other.mkdir()
        monkeypatch.chdir(other)

        result = _resolve_project_root(InstallScope.LOCAL, anchor=target)
        assert result == target.resolve()

    def test_anchor_auto_creates_claude(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        target.mkdir()

        result = _resolve_project_root(InstallScope.LOCAL, anchor=target, auto_create=True)
        assert result == target.resolve()
        assert (target / ".claude").is_dir()

    def test_anchor_without_auto_create(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        target.mkdir()

        result = _resolve_project_root(InstallScope.LOCAL, anchor=target, auto_create=False)
        assert result == target.resolve()
        assert not (target / ".claude").is_dir()

    def test_anchor_ignored_for_user_scope(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        target.mkdir()
        assert _resolve_project_root(InstallScope.USER, anchor=target) is None

    def test_anchor_normalizes_path(self, tmp_path: Path) -> None:
        (tmp_path / "repo" / "src").mkdir(parents=True)
        # Pass a non-canonical path with ..
        target = tmp_path / "repo" / "src" / ".." / "src"

        result = _resolve_project_root(InstallScope.LOCAL, anchor=target)
        assert result == (tmp_path / "repo" / "src").resolve()


class TestEnableWithPath:
    """Tests for enable_cmd with --scope and --root options."""

    def test_path_with_scope_local(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock, patch

        from click.testing import CliRunner

        from forge.cli.extensions import enable_cmd

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".claude").mkdir()

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        mock_plan = MagicMock()
        mock_plan.has_conflicts = False
        mock_plan.files = []
        mock_plan.codex = None
        mock_plan.settings = []
        mock_plan.settings_entries = []
        mock_plan.modules = []
        mock_plan.profile = "standard"

        with (
            patch("forge.cli.extensions.Installer") as MockInstaller,
            patch("forge.install.version.check_minimum_version") as mock_ver,
        ):
            mock_instance = MockInstaller.return_value
            mock_instance.plan.return_value = mock_plan
            mock_instance.init.return_value = mock_plan
            mock_ver.return_value = MagicMock(ok=True)

            runner = CliRunner()
            result = runner.invoke(enable_cmd, ["--scope", "local", "--root", str(repo)])

        assert result.exit_code == 0
        MockInstaller.assert_called_once()
        call_kwargs = MockInstaller.call_args
        assert call_kwargs.kwargs["scope"] == InstallScope.LOCAL
        assert call_kwargs.kwargs["project_root"] == repo.resolve()

    def test_path_defaults_to_local_scope(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock, patch

        from click.testing import CliRunner

        from forge.cli.extensions import enable_cmd

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".claude").mkdir()

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        mock_plan = MagicMock()
        mock_plan.has_conflicts = False
        mock_plan.files = []
        mock_plan.codex = None
        mock_plan.settings = []
        mock_plan.settings_entries = []
        mock_plan.modules = []
        mock_plan.profile = "standard"

        with (
            patch("forge.cli.extensions.Installer") as MockInstaller,
            patch("forge.install.version.check_minimum_version") as mock_ver,
        ):
            mock_instance = MockInstaller.return_value
            mock_instance.plan.return_value = mock_plan
            mock_instance.init.return_value = mock_plan
            mock_ver.return_value = MagicMock(ok=True)

            runner = CliRunner()
            result = runner.invoke(enable_cmd, ["--root", str(repo)])

        assert result.exit_code == 0
        call_kwargs = MockInstaller.call_args
        assert call_kwargs.kwargs["scope"] == InstallScope.LOCAL

    def test_auto_local_enable_prints_user_scope_runtime_hook_next_step(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import MagicMock, patch

        from forge.cli.extensions import enable_cmd

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        monkeypatch.chdir(repo)

        mock_plan = MagicMock()
        mock_plan.has_conflicts = False
        mock_plan.conflicts = []
        mock_plan.files = []
        mock_plan.codex = None
        mock_plan.settings = []
        mock_plan.settings_entries = []
        mock_plan.modules = []
        mock_plan.profile = "standard"

        with (
            patch("forge.cli.extensions.Installer") as MockInstaller,
            patch("forge.install.version.check_minimum_version") as mock_ver,
        ):
            mock_instance = MockInstaller.return_value
            mock_instance.plan.return_value = mock_plan
            mock_instance.init.return_value = mock_plan
            mock_ver.return_value = MagicMock(ok=True)
            result = CliRunner().invoke(enable_cmd, [])

        assert result.exit_code == 0, result.output
        assert "Auto-detected scope: local" in result.output
        assert "Next steps (runtime hooks):" in result.output
        assert "forge extension enable --scope user" in result.output
        call_kwargs = MockInstaller.call_args
        assert call_kwargs.kwargs["scope"] == InstallScope.LOCAL

    def test_path_with_scope_user_errors(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock, patch

        from click.testing import CliRunner

        from forge.cli.extensions import enable_cmd

        repo = tmp_path / "repo"
        repo.mkdir()

        with patch("forge.install.version.check_minimum_version") as mock_ver:
            mock_ver.return_value = MagicMock(ok=True)
            runner = CliRunner()
            result = runner.invoke(enable_cmd, ["--scope", "user", "--root", str(repo)])

        assert result.exit_code != 0
        assert "not applicable" in result.output.lower()

    def test_dry_run_with_path_no_side_effects(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock, patch

        from click.testing import CliRunner

        from forge.cli.extensions import enable_cmd

        repo = tmp_path / "repo"
        repo.mkdir()

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        mock_plan = MagicMock()
        mock_plan.has_conflicts = False
        mock_plan.files = []
        mock_plan.codex = None
        mock_plan.settings = []
        mock_plan.settings_entries = []
        mock_plan.modules = []
        mock_plan.profile = "standard"

        with (
            patch("forge.cli.extensions.Installer") as MockInstaller,
            patch("forge.install.version.check_minimum_version") as mock_ver,
        ):
            mock_instance = MockInstaller.return_value
            mock_instance.plan.return_value = mock_plan
            mock_ver.return_value = MagicMock(ok=True)

            runner = CliRunner()
            result = runner.invoke(enable_cmd, ["--scope", "local", "--root", str(repo), "--dry-run"])

        assert result.exit_code == 0
        assert not (repo / ".claude").is_dir()
        assert not (repo / ".forge").is_dir()

    def test_path_inside_claude_dir_errors(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock, patch

        from click.testing import CliRunner

        from forge.cli.extensions import enable_cmd

        claude_dir = tmp_path / "repo" / ".claude"
        claude_dir.mkdir(parents=True)

        with patch("forge.install.version.check_minimum_version") as mock_ver:
            mock_ver.return_value = MagicMock(ok=True)
            runner = CliRunner()
            result = runner.invoke(enable_cmd, ["--scope", "local", "--root", str(claude_dir)])

        assert result.exit_code != 0
        assert "inside a .claude directory" in result.output

    def test_project_scope_explicit_hooks_request_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import MagicMock, patch

        from forge.cli.extensions import enable_cmd

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        home = tmp_path / "home"
        forge_home = tmp_path / "forge-home"
        claude_home = tmp_path / "claude-home"
        home.mkdir()
        forge_home.mkdir()
        claude_home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("FORGE_HOME", str(forge_home))
        monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
        monkeypatch.chdir(repo)

        with patch("forge.install.version.check_minimum_version") as mock_ver:
            mock_ver.return_value = MagicMock(ok=True)
            result = CliRunner().invoke(
                enable_cmd,
                [
                    "--scope",
                    "local",
                    "--profile",
                    "minimal",
                    "--with",
                    "hooks",
                    "--without",
                    "commands",
                ],
            )

        assert result.exit_code == 1
        assert "user-scope only" in result.output
        assert "forge extension enable --scope user" in result.output
        assert not (repo / ".forge").exists()


class TestScopeAllConflict:
    """Tests for --all + --scope mutual exclusivity."""

    def test_disable_all_with_scope_errors(self) -> None:
        from click.testing import CliRunner

        from forge.cli.extensions import disable_cmd

        runner = CliRunner()
        result = runner.invoke(disable_cmd, ["--all", "--scope", "local"])
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output.lower()

    def test_disable_all_attempts_every_installation_and_exits_nonzero_on_failure(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock, call, patch

        from forge.install.models import Installation

        tracking = MagicMock()
        tracking.list_installations.return_value = [
            (
                "user",
                None,
                Installation(
                    scope="user",
                    mode="copy",
                    profile="standard",
                    codex_config_path=str(tmp_path / "codex" / "config.toml"),
                ),
            ),
            (
                "project",
                str(tmp_path),
                Installation(
                    scope="project",
                    project_path=str(tmp_path),
                    mode="copy",
                    profile="standard",
                ),
            ),
        ]
        failed_installer = MagicMock()
        failed_installer.uninstall.side_effect = OSError("permission denied")
        successful_installer = MagicMock()

        with (
            patch("forge.cli.extensions.TrackingStore", return_value=tracking),
            patch(
                "forge.cli.extensions.Installer",
                side_effect=[failed_installer, successful_installer],
            ) as installer_class,
            patch("forge.cli.extensions._enforce_project_compatibility"),
        ):
            result = CliRunner().invoke(extensions, ["disable", "--all", "--yes"])

        assert result.exit_code == 1, result.output
        assert "Completed with 1 error(s)." in result.output
        assert "permission denied" in result.output
        assert "one-time interactive trust ceremony" in result.output
        assert "Forge cannot verify trust" in result.output
        assert installer_class.call_args_list == [
            call(scope=InstallScope.USER, project_root=None),
            call(scope=InstallScope.PROJECT, project_root=tmp_path),
        ]
        failed_installer.uninstall.assert_called_once_with()
        successful_installer.uninstall.assert_called_once_with()

    def test_status_all_with_scope_errors(self) -> None:
        from click.testing import CliRunner

        from forge.cli.extensions import status_cmd

        runner = CliRunner()
        result = runner.invoke(status_cmd, ["--all", "--scope", "local"])
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output.lower()

    def test_status_all_with_path_errors(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from forge.cli.extensions import status_cmd

        runner = CliRunner()
        result = runner.invoke(status_cmd, ["--all", "--root", str(tmp_path)])
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output.lower()

    def test_status_user_with_path_errors(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from forge.cli.extensions import status_cmd

        runner = CliRunner()
        result = runner.invoke(status_cmd, ["--scope", "user", "--root", str(tmp_path)])
        assert result.exit_code != 0
        assert "not applicable" in result.output.lower()


@pytest.mark.parametrize("as_json", [False, True], ids=["human", "json"])
def test_status_all_outside_project_skips_unresolved_non_user_scopes(
    as_json: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    home = tmp_path / "home"
    outside = tmp_path / "outside"
    home.mkdir()
    outside.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge-home"))
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / "claude-home"))
    monkeypatch.chdir(outside)
    args = ["status", "--all"]
    if as_json:
        args.append("--json")

    result = CliRunner().invoke(extensions, args)

    assert result.exit_code == 0, result.output
    if as_json:
        assert json.loads(result.output) == {
            "schema_version": 3,
            "installations": [],
            "unmanaged_skill_packages": [],
        }
    else:
        assert "Scope: user" in result.output
        assert "Scope: project" in result.output
        assert "Scope: local" in result.output
        assert result.output.count("Not enabled") == 3


def test_status_json_reports_unmanaged_package_without_installation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    home = tmp_path / "home"
    package = home / ".agents" / "skills" / "understand"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text("untracked pre-marker package\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge-home"))
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / "claude-home"))

    result = CliRunner().invoke(extensions, ["status", "--scope", "user", "--json"])

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 3
    assert payload["installations"] == []
    assert len(payload["unmanaged_skill_packages"]) == 1
    unmanaged = payload["unmanaged_skill_packages"][0]
    assert unmanaged["runtime"] == "codex"
    assert unmanaged["skill"] == "understand"
    assert unmanaged["target_dir"] == str(package)
    assert unmanaged["target_scopes"] == ["user"]
    assert unmanaged["provenance"] == "unmarked"
    assert unmanaged["cleanup_eligible"] is False
    assert unmanaged["cleanup_scope"] is None
    assert "Remove or rename" in unmanaged["recovery"]

    human = CliRunner().invoke(extensions, ["status", "--scope", "user"])
    assert human.exit_code == 0, human.output
    assert "Unmanaged runtime skill packages" in human.output
    assert "understand" in human.output
    assert "Remove or rename" in human.output


def test_status_json_v3_reports_exact_ownership_and_unattributed_shape(
    tmp_path: Path,
) -> None:
    import json

    from forge.install.models import (
        Installation,
        InstalledFile,
        InstalledSettingsEntry,
    )
    from forge.install.ownership import unattributed
    from forge.install.tracking import TrackingStore

    tracking = TrackingStore()
    tracking.set_installation(
        "user",
        Installation(
            scope="user",
            mode="copy",
            profile="standard",
            module_owners=sorted(
                [
                    attributed(InstallModule.SKILLS, "claude_code"),
                    attributed(InstallModule.SKILLS, "codex"),
                ]
            ),
            files=[
                InstalledFile(
                    target_path=str(tmp_path / "opaque.bin"),
                    source_path="/legacy/opaque.bin",
                    checksum="abc",
                    mode="copy",
                    installed_at="2026-07-30T00:00:00Z",
                    attribution=unattributed("legacy_path_unmapped"),
                )
            ],
            settings_entries=[
                InstalledSettingsEntry(
                    key_path="future.setting",
                    value="TOP-SECRET-SETTING-VALUE",
                    merge_type="scalar",
                    stable_id="future.setting",
                    attribution=unattributed("legacy_key_unmapped"),
                )
            ],
            installed_at="2026-07-30T00:00:00Z",
            updated_at="2026-07-30T00:00:01Z",
        ),
    )

    result = CliRunner().invoke(
        extensions,
        ["status", "--scope", "user", "--json"],
    )

    assert result.exit_code == 0, result.output
    assert "TOP-SECRET-SETTING-VALUE" not in result.output
    payload = json.loads(result.output)
    assert set(payload) == {
        "schema_version",
        "installations",
        "unmanaged_skill_packages",
    }
    assert payload["schema_version"] == 3
    assert payload["unmanaged_skill_packages"] == []
    assert len(payload["installations"]) == 1
    installation = payload["installations"][0]
    assert set(installation) == {
        "scope",
        "profile",
        "mode",
        "managed_runtimes",
        "module_owners",
        "modules",
        "unattributed_surfaces",
        "files_count",
        "skill_packages",
        "settings_count",
        "codex_config_path",
        "codex_commands",
        "installed_at",
        "updated_at",
    }
    assert installation["managed_runtimes"] == ["claude_code", "codex"]
    assert installation["module_owners"] == [
        {"module": "skills", "runtime": "claude_code"},
        {"module": "skills", "runtime": "codex"},
    ]
    assert installation["modules"] == ["skills"]
    assert installation["unattributed_surfaces"] == [
        {
            "surface": "file",
            "target_path": str(tmp_path / "opaque.bin"),
            "reason": "legacy_path_unmapped",
        },
        {
            "surface": "settings",
            "key_path": "future.setting",
            "stable_id": "future.setting",
            "reason": "legacy_key_unmapped",
        },
    ]

    human = CliRunner().invoke(extensions, ["status", "--scope", "user"])
    assert human.exit_code == 0, human.output
    assert "2 unattributed surface(s)" in human.output
    assert "TOP-SECRET-SETTING-VALUE" not in human.output


def test_status_human_reports_symlinked_runtime_root_without_traversing_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    home = tmp_path / "home"
    real_root = tmp_path / "external-skills"
    hidden_package = real_root / "understand"
    hidden_package.mkdir(parents=True)
    (hidden_package / "SKILL.md").write_text("must not be traversed\n", encoding="utf-8")
    linked_root = home / ".agents" / "skills"
    linked_root.parent.mkdir(parents=True)
    linked_root.symlink_to(real_root, target_is_directory=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge-home"))
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / "claude-home"))

    human = CliRunner().invoke(extensions, ["status", "--scope", "user"])

    assert human.exit_code == 0, human.output
    assert "Root not scanned:" in human.output
    assert ".agents/skills" in human.output
    assert "is not a real directory" in human.output
    assert "None found in the selected runtime roots" not in human.output
    assert str(hidden_package) not in human.output

    machine = CliRunner().invoke(extensions, ["status", "--scope", "user", "--json"])

    assert machine.exit_code == 0, machine.output
    assert json.loads(machine.stdout) == {
        "schema_version": 3,
        "installations": [],
        "unmanaged_skill_packages": [],
    }


def test_status_uses_one_tracking_snapshot_for_detection_and_rendering(tmp_path: Path) -> None:
    from unittest.mock import patch

    from forge.install.tracking import TrackingStore

    tracking = TrackingStore(tmp_path / "installed.json")
    with (
        patch("forge.cli.extensions.TrackingStore", return_value=tracking),
        patch.object(tracking, "read", wraps=tracking.read) as read_tracking,
    ):
        result = CliRunner().invoke(extensions, ["status", "--all", "--json"])

    assert result.exit_code == 0, result.output
    read_tracking.assert_called_once_with()


def test_status_uses_historical_names_when_current_source_discovery_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from unittest.mock import patch

    home = tmp_path / "home"
    package = home / ".agents" / "skills" / "understand"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text("historical name\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge-home"))
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / "claude-home"))

    with patch(
        "forge.cli.extensions.discover_skill_source_names",
        side_effect=OSError("broken source tree"),
    ):
        result = CliRunner().invoke(extensions, ["status", "--scope", "user", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [record["skill"] for record in payload["unmanaged_skill_packages"]] == ["understand"]


def test_unavailable_runtime_conflict_says_force_cannot_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    home.mkdir()
    outside.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge-home"))
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / "claude-home"))
    monkeypatch.chdir(outside)
    monkeypatch.setattr("forge.install.installer.installed_runtimes", lambda: [])

    result = CliRunner().invoke(
        extensions,
        [
            "enable",
            "--scope",
            "user",
            "--runtime",
            "codex",
            "--force",
            "--dry-run",
        ],
    )

    assert result.exit_code == 1, result.output
    output = " ".join(result.output.split())
    assert "runtime_unavailable" in output
    assert "--force does not override" in output
    assert "Use --force to override" not in output


class TestDisableNoInstallMessage:
    """Regression tests for disable guidance when auto-detection misses."""

    def test_disable_without_install_names_extension_enable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from click.testing import CliRunner

        from forge.cli.extensions import disable_cmd

        home = tmp_path / "home"
        workspace = tmp_path / "workspace"
        home.mkdir()
        workspace.mkdir()
        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.chdir(workspace)

        runner = CliRunner()
        result = runner.invoke(disable_cmd, [])

        assert result.exit_code != 0
        normalized = " ".join(result.output.split())
        assert "forge extension enable" in normalized
        assert "forge init" not in result.output


def test_disable_runtime_noop_names_autodetected_scope_and_scope_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from forge.install.models import Installation
    from forge.install.tracking import TrackingStore

    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    tracking = TrackingStore()
    installation = Installation(
        scope="local",
        project_path=str(project),
        mode="copy",
        profile="standard",
        module_owners=[attributed(InstallModule.HOOKS, "claude_code")],
    )
    tracking.set_installation("local", installation, str(project))
    monkeypatch.chdir(project)

    result = CliRunner().invoke(extensions, ["disable", "--runtime", "codex"])

    assert result.exit_code == 0, result.output
    assert "Auto-detected scope: local" in result.output
    assert "Resolved scope 'local' does not manage the selected codex runtime" in result.output
    assert "Use --scope" in result.output
    assert tracking.get_installation("local", str(project)) == installation


def test_disable_runtime_plan_reports_retained_unattributed_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from forge.install.models import Installation, InstalledFile
    from forge.install.ownership import unattributed
    from forge.install.tracking import TrackingStore

    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    tracking = TrackingStore()
    installation = Installation(
        scope="local",
        project_path=str(project),
        mode="copy",
        profile="standard",
        module_owners=[
            attributed(InstallModule.SKILLS, "claude_code"),
            attributed(InstallModule.SKILLS, "codex"),
        ],
        files=[
            InstalledFile(
                target_path=str(project / "legacy" / "unknown"),
                source_path=str(project / "source" / "unknown"),
                checksum="legacy",
                mode="copy",
                installed_at="2026-01-01T00:00:00Z",
                attribution=unattributed("legacy_path_unmapped"),
            )
        ],
    )
    tracking.set_installation("local", installation, str(project))
    monkeypatch.chdir(project)

    result = CliRunner().invoke(
        extensions,
        ["disable", "--runtime", "claude"],
        input="n\n",
    )

    assert result.exit_code == 0, result.output
    assert "Retaining 1 legacy unattributed surface(s)" in result.output
    assert "legacy_path_unmapped" in result.output
    assert "Proceed with runtime disable?" in result.output


def test_disable_all_runtime_summary_distinguishes_noop_partial_and_full(
    tmp_path: Path,
) -> None:
    import re

    from forge.install.models import Installation, InstalledFile
    from forge.install.ownership import unattributed
    from forge.install.tracking import TrackingStore

    tracking = TrackingStore()
    partial_root = tmp_path / "partial"
    full_root = tmp_path / "full"
    for root in (partial_root, full_root):
        root.mkdir()
    tracking.set_installation(
        "user",
        Installation(
            scope="user",
            mode="copy",
            profile="standard",
            module_owners=[attributed(InstallModule.SKILLS, "claude_code")],
        ),
        None,
    )
    tracking.set_installation(
        "project",
        Installation(
            scope="project",
            project_path=str(partial_root),
            mode="copy",
            profile="standard",
            module_owners=[
                attributed(InstallModule.SKILLS, "claude_code"),
                attributed(InstallModule.SKILLS, "codex"),
            ],
            files=[
                InstalledFile(
                    target_path=str(partial_root / "legacy-partial"),
                    source_path=str(partial_root / "source-partial"),
                    checksum="legacy",
                    mode="copy",
                    installed_at="2026-01-01T00:00:00Z",
                    attribution=unattributed("legacy_path_unmapped"),
                )
            ],
        ),
        str(partial_root),
    )
    tracking.set_installation(
        "local",
        Installation(
            scope="local",
            project_path=str(full_root),
            mode="copy",
            profile="standard",
            module_owners=[attributed(InstallModule.SKILLS, "codex")],
            files=[
                InstalledFile(
                    target_path=str(full_root / "legacy-full"),
                    source_path=str(full_root / "source-full"),
                    checksum="legacy",
                    mode="copy",
                    installed_at="2026-01-01T00:00:00Z",
                    attribution=unattributed("legacy_v1_unprovable"),
                )
            ],
        ),
        str(full_root),
    )

    result = CliRunner().invoke(
        extensions,
        ["disable", "--all", "--runtime", "codex"],
        input="n\n",
    )

    assert result.exit_code == 0, result.output
    assert "DISPOSITION" in result.output
    assert re.search(r"user\s+\(global\)\s+standard\s+no-op\s+0\s+0", result.output)
    assert re.search(r"project\s+.*standard\s+partial\s+0\s+0", result.output)
    assert re.search(r"local\s+.*standard\s+full\s+1\s+0", result.output)
    assert "legacy_path_unmapped" in result.output
    assert "legacy_v1_unprovable" not in result.output
    assert "Remove selected codex runtime surfaces across these scopes?" in result.output


def test_disable_all_runtime_aggregates_failure_and_processes_healthy_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from forge.install.models import Installation, InstalledFile
    from forge.install.tracking import TrackingStore

    tracking = TrackingStore()
    failed_root = tmp_path / "failed"
    healthy_root = tmp_path / "healthy"
    targets: dict[str, Path] = {}
    for root in (failed_root, healthy_root):
        target = root / ".claude" / "commands" / "review.md"
        target.parent.mkdir(parents=True)
        target.write_text("managed\n", encoding="utf-8")
        targets[root.name] = target
        tracking.set_installation(
            "project",
            Installation(
                scope="project",
                project_path=str(root),
                mode="copy",
                profile="minimal",
                module_owners=[attributed(InstallModule.COMMANDS, "claude_code")],
                files=[
                    InstalledFile(
                        target_path=str(target),
                        source_path=str(root / "source" / "review.md"),
                        checksum="checksum",
                        mode="copy",
                        installed_at="2026-01-01T00:00:00Z",
                        attribution=attributed(InstallModule.COMMANDS, "claude_code"),
                    )
                ],
            ),
            str(root),
        )
    real_unlink = Path.unlink

    def fail_one_target(path: Path, missing_ok: bool = False) -> None:
        if path == targets["failed"]:
            raise OSError("injected batch removal fault")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_one_target)

    result = CliRunner().invoke(
        extensions,
        ["disable", "--all", "--runtime", "claude", "--yes"],
    )

    assert result.exit_code == 1, result.output
    output = " ".join(result.output.split())
    assert "Completed with 1 error(s)." in output
    assert "injected batch removal fault" in output
    assert tracking.get_installation("project", str(failed_root)) is not None
    assert tracking.get_installation("project", str(healthy_root)) is None
    assert targets["failed"].exists()
    assert not targets["healthy"].exists()


class TestCleanupProject:
    def test_user_enable_aborts_on_corrupt_tracking_before_user_write(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import os

        from forge.core.state.exceptions import StateCorruptedError
        from forge.install.tracking import TrackingStore

        claude_home = Path(os.environ["CLAUDE_HOME"])
        settings = claude_home / "settings.json"
        settings.write_text('{"custom": true}', encoding="utf-8")
        tracking = TrackingStore().path
        tracking.parent.mkdir(parents=True, exist_ok=True)
        tracking.write_text("{not json", encoding="utf-8")
        dispatcher_calls: list[bool] = []
        monkeypatch.setattr(
            "forge.install.version.check_minimum_version",
            lambda: type("Check", (), {"ok": True})(),
        )
        monkeypatch.setattr(
            "forge.install.installer._ensure_hook_dispatcher",
            lambda: dispatcher_calls.append(True),
        )
        monkeypatch.setattr("forge.install.installer._codex_available", lambda: False)

        result = CliRunner().invoke(extensions, ["enable", "--scope", "user", "--profile", "standard"])

        assert result.exit_code == 1
        assert isinstance(result.exception, StateCorruptedError)
        assert settings.read_text(encoding="utf-8") == '{"custom": true}'
        assert tracking.read_text(encoding="utf-8") == "{not json"
        assert dispatcher_calls == []

    def test_user_enable_preflights_both_user_settings_before_writes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import os

        from forge.install.tracking import TrackingStore

        claude_home = Path(os.environ["CLAUDE_HOME"])
        current = claude_home / "settings.json"
        current.write_text('{"custom": true}', encoding="utf-8")
        (claude_home / "settings.local.json").write_text("{not json", encoding="utf-8")
        dispatcher_calls: list[bool] = []
        monkeypatch.setattr(
            "forge.install.version.check_minimum_version",
            lambda: type("Check", (), {"ok": True})(),
        )
        monkeypatch.setattr(
            "forge.install.installer._ensure_hook_dispatcher",
            lambda: dispatcher_calls.append(True),
        )
        monkeypatch.setattr("forge.install.installer._codex_available", lambda: False)

        result = CliRunner().invoke(extensions, ["enable", "--scope", "user", "--profile", "standard"])

        assert result.exit_code == 1
        assert "cannot read settings" in result.output
        assert current.read_text(encoding="utf-8") == '{"custom": true}'
        assert dispatcher_calls == []
        assert not TrackingStore().path.exists()

    def test_user_enable_ignores_corrupt_registry_and_reports_tracked_root(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from forge.install.models import (
            Installation,
            InstallMode,
            InstallModule,
            InstallProfile,
        )
        from forge.install.tracking import TrackingStore

        root = tmp_path / "legacy"
        (root / ".forge").mkdir(parents=True)
        registry = ProjectRegistryStore().path
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text("{not json", encoding="utf-8")
        tracking = TrackingStore()
        tracking.set_installation(
            InstallScope.PROJECT.value,
            Installation(
                scope=InstallScope.PROJECT.value,
                project_path=str(root),
                mode=InstallMode.COPY.value,
                profile=InstallProfile.STANDARD.value,
                module_owners=[attributed(InstallModule.HOOKS, "claude_code")],
                installed_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
            ),
            str(root),
        )
        monkeypatch.setattr(
            "forge.install.version.check_minimum_version",
            lambda: type("Check", (), {"ok": True})(),
        )
        monkeypatch.setattr("forge.install.installer._ensure_hook_dispatcher", lambda: None)
        monkeypatch.setattr("forge.install.installer._codex_available", lambda: False)

        result = CliRunner().invoke(extensions, ["enable", "--scope", "user", "--profile", "standard"])

        assert result.exit_code == 0, result.output
        assert "cleanup-project --root" in result.output
        assert registry.read_text(encoding="utf-8") == "{not json"

    def test_ambiguous_other_root_cannot_block_user_enable_or_mutate_either_root(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import json

        from forge.install import hook_migration
        from forge.install.models import (
            Installation,
            InstallMode,
            InstallModule,
            InstallProfile,
        )
        from forge.install.tracking import TrackingStore

        ambiguous_root = tmp_path / "ambiguous"
        healthy_root = tmp_path / "healthy"
        for root in (ambiguous_root, healthy_root):
            (root / ".forge").mkdir(parents=True)
            (root / ".claude").mkdir()
        ambiguous_settings = ambiguous_root / ".claude" / "settings.json"
        ambiguous_settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "forge hook session-start",
                                        "timeout": 99,
                                    }
                                ]
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        healthy_settings = healthy_root / ".claude" / "settings.json"
        healthy_settings.write_text('{"custom": true}', encoding="utf-8")
        before = {
            ambiguous_settings: ambiguous_settings.read_text(encoding="utf-8"),
            healthy_settings: healthy_settings.read_text(encoding="utf-8"),
        }
        tracking = TrackingStore()
        for root in (ambiguous_root, healthy_root):
            tracking.set_installation(
                InstallScope.PROJECT.value,
                Installation(
                    scope=InstallScope.PROJECT.value,
                    project_path=str(root),
                    mode=InstallMode.COPY.value,
                    profile=InstallProfile.STANDARD.value,
                    module_owners=[attributed(InstallModule.HOOKS, "claude_code")],
                    installed_at="2026-01-01T00:00:00Z",
                    updated_at="2026-01-01T00:00:00Z",
                ),
                str(root),
            )
        read_settings_strict = hook_migration._read_settings_strict
        opened_roots: list[Path] = []

        def reject_root_read(path: Path) -> dict[str, Any]:
            if any(path.is_relative_to(root) for root in (ambiguous_root, healthy_root)):
                opened_roots.append(path)
                raise AssertionError(f"user enable opened tracked root settings: {path}")
            return read_settings_strict(path)

        monkeypatch.setattr(hook_migration, "_read_settings_strict", reject_root_read)
        monkeypatch.setattr(
            "forge.install.version.check_minimum_version",
            lambda: type("Check", (), {"ok": True})(),
        )
        monkeypatch.setattr("forge.install.installer._ensure_hook_dispatcher", lambda: None)
        monkeypatch.setattr("forge.install.installer._codex_available", lambda: False)

        result = CliRunner().invoke(extensions, ["enable", "--scope", "user", "--profile", "standard"])

        assert result.exit_code == 0, result.output
        assert result.output.count("cleanup-project --root") == 2
        assert opened_roots == []
        assert {path: path.read_text(encoding="utf-8") for path in before} == before
        assert not ProjectRegistryStore().path.exists()

    def test_incompatible_selected_root_aborts_without_opening_unrelated_root(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import json

        from forge.install import hook_migration
        from forge.install.models import (
            Installation,
            InstallMode,
            InstallModule,
            InstallProfile,
        )
        from forge.install.tracking import TrackingStore

        selected = tmp_path / "selected"
        unrelated = tmp_path / "unrelated"
        for root in (selected, unrelated):
            (root / ".forge").mkdir(parents=True)
            (root / ".claude").mkdir()
        (selected / ".forge" / "project.toml").write_text(
            'schema_version = 1\nrequired_forge = ">=9999"\n',
            encoding="utf-8",
        )
        selected_settings = selected / ".claude" / "settings.json"
        selected_settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "forge hook session-start",
                                    }
                                ]
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        unrelated_settings = unrelated / ".claude" / "settings.json"
        unrelated_settings.write_text('{"custom": true}', encoding="utf-8")
        tracking = TrackingStore()
        tracking.set_installation(
            InstallScope.PROJECT.value,
            Installation(
                scope=InstallScope.PROJECT.value,
                project_path=str(unrelated),
                mode=InstallMode.COPY.value,
                profile=InstallProfile.STANDARD.value,
                module_owners=[attributed(InstallModule.HOOKS, "claude_code")],
                installed_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
            ),
            str(unrelated),
        )
        read_settings_strict = hook_migration._read_settings_strict
        unrelated_reads: list[Path] = []

        def reject_unrelated_read(path: Path) -> dict[str, Any]:
            if path.is_relative_to(unrelated):
                unrelated_reads.append(path)
                raise AssertionError(f"selected cleanup opened unrelated root settings: {path}")
            return read_settings_strict(path)

        monkeypatch.setattr(hook_migration, "_read_settings_strict", reject_unrelated_read)
        selected_before = selected_settings.read_text(encoding="utf-8")
        unrelated_before = unrelated_settings.read_text(encoding="utf-8")

        result = CliRunner().invoke(
            extensions,
            ["cleanup-project", "--root", str(selected), "--yes"],
        )

        assert result.exit_code == 1
        assert "requires Forge >=9999" in result.output
        assert unrelated_reads == []
        assert selected_settings.read_text(encoding="utf-8") == selected_before
        assert unrelated_settings.read_text(encoding="utf-8") == unrelated_before
        assert not ProjectRegistryStore().path.exists()

    def test_cleanup_rejects_corrupt_registry_before_any_write(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import json
        import os
        from types import SimpleNamespace

        from forge.core.state.exceptions import StateCorruptedError
        from forge.install.tracking import TrackingStore

        root = tmp_path / "repo"
        (root / ".forge").mkdir(parents=True)
        (root / ".claude").mkdir()
        settings = root / ".claude" / "settings.json"
        original = {
            "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "forge hook session-start"}]}]}
        }
        settings.write_text(json.dumps(original), encoding="utf-8")
        registry = ProjectRegistryStore().path
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text("{not json", encoding="utf-8")
        user_settings = Path(os.environ["CLAUDE_HOME"]) / "settings.json"
        tracking_path = TrackingStore().path
        monkeypatch.setattr(
            "forge.install.hook_migration.diagnose_hook_dispatcher",
            lambda: SimpleNamespace(status="current"),
        )

        result = CliRunner().invoke(extensions, ["cleanup-project", "--root", str(root), "--yes"])

        assert result.exit_code == 1
        assert isinstance(result.exception, StateCorruptedError)
        assert json.loads(settings.read_text(encoding="utf-8")) == original
        assert not user_settings.exists()
        assert not tracking_path.exists()
        assert registry.read_text(encoding="utf-8") == "{not json"

    def test_user_enable_consolidates_safe_legacy_siblings(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import json
        import os

        claude_home = Path(os.environ["CLAUDE_HOME"])
        current_path = claude_home / "settings.json"
        local_path = claude_home / "settings.local.json"
        legacy = {"hooks": [{"type": "command", "command": "forge hook session-start"}]}
        current_path.write_text(
            json.dumps({"hooks": {"SessionStart": [legacy]}, "custom": True}),
            encoding="utf-8",
        )
        local_path.write_text(
            json.dumps({"hooks": {"SessionStart": [legacy]}, "localCustom": True}),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "forge.install.version.check_minimum_version",
            lambda: type("Check", (), {"ok": True})(),
        )
        monkeypatch.setattr("forge.install.installer._ensure_hook_dispatcher", lambda: None)
        monkeypatch.setattr("forge.install.installer._codex_available", lambda: False)
        monkeypatch.setattr(extensions_console, "_width", 40)

        result = CliRunner().invoke(extensions, ["enable", "--scope", "user", "--profile", "standard"])

        assert result.exit_code == 0, result.output
        current = json.loads(current_path.read_text(encoding="utf-8"))
        local = json.loads(local_path.read_text(encoding="utf-8"))
        assert current["custom"] is True
        assert current["hooks"]["SessionStart"][0]["hooks"][0]["command"].endswith("/bin/forge-hook session-start")
        assert local == {"localCustom": True}
        assert list(claude_home.glob(".settings.json.forge.backup.*"))
        assert list(claude_home.glob(".settings.local.json.forge.backup.*"))
        compact_output = "".join(result.output.split())
        assert str(current_path) in compact_output
        assert str(local_path) in compact_output

    def test_user_sync_consolidates_safe_legacy_siblings(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import json
        import os

        # User-scope sync must not inherit Codex duplicate packages from the
        # developer checkout that happens to host the test run.
        monkeypatch.chdir(tmp_path)
        claude_home = Path(os.environ["CLAUDE_HOME"])
        monkeypatch.setattr(
            "forge.install.version.check_minimum_version",
            lambda: type("Check", (), {"ok": True})(),
        )
        monkeypatch.setattr("forge.install.installer._ensure_hook_dispatcher", lambda: None)
        monkeypatch.setattr("forge.install.installer._codex_available", lambda: False)
        runner = CliRunner()
        enabled = runner.invoke(extensions, ["enable", "--scope", "user", "--profile", "standard"])
        assert enabled.exit_code == 0, enabled.output

        legacy = {"hooks": [{"type": "command", "command": "forge hook session-start"}]}
        current_path = claude_home / "settings.json"
        current = json.loads(current_path.read_text(encoding="utf-8"))
        current["hooks"]["SessionStart"].append(legacy)
        current_path.write_text(json.dumps(current), encoding="utf-8")
        local_path = claude_home / "settings.local.json"
        local_path.write_text(
            json.dumps({"hooks": {"SessionStart": [legacy]}, "localCustom": True}),
            encoding="utf-8",
        )
        monkeypatch.setattr(extensions_console, "_width", 40)

        result = runner.invoke(extensions, ["sync", "--scope", "user"])

        assert result.exit_code == 0, result.output
        synced = json.loads(current_path.read_text(encoding="utf-8"))
        commands = [entry["hooks"][0]["command"] for entry in synced["hooks"]["SessionStart"]]
        assert all("forge hook session-start" not in command for command in commands)
        assert json.loads(local_path.read_text(encoding="utf-8")) == {"localCustom": True}
        compact_output = "".join(result.output.split())
        assert str(current_path) in compact_output
        assert str(local_path) in compact_output

    def test_preview_apply_and_repeat_are_safe(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import json
        from types import SimpleNamespace

        root = tmp_path / "repo"
        (root / ".forge").mkdir(parents=True)
        (root / ".claude").mkdir()
        settings = root / ".claude" / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "forge hook session-start",
                                    }
                                ]
                            }
                        ]
                    },
                    "permissions": {"allow": ["Read"]},
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "forge.install.hook_migration.diagnose_hook_dispatcher",
            lambda: SimpleNamespace(status="current"),
        )
        monkeypatch.setattr("forge.install.hook_migration.install_hook_dispatcher", lambda: None)
        runner = CliRunner()

        preview = runner.invoke(extensions, ["cleanup-project", "--root", str(root)])

        assert preview.exit_code == 0, preview.output
        assert "Hook Migration Plan" in preview.output
        assert "enroll last" in preview.output
        assert "forge hook session-start" in settings.read_text(encoding="utf-8")
        assert not ProjectRegistryStore().contains_root(root)

        applied = runner.invoke(extensions, ["cleanup-project", "--root", str(root), "--yes"])

        assert applied.exit_code == 0, applied.output
        assert "Project hook migration complete" in applied.output
        data = json.loads(settings.read_text(encoding="utf-8"))
        assert "hooks" not in data
        assert data["permissions"] == {"allow": ["Read"]}
        assert ProjectRegistryStore().contains_root(root)

        repeated = runner.invoke(extensions, ["cleanup-project", "--root", str(root), "--yes"])
        assert repeated.exit_code == 0, repeated.output
        assert "Already migrated" in repeated.output

    def test_cleanup_uses_applied_result_for_codex_retrust_notice(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from types import SimpleNamespace

        from forge.install.hook_migration import ProjectHookMigrationResult

        root = tmp_path / "repo"
        (root / ".forge").mkdir(parents=True)
        preview_plan = SimpleNamespace(
            root=root,
            settings=(),
            codex=SimpleNamespace(action="skip"),
            user=SimpleNamespace(changed=False, codex=None),
            tracked_installations=(),
            enrolled=True,
            has_actions=False,
            blockers=(),
        )
        applied_result = ProjectHookMigrationResult(
            root=root,
            removed_hooks=0,
            changed_paths=(tmp_path / "codex-user" / "config.toml",),
            backup_paths=(),
            enrolled=True,
            enrollment_created=False,
            user_codex_action="update",
        )
        monkeypatch.setattr(
            "forge.cli.extensions.plan_project_hook_migration",
            lambda _root: preview_plan,
        )
        monkeypatch.setattr(
            "forge.cli.extensions.apply_project_hook_migration",
            lambda _root: applied_result,
        )

        result = CliRunner().invoke(
            extensions,
            ["cleanup-project", "--root", str(root), "--yes"],
        )

        assert result.exit_code == 0, result.output
        assert "Next steps (Codex hooks)" in result.output
        assert "grant trust" in result.output

    def test_ambiguous_entry_blocks_before_writes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import json
        from types import SimpleNamespace

        root = tmp_path / "repo"
        (root / ".forge").mkdir(parents=True)
        (root / ".claude").mkdir()
        settings = root / ".claude" / "settings.json"
        original = {
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "forge hook session-start",
                                "timeout": 99,
                            }
                        ]
                    }
                ]
            }
        }
        settings.write_text(json.dumps(original), encoding="utf-8")
        monkeypatch.setattr(
            "forge.install.hook_migration.diagnose_hook_dispatcher",
            lambda: SimpleNamespace(status="current"),
        )

        result = CliRunner().invoke(extensions, ["cleanup-project", "--root", str(root), "--yes"])

        assert result.exit_code == 1
        assert "Cleanup blockers" in result.output
        assert json.loads(settings.read_text(encoding="utf-8")) == original
        assert not ProjectRegistryStore().contains_root(root)


class TestExtensionDoctorRuntimeHooks:
    @staticmethod
    def _write_double_scope_hooks(project: Path, claude_home: Path) -> None:
        import json

        (project / ".claude").mkdir(parents=True)
        (project / ".claude" / "settings.local.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "forge hook session-start",
                                    }
                                ]
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        (claude_home / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "forge-hook session-start",
                                    }
                                ]
                            },
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _write_same_user_file_duplicate_hooks(claude_home: Path) -> None:
        import json

        (claude_home / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "forge hook session-start",
                                    }
                                ]
                            },
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "forge-hook session-start",
                                    }
                                ]
                            },
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

    def test_json_reports_double_fire_hook_scopes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import json
        import os

        project = tmp_path / "repo"
        claude_home = Path(os.environ["CLAUDE_HOME"])
        self._write_double_scope_hooks(project, claude_home)
        monkeypatch.chdir(project)

        result = CliRunner().invoke(extensions, ["doctor", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        runtime = data["runtime_hooks"]
        assert runtime["scopes"] == ["local", "user"]
        assert runtime["double_fire_risk"] is True
        assert runtime["cleanup_required"] is True
        assert len(runtime["legacy_registrations"]) == 1
        assert runtime["legacy_registrations"][0]["scope"] == "local"

    def test_json_reports_lone_legacy_hook_as_cleanup_without_double_fire(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        project = tmp_path / "repo"
        (project / ".claude").mkdir(parents=True)
        (project / ".claude" / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "forge hook session-start",
                                    }
                                ]
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.chdir(project)

        result = CliRunner().invoke(extensions, ["doctor", "--json"])

        assert result.exit_code == 0, result.output
        runtime = json.loads(result.output)["runtime_hooks"]
        assert runtime["scopes"] == ["project"]
        assert runtime["double_fire_risk"] is False
        assert runtime["cleanup_required"] is True
        assert [registration["scope"] for registration in runtime["legacy_registrations"]] == ["project"]

    def test_json_reports_same_user_file_duplicate_as_double_fire(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json
        import os

        project = tmp_path / "repo"
        project.mkdir()
        claude_home = Path(os.environ["CLAUDE_HOME"])
        self._write_same_user_file_duplicate_hooks(claude_home)
        monkeypatch.chdir(project)

        result = CliRunner().invoke(extensions, ["doctor", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        runtime = data["runtime_hooks"]
        assert runtime["scopes"] == ["user"]
        assert runtime["double_fire_risk"] is True
        assert runtime["cleanup_required"] is True
        assert len(runtime["legacy_registrations"]) == 1
        assert runtime["legacy_registrations"][0]["command"] == "forge hook session-start"

    def test_json_treats_home_cwd_user_hooks_as_single_scope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        home = tmp_path / "home"
        claude_home = home / ".claude"
        home.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
        monkeypatch.setattr(Path, "home", lambda: home)
        claude_home.mkdir(parents=True)
        (claude_home / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "forge-hook session-start",
                                    }
                                ]
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.chdir(home)

        result = CliRunner().invoke(extensions, ["doctor", "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["runtime_hooks"] == {
            "scopes": ["user"],
            "double_fire_risk": False,
            "cleanup_required": False,
            "legacy_registrations": [],
        }

    def test_human_report_distinguishes_cleanup_from_double_fire(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import os

        project = tmp_path / "repo"
        claude_home = Path(os.environ["CLAUDE_HOME"])
        self._write_double_scope_hooks(project, claude_home)
        monkeypatch.chdir(project)

        result = CliRunner().invoke(extensions, ["doctor"])

        assert result.exit_code == 0, result.output
        assert "may fire twice" in result.output
        assert "Cleanup needed: yes" in result.output
        assert "forge extension cleanup-project" in result.output
        assert "forge extension disable --scope local" not in result.output


class TestEnableCodexHooks:
    """Tests for Codex-owned hooks on enable/status/disable."""

    @staticmethod
    def _codex_config() -> Path:
        import os

        return Path(os.environ["CODEX_HOME"]) / "config.toml"

    def _enable(self, available: bool) -> Any:
        from unittest.mock import MagicMock, patch

        from click.testing import CliRunner

        from forge.cli.extensions import enable_cmd

        with (
            patch("forge.install.version.check_minimum_version") as mock_ver,
            patch("forge.install.installer._codex_available", return_value=available),
        ):
            mock_ver.return_value = MagicMock(ok=True)
            runner = CliRunner()
            return runner.invoke(
                enable_cmd,
                [
                    "--scope",
                    "user",
                    "--profile",
                    "minimal",
                    "--with",
                    "hooks",
                    "--without",
                    "commands",
                    "--runtime",
                    "all",
                ],
            )

    def test_enable_registers_and_prints_ceremony_next_steps(self) -> None:
        result = self._enable(available=True)
        assert result.exit_code == 0, result.output
        assert "Next steps (Codex hooks):" in result.output
        assert "grant trust" in result.output
        assert "# >>> forge hooks >>>" in self._codex_config().read_text()

    def test_enable_without_codex_binary_skips_visibly(self) -> None:
        from forge.install.tracking import TrackingStore

        result = self._enable(available=False)
        assert result.exit_code == 0, result.output
        assert "Codex hooks skipped: codex binary not found on PATH" in result.output
        assert "Next steps (Codex hooks):" not in result.output
        assert not self._codex_config().exists()
        installation = TrackingStore().get_installation("user")
        assert installation is not None
        assert attributed(InstallModule.HOOKS, "claude_code") in installation.module_owners
        assert attributed(InstallModule.HOOKS, "codex") not in installation.module_owners

    def test_status_shows_codex_registration(self) -> None:
        from click.testing import CliRunner

        from forge.cli.extensions import status_cmd

        self._enable(available=True)
        result = CliRunner().invoke(status_cmd, ["--scope", "user"])
        assert result.exit_code == 0, result.output
        assert "Profile:   minimal (installed)" in result.output
        assert "Codex:" in result.output
        assert "hooks registered in" in result.output

    def test_status_json_carries_codex_fields(self) -> None:
        import json

        from click.testing import CliRunner

        from forge.cli.extensions import status_cmd

        self._enable(available=True)
        result = CliRunner().invoke(status_cmd, ["--scope", "user", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["schema_version"] == 3
        assert data["unmanaged_skill_packages"] == []
        installation = data["installations"][0]
        assert installation["codex_config_path"] == str(self._codex_config())
        assert [_normalize_forge_home(command) for command in installation["codex_commands"]] == [
            "$FORGE_HOME/bin/forge-hook codex-policy-check",
            "$FORGE_HOME/bin/forge-hook codex-session-start",
        ]

    def test_disable_previews_and_removes_block(self) -> None:
        from click.testing import CliRunner

        from forge.cli.extensions import disable_cmd

        self._enable(available=True)
        assert self._codex_config().is_file()
        result = CliRunner().invoke(disable_cmd, ["--scope", "user", "--yes"])
        assert result.exit_code == 0, result.output
        assert "Codex hooks:" in result.output
        assert "one-time interactive trust ceremony" in result.output
        assert "Forge cannot verify trust" in result.output
        assert not self._codex_config().exists()

    def test_disable_runtime_codex_renders_exact_plan_and_retrust_consequence(self) -> None:
        import os

        from click.testing import CliRunner

        from forge.cli.extensions import disable_cmd
        from forge.install.tracking import TrackingStore

        self._enable(available=True)
        claude_settings = Path(os.environ["CLAUDE_HOME"]) / "settings.json"
        settings_before = claude_settings.read_bytes()

        result = CliRunner().invoke(disable_cmd, ["--scope", "user", "--runtime", "codex", "--yes"])

        assert result.exit_code == 0, result.output
        assert "selected codex runtime surfaces" in result.output
        assert "Codex hooks:" in result.output
        assert "Settings:" not in result.output
        assert "one-time interactive trust ceremony" in result.output
        assert "Forge cannot verify trust" in result.output
        assert claude_settings.read_bytes() == settings_before
        assert not self._codex_config().exists()
        surviving = TrackingStore().get_installation("user", None)
        assert surviving is not None
        assert surviving.codex_config_path is None
        assert {owner.runtime for owner in surviving.module_owners} == {"claude_code"}

    def test_status_json_after_partial_runtime_disable_is_coherent(self) -> None:
        import json

        from click.testing import CliRunner

        from forge.cli.extensions import disable_cmd, status_cmd

        self._enable(available=True)
        disabled = CliRunner().invoke(
            disable_cmd,
            ["--scope", "user", "--runtime", "codex", "--yes"],
        )
        assert disabled.exit_code == 0, disabled.output

        result = CliRunner().invoke(status_cmd, ["--scope", "user", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        installation = payload["installations"][0]
        assert installation["managed_runtimes"] == ["claude_code"]
        assert all(owner["runtime"] == "claude_code" for owner in installation["module_owners"])
        assert installation["codex_config_path"] is None
        assert installation["profile"] == "minimal"

    def test_individual_runtime_flags_that_cover_row_prompt_as_full_disable(self) -> None:
        from click.testing import CliRunner

        from forge.cli.extensions import disable_cmd

        self._enable(available=True)
        repeated = CliRunner().invoke(
            disable_cmd,
            ["--scope", "user", "--runtime", "claude", "--runtime", "codex"],
            input="n\n",
        )

        assert repeated.exit_code == 0, repeated.output
        assert "removes the whole Forge installation" in repeated.output
        assert "Proceed with full disable?" in repeated.output

        removed_claude = CliRunner().invoke(
            disable_cmd,
            ["--scope", "user", "--runtime", "claude", "--yes"],
        )
        assert removed_claude.exit_code == 0, removed_claude.output
        last_runtime = CliRunner().invoke(
            disable_cmd,
            ["--scope", "user", "--runtime", "codex"],
            input="n\n",
        )
        assert last_runtime.exit_code == 0, last_runtime.output
        assert "removes the whole Forge installation" in last_runtime.output
        assert "Proceed with full disable?" in last_runtime.output

    def test_explicit_runtime_all_keeps_existing_prompt_and_plan_tables(self) -> None:
        from click.testing import CliRunner

        from forge.cli.extensions import disable_cmd

        self._enable(available=True)
        bare = CliRunner().invoke(disable_cmd, ["--scope", "user"], input="n\n")
        runtime_all = CliRunner().invoke(
            disable_cmd,
            ["--scope", "user", "--runtime", "all"],
            input="n\n",
        )

        assert bare.exit_code == 0, bare.output
        assert runtime_all.exit_code == 0, runtime_all.output
        for expected in ("Will disable Forge extensions (user):", "Settings:", "Codex hooks:", "Proceed with disable?"):
            assert expected in bare.output
            assert expected in runtime_all.output
        assert "Proceed with full disable?" not in runtime_all.output

    def test_runtime_codex_malformed_markers_refuse_before_prompt(self) -> None:
        from unittest.mock import patch

        from click.testing import CliRunner

        from forge.cli.extensions import disable_cmd
        from forge.install.tracking import TrackingStore

        self._enable(available=True)
        config = self._codex_config()
        config.write_text(config.read_text(encoding="utf-8") + "\n# >>> forge hooks >>>\n", encoding="utf-8")
        tracking_before = TrackingStore().path.read_bytes()
        config_before = config.read_bytes()

        with patch("forge.cli.extensions.click.confirm") as confirm:
            result = CliRunner().invoke(disable_cmd, ["--scope", "user", "--runtime", "codex"])

        assert result.exit_code == 1, result.output
        assert str(config) in " ".join(result.output.split())
        assert "partial, duplicated, or unbalanced" in " ".join(result.output.split())
        confirm.assert_not_called()
        assert config.read_bytes() == config_before
        assert TrackingStore().path.read_bytes() == tracking_before

    def test_runtime_tracking_write_fault_names_prior_mutation_and_restored_settings(self) -> None:
        import os
        from unittest.mock import patch

        from click.testing import CliRunner

        from forge.cli.extensions import disable_cmd
        from forge.install.tracking import TrackingStore

        self._enable(available=True)
        tracking = TrackingStore()
        settings_path = Path(os.environ["CLAUDE_HOME"]) / "settings.json"
        settings_before = settings_path.read_bytes()
        tracking_before = tracking.path.read_bytes()

        with patch.object(TrackingStore, "remove_installation", side_effect=OSError("injected tracking fault")):
            result = CliRunner().invoke(
                disable_cmd,
                ["--scope", "user", "--runtime", "all", "--yes"],
            )

        assert result.exit_code == 1, result.output
        normalized = " ".join(result.output.split())
        assert str(tracking.path) in normalized
        assert "already changed the filesystem" in normalized
        assert "settings and ownership sidecars were restored" in normalized
        assert settings_path.read_bytes() == settings_before
        assert tracking.path.read_bytes() == tracking_before
        assert not self._codex_config().exists()

    def test_disable_scope_mismatch_fails_before_plan_and_prompt(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from unittest.mock import patch

        from click.testing import CliRunner

        from forge.cli.extensions import disable_cmd
        from forge.install.tracking import TrackingStore

        original_codex_home = tmp_path / "original_home"
        original_codex_home.mkdir()
        monkeypatch.setenv("CODEX_HOME", str(original_codex_home))
        self._enable(available=True)
        tracked_config = self._codex_config()
        moved_codex_home = tmp_path / "moved_home"
        moved_codex_home.mkdir()
        monkeypatch.setenv("CODEX_HOME", str(moved_codex_home))
        expected_config = moved_codex_home / "config.toml"

        with patch("forge.cli.extensions.click.confirm") as confirm:
            result = CliRunner().invoke(disable_cmd, ["--scope", "user"])

        assert result.exit_code == 1, result.output
        assert "Will disable Forge extensions" not in result.output
        assert "Codex hooks:" not in result.output
        compact_output = "".join(result.output.split())
        assert "".join(str(tracked_config).split()) in compact_output
        assert "".join(str(expected_config).split()) in compact_output
        confirm.assert_not_called()
        assert TrackingStore().get_installation("user", None) is not None
        assert "# >>> forge hooks >>>" in tracked_config.read_text()

    def test_disable_scope_mismatch_with_yes_preserves_tracking_bytes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from click.testing import CliRunner

        from forge.cli.extensions import disable_cmd
        from forge.install.tracking import TrackingStore

        self._enable(available=True)
        tracked_config = self._codex_config()
        tracking = TrackingStore()
        config_before = tracked_config.read_bytes()
        tracking_before = tracking.path.read_bytes()
        moved_codex_home = tmp_path / "moved_codex_home"
        moved_codex_home.mkdir()
        monkeypatch.setenv("CODEX_HOME", str(moved_codex_home))

        result = CliRunner().invoke(disable_cmd, ["--scope", "user", "--yes"])

        assert result.exit_code == 1, result.output
        assert tracked_config.read_bytes() == config_before
        assert tracking.path.read_bytes() == tracking_before
        assert tracking.get_installation("user", None) is not None

    def test_disable_all_aggregates_scope_mismatch_and_disables_other_scope(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from unittest.mock import patch

        from click.testing import CliRunner

        from forge.install.models import Installation
        from forge.install.tracking import TrackingStore

        tracking = TrackingStore()
        tracked_config = tmp_path / "original_codex_home" / "config.toml"
        tracked_config.parent.mkdir()
        tracked_config.write_text("# >>> forge hooks >>>\n# <<< forge hooks <<<\n")
        tracking.set_installation(
            "user",
            Installation(
                scope="user",
                mode="copy",
                profile="standard",
                module_owners=[attributed(InstallModule.HOOKS, "codex")],
                codex_config_path=str(tracked_config),
            ),
            None,
        )

        project = tmp_path / "project"
        (project / ".claude").mkdir(parents=True)
        tracking.set_installation(
            "project",
            Installation(
                scope="project",
                project_path=str(project),
                mode="copy",
                profile="minimal",
            ),
            str(project),
        )
        moved_codex_home = tmp_path / "moved_codex_home"
        moved_codex_home.mkdir()
        monkeypatch.setenv("CODEX_HOME", str(moved_codex_home))

        with patch("forge.cli.extensions._enforce_project_compatibility"):
            result = CliRunner().invoke(extensions, ["disable", "--all", "--yes"])

        assert result.exit_code == 1, result.output
        assert "Completed with 1 error(s)." in result.output
        assert "user (global)" in result.output
        assert "tracked Codex config" in result.output
        assert tracking.get_installation("user", None) is not None
        assert tracking.get_installation("project", str(project)) is None
        assert tracked_config.read_text() == "# >>> forge hooks >>>\n# <<< forge hooks <<<\n"

    def _sync(self, available: bool = True) -> Any:
        from unittest.mock import MagicMock, patch

        from click.testing import CliRunner

        from forge.cli.extensions import sync_cmd

        with (
            patch("forge.install.version.check_minimum_version") as mock_ver,
            patch("forge.install.installer._codex_available", return_value=available),
        ):
            mock_ver.return_value = MagicMock(ok=True)
            return CliRunner().invoke(sync_cmd, ["--scope", "user"])

    def test_sync_restores_block_counts_it_and_prints_ceremony(self) -> None:
        """A codex-only sync change must not render "Already up to date." and
        must print the trust next-steps (an updated block can carry untrusted
        new entries -- per-entry trusted_hash)."""
        self._enable(available=True)
        self._codex_config().unlink()  # block gone; sync should restore it

        result = self._sync(available=True)
        assert result.exit_code == 0, result.output
        assert "Already up to date." not in result.output
        assert "Codex hooks" in result.output  # counted as an action
        assert "Next steps (Codex hooks):" in result.output
        assert "# >>> forge hooks >>>" in self._codex_config().read_text()

    def test_sync_unchanged_block_stays_quiet(self) -> None:
        """No codex change -> no ceremony nag, counts stay honest."""
        self._enable(available=True)
        result = self._sync(available=True)
        assert result.exit_code == 0, result.output
        assert "Already up to date." in result.output
        assert "Next steps (Codex hooks):" not in result.output

    def test_rerun_enable_without_codex_keeps_tracking(self) -> None:
        """CLI-level pin of the preserve fix: enable -> re-enable codex-less."""
        import json

        from click.testing import CliRunner

        from forge.cli.extensions import status_cmd
        from forge.install.tracking import TrackingStore

        self._enable(available=True)
        result = self._enable(available=False)
        assert result.exit_code == 0, result.output
        assert "Codex hooks skipped: codex binary not found on PATH" in result.output
        status = CliRunner().invoke(status_cmd, ["--scope", "user", "--json"])
        data = json.loads(status.output)
        assert data["installations"][0]["codex_config_path"] == str(self._codex_config())
        installation = TrackingStore().get_installation("user")
        assert installation is not None
        assert attributed(InstallModule.HOOKS, "codex") in installation.module_owners

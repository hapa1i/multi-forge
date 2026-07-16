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
from forge.core.paths import find_git_root, get_forge_home
from forge.install.exceptions import NoClaudeDirectoryError
from forge.install.models import InstallScope
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


class TestFindGitRoot:
    """Tests for the shared find_git_root helper."""

    def test_finds_git_in_current_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        assert find_git_root(tmp_path) == tmp_path.resolve()

    def test_finds_git_in_parent(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        child = tmp_path / "src" / "deep"
        child.mkdir(parents=True)
        assert find_git_root(child) == tmp_path.resolve()

    def test_returns_none_outside_git(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "nonexistent")
        assert find_git_root(tmp_path) is None


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
                modules_enabled=[InstallModule.HOOKS.value],
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
                    modules_enabled=[InstallModule.HOOKS.value],
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
                modules_enabled=[InstallModule.HOOKS.value],
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
    ) -> None:
        import json
        import os

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
    """Tests for the codex-hooks module surfaces on enable/status/disable."""

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
                ["--scope", "user", "--profile", "minimal", "--with", "codex-hooks"],
            )

    def test_enable_registers_and_prints_ceremony_next_steps(self) -> None:
        result = self._enable(available=True)
        assert result.exit_code == 0, result.output
        assert "Next steps (Codex hooks):" in result.output
        assert "grant trust" in result.output
        assert "# >>> forge hooks >>>" in self._codex_config().read_text()

    def test_enable_without_codex_binary_skips_visibly(self) -> None:
        result = self._enable(available=False)
        assert result.exit_code == 0, result.output
        assert "Codex hooks skipped: codex binary not found on PATH" in result.output
        assert "Next steps (Codex hooks):" not in result.output
        assert not self._codex_config().exists()

    def test_status_shows_codex_registration(self) -> None:
        from click.testing import CliRunner

        from forge.cli.extensions import status_cmd

        self._enable(available=True)
        result = CliRunner().invoke(status_cmd, ["--scope", "user"])
        assert result.exit_code == 0, result.output
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
        assert data[0]["codex_config_path"] == str(self._codex_config())
        assert [_normalize_forge_home(command) for command in data[0]["codex_commands"]] == [
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
        assert not self._codex_config().exists()

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

        self._enable(available=True)
        result = self._enable(available=False)
        assert result.exit_code == 0, result.output
        status = CliRunner().invoke(status_cmd, ["--scope", "user", "--json"])
        data = json.loads(status.output)
        assert data[0]["codex_config_path"] == str(self._codex_config())

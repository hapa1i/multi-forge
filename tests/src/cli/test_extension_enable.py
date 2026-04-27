"""Tests for extension enable auto-create .claude/ behavior (Rule 4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.cli.extensions import (
    _create_claude_dir,
    _detect_git_project_root,
    _find_git_root,
    _resolve_project_root,
)
from forge.install.exceptions import NoClaudeDirectoryError
from forge.install.models import InstallScope


class TestFindGitRoot:
    """Tests for _find_git_root helper."""

    def test_finds_git_in_current_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        assert _find_git_root(tmp_path) == tmp_path

    def test_finds_git_in_parent(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        child = tmp_path / "src" / "deep"
        child.mkdir(parents=True)
        assert _find_git_root(child) == tmp_path

    def test_returns_none_outside_git(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "nonexistent")
        assert _find_git_root(tmp_path) is None


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
        mock_plan.settings_entries = []

        with (
            patch("forge.cli.extensions.Installer") as MockInstaller,
            patch("forge.install.version.check_minimum_version") as mock_ver,
        ):
            mock_instance = MockInstaller.return_value
            mock_instance.init.return_value = mock_plan
            mock_ver.return_value = MagicMock(ok=True)
            runner = CliRunner()
            result = runner.invoke(enable_cmd, ["--local"])

        assert result.exit_code != 0
        assert not (repo / ".forge").is_dir()

"""Tests for forge.install.installer."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from forge.install.exceptions import (
    NestedClaudeDirectoryError,
    NoClaudeDirectoryError,
    NoForgeInstallationError,
    NotInstalledError,
    PathBoundaryViolationError,
)
from forge.install.installer import (
    Installer,
    find_claude_root,
    find_forge_installation,
    get_extensions_root,
    get_forge_source_root,
    get_target_root,
    resolve_modules,
    validate_path_within_boundary,
)
from forge.install.models import (
    InstallMode,
    InstallModule,
    InstallProfile,
    InstallScope,
)
from forge.install.tracking import TrackingStore


class TestResolveModules:
    """Tests for resolve_modules function."""

    def test_minimal_profile(self) -> None:
        modules = resolve_modules(InstallProfile.MINIMAL)
        assert modules == {InstallModule.COMMANDS}

    def test_standard_profile(self) -> None:
        modules = resolve_modules(InstallProfile.STANDARD)
        assert InstallModule.COMMANDS in modules
        assert InstallModule.AGENTS in modules
        assert InstallModule.HOOKS in modules
        assert InstallModule.PERMISSIONS in modules
        assert InstallModule.STATUSLINE in modules

    def test_full_profile(self) -> None:
        modules = resolve_modules(InstallProfile.FULL)
        assert modules == set(InstallModule)

    def test_with_modules_adds(self) -> None:
        modules = resolve_modules(InstallProfile.MINIMAL, with_modules={InstallModule.STATUSLINE})
        assert InstallModule.COMMANDS in modules
        assert InstallModule.STATUSLINE in modules

    def test_without_modules_removes(self) -> None:
        modules = resolve_modules(InstallProfile.STANDARD, without_modules={InstallModule.AGENTS})
        assert InstallModule.AGENTS not in modules
        assert InstallModule.COMMANDS in modules

    def test_hooks_does_not_force_permissions(self) -> None:
        modules = resolve_modules(InstallProfile.MINIMAL, with_modules={InstallModule.HOOKS})
        assert InstallModule.HOOKS in modules
        assert InstallModule.PERMISSIONS not in modules


class TestGetTargetRoot:
    """Tests for get_target_root function."""

    def test_user_scope(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Should respect CLAUDE_HOME env var (isolation fixture sets it)."""
        # The isolate_claude_home fixture sets CLAUDE_HOME to tmp_path/claude_home
        target = get_target_root(InstallScope.USER)
        # Should be the isolated path, not the real ~/.claude
        assert target.name == "claude_home" or str(target).startswith(str(tmp_path))

    def test_project_scope(self, tmp_path: Path) -> None:
        target = get_target_root(InstallScope.PROJECT, project_root=tmp_path)
        assert target == tmp_path / ".claude"

    def test_local_scope(self, tmp_path: Path) -> None:
        target = get_target_root(InstallScope.LOCAL, project_root=tmp_path)
        assert target == tmp_path / ".claude"

    def test_project_requires_root(self) -> None:
        with pytest.raises(ValueError, match="project_root required"):
            get_target_root(InstallScope.PROJECT)

    def test_rejects_nested_claude_directory(self, tmp_path: Path) -> None:
        """Guard against running from inside a .claude directory."""
        nested_claude = tmp_path / "project" / ".claude"
        nested_claude.mkdir(parents=True)

        with pytest.raises(NestedClaudeDirectoryError) as exc_info:
            get_target_root(InstallScope.PROJECT, project_root=nested_claude)

        assert ".claude" in str(exc_info.value)
        assert "nested" in str(exc_info.value).lower()

    def test_rejects_deeply_nested_claude_directory(self, tmp_path: Path) -> None:
        """Guard against running from subdirectory of .claude."""
        nested_claude = tmp_path / "project" / ".claude" / "commands"
        nested_claude.mkdir(parents=True)

        with pytest.raises(NestedClaudeDirectoryError):
            get_target_root(InstallScope.PROJECT, project_root=nested_claude)

    def test_allows_normal_project_root(self, tmp_path: Path) -> None:
        """Normal project roots (not inside .claude) should work."""
        project = tmp_path / "my-project"
        project.mkdir()

        # Should not raise
        target = get_target_root(InstallScope.PROJECT, project_root=project)
        assert target == project / ".claude"


class TestGetForgeSourceRoot:
    """Tests for get_forge_source_root function."""

    def test_returns_path(self) -> None:
        root = get_forge_source_root()
        assert isinstance(root, Path)
        # Should contain src/ directory
        assert (root / "src").is_dir() or not root.exists()


class TestIsRepoCheckout:
    """Tests for the strengthened repo-detection heuristic."""

    def test_repo_with_skills(self, tmp_path: Path) -> None:
        from forge.install.installer import _is_repo_checkout

        (tmp_path / "src" / "forge").mkdir(parents=True)
        (tmp_path / "src" / "skills").mkdir()
        assert _is_repo_checkout(tmp_path) is True

    def test_repo_with_agents(self, tmp_path: Path) -> None:
        from forge.install.installer import _is_repo_checkout

        (tmp_path / "src" / "forge").mkdir(parents=True)
        (tmp_path / "src" / "agents").mkdir()
        assert _is_repo_checkout(tmp_path) is True

    def test_rejects_user_project_with_only_skills(self, tmp_path: Path) -> None:
        """A user project with src/skills but no src/forge is NOT a Forge checkout."""
        from forge.install.installer import _is_repo_checkout

        (tmp_path / "src" / "skills").mkdir(parents=True)
        assert _is_repo_checkout(tmp_path) is False

    def test_rejects_forge_only_no_extensions(self, tmp_path: Path) -> None:
        """src/forge without any extension dir doesn't count (incomplete checkout)."""
        from forge.install.installer import _is_repo_checkout

        (tmp_path / "src" / "forge").mkdir(parents=True)
        assert _is_repo_checkout(tmp_path) is False

    def test_rejects_empty_dir(self, tmp_path: Path) -> None:
        from forge.install.installer import _is_repo_checkout

        assert _is_repo_checkout(tmp_path) is False


class TestGetExtensionsRoot:
    """Tests for get_extensions_root with repo vs bundled fallback."""

    def test_prefers_repo_checkout(self) -> None:
        root = get_extensions_root()
        assert (root / "skills").is_dir()

    def test_falls_back_to_bundled(self, tmp_path: Path) -> None:
        """When repo src/skills doesn't exist, return the bundled location."""
        bundled = tmp_path / "_extensions"
        (bundled / "skills").mkdir(parents=True)
        (bundled / "agents").mkdir()
        (bundled / "commands").mkdir()

        with patch(
            "forge.install.installer.get_forge_source_root",
            return_value=tmp_path / "no-repo",
        ):
            with patch(
                "forge.install.installer._get_bundled_extensions_path",
                return_value=bundled,
            ):
                result = get_extensions_root()

        assert result == bundled
        assert (result / "skills").is_dir()

    def test_raises_when_neither_exists(self, tmp_path: Path) -> None:
        """Both repo and bundled missing → clear error."""
        with patch(
            "forge.install.installer.get_forge_source_root",
            return_value=tmp_path / "no-repo",
        ):
            with patch(
                "forge.install.installer._get_bundled_extensions_path",
                return_value=tmp_path / "no-bundled",
            ):
                with pytest.raises(FileNotFoundError, match="Extension source files not found"):
                    get_extensions_root()


class TestInstallerPlan:
    """Tests for Installer.plan method."""

    @pytest.fixture
    def installer(self, tmp_path: Path, temp_forge_home: Path, temp_source_dir: Path) -> Installer:
        """Create installer with temp directories."""
        tracking = TrackingStore(tracking_path=temp_forge_home / "installed.json")
        installer = Installer(
            scope=InstallScope.USER,
            tracking_store=tracking,
        )
        return installer

    def test_plan_returns_install_plan(self, installer: Installer) -> None:
        plan = installer.plan()

        assert plan.scope == "user"
        assert plan.mode == "copy"
        assert plan.profile == "standard"
        assert len(plan.modules) > 0

    def test_plan_modules_are_sorted(self, installer: Installer) -> None:
        plan = installer.plan()

        # Modules should be alphabetically sorted
        assert plan.modules == sorted(plan.modules)

    def test_plan_files_are_sorted(self, installer: Installer) -> None:
        plan = installer.plan()

        # Files should be sorted by target path
        target_paths = [f.target_path for f in plan.files]
        assert target_paths == sorted(target_paths)

    def test_plan_dry_run_makes_no_changes(self, installer: Installer, temp_forge_home: Path) -> None:
        installer.plan()

        # No tracking file should be created
        assert not (temp_forge_home / "installed.json").exists()


class TestInstallerInit:
    """Tests for Installer.init method."""

    @pytest.fixture
    def setup_installer(self, tmp_path: Path) -> Generator[tuple[Installer, Path, Path, Path], None, None]:
        """Set up installer with all temp directories."""
        forge_home = tmp_path / ".forge"
        forge_home.mkdir()

        claude_home = tmp_path / ".claude"
        claude_home.mkdir()

        # Create source directory with files
        src = tmp_path / "src"
        src.mkdir()
        commands = src / "commands"
        commands.mkdir()
        (commands / "test.md").write_text("# Test Command\n")
        (src / "skills").mkdir()
        (src / "forge").mkdir()  # _is_repo_checkout requires src/forge + extension dir

        tracking = TrackingStore(tracking_path=forge_home / "installed.json")

        # Patch get_forge_source_root to return our temp directory.
        # The preset auto-creates at $FORGE_HOME/claude.preset.json (built-in defaults).
        with patch(
            "forge.install.installer.get_forge_source_root",
            return_value=tmp_path,
        ):
            with patch(
                "forge.install.installer.get_target_root",
                return_value=claude_home,
            ):
                installer = Installer(
                    scope=InstallScope.USER,
                    tracking_store=tracking,
                )
                yield installer, forge_home, claude_home, src

    def test_init_creates_tracking_file(self, setup_installer: tuple[Installer, Path, Path, Path]) -> None:
        installer, forge_home, claude_home, src = setup_installer

        with patch(
            "forge.install.installer.get_forge_source_root",
            return_value=src.parent,
        ):
            with patch(
                "forge.install.installer.get_target_root",
                return_value=claude_home,
            ):
                installer.init(profile=InstallProfile.MINIMAL)

        assert (forge_home / "installed.json").exists()

    def test_init_installs_files(self, setup_installer: tuple[Installer, Path, Path, Path]) -> None:
        installer, forge_home, claude_home, src = setup_installer

        with patch(
            "forge.install.installer.get_forge_source_root",
            return_value=src.parent,
        ):
            with patch(
                "forge.install.installer.get_target_root",
                return_value=claude_home,
            ):
                installer.init(profile=InstallProfile.MINIMAL)

        assert (claude_home / "commands" / "test.md").exists()

    def test_init_is_idempotent(self, setup_installer: tuple[Installer, Path, Path, Path]) -> None:
        installer, forge_home, claude_home, src = setup_installer

        with patch(
            "forge.install.installer.get_forge_source_root",
            return_value=src.parent,
        ):
            with patch(
                "forge.install.installer.get_target_root",
                return_value=claude_home,
            ):
                installer.init(profile=InstallProfile.MINIMAL)
                plan2 = installer.init(profile=InstallProfile.MINIMAL)

        # Second run should have "skip" actions for unchanged files
        skip_count = sum(1 for f in plan2.files if f.action == "skip")
        install_count = sum(1 for f in plan2.files if f.action == "install")

        # At least the original file should be skipped (unchanged)
        assert skip_count > 0 or install_count == 0

    def test_init_backfills_permissions_into_settings_from_upgraded_preset(
        self,
        setup_installer: tuple[Installer, Path, Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Installer writes Write/Edit into settings.json for upgraded preset files."""
        import json

        from forge.install.preset import ensure_preset, get_preset_path

        installer, forge_home, claude_home, src = setup_installer

        monkeypatch.setenv("FORGE_HOME", str(forge_home))
        monkeypatch.setenv("CLAUDE_HOME", str(claude_home))

        ensure_preset()
        get_preset_path().write_text(
            json.dumps(
                {
                    "permissions": {"allow": ["Bash(npm test)"]},
                    "hooks": {},
                }
            )
        )

        with patch(
            "forge.install.installer.get_forge_source_root",
            return_value=src.parent,
        ):
            with patch(
                "forge.install.installer.get_target_root",
                return_value=claude_home,
            ):
                installer.init(profile=InstallProfile.STANDARD)

        settings = json.loads((claude_home / "settings.json").read_text())
        allow = settings["permissions"]["allow"]
        assert "Bash(npm test)" in allow
        assert "Write" in allow
        assert "Edit" in allow


class TestInstallerUpdate:
    """Tests for Installer.update method."""

    def test_update_raises_when_not_installed(self, temp_forge_home: Path) -> None:
        tracking = TrackingStore(tracking_path=temp_forge_home / "installed.json")
        installer = Installer(
            scope=InstallScope.USER,
            tracking_store=tracking,
        )

        with pytest.raises(NotInstalledError) as exc_info:
            installer.update()

        assert exc_info.value.scope == "user"


class TestInstallerUninstall:
    """Tests for Installer.uninstall method."""

    def test_uninstall_raises_when_not_installed(self, temp_forge_home: Path) -> None:
        tracking = TrackingStore(tracking_path=temp_forge_home / "installed.json")
        installer = Installer(
            scope=InstallScope.USER,
            tracking_store=tracking,
        )

        with pytest.raises(NotInstalledError) as exc_info:
            installer.uninstall()

        assert exc_info.value.scope == "user"


class TestInstallerSymlinkMode:
    """Tests for symlink installation mode."""

    @pytest.fixture
    def setup_symlink_installer(self, tmp_path: Path) -> tuple[Installer, Path, Path, Path]:
        """Set up installer for symlink mode testing."""
        forge_home = tmp_path / ".forge"
        forge_home.mkdir()

        claude_home = tmp_path / ".claude"
        claude_home.mkdir()

        src = tmp_path / "src"
        src.mkdir()
        commands = src / "commands"
        commands.mkdir()
        (commands / "test.md").write_text("# Test\n")
        (src / "skills").mkdir()
        (src / "forge").mkdir()  # _is_repo_checkout requires src/forge + extension dir

        tracking = TrackingStore(tracking_path=forge_home / "installed.json")
        installer = Installer(
            scope=InstallScope.USER,
            tracking_store=tracking,
        )

        return installer, forge_home, claude_home, src

    def test_symlink_mode_creates_symlinks(self, setup_symlink_installer: tuple[Installer, Path, Path, Path]) -> None:
        installer, forge_home, claude_home, src = setup_symlink_installer

        with patch(
            "forge.install.installer.get_forge_source_root",
            return_value=src.parent,
        ):
            with patch(
                "forge.install.installer.get_target_root",
                return_value=claude_home,
            ):
                installer.init(
                    profile=InstallProfile.MINIMAL,
                    mode=InstallMode.SYMLINK,
                )

        target = claude_home / "commands" / "test.md"
        assert target.is_symlink()
        assert target.resolve() == (src / "commands" / "test.md").resolve()


class TestFindClaudeRoot:
    """Tests for find_claude_root function."""

    def test_finds_claude_in_current_dir(self, tmp_path: Path) -> None:
        """Should find .claude in the starting directory."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        scope, project_root = find_claude_root(start=tmp_path)

        assert scope == InstallScope.LOCAL
        assert project_root == tmp_path

    def test_finds_claude_in_parent_dir(self, tmp_path: Path) -> None:
        """Should walk up to find .claude in parent."""
        project = tmp_path / "project"
        subdir = project / "src" / "module"
        subdir.mkdir(parents=True)
        (project / ".claude").mkdir()

        scope, project_root = find_claude_root(start=subdir)

        assert scope == InstallScope.LOCAL
        assert project_root == project

    def test_returns_user_scope_at_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return USER scope when reaching home directory."""
        # Create a fake home directory with .claude
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        (fake_home / ".claude").mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        scope, project_root = find_claude_root(start=fake_home)

        assert scope == InstallScope.USER
        assert project_root is None

    def test_returns_user_when_no_claude_found_but_reaches_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should return USER scope when walking up reaches home without finding .claude."""
        # Create a fake home directory (no .claude)
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Start from home itself
        scope, project_root = find_claude_root(start=fake_home)

        assert scope == InstallScope.USER
        assert project_root is None

    def test_raises_when_no_claude_and_not_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should raise NoClaudeDirectoryError when no .claude found and not at home."""
        # Create a fake home that's different from tmp_path
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Create a separate directory tree without .claude
        other_dir = tmp_path / "other" / "deep" / "path"
        other_dir.mkdir(parents=True)

        with pytest.raises(NoClaudeDirectoryError) as exc_info:
            find_claude_root(start=other_dir)

        assert "other/deep/path" in str(exc_info.value) or "other" in str(exc_info.value)

    def test_finds_first_claude_going_up(self, tmp_path: Path) -> None:
        """Should find the nearest .claude, not a higher one."""
        # Create nested projects, each with .claude
        outer = tmp_path / "outer"
        inner = outer / "inner"
        (outer / ".claude").mkdir(parents=True)
        (inner / ".claude").mkdir(parents=True)
        deepest = inner / "src"
        deepest.mkdir()

        scope, project_root = find_claude_root(start=deepest)

        # Should find inner's .claude first
        assert scope == InstallScope.LOCAL
        assert project_root == inner


class TestFindForgeInstallation:
    """Tests for find_forge_installation function."""

    def test_finds_local_installation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should detect LOCAL installation via .forge-added file."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        project = tmp_path / "project"
        claude_dir = project / ".claude"
        claude_dir.mkdir(parents=True)
        # Create evidence of LOCAL installation
        (claude_dir / ".settings.local.json.forge.added.20250101-120000").write_text("{}")

        scope, project_root = find_forge_installation(start=project)

        assert scope == InstallScope.LOCAL
        assert project_root == project

    def test_finds_local_via_backup_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should detect LOCAL installation via .forge-backup file."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        project = tmp_path / "project"
        claude_dir = project / ".claude"
        claude_dir.mkdir(parents=True)
        # Create evidence of LOCAL installation (backup only)
        (claude_dir / ".settings.local.json.forge.backup.20250101-120000").write_text("{}")

        scope, project_root = find_forge_installation(start=project)

        assert scope == InstallScope.LOCAL
        assert project_root == project

    def test_finds_project_installation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should detect PROJECT installation via .forge-added file."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        project = tmp_path / "project"
        claude_dir = project / ".claude"
        claude_dir.mkdir(parents=True)
        # Create evidence of PROJECT installation
        (claude_dir / ".settings.json.forge.added.20250101-120000").write_text("{}")

        scope, project_root = find_forge_installation(start=project)

        assert scope == InstallScope.PROJECT
        assert project_root == project

    def test_prefers_local_over_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should prefer LOCAL over PROJECT when both exist."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        project = tmp_path / "project"
        claude_dir = project / ".claude"
        claude_dir.mkdir(parents=True)
        # Both LOCAL and PROJECT have evidence
        (claude_dir / ".settings.local.json.forge.added.20250101-120000").write_text("{}")
        (claude_dir / ".settings.json.forge.added.20250101-120000").write_text("{}")

        scope, project_root = find_forge_installation(start=project)

        assert scope == InstallScope.LOCAL

    def test_finds_user_installation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should detect USER installation at home directory."""
        fake_home = tmp_path / "home"
        claude_home = fake_home / ".claude"
        claude_home.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Create evidence of USER installation
        (claude_home / ".settings.json.forge.added.20250101-120000").write_text("{}")

        # Start from somewhere else (subdir of home)
        start_dir = fake_home / "projects" / "myapp"
        start_dir.mkdir(parents=True)

        scope, project_root = find_forge_installation(start=start_dir)

        assert scope == InstallScope.USER
        assert project_root is None

    def test_walks_up_to_find_installation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should walk up directory tree to find installation."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        project = tmp_path / "project"
        claude_dir = project / ".claude"
        claude_dir.mkdir(parents=True)
        (claude_dir / ".settings.local.json.forge.added.20250101-120000").write_text("{}")

        # Start from deep subdirectory
        deep = project / "src" / "lib" / "utils"
        deep.mkdir(parents=True)

        scope, project_root = find_forge_installation(start=deep)

        assert scope == InstallScope.LOCAL
        assert project_root == project

    def test_raises_when_no_installation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should raise NoForgeInstallationError when nothing found."""
        fake_home = tmp_path / "home"
        claude_home = fake_home / ".claude"
        claude_home.mkdir(parents=True)  # .claude exists but no forge files
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        start_dir = fake_home / "projects"
        start_dir.mkdir()

        with pytest.raises(NoForgeInstallationError) as exc_info:
            find_forge_installation(start=start_dir)

        assert "projects" in str(exc_info.value)
        assert "forge extension enable" in str(exc_info.value)
        assert "forge init" not in str(exc_info.value)

    def test_skips_project_at_home_level(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should not detect PROJECT scope at home directory (only USER)."""
        fake_home = tmp_path / "home"
        claude_home = fake_home / ".claude"
        claude_home.mkdir(parents=True)
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Create .settings.json.forge.added.20250101-120000 at home level
        # This should be treated as USER, not PROJECT
        (claude_home / ".settings.json.forge.added.20250101-120000").write_text("{}")

        scope, project_root = find_forge_installation(start=fake_home)

        assert scope == InstallScope.USER
        assert project_root is None

    def test_finds_installation_in_parent_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should find installation in parent project when nested."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Parent project with installation
        parent_project = tmp_path / "parent"
        (parent_project / ".claude").mkdir(parents=True)
        (parent_project / ".claude" / ".settings.local.json.forge.added.20250101-120000").write_text("{}")

        # Child directory without installation
        child = parent_project / "packages" / "child"
        (child / ".claude").mkdir(parents=True)  # Has .claude but no forge files

        scope, project_root = find_forge_installation(start=child)

        assert scope == InstallScope.LOCAL
        assert project_root == parent_project


class TestValidatePathWithinBoundary:
    """Tests for validate_path_within_boundary security function."""

    def test_accepts_path_within_boundary(self, tmp_path: Path) -> None:
        """Valid path within boundary should not raise."""
        boundary = tmp_path / ".claude"
        boundary.mkdir()
        target = boundary / "commands" / "test.md"

        # Should not raise
        validate_path_within_boundary(target, boundary)

    def test_accepts_nested_path(self, tmp_path: Path) -> None:
        """Deeply nested path should be accepted."""
        boundary = tmp_path / ".claude"
        boundary.mkdir()
        target = boundary / "a" / "b" / "c" / "d" / "file.txt"

        # Should not raise
        validate_path_within_boundary(target, boundary)

    def test_rejects_path_outside_boundary(self, tmp_path: Path) -> None:
        """Path outside boundary should raise PathBoundaryViolationError."""
        boundary = tmp_path / ".claude"
        boundary.mkdir()
        target = tmp_path / "other" / "malicious.txt"

        with pytest.raises(PathBoundaryViolationError) as exc_info:
            validate_path_within_boundary(target, boundary, "delete")

        assert "security violation" in str(exc_info.value)
        assert "delete" in str(exc_info.value)

    def test_rejects_system_path(self, tmp_path: Path) -> None:
        """System paths like /etc should be rejected."""
        boundary = tmp_path / ".claude"
        boundary.mkdir()
        target = Path("/etc/passwd")

        with pytest.raises(PathBoundaryViolationError):
            validate_path_within_boundary(target, boundary)

    def test_rejects_parent_traversal(self, tmp_path: Path) -> None:
        """Path with .. traversal escaping boundary should be rejected."""
        boundary = tmp_path / ".claude"
        boundary.mkdir()
        # Try to escape using .. traversal
        target = boundary / ".." / "escaped.txt"

        with pytest.raises(PathBoundaryViolationError):
            validate_path_within_boundary(target, boundary)

    def test_handles_symlinks_inside_boundary(self, tmp_path: Path) -> None:
        """Symlinks inside boundary should be accepted, regardless of target.

        We care about the symlink's LOCATION (what we're deleting), not where it
        points to. This allows uninstall to remove symlinks that point to the
        Forge repo (outside .claude/).
        """
        boundary = tmp_path / ".claude"
        boundary.mkdir()

        # Create a file outside boundary
        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("outside")

        # Create symlink inside boundary pointing outside
        symlink = boundary / "sneaky_link"
        symlink.symlink_to(outside_file)

        # Should ACCEPT because the symlink itself is inside boundary
        # (we're deleting the symlink, not following it to the target)
        validate_path_within_boundary(symlink, boundary)  # Should not raise

    def test_rejects_symlinks_outside_boundary(self, tmp_path: Path) -> None:
        """Symlinks outside boundary should be rejected, even if target is inside."""
        boundary = tmp_path / ".claude"
        boundary.mkdir()

        # Create a file inside boundary
        inside_file = boundary / "inside.txt"
        inside_file.write_text("inside")

        # Create symlink outside boundary pointing inside
        symlink = tmp_path / "outside_link"
        symlink.symlink_to(inside_file)

        # Should reject because the symlink itself is outside boundary
        with pytest.raises(PathBoundaryViolationError):
            validate_path_within_boundary(symlink, boundary)

    def test_error_includes_operation(self, tmp_path: Path) -> None:
        """Error message should include the operation description."""
        boundary = tmp_path / ".claude"
        boundary.mkdir()
        target = Path("/some/other/path")

        with pytest.raises(PathBoundaryViolationError) as exc_info:
            validate_path_within_boundary(target, boundary, "remove backup file")

        assert "remove backup file" in str(exc_info.value)


class TestInstallerCodexHooks:
    """Tests for the codex-hooks module wiring (plan/init/uninstall/update)."""

    @pytest.fixture
    def setup_installer(self, tmp_path: Path) -> Generator[tuple[Installer, Path, Path, Path], None, None]:
        """Installer with temp dirs; codex config lands in the isolated CODEX_HOME."""
        forge_home = tmp_path / ".forge"
        forge_home.mkdir()
        # Must match the autouse isolate_claude_home target: uninstall's
        # path-boundary check validates settings paths against this root.
        claude_home = tmp_path / "claude_home"

        src = tmp_path / "src"
        src.mkdir()
        commands = src / "commands"
        commands.mkdir()
        (commands / "test.md").write_text("# Test Command\n")
        (src / "skills").mkdir()
        (src / "forge").mkdir()  # _is_repo_checkout requires src/forge + extension dir

        tracking = TrackingStore(tracking_path=forge_home / "installed.json")
        installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
        yield installer, forge_home, claude_home, src

    def _run(
        self,
        installer: Installer,
        src: Path,
        claude_home: Path,
        method: str = "init",
        available: bool = True,
        **kwargs: Any,
    ) -> Any:
        with patch("forge.install.installer.get_forge_source_root", return_value=src.parent):
            with patch("forge.install.installer.get_target_root", return_value=claude_home):
                with patch("forge.install.installer._codex_available", return_value=available):
                    return getattr(installer, method)(**kwargs)

    @staticmethod
    def _codex_config(monkeypatch_free_env: None = None) -> Path:
        import os

        return Path(os.environ["CODEX_HOME"]) / "config.toml"

    def test_plan_standard_includes_codex_install(self, setup_installer: tuple[Installer, Path, Path, Path]) -> None:
        installer, _, claude_home, src = setup_installer
        plan = self._run(installer, src, claude_home, method="plan")
        assert plan.codex is not None
        assert plan.codex.action == "install"
        assert plan.codex.config_path == str(self._codex_config())
        assert plan.codex.commands == [
            "forge hook codex-session-start",
            "forge hook codex-policy-check",
        ]

    def test_plan_minimal_has_no_codex(self, setup_installer: tuple[Installer, Path, Path, Path]) -> None:
        installer, _, claude_home, src = setup_installer
        plan = self._run(installer, src, claude_home, method="plan", profile=InstallProfile.MINIMAL)
        assert plan.codex is None

    def test_plan_without_codex_binary_is_unavailable(
        self, setup_installer: tuple[Installer, Path, Path, Path]
    ) -> None:
        installer, _, claude_home, src = setup_installer
        plan = self._run(installer, src, claude_home, method="plan", available=False)
        assert plan.codex.action == "unavailable"
        assert "not found on PATH" in plan.codex.reason
        assert not plan.has_conflicts

    def test_codex_conflict_never_blocks_the_install(self, setup_installer: tuple[Installer, Path, Path, Path]) -> None:
        installer, forge_home, claude_home, src = setup_installer
        config = self._codex_config()
        config.write_text("not = valid = toml\n")
        plan = self._run(installer, src, claude_home)
        assert plan.codex.action == "conflict"
        assert not plan.has_conflicts
        # The Claude install completed despite the codex conflict.
        assert (claude_home / "commands" / "test.md").exists()
        assert config.read_text() == "not = valid = toml\n"
        installation = installer._tracking.get_installation("user", None)
        assert installation is not None and installation.codex_config_path is None

    def test_init_writes_block_and_tracks(self, setup_installer: tuple[Installer, Path, Path, Path]) -> None:
        installer, forge_home, claude_home, src = setup_installer
        self._run(installer, src, claude_home)
        config = self._codex_config()
        text = config.read_text()
        assert "# >>> forge hooks >>>" in text
        installation = installer._tracking.get_installation("user", None)
        assert installation is not None
        assert installation.codex_config_path == str(config)
        assert installation.codex_commands == [
            "forge hook codex-policy-check",
            "forge hook codex-session-start",
        ]

    def test_init_is_idempotent(self, setup_installer: tuple[Installer, Path, Path, Path]) -> None:
        installer, _, claude_home, src = setup_installer
        self._run(installer, src, claude_home)
        before = self._codex_config().read_text()
        self._run(installer, src, claude_home)
        assert self._codex_config().read_text() == before
        assert before.count("# >>> forge hooks >>>") == 1

    def test_update_preserves_block_bytes(self, setup_installer: tuple[Installer, Path, Path, Path]) -> None:
        """Trust stability: sync must not change the registered definitions."""
        installer, _, claude_home, src = setup_installer
        self._run(installer, src, claude_home)
        before = self._codex_config().read_text()
        self._run(installer, src, claude_home, method="update")
        assert self._codex_config().read_text() == before

    def test_uninstall_removes_block_and_forge_created_file(
        self, setup_installer: tuple[Installer, Path, Path, Path]
    ) -> None:
        installer, _, claude_home, src = setup_installer
        self._run(installer, src, claude_home)
        assert self._codex_config().is_file()
        self._run(installer, src, claude_home, method="uninstall")
        assert not self._codex_config().exists()

    def test_uninstall_preserves_user_content(self, setup_installer: tuple[Installer, Path, Path, Path]) -> None:
        installer, _, claude_home, src = setup_installer
        config = self._codex_config()
        config.write_text('model = "gpt-5.5-codex"\n')
        self._run(installer, src, claude_home)
        self._run(installer, src, claude_home, method="uninstall")
        assert config.read_text() == 'model = "gpt-5.5-codex"\n'

    def test_uninstall_refuses_mismatched_tracked_path(
        self, setup_installer: tuple[Installer, Path, Path, Path], tmp_path: Path
    ) -> None:
        """A tampered tracking path (or changed CODEX_HOME) is never edited."""
        installer, _, claude_home, src = setup_installer
        self._run(installer, src, claude_home)
        victim = tmp_path / "victim.toml"
        victim.write_text("# >>> forge hooks >>>\n# <<< forge hooks <<<\n")
        installation = installer._tracking.get_installation("user", None)
        assert installation is not None
        installation.codex_config_path = str(victim)
        installer._tracking.set_installation("user", installation, None)
        self._run(installer, src, claude_home, method="uninstall")
        assert victim.read_text() == "# >>> forge hooks >>>\n# <<< forge hooks <<<\n"

    def test_module_dropped_preserves_tracking(self, setup_installer: tuple[Installer, Path, Path, Path]) -> None:
        """Re-enabling without codex-hooks keeps tracking so disable still cleans up."""
        installer, _, claude_home, src = setup_installer
        self._run(installer, src, claude_home)
        self._run(installer, src, claude_home, profile=InstallProfile.MINIMAL)
        installation = installer._tracking.get_installation("user", None)
        assert installation is not None
        assert installation.codex_config_path == str(self._codex_config())

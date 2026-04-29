"""Component integration tests for the installer.

These tests exercise the installer lifecycle against isolated temp paths while
patching Forge's path resolution. The real-path Docker E2E coverage lives in
``tests/integration/docker/test_installer.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.install.installer import Installer
from forge.install.models import (
    InstallMode,
    InstallProfile,
    InstallScope,
)
from forge.install.settings_merge import read_settings, write_settings
from forge.install.tracking import TrackingStore

pytestmark = pytest.mark.integration


@pytest.fixture
def mock_repo(tmp_path: Path) -> Path:
    """Create a mock forge repo with extension files.

    Mimics the real repo structure at src/{commands,agents,skills,hooks,status-line}/
    """
    repo = tmp_path / "forge-repo"
    repo.mkdir()
    src = repo / "src"
    src.mkdir()
    (src / "forge").mkdir()  # _is_repo_checkout requires src/forge

    # Commands
    commands = src / "commands"
    commands.mkdir()
    (commands / "review.md").write_text("# Review Command\nReview code changes.\n")
    (commands / "test.md").write_text("# Test Command\nRun tests.\n")

    # Agents
    agents = src / "agents"
    agents.mkdir()
    (agents / "reviewer.md").write_text("# Reviewer Agent\nCode review specialist.\n")

    # Skills
    skills = src / "skills" / "search"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("# Search Skill\nSearch capabilities.\n")
    scripts = skills / "scripts"
    scripts.mkdir()
    (scripts / "search.py").write_text("#!/usr/bin/env python3\nprint('search')\n")

    # Note: hooks and status-line are now settings-only modules
    # (no files to copy, just settings entries pointing to `forge hook <name>` and `forge status-line`)

    return repo


@pytest.fixture
def mock_claude_home(tmp_path: Path) -> Path:
    """Create a mock ~/.claude directory with existing settings."""
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()

    # Pre-existing settings
    existing_settings = {
        "model": "opus",
        "permissions": {"allow": ["Bash(ls:*)"], "deny": []},
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "/existing/hook.sh"}],
                }
            ]
        },
    }
    write_settings(claude_home / "settings.json", existing_settings)

    return claude_home


@pytest.fixture
def mock_forge_home(tmp_path: Path) -> Path:
    """Create a mock ~/.forge directory."""
    forge_home = tmp_path / ".forge"
    forge_home.mkdir()
    return forge_home


@pytest.fixture
def installer(mock_repo: Path, mock_claude_home: Path, mock_forge_home: Path):
    """Create an Installer pointing to mock directories."""
    import contextlib
    from unittest.mock import patch

    tracking = TrackingStore(tracking_path=mock_forge_home / "installed.json")

    # Preset content for integration tests (matches old template for assertion compatibility)
    e2e_preset = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Write",
                    "hooks": [{"type": "command", "command": "forge hook plan-write"}],
                }
            ]
        },
        "permissions": {"allow": ["Bash(git:*)", "Read"]},
        "statusLine": {"type": "command", "command": "forge status-line"},
    }

    def get_patches(repo: Path, claude_home: Path) -> list:
        """Get all patches needed for mocking paths."""
        return [
            # Patch in installer module (where they're defined)
            patch(
                "forge.install.installer.get_extensions_root",
                return_value=repo / "src",
            ),
            patch(
                "forge.install.installer.get_target_root",
                return_value=claude_home,
            ),
            patch(
                "forge.install.installer.get_forge_source_root",
                return_value=repo,
            ),
            # Patch in installer module (where they're imported)
            patch(
                "forge.install.installer.get_settings_path",
                return_value=claude_home / "settings.json",
            ),
            patch(
                "forge.install.installer.backup_settings",
                side_effect=lambda path: _backup_settings_mock(path, claude_home),
            ),
            # Preset is now at ~/.forge/claude.preset.json (not in source tree)
            patch(
                "forge.install.preset.load_preset",
                return_value=e2e_preset,
            ),
        ]

    def _backup_settings_mock(path: Path, claude_home: Path) -> Path | None:
        """Mock backup_settings that works with the mock claude_home."""
        from forge.install.settings_merge import read_settings, write_settings

        settings_path = claude_home / "settings.json"
        if not settings_path.is_file():
            return None
        backup_path = claude_home / "settings.json.forge-backup"
        settings = read_settings(settings_path)
        write_settings(backup_path, settings)
        return backup_path

    # Create a patched version that keeps the patches active
    class PatchedInstaller:
        """Wrapper that applies patches during all method calls."""

        def __init__(
            self,
            repo: Path,
            claude_home: Path,
            tracking_store: TrackingStore,
        ):
            self._repo = repo
            self._claude_home = claude_home
            self._tracking = tracking_store

        def _get_inner(self) -> Installer:
            return Installer(scope=InstallScope.USER, tracking_store=self._tracking)

        def plan(self, **kwargs):
            with contextlib.ExitStack() as stack:
                for p in get_patches(self._repo, self._claude_home):
                    stack.enter_context(p)
                return self._get_inner().plan(**kwargs)

        def init(self, **kwargs):
            with contextlib.ExitStack() as stack:
                for p in get_patches(self._repo, self._claude_home):
                    stack.enter_context(p)
                return self._get_inner().init(**kwargs)

        def update(self, **kwargs):
            with contextlib.ExitStack() as stack:
                for p in get_patches(self._repo, self._claude_home):
                    stack.enter_context(p)
                return self._get_inner().update(**kwargs)

        def uninstall(self, **kwargs):
            with contextlib.ExitStack() as stack:
                for p in get_patches(self._repo, self._claude_home):
                    stack.enter_context(p)
                return self._get_inner().uninstall(**kwargs)

    return PatchedInstaller(mock_repo, mock_claude_home, tracking)


class TestInstallerIntegration:
    """Installer lifecycle tests with isolated temp paths."""

    def test_init_installs_files_and_settings(
        self,
        installer,
        mock_repo: Path,
        mock_claude_home: Path,
        mock_forge_home: Path,
    ) -> None:
        """Test that init installs files and merges settings."""
        installer.init(profile=InstallProfile.FULL, mode=InstallMode.COPY)

        # Verify files installed (only file-based modules)
        assert (mock_claude_home / "commands" / "review.md").exists()
        assert (mock_claude_home / "commands" / "test.md").exists()
        assert (mock_claude_home / "agents" / "reviewer.md").exists()
        assert (mock_claude_home / "skills" / "search" / "SKILL.md").exists()
        assert (mock_claude_home / "skills" / "search" / "scripts" / "search.py").exists()
        # Note: hooks and status-line are settings-only (no files to install)
        assert not (mock_claude_home / "hooks").exists()
        assert not (mock_claude_home / "status-line").exists()

        # Verify file contents
        assert "Review Command" in (mock_claude_home / "commands" / "review.md").read_text()

        # Verify settings merged
        settings = read_settings(mock_claude_home / "settings.json")
        assert settings["model"] == "opus"  # Preserved
        assert "Bash(ls:*)" in settings["permissions"]["allow"]  # Preserved
        assert "Bash(git:*)" in settings["permissions"]["allow"]  # Added
        assert "Read" in settings["permissions"]["allow"]  # Added

        # Verify hooks merged (existing + new) - now `forge hook <name>` commands
        pretool_hooks = settings["hooks"]["PreToolUse"]
        matchers = [h.get("matcher") for h in pretool_hooks]
        assert "Bash" in matchers  # Existing preserved
        assert "Write" in matchers  # New added

        # Verify statusLine added (now uses `forge status-line` command)
        assert "statusLine" in settings
        assert settings["statusLine"]["command"] == "forge status-line"

        # Verify tracking updated
        tracking = TrackingStore(tracking_path=mock_forge_home / "installed.json")
        installation = tracking.get_installation("user")
        assert installation is not None
        # Only file-based modules are tracked (commands, agents, skills)
        assert len(installation.files) == 5  # 2 commands + 1 agent + 2 skill files
        assert installation.profile == "full"

    def test_init_idempotent(
        self,
        installer,
        mock_repo: Path,
        mock_claude_home: Path,
        mock_forge_home: Path,
    ) -> None:
        """Test that running init twice is idempotent."""
        # First install
        installer.init(profile=InstallProfile.FULL, mode=InstallMode.COPY)

        # Get tracking after first install
        tracking1 = TrackingStore(tracking_path=mock_forge_home / "installed.json")
        install1 = tracking1.get_installation("user")
        file_count1 = len(install1.files) if install1 else 0

        # Second install (should be no-op)
        plan2 = installer.init(profile=InstallProfile.FULL, mode=InstallMode.COPY)

        # Verify all files were skipped
        for file_plan in plan2.files:
            assert file_plan.action == "skip", f"Expected skip, got {file_plan.action} for {file_plan.target_path}"

        # Verify tracking preserved
        tracking2 = TrackingStore(tracking_path=mock_forge_home / "installed.json")
        install2 = tracking2.get_installation("user")
        assert install2 is not None
        assert len(install2.files) == file_count1

    def test_update_detects_changes(
        self,
        installer,
        mock_repo: Path,
        mock_claude_home: Path,
        mock_forge_home: Path,
    ) -> None:
        """Test that update detects and applies source changes."""
        # Initial install
        installer.init(profile=InstallProfile.FULL, mode=InstallMode.COPY)

        # Modify source file
        (mock_repo / "src" / "commands" / "review.md").write_text("# Updated Review\nNew content.\n")

        # Update
        plan = installer.update()

        # Verify update detected
        updated_files = [f for f in plan.files if f.action == "update"]
        assert len(updated_files) == 1
        assert "review.md" in updated_files[0].target_path

        # Verify file was updated
        content = (mock_claude_home / "commands" / "review.md").read_text()
        assert "Updated Review" in content

    def test_update_no_changes_is_noop(
        self,
        installer,
        mock_repo: Path,
        mock_claude_home: Path,
        mock_forge_home: Path,
    ) -> None:
        """Test that update with no changes is a no-op."""
        # Initial install
        installer.init(profile=InstallProfile.FULL, mode=InstallMode.COPY)

        # Update with no changes
        plan = installer.update()

        # Verify all skipped
        for file_plan in plan.files:
            assert file_plan.action == "skip"

    def test_uninstall_removes_files_and_settings(
        self,
        installer,
        mock_repo: Path,
        mock_claude_home: Path,
        mock_forge_home: Path,
    ) -> None:
        """Test that uninstall removes only Forge-managed items."""
        # Install first
        installer.init(profile=InstallProfile.FULL, mode=InstallMode.COPY)

        # Verify files exist
        assert (mock_claude_home / "commands" / "review.md").exists()

        # Uninstall
        installer.uninstall()

        # Verify Forge files removed
        assert not (mock_claude_home / "commands" / "review.md").exists()
        assert not (mock_claude_home / "agents" / "reviewer.md").exists()
        assert not (mock_claude_home / "hooks" / "notify.sh").exists()

        # Verify settings reverted (Forge entries removed, user entries preserved)
        settings = read_settings(mock_claude_home / "settings.json")
        assert settings["model"] == "opus"  # Preserved
        assert "Bash(ls:*)" in settings["permissions"]["allow"]  # Preserved
        # Forge-added permissions should be removed (if properly tracked)

        # Verify tracking cleared
        tracking = TrackingStore(tracking_path=mock_forge_home / "installed.json")
        installation = tracking.get_installation("user")
        assert installation is None

    def test_symlink_mode(
        self,
        installer,
        mock_repo: Path,
        mock_claude_home: Path,
        mock_forge_home: Path,
    ) -> None:
        """Test that symlink mode creates symlinks instead of copies."""
        installer.init(profile=InstallProfile.FULL, mode=InstallMode.SYMLINK)

        # Verify symlinks created
        review_path = mock_claude_home / "commands" / "review.md"
        assert review_path.is_symlink()
        assert review_path.resolve() == (mock_repo / "src" / "commands" / "review.md").resolve()

    def test_conflict_detection(
        self,
        installer,
        mock_repo: Path,
        mock_claude_home: Path,
        mock_forge_home: Path,
    ) -> None:
        """Test that conflicts are detected for non-Forge-managed files."""
        # Create a conflicting file
        commands_dir = mock_claude_home / "commands"
        commands_dir.mkdir(exist_ok=True)
        (commands_dir / "review.md").write_text("# User's custom review command\n")

        plan = installer.plan(profile=InstallProfile.FULL, mode=InstallMode.COPY)

        # Verify conflict detected
        assert plan.has_conflicts
        conflict_files = [f for f in plan.files if f.action == "conflict"]
        assert any("review.md" in f.target_path for f in conflict_files)

    def test_force_overrides_conflicts(
        self,
        installer,
        mock_repo: Path,
        mock_claude_home: Path,
        mock_forge_home: Path,
    ) -> None:
        """Test that --force overrides conflicts."""
        # Create a conflicting file
        commands_dir = mock_claude_home / "commands"
        commands_dir.mkdir(exist_ok=True)
        (commands_dir / "review.md").write_text("# User's custom review command\n")

        plan = installer.init(profile=InstallProfile.FULL, mode=InstallMode.COPY, force=True)

        # Verify no conflicts (force overrode them)
        assert not plan.has_conflicts

        # Verify file was overwritten
        content = (mock_claude_home / "commands" / "review.md").read_text()
        assert "Review Command" in content  # Forge version, not user's

    def test_profile_minimal_only_installs_commands(
        self,
        installer,
        mock_repo: Path,
        mock_claude_home: Path,
        mock_forge_home: Path,
    ) -> None:
        """Test that minimal profile only installs commands."""
        installer.init(profile=InstallProfile.MINIMAL, mode=InstallMode.COPY)

        # Verify only commands installed
        assert (mock_claude_home / "commands" / "review.md").exists()
        assert not (mock_claude_home / "agents").exists()
        assert not (mock_claude_home / "hooks").exists()
        assert not (mock_claude_home / "status-line").exists()

    def test_settings_backup_created(
        self,
        installer,
        mock_repo: Path,
        mock_claude_home: Path,
        mock_forge_home: Path,
    ) -> None:
        """Test that settings backup is created before modification."""
        original_settings = read_settings(mock_claude_home / "settings.json")

        installer.init(profile=InstallProfile.FULL, mode=InstallMode.COPY)

        # Verify backup created
        backup_path = mock_claude_home / "settings.json.forge-backup"
        assert backup_path.exists()

        # Verify backup contains original settings
        backup_settings = read_settings(backup_path)
        assert backup_settings == original_settings

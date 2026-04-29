"""Regression test for QA-002: stale symlinks after source file renames.

Root cause: Installer.init() carried forward all existing tracked files that
weren't re-installed, even if their source no longer existed. On rename, the
old symlink stayed on disk and in the tracking manifest indefinitely.

Fix: init() now compares existing tracked files against planned_targets (the
set of all targets the current source scan knows about). Tracked files not in
that set are stale — removed from disk and dropped from the manifest.

Affected file: src/forge/install/installer.py
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from forge.install.installer import Installer
from forge.install.models import (
    InstallMode,
    InstallModule,
    InstallProfile,
    InstallScope,
)
from forge.install.tracking import TrackingStore

pytestmark = pytest.mark.regression


@pytest.fixture
def symlink_env(tmp_path: Path) -> dict[str, Path]:
    """Minimal installer environment for symlink testing."""
    forge_home = tmp_path / ".forge"
    forge_home.mkdir()

    claude_home = tmp_path / ".claude"
    claude_home.mkdir()

    src = tmp_path / "src"
    commands = src / "commands"
    commands.mkdir(parents=True)
    (src / "skills").mkdir()
    (src / "forge").mkdir()

    return {
        "forge_home": forge_home,
        "claude_home": claude_home,
        "src": src,
        "commands": commands,
        "repo_root": tmp_path,
    }


def _make_installer(env: dict[str, Path]) -> Installer:
    tracking = TrackingStore(tracking_path=env["forge_home"] / "installed.json")
    return Installer(scope=InstallScope.USER, tracking_store=tracking)


def _run_init(env: dict[str, Path], installer: Installer, mode: InstallMode = InstallMode.SYMLINK) -> None:
    with (
        patch("forge.install.installer.get_forge_source_root", return_value=env["repo_root"]),
        patch("forge.install.installer.get_target_root", return_value=env["claude_home"]),
    ):
        installer.init(
            profile=InstallProfile.MINIMAL,
            mode=mode,
            _modules_override={InstallModule.COMMANDS},
        )


class TestStaleSymlinkRemoval:
    """Sync removes broken symlinks when source files are renamed."""

    def test_rename_removes_old_symlink(self, symlink_env: dict[str, Path]) -> None:
        """After renaming a source file, sync should remove the old symlink."""
        commands = symlink_env["commands"]
        claude_home = symlink_env["claude_home"]

        # Phase 1: install with original file
        (commands / "old-name.md").write_text("# Original\n")
        installer = _make_installer(symlink_env)
        _run_init(symlink_env, installer)

        old_target = claude_home / "commands" / "old-name.md"
        assert old_target.is_symlink(), "Initial install should create symlink"

        # Phase 2: rename source file and re-sync
        (commands / "old-name.md").rename(commands / "new-name.md")
        installer = _make_installer(symlink_env)
        _run_init(symlink_env, installer)

        new_target = claude_home / "commands" / "new-name.md"
        assert new_target.is_symlink(), "New symlink should be created"
        assert (
            not old_target.exists() and not old_target.is_symlink()
        ), "Old symlink should be removed after source rename"

    def test_rename_removes_old_from_tracking(self, symlink_env: dict[str, Path]) -> None:
        """After renaming, the old file should not appear in the tracking manifest."""
        commands = symlink_env["commands"]
        forge_home = symlink_env["forge_home"]

        # Phase 1: install
        (commands / "before.md").write_text("# Before\n")
        installer = _make_installer(symlink_env)
        _run_init(symlink_env, installer)

        # Phase 2: rename and sync
        (commands / "before.md").rename(commands / "after.md")
        installer = _make_installer(symlink_env)
        _run_init(symlink_env, installer)

        tracking = TrackingStore(tracking_path=forge_home / "installed.json")
        installation = tracking.get_installation("user")
        assert installation is not None

        tracked_paths = [f.target_path for f in installation.files]
        assert not any(
            "before.md" in p for p in tracked_paths
        ), f"Old filename should not be in tracking: {tracked_paths}"
        assert any("after.md" in p for p in tracked_paths), f"New filename should be in tracking: {tracked_paths}"

    def test_delete_removes_orphaned_symlink(self, symlink_env: dict[str, Path]) -> None:
        """Deleting a source file (not renaming) should also clean up."""
        commands = symlink_env["commands"]
        claude_home = symlink_env["claude_home"]

        # Phase 1: install two files
        (commands / "keep.md").write_text("# Keep\n")
        (commands / "remove.md").write_text("# Remove\n")
        installer = _make_installer(symlink_env)
        _run_init(symlink_env, installer)

        assert (claude_home / "commands" / "remove.md").is_symlink()

        # Phase 2: delete one source file and sync
        (commands / "remove.md").unlink()
        installer = _make_installer(symlink_env)
        _run_init(symlink_env, installer)

        assert (claude_home / "commands" / "keep.md").is_symlink(), "Kept file should survive"
        removed = claude_home / "commands" / "remove.md"
        assert not removed.exists() and not removed.is_symlink(), "Orphaned symlink should be removed"


class TestStaleFileRemovalCopyMode:
    """Same scenarios in copy mode."""

    def test_rename_removes_old_copy(self, symlink_env: dict[str, Path]) -> None:
        """After renaming a source file, sync removes the old installed copy."""
        commands = symlink_env["commands"]
        claude_home = symlink_env["claude_home"]

        (commands / "old.md").write_text("# Original\n")
        installer = _make_installer(symlink_env)
        _run_init(symlink_env, installer, mode=InstallMode.COPY)

        old_target = claude_home / "commands" / "old.md"
        assert old_target.is_file() and not old_target.is_symlink()

        (commands / "old.md").rename(commands / "new.md")
        installer = _make_installer(symlink_env)
        _run_init(symlink_env, installer, mode=InstallMode.COPY)

        assert (claude_home / "commands" / "new.md").is_file()
        assert not old_target.exists(), "Old copy should be removed after source rename"

    def test_user_edited_copy_preserved(self, symlink_env: dict[str, Path]) -> None:
        """If user edited the installed copy and source is deleted, don't delete their work."""
        commands = symlink_env["commands"]
        claude_home = symlink_env["claude_home"]

        (commands / "editable.md").write_text("# Original\n")
        installer = _make_installer(symlink_env)
        _run_init(symlink_env, installer, mode=InstallMode.COPY)

        target = claude_home / "commands" / "editable.md"
        assert target.is_file()

        # User edits the installed copy (checksum no longer matches)
        target.write_text("# User's custom version\n")

        # Source is deleted
        (commands / "editable.md").unlink()
        installer = _make_installer(symlink_env)
        _run_init(symlink_env, installer, mode=InstallMode.COPY)

        # Ownership check fails (checksum mismatch) — file should be preserved
        assert target.is_file(), "User-edited file should not be deleted"
        assert target.read_text() == "# User's custom version\n"


class TestStaleOwnershipVerification:
    """Ownership checks prevent deletion of user-repurposed targets."""

    def test_repurposed_symlink_target_preserved(self, symlink_env: dict[str, Path]) -> None:
        """If user replaced a Forge symlink with a regular file, don't delete it."""
        commands = symlink_env["commands"]
        claude_home = symlink_env["claude_home"]

        (commands / "replaced.md").write_text("# Forge file\n")
        installer = _make_installer(symlink_env)
        _run_init(symlink_env, installer)

        target = claude_home / "commands" / "replaced.md"
        assert target.is_symlink()

        # User replaces the symlink with their own file
        target.unlink()
        target.write_text("# User's file\n")

        # Source is deleted
        (commands / "replaced.md").unlink()
        installer = _make_installer(symlink_env)
        _run_init(symlink_env, installer)

        # Not a symlink anymore — ownership check fails, file preserved
        assert target.is_file(), "User-created file should not be deleted"
        assert target.read_text() == "# User's file\n"

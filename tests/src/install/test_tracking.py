"""Tests for forge.install.tracking."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.install.exceptions import TrackingCorruptedError
from forge.install.models import (
    TRACKING_VERSION,
    Installation,
    InstalledManifest,
    InstalledSkillPackage,
)
from forge.install.tracking import (
    TrackingStore,
    compute_checksum,
    get_tracking_path,
)


class TestComputeChecksum:
    """Tests for compute_checksum function."""

    def test_compute_checksum_basic(self, tmp_path: Path) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        checksum = compute_checksum(test_file)

        assert isinstance(checksum, str)
        assert len(checksum) == 64  # SHA256 hex is 64 chars

    def test_checksum_is_deterministic(self, tmp_path: Path) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("deterministic content")

        checksum1 = compute_checksum(test_file)
        checksum2 = compute_checksum(test_file)

        assert checksum1 == checksum2

    def test_different_content_different_checksum(self, tmp_path: Path) -> None:
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content a")
        file2.write_text("content b")

        assert compute_checksum(file1) != compute_checksum(file2)


class TestGetTrackingPath:
    """Tests for get_tracking_path function."""

    def test_returns_path_in_forge_home(self) -> None:
        path = get_tracking_path()
        assert path.name == "installed.json"
        # Should live under the forge home directory (respects FORGE_HOME in tests)
        assert str(path).endswith("/installed.json")


class TestTrackingStore:
    """Tests for TrackingStore class."""

    def test_exists_returns_false_when_missing(self, tracking_store: TrackingStore) -> None:
        assert not tracking_store.exists()

    def test_exists_returns_true_when_present(
        self, tracking_store: TrackingStore, sample_manifest: InstalledManifest
    ) -> None:
        tracking_store.write(sample_manifest)
        assert tracking_store.exists()

    def test_read_returns_empty_when_missing(self, tracking_store: TrackingStore) -> None:
        manifest = tracking_store.read()
        assert manifest.version == TRACKING_VERSION
        assert manifest.installations == {}

    def test_read_raises_on_corrupted_json(self, tracking_store: TrackingStore) -> None:
        tracking_store.path.write_text("not valid json {{{")

        with pytest.raises(TrackingCorruptedError) as exc_info:
            tracking_store.read()

        assert "invalid JSON" in str(exc_info.value)
        assert str(tracking_store.path) in exc_info.value.path

    def test_read_raises_on_invalid_version(self, tracking_store: TrackingStore) -> None:
        tracking_store.path.write_text(json.dumps({"version": 999}))

        with pytest.raises(TrackingCorruptedError) as exc_info:
            tracking_store.read()

        assert "incompatible version" in str(exc_info.value)

    def test_read_v1_normalizes_in_memory_without_rewriting(self, tracking_store: TrackingStore) -> None:
        legacy = {
            "version": 1,
            "installations": {
                "user": {
                    "scope": "user",
                    "mode": "copy",
                    "profile": "standard",
                    "modules_enabled": ["skills"],
                    "files": [
                        {
                            "target_path": "/home/user/.claude/skills/challenge/SKILL.md",
                            "source_path": "/src/skills/challenge/SKILL.md",
                            "checksum": "abc",
                            "mode": "copy",
                            "installed_at": "2026-01-01T00:00:00Z",
                        }
                    ],
                    "settings_entries": [
                        {
                            "key_path": "permissions.allow",
                            "value": "Read",
                            "merge_type": "union",
                            "stable_id": "Read",
                        }
                    ],
                    "settings_backup_path": "/home/user/.claude/settings.json.forge-backup",
                    "codex_config_path": "/home/user/.codex/config.toml",
                    "codex_commands": ["forge-hook codex-session-start"],
                    "installed_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            },
        }
        original = json.dumps(legacy, indent=2)
        tracking_store.path.write_text(original, encoding="utf-8")

        manifest = tracking_store.read()

        assert manifest.version == TRACKING_VERSION == 2
        installation = manifest.installations["user"]
        assert installation.modules_enabled == ["skills"]
        assert installation.files[0].target_path.endswith("/challenge/SKILL.md")
        assert installation.settings_entries[0].stable_id == "Read"
        assert installation.settings_backup_path == "/home/user/.claude/settings.json.forge-backup"
        assert installation.codex_config_path == "/home/user/.codex/config.toml"
        assert installation.codex_commands == ["forge-hook codex-session-start"]
        assert installation.skill_packages == []
        assert tracking_store.path.read_text(encoding="utf-8") == original

    def test_read_v1_rejects_current_only_skill_packages_field(self, tracking_store: TrackingStore) -> None:
        tracking_store.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "installations": {
                        "user": {
                            "scope": "user",
                            "mode": "copy",
                            "profile": "standard",
                            "skill_packages": [],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(TrackingCorruptedError, match="deserialization error"):
            tracking_store.read()

    def test_read_v2_rejects_unknown_package_field(self, tracking_store: TrackingStore) -> None:
        tracking_store.path.write_text(
            json.dumps(
                {
                    "version": 2,
                    "installations": {
                        "user": {
                            "scope": "user",
                            "mode": "copy",
                            "profile": "standard",
                            "skill_packages": [
                                {
                                    "runtime": "codex",
                                    "skill": "challenge",
                                    "target_dir": "/home/user/.agents/skills/challenge",
                                    "file_paths": [],
                                    "future": True,
                                }
                            ],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(TrackingCorruptedError, match="deserialization error"):
            tracking_store.read()

    def test_read_rejects_manifest_with_removed_patched_files_field(self, tracking_store: TrackingStore) -> None:
        """A manifest carrying the removed patched_files field is rejected, not silently loaded.

        The bespoke pre-OSS tombstone is gone; dacite strict=True rejects the unexpected
        field, so the manifest surfaces as TrackingCorruptedError (a StateCorruptedError)
        through the unified corrupt-state handler instead of degrading to a default.
        """
        tracking_store.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "installations": {
                        "user": {
                            "scope": "user",
                            "mode": "copy",
                            "profile": "standard",
                            "modules_enabled": [],
                            "files": [],
                            "settings_entries": [],
                            "patched_files": [],
                        }
                    },
                }
            )
        )

        with pytest.raises(TrackingCorruptedError) as exc_info:
            tracking_store.read()

        assert "deserialization error" in str(exc_info.value)

    def test_write_creates_file(self, tracking_store: TrackingStore, sample_manifest: InstalledManifest) -> None:
        tracking_store.write(sample_manifest)

        assert tracking_store.path.is_file()
        content = tracking_store.path.read_text()
        assert f'"version": {TRACKING_VERSION}' in content

    def test_write_creates_parent_directory(self, tmp_path: Path) -> None:
        nested_path = tmp_path / "nested" / "dir" / "installed.json"
        store = TrackingStore(tracking_path=nested_path)

        store.write(InstalledManifest())

        assert nested_path.is_file()

    def test_write_is_atomic(self, tracking_store: TrackingStore, sample_manifest: InstalledManifest) -> None:
        """Test that writes use atomic pattern (temp file + rename)."""
        # Write content
        tracking_store.write(sample_manifest)

        # Check no temp files left behind
        parent = tracking_store.path.parent
        temp_files = list(parent.glob(".installed.*.tmp"))
        assert len(temp_files) == 0

    def test_read_write_roundtrip(self, tracking_store: TrackingStore, sample_manifest: InstalledManifest) -> None:
        tracking_store.write(sample_manifest)
        loaded = tracking_store.read()

        assert loaded.version == sample_manifest.version
        assert "user" in loaded.installations
        assert loaded.installations["user"].scope == "user"
        assert loaded.installations["user"].profile == "standard"

    def test_read_write_roundtrip_preserves_runtime_skill_packages(self, tracking_store: TrackingStore) -> None:
        package = InstalledSkillPackage(
            runtime="codex",
            skill="challenge",
            target_dir="/home/user/.agents/skills/challenge",
            file_paths=["/home/user/.agents/skills/challenge/SKILL.md"],
        )
        manifest = InstalledManifest(
            installations={
                "user": Installation(
                    scope="user",
                    mode="copy",
                    profile="standard",
                    modules_enabled=["skills"],
                    skill_packages=[package],
                )
            }
        )

        tracking_store.write(manifest)
        loaded = tracking_store.read()

        assert loaded.installations["user"].skill_packages == [package]

    def test_write_always_emits_current_version(self, tracking_store: TrackingStore) -> None:
        tracking_store.write(InstalledManifest(version=1))

        assert json.loads(tracking_store.path.read_text(encoding="utf-8"))["version"] == TRACKING_VERSION == 2

    def test_get_installation_returns_none_when_empty(self, tracking_store: TrackingStore) -> None:
        result = tracking_store.get_installation("user")
        assert result is None

    def test_get_installation_returns_installation(
        self, tracking_store: TrackingStore, sample_manifest: InstalledManifest
    ) -> None:
        tracking_store.write(sample_manifest)

        result = tracking_store.get_installation("user")

        assert result is not None
        assert result.scope == "user"
        assert result.profile == "standard"

    def test_get_installation_returns_none_for_missing_scope(
        self, tracking_store: TrackingStore, sample_manifest: InstalledManifest
    ) -> None:
        tracking_store.write(sample_manifest)

        # Local scope with non-existent project path should return None
        result = tracking_store.get_installation("local", project_path="/nonexistent/project")
        assert result is None

    def test_set_installation_creates_new(
        self, tracking_store: TrackingStore, sample_installation: Installation
    ) -> None:
        tracking_store.set_installation("user", sample_installation)

        loaded = tracking_store.read()
        assert "user" in loaded.installations

    def test_set_installation_updates_existing(
        self, tracking_store: TrackingStore, sample_installation: Installation
    ) -> None:
        tracking_store.set_installation("user", sample_installation)

        updated = Installation(
            scope="user",
            mode="symlink",
            profile="full",
        )
        tracking_store.set_installation("user", updated)

        loaded = tracking_store.read()
        assert loaded.installations["user"].mode == "symlink"
        assert loaded.installations["user"].profile == "full"

    def test_remove_installation_returns_true_when_exists(
        self, tracking_store: TrackingStore, sample_manifest: InstalledManifest
    ) -> None:
        tracking_store.write(sample_manifest)

        result = tracking_store.remove_installation("user")

        assert result is True
        loaded = tracking_store.read()
        assert "user" not in loaded.installations

    def test_remove_installation_returns_false_when_missing(self, tracking_store: TrackingStore) -> None:
        result = tracking_store.remove_installation("user")
        assert result is False

    def test_is_forge_managed_returns_false_when_no_installation(self, tracking_store: TrackingStore) -> None:
        result = tracking_store.is_forge_managed("/some/path", "user")
        assert result is False

    def test_is_forge_managed_returns_true_for_tracked_file(
        self, tracking_store: TrackingStore, sample_manifest: InstalledManifest
    ) -> None:
        tracking_store.write(sample_manifest)

        # Use the path from sample_installation
        result = tracking_store.is_forge_managed("/home/user/.claude/commands/test.md", "user")
        assert result is True

    def test_is_forge_managed_returns_false_for_untracked_file(
        self, tracking_store: TrackingStore, sample_manifest: InstalledManifest
    ) -> None:
        tracking_store.write(sample_manifest)

        result = tracking_store.is_forge_managed("/some/other/path", "user")
        assert result is False

    # -------------------------------------------------------------------------
    # Project path support tests
    # -------------------------------------------------------------------------

    def test_get_installation_with_project_path(
        self, tracking_store: TrackingStore, sample_installation: Installation
    ) -> None:
        """Test getting installation for a specific project path."""
        local_install = Installation(
            scope="local",
            mode="copy",
            profile="standard",
            project_path="/path/to/project",
        )
        tracking_store.set_installation("local", local_install, project_path="/path/to/project")

        # Get with correct project path
        result = tracking_store.get_installation("local", project_path="/path/to/project")
        assert result is not None
        assert result.project_path == "/path/to/project"

        # Get with different project path returns None
        result2 = tracking_store.get_installation("local", project_path="/other/project")
        assert result2 is None

    def test_set_installation_with_project_path(self, tracking_store: TrackingStore) -> None:
        """Test setting installation with project path."""
        install = Installation(
            scope="local",
            mode="symlink",
            profile="minimal",
        )
        tracking_store.set_installation("local", install, project_path="/my/project")

        # Verify it was saved with the project_path
        loaded = tracking_store.read()
        key = "local:/my/project"
        assert key in loaded.installations
        assert loaded.installations[key].project_path == "/my/project"

    def test_remove_installation_with_project_path(self, tracking_store: TrackingStore) -> None:
        """Test removing installation for a specific project path."""
        install = Installation(scope="local", mode="copy", profile="standard")
        tracking_store.set_installation("local", install, project_path="/project/a")
        tracking_store.set_installation("local", install, project_path="/project/b")

        # Remove only one
        result = tracking_store.remove_installation("local", project_path="/project/a")
        assert result is True

        # Verify /project/a is gone but /project/b remains
        assert tracking_store.get_installation("local", project_path="/project/a") is None
        assert tracking_store.get_installation("local", project_path="/project/b") is not None

    def test_list_installations(self, tracking_store: TrackingStore, sample_installation: Installation) -> None:
        """Test listing all installations."""
        # Add user installation
        tracking_store.set_installation("user", sample_installation)

        # Add local installations for different projects
        local1 = Installation(scope="local", mode="copy", profile="standard")
        local2 = Installation(scope="local", mode="symlink", profile="minimal")
        tracking_store.set_installation("local", local1, project_path="/project/a")
        tracking_store.set_installation("local", local2, project_path="/project/b")

        # List all
        installations = tracking_store.list_installations()
        assert len(installations) == 3

        # Verify we have all three
        scopes_paths = [(scope, path) for scope, path, _ in installations]
        assert ("user", None) in scopes_paths
        assert ("local", "/project/a") in scopes_paths
        assert ("local", "/project/b") in scopes_paths

    def test_has_installation(self, tracking_store: TrackingStore, sample_installation: Installation) -> None:
        """Test has_installation helper."""
        assert not tracking_store.has_installation("user")

        tracking_store.set_installation("user", sample_installation)
        assert tracking_store.has_installation("user")

        # Project scope
        assert not tracking_store.has_installation("local", project_path="/my/project")
        local = Installation(scope="local", mode="copy", profile="standard")
        tracking_store.set_installation("local", local, project_path="/my/project")
        assert tracking_store.has_installation("local", project_path="/my/project")

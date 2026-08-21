"""Tests for forge.install.settings_merge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from forge.install.exceptions import SettingsConflictError
from forge.install.models import InstalledSettingsEntry, InstallModule, InstallScope
from forge.install.ownership import attributed
from forge.install.settings_merge import (
    backup_settings,
    find_backup_files,
    get_settings_path,
    hooks_already_present,
    merge,
    merge_hooks,
    merge_permissions,
    permissions_already_present,
    read_settings,
    read_tracked_settings_baseline,
    scalar_already_set,
    set_scalar,
    smart_unmerge,
    unmerge,
    write_settings,
)

HOOK_ATTRIBUTION = attributed(InstallModule.HOOKS, "claude_code")
PERMISSION_ATTRIBUTION = attributed(InstallModule.PERMISSIONS, "claude_code")
STATUSLINE_ATTRIBUTION = attributed(InstallModule.STATUSLINE, "claude_code")
SETTINGS_ATTRIBUTIONS = {
    InstallModule.HOOKS.value: HOOK_ATTRIBUTION,
    InstallModule.PERMISSIONS.value: PERMISSION_ATTRIBUTION,
    InstallModule.STATUSLINE.value: STATUSLINE_ATTRIBUTION,
}


class TestGetSettingsPath:
    """Tests for get_settings_path function."""

    def test_user_scope(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Should respect CLAUDE_HOME env var (isolation fixture sets it)."""
        # The isolate_claude_home fixture sets CLAUDE_HOME to tmp_path/claude_home
        path = get_settings_path(InstallScope.USER)
        # Should be the isolated path, not the real ~/.claude/settings.json
        assert path.name == "settings.json"
        assert "claude_home" in str(path) or str(path).startswith(str(tmp_path))

    def test_project_scope(self, tmp_path: Path) -> None:
        path = get_settings_path(InstallScope.PROJECT, project_root=tmp_path)
        assert path == tmp_path / ".claude" / "settings.json"

    def test_local_scope(self, tmp_path: Path) -> None:
        path = get_settings_path(InstallScope.LOCAL, project_root=tmp_path)
        assert path == tmp_path / ".claude" / "settings.local.json"

    def test_project_scope_requires_root(self) -> None:
        with pytest.raises(ValueError, match="project_root required"):
            get_settings_path(InstallScope.PROJECT)

    def test_local_scope_requires_root(self) -> None:
        with pytest.raises(ValueError, match="project_root required"):
            get_settings_path(InstallScope.LOCAL)


class TestReadWriteSettings:
    """Tests for read_settings and write_settings functions."""

    def test_read_returns_empty_when_missing(self, tmp_path: Path) -> None:
        result = read_settings(tmp_path / "missing.json")
        assert result == {}

    def test_read_returns_content(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.json"
        settings_file.write_text('{"key": "value"}')

        result = read_settings(settings_file)
        assert result == {"key": "value"}

    def test_write_creates_file(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.json"

        write_settings(settings_file, {"key": "value"})

        assert settings_file.is_file()
        content = json.loads(settings_file.read_text())
        assert content == {"key": "value"}

    def test_write_creates_parent_directories(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "nested" / "dir" / "settings.json"

        write_settings(settings_file, {"key": "value"})

        assert settings_file.is_file()

    def test_write_is_atomic(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.json"

        write_settings(settings_file, {"key": "value"})

        # No temp files left behind
        temp_files = list(tmp_path.glob(".settings.*.tmp"))
        assert len(temp_files) == 0


class TestBackupSettings:
    """Tests for backup_settings function."""

    def test_backup_returns_none_when_no_file(self, tmp_path: Path) -> None:
        result = backup_settings(tmp_path / "missing.json")
        assert result is None

    def test_backup_creates_backup_file(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.json"
        settings_file.write_text('{"key": "value"}')

        backup_path = backup_settings(settings_file)

        assert backup_path is not None
        assert backup_path.is_file()
        # New format: .settings.json.forge.backup.{timestamp}
        assert backup_path.name.startswith(".settings.json.forge.backup.")
        assert backup_path.read_text() == '{"key": "value"}'

    def test_same_second_backups_never_overwrite_prior_snapshot(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        settings_file = tmp_path / "settings.json"
        monkeypatch.setattr("forge.install.settings_merge._get_timestamp", lambda: "20260101-000000")
        settings_file.write_text('{"generation": 1}', encoding="utf-8")

        first = backup_settings(settings_file)
        settings_file.write_text('{"generation": 2}', encoding="utf-8")
        second = backup_settings(settings_file)

        assert first is not None
        assert second is not None
        assert second != first
        assert second.name == f"{first.name}.001"
        assert first.read_text(encoding="utf-8") == '{"generation": 1}'
        assert second.read_text(encoding="utf-8") == '{"generation": 2}'
        assert find_backup_files(settings_file) == [second, first]

    def test_failed_snapshot_does_not_remove_same_second_baseline(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        settings_file = tmp_path / "settings.json"
        settings_file.write_text('{"generation": 2}', encoding="utf-8")
        baseline = tmp_path / ".settings.json.forge.backup.20260101-000000"
        baseline.write_text('{"generation": 1}', encoding="utf-8")
        monkeypatch.setattr("forge.install.settings_merge._get_timestamp", lambda: "20260101-000000")
        real_open = Path.open

        def fail_source_read(path: Path, *args: Any, **kwargs: Any) -> Any:
            if path == settings_file and args and args[0] == "rb":
                raise PermissionError("injected source read failure")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", fail_source_read)

        with pytest.raises(PermissionError, match="injected source read failure"):
            backup_settings(settings_file)

        assert baseline.read_text(encoding="utf-8") == '{"generation": 1}'
        assert not baseline.with_name(f"{baseline.name}.001").exists()


class TestReadTrackedSettingsBaseline:
    def test_null_legacy_path_does_not_discover_newer_history(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.json"
        backup = tmp_path / ".settings.json.forge.backup.20260101-000000"
        write_settings(backup, {"statusLine": "forge status-line"})

        assert read_tracked_settings_baseline(None) == {}
        assert find_backup_files(settings_file) == [backup]

    def test_recorded_path_must_remain_a_regular_file(self, tmp_path: Path) -> None:
        missing = tmp_path / ".settings.json.forge.backup.missing"
        directory = tmp_path / ".settings.json.forge.backup.directory"
        directory.mkdir()

        with pytest.raises(FileNotFoundError, match="tracked settings baseline does not exist"):
            read_tracked_settings_baseline(missing)
        with pytest.raises(OSError, match="tracked settings baseline is not a regular file"):
            read_tracked_settings_baseline(directory)

    def test_recorded_baseline_vanishing_after_validation_is_not_authoritative_null(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        baseline = tmp_path / ".settings.json.forge.backup.20260101-000000"
        write_settings(baseline, {"statusLine": "original"})
        real_lstat = Path.lstat

        def delete_after_lstat(path: Path) -> Any:
            result = real_lstat(path)
            if path == baseline:
                path.unlink()
            return result

        monkeypatch.setattr(Path, "lstat", delete_after_lstat)

        with pytest.raises(FileNotFoundError, match="tracked settings baseline does not exist"):
            read_tracked_settings_baseline(baseline)

    def test_recorded_baseline_must_contain_a_json_object(self, tmp_path: Path) -> None:
        baseline = tmp_path / ".settings.json.forge.backup.20260101-000000"
        baseline.write_text('["not", "an", "object"]', encoding="utf-8")

        with pytest.raises(ValueError, match="tracked settings baseline is not a JSON object"):
            read_tracked_settings_baseline(baseline)


class TestMergeHooks:
    """Tests for merge_hooks function."""

    def test_appends_new_hooks(self, sample_settings: dict[str, Any]) -> None:
        new_entry = {
            "hooks": [{"command": "/new/hook", "type": "command"}],
            "matcher": {"tool_name": "Write"},
        }

        entries = merge_hooks(sample_settings, "PreToolUse", [new_entry], attribution=HOOK_ATTRIBUTION)

        assert len(entries) == 1
        assert entries[0].key_path == "hooks.PreToolUse"
        # stable_id is now canonical JSON (full-entry equality, not command-path)
        assert "/new/hook" in entries[0].stable_id
        assert len(sample_settings["hooks"]["PreToolUse"]) == 2

    def test_dedupes_by_command_path(self, sample_settings: dict[str, Any]) -> None:
        dupe_entry = {
            "hooks": [{"command": "/existing/hook", "type": "command"}],
            "matcher": {"tool_name": "Bash"},
        }

        entries = merge_hooks(sample_settings, "PreToolUse", [dupe_entry], attribution=HOOK_ATTRIBUTION)

        assert len(entries) == 0  # Not added (duplicate)
        assert len(sample_settings["hooks"]["PreToolUse"]) == 1  # Still just one

    def test_creates_hook_type_if_missing(self) -> None:
        settings: dict[str, Any] = {}
        new_entry = {"hooks": [{"command": "/new/hook"}]}

        entries = merge_hooks(settings, "PostToolUse", [new_entry], attribution=HOOK_ATTRIBUTION)

        assert len(entries) == 1
        assert "PostToolUse" in settings["hooks"]


class TestMergePermissions:
    """Tests for merge_permissions function."""

    def test_adds_new_permissions(self, sample_settings: dict[str, Any]) -> None:
        entries = merge_permissions(
            sample_settings,
            "allow",
            ["Bash(git:*)", "Read"],
            attribution=PERMISSION_ATTRIBUTION,
        )

        assert len(entries) == 2
        assert "Bash(git:*)" in sample_settings["permissions"]["allow"]
        assert "Read" in sample_settings["permissions"]["allow"]

    def test_dedupes_existing_permissions(self, sample_settings: dict[str, Any]) -> None:
        entries = merge_permissions(
            sample_settings,
            "allow",
            ["Bash(ls:*)"],
            attribution=PERMISSION_ATTRIBUTION,
        )

        assert len(entries) == 0  # Already exists
        assert sample_settings["permissions"]["allow"].count("Bash(ls:*)") == 1

    def test_stable_id_is_value(self, sample_settings: dict[str, Any]) -> None:
        entries = merge_permissions(
            sample_settings,
            "allow",
            ["NewPerm"],
            attribution=PERMISSION_ATTRIBUTION,
        )

        assert entries[0].stable_id == "NewPerm"

    def test_creates_permission_type_if_missing(self) -> None:
        settings: dict[str, Any] = {}

        merge_permissions(settings, "allow", ["Read"], attribution=PERMISSION_ATTRIBUTION)

        assert "allow" in settings["permissions"]
        assert "Read" in settings["permissions"]["allow"]


class TestSetScalar:
    """Tests for set_scalar function."""

    def test_sets_new_value(self) -> None:
        settings: dict[str, Any] = {}

        entry = set_scalar(settings, "statusLine", "/path", attribution=STATUSLINE_ATTRIBUTION)

        assert entry is not None
        assert settings["statusLine"] == "/path"
        assert entry.key_path == "statusLine"
        assert entry.merge_type == "scalar"

    def test_returns_none_when_same_value(self) -> None:
        settings = {"statusLine": "/same"}

        entry = set_scalar(settings, "statusLine", "/same", attribution=STATUSLINE_ATTRIBUTION)

        assert entry is None  # No change needed

    def test_raises_on_conflict_without_force(self) -> None:
        settings = {"statusLine": "/current"}

        with pytest.raises(SettingsConflictError) as exc_info:
            set_scalar(settings, "statusLine", "/new", attribution=STATUSLINE_ATTRIBUTION)

        assert exc_info.value.key_path == "statusLine"
        assert exc_info.value.current_value == "/current"
        assert exc_info.value.forge_value == "/new"

    def test_overrides_with_force(self) -> None:
        settings = {"statusLine": "/current"}

        entry = set_scalar(
            settings,
            "statusLine",
            "/new",
            attribution=STATUSLINE_ATTRIBUTION,
            force=True,
        )

        assert entry is not None
        assert settings["statusLine"] == "/new"


class TestMerge:
    """Tests for full merge function."""

    def test_merges_hooks_and_permissions(
        self,
        sample_settings: dict[str, Any],
        forge_settings: dict[str, Any],
    ) -> None:
        merge(sample_settings, forge_settings, attributions=SETTINGS_ATTRIBUTIONS)

        assert len(sample_settings["hooks"]["PreToolUse"]) == 2  # original + forge

        assert "Bash(git:*)" in sample_settings["permissions"]["allow"]
        assert "Read" in sample_settings["permissions"]["allow"]

    def test_skips_statusline_by_default(
        self,
        sample_settings: dict[str, Any],
        forge_settings: dict[str, Any],
    ) -> None:
        merge(sample_settings, forge_settings, attributions=SETTINGS_ATTRIBUTIONS)

        assert "statusLine" not in sample_settings

    def test_includes_statusline_when_requested(
        self,
        sample_settings: dict[str, Any],
        forge_settings: dict[str, Any],
    ) -> None:
        merge(
            sample_settings,
            forge_settings,
            attributions=SETTINGS_ATTRIBUTIONS,
            include_statusline=True,
        )

        assert sample_settings["statusLine"] == "/path/to/status-line.sh"

    def test_can_exclude_env(self) -> None:
        settings: dict[str, Any] = {}
        forge_settings = {"env": {"CUSTOM": "1"}}

        entries = merge(
            settings,
            forge_settings,
            attributions=SETTINGS_ATTRIBUTIONS,
            include_env=False,
        )

        assert settings == {}
        assert entries == []

    def test_raises_on_statusline_conflict(self, forge_settings: dict[str, Any]) -> None:
        settings = {"statusLine": "/existing/path"}

        with pytest.raises(SettingsConflictError):
            merge(
                settings,
                forge_settings,
                attributions=SETTINGS_ATTRIBUTIONS,
                include_statusline=True,
            )

    def test_force_overrides_statusline_conflict(self, forge_settings: dict[str, Any]) -> None:
        settings = {"statusLine": "/existing/path"}

        merge(
            settings,
            forge_settings,
            attributions=SETTINGS_ATTRIBUTIONS,
            include_statusline=True,
            force=True,
        )

        assert settings["statusLine"] == "/path/to/status-line.sh"


class TestUnmerge:
    """Tests for unmerge function."""

    def test_removes_hooks_by_canonical_json(self) -> None:
        forge_hook = {"hooks": [{"command": "/forge/hook"}]}
        user_hook = {"hooks": [{"command": "/user/hook"}]}
        settings = {
            "hooks": {
                "PreToolUse": [forge_hook, user_hook],
            }
        }
        tracking_entries = [
            InstalledSettingsEntry(
                key_path="hooks.PreToolUse",
                value=forge_hook,
                merge_type="append",
                stable_id='{"hooks":[{"command":"/forge/hook"}]}',
                attribution=HOOK_ATTRIBUTION,
            )
        ]

        unmerge(settings, tracking_entries)

        assert len(settings["hooks"]["PreToolUse"]) == 1
        assert settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "/user/hook"

    def test_removes_permissions_by_value(self) -> None:
        settings = {
            "permissions": {
                "allow": ["Bash(git:*)", "Read", "UserPerm"],
            }
        }
        tracking_entries = [
            InstalledSettingsEntry(
                key_path="permissions.allow",
                value="Bash(git:*)",
                merge_type="union",
                stable_id="Bash(git:*)",
                attribution=PERMISSION_ATTRIBUTION,
            ),
            InstalledSettingsEntry(
                key_path="permissions.allow",
                value="Read",
                merge_type="union",
                stable_id="Read",
                attribution=PERMISSION_ATTRIBUTION,
            ),
        ]

        unmerge(settings, tracking_entries)

        assert settings["permissions"]["allow"] == ["UserPerm"]

    def test_removes_scalar_keys(self) -> None:
        settings = {"statusLine": "/forge/path", "otherKey": "value"}
        tracking_entries = [
            InstalledSettingsEntry(
                key_path="statusLine",
                value="/forge/path",
                merge_type="scalar",
                stable_id="statusLine",
                attribution=STATUSLINE_ATTRIBUTION,
            )
        ]

        unmerge(settings, tracking_entries)

        assert "statusLine" not in settings
        assert "otherKey" in settings

    @pytest.mark.parametrize(
        ("settings", "expected"),
        [
            (
                {"statusLine": "/user/path", "otherKey": "value"},
                {"statusLine": "/user/path", "otherKey": "value"},
            ),
            ({"otherKey": "value"}, {"otherKey": "value"}),
        ],
        ids=["modified", "absent"],
    )
    def test_preserves_modified_or_absent_scalar_keys(
        self,
        settings: dict[str, Any],
        expected: dict[str, Any],
    ) -> None:
        tracking_entries = [
            InstalledSettingsEntry(
                key_path="statusLine",
                value="/forge/path",
                merge_type="scalar",
                stable_id="statusLine",
                attribution=STATUSLINE_ATTRIBUTION,
            )
        ]

        unmerge(settings, tracking_entries)

        assert settings == expected

    def test_removes_only_environment_values_that_still_match_tracking(self) -> None:
        settings = {
            "env": {
                "OWNED": "forge-value",
                "EDITED": "user-value",
                "USER_ONLY": "keep-me",
            }
        }
        tracking_entries = [
            InstalledSettingsEntry(
                key_path="env.OWNED",
                value="forge-value",
                merge_type="env",
                stable_id="OWNED",
                attribution=PERMISSION_ATTRIBUTION,
            ),
            InstalledSettingsEntry(
                key_path="env.EDITED",
                value="forge-value",
                merge_type="env",
                stable_id="EDITED",
                attribution=PERMISSION_ATTRIBUTION,
            ),
            InstalledSettingsEntry(
                key_path="env.ABSENT",
                value="forge-value",
                merge_type="env",
                stable_id="ABSENT",
                attribution=PERMISSION_ATTRIBUTION,
            ),
        ]

        unmerge(settings, tracking_entries)

        assert settings == {"env": {"EDITED": "user-value", "USER_ONLY": "keep-me"}}

    def test_removes_empty_environment_container_after_matching_value(self) -> None:
        settings = {"env": {"OWNED": "forge-value"}}
        tracking_entries = [
            InstalledSettingsEntry(
                key_path="env.OWNED",
                value="forge-value",
                merge_type="env",
                stable_id="OWNED",
                attribution=PERMISSION_ATTRIBUTION,
            )
        ]

        unmerge(settings, tracking_entries)

        assert settings == {}

    def test_unmerge_preserves_untracked_entries(self) -> None:
        settings: dict[str, Any] = {
            "hooks": {
                "PreToolUse": [
                    {"hooks": [{"command": "/forge/hook"}]},
                    {"hooks": [{"command": "/user/hook"}]},
                ]
            },
            "permissions": {"allow": ["ForgePerm", "UserPerm"]},
        }
        forge_hook = {"hooks": [{"command": "/forge/hook"}]}
        tracking_entries = [
            InstalledSettingsEntry(
                key_path="hooks.PreToolUse",
                value=forge_hook,
                merge_type="append",
                stable_id='{"hooks":[{"command":"/forge/hook"}]}',
                attribution=HOOK_ATTRIBUTION,
            ),
            InstalledSettingsEntry(
                key_path="permissions.allow",
                value="ForgePerm",
                merge_type="union",
                stable_id="ForgePerm",
                attribution=PERMISSION_ATTRIBUTION,
            ),
        ]

        unmerge(settings, tracking_entries)

        # User entries preserved
        assert len(settings["hooks"]["PreToolUse"]) == 1
        assert settings["permissions"]["allow"] == ["UserPerm"]


class TestSmartUnmerge:
    def test_preserves_user_modified_scalar_and_env_values(self) -> None:
        current = {
            "statusLine": "user replacement",
            "env": {"FORGE_MODE": "user replacement"},
        }
        backup = {
            "statusLine": "original status",
            "env": {"FORGE_MODE": "original mode"},
        }
        added = {
            "statusLine": "forge status-line",
            "env": {"FORGE_MODE": "managed"},
        }

        result = smart_unmerge(current, backup, added)

        assert result == current


class TestHooksAlreadyPresent:
    """Tests for hooks_already_present pre-check function."""

    def test_returns_true_when_all_hooks_present(self) -> None:
        """Should return True when all hooks are already in settings."""
        current_settings = {
            "hooks": {
                "PreToolUse": [
                    {"hooks": [{"command": "forge hook policy-check"}]},
                    {"hooks": [{"command": "other-hook"}]},
                ]
            }
        }
        entries = [{"hooks": [{"command": "forge hook policy-check"}]}]

        result = hooks_already_present(current_settings, "PreToolUse", entries)

        assert result is True

    def test_returns_false_when_hook_missing(self) -> None:
        """Should return False when at least one hook is not present."""
        current_settings = {
            "hooks": {
                "PreToolUse": [
                    {"hooks": [{"command": "other-hook"}]},
                ]
            }
        }
        entries = [{"hooks": [{"command": "forge hook policy-check"}]}]

        result = hooks_already_present(current_settings, "PreToolUse", entries)

        assert result is False

    def test_returns_false_when_no_hooks_in_settings(self) -> None:
        """Should return False when hook type doesn't exist in settings."""
        current_settings: dict[str, Any] = {}
        entries = [{"hooks": [{"command": "forge hook policy-check"}]}]

        result = hooks_already_present(current_settings, "PreToolUse", entries)

        assert result is False

    def test_handles_multiple_entries(self) -> None:
        """Should check all entries, not just the first one."""
        current_settings = {
            "hooks": {
                "PreToolUse": [
                    {"hooks": [{"command": "hook-a"}]},
                ]
            }
        }
        # Two entries, only one present
        entries = [
            {"hooks": [{"command": "hook-a"}]},
            {"hooks": [{"command": "hook-b"}]},
        ]

        result = hooks_already_present(current_settings, "PreToolUse", entries)

        assert result is False  # hook-b is missing


class TestPermissionsAlreadyPresent:
    """Tests for permissions_already_present pre-check function."""

    def test_returns_true_when_all_permissions_present(self) -> None:
        """Should return True when all permissions are already in settings."""
        current_settings = {
            "permissions": {
                "allow": ["Bash(git:*)", "Read", "Write"],
            }
        }
        entries = ["Bash(git:*)", "Read"]

        result = permissions_already_present(current_settings, "allow", entries)

        assert result is True

    def test_returns_false_when_permission_missing(self) -> None:
        """Should return False when at least one permission is not present."""
        current_settings = {
            "permissions": {
                "allow": ["Read"],
            }
        }
        entries = ["Read", "Write"]

        result = permissions_already_present(current_settings, "allow", entries)

        assert result is False  # Write is missing

    def test_returns_false_when_no_permissions_in_settings(self) -> None:
        """Should return False when permission type doesn't exist in settings."""
        current_settings: dict[str, Any] = {}
        entries = ["Bash(git:*)"]

        result = permissions_already_present(current_settings, "allow", entries)

        assert result is False

    def test_handles_empty_entries(self) -> None:
        """Empty entries list should return True (nothing to check)."""
        current_settings = {"permissions": {"allow": ["Read"]}}

        result = permissions_already_present(current_settings, "allow", [])

        assert result is True


class TestScalarAlreadySet:
    """Tests for scalar_already_set pre-check function."""

    def test_returns_true_when_value_matches(self) -> None:
        """Should return True when scalar is set to expected value."""
        current_settings = {"statusLine": "/path/to/script"}

        result = scalar_already_set(current_settings, "statusLine", "/path/to/script")

        assert result is True

    def test_returns_false_when_value_differs(self) -> None:
        """Should return False when scalar is set to different value."""
        current_settings = {"statusLine": "/other/path"}

        result = scalar_already_set(current_settings, "statusLine", "/path/to/script")

        assert result is False

    def test_returns_false_when_key_missing(self) -> None:
        """Should return False when key doesn't exist."""
        current_settings: dict[str, Any] = {}

        result = scalar_already_set(current_settings, "statusLine", "/path/to/script")

        assert result is False

    def test_handles_dict_values(self) -> None:
        """Should work with dict values (like statusLine objects)."""
        status_line = {"type": "command", "command": "forge status-line"}
        current_settings = {"statusLine": status_line}

        result = scalar_already_set(current_settings, "statusLine", status_line)

        assert result is True

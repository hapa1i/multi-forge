"""Tests for explicit legacy hook migration."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from forge.install.codex_hooks import (
    apply_codex_merge,
    get_builtin_codex_entries,
    get_codex_config_path,
)
from forge.install.exceptions import TrackingCorruptedError
from forge.install.hook_migration import (
    KNOWN_LEGACY_HOOK_SHAPES,
    HookMigrationError,
    apply_project_hook_migration,
    known_legacy_hook_shape,
    list_hook_migration_candidates,
    plan_project_hook_migration,
)
from forge.install.models import (
    Installation,
    InstalledFile,
    InstalledManifest,
    InstalledSettingsEntry,
    InstalledSkillPackage,
    InstallMode,
    InstallModule,
    InstallProfile,
    InstallScope,
)
from forge.install.project_registry import (
    EnrollmentSource,
    ProjectRegistryStore,
    get_project_registry_path,
)
from forge.install.settings_merge import (
    entries_to_added_structure,
    find_backup_files,
    get_added_path,
    get_settings_path,
    load_added_settings,
    read_settings,
    save_added_settings,
)
from forge.install.tracking import TrackingStore


def _legacy_entry(
    handler: str = "session-start",
    *,
    matcher: str | None = None,
    timeout: int | None = None,
    command: str | None = None,
) -> dict[str, object]:
    hook: dict[str, object] = {
        "type": "command",
        "command": command or f"forge hook {handler}",
    }
    if timeout is not None:
        hook["timeout"] = timeout
    entry: dict[str, object] = {"hooks": [hook]}
    if matcher is not None:
        entry["matcher"] = matcher
    return entry


def _installation(root: Path, entry: dict[str, object]) -> Installation:
    return Installation(
        scope=InstallScope.PROJECT.value,
        project_path=str(root),
        mode=InstallMode.COPY.value,
        profile=InstallProfile.STANDARD.value,
        modules_enabled=[InstallModule.HOOKS.value, InstallModule.STATUSLINE.value],
        settings_entries=[
            InstalledSettingsEntry(
                key_path="hooks.SessionStart",
                value=entry,
                merge_type="append",
                stable_id=json.dumps(entry, sort_keys=True, separators=(",", ":")),
            )
        ],
        installed_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


def _forge_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".forge").mkdir(parents=True)
    (root / ".claude").mkdir()
    return root


def test_known_legacy_shape_normalizes_only_the_direct_command() -> None:
    bare = _legacy_entry()
    absolute = _legacy_entry(command="/opt/forge/bin/forge hook session-start")
    dispatcher = _legacy_entry(command="forge-hook session-start")
    changed = _legacy_entry(timeout=9)

    assert known_legacy_hook_shape("SessionStart", bare) is not None
    assert known_legacy_hook_shape("SessionStart", absolute) is not None
    assert known_legacy_hook_shape("SessionStart", dispatcher) is None
    assert known_legacy_hook_shape("SessionStart", changed) is None


def test_released_legacy_generation_is_frozen() -> None:
    assert [(shape.event, shape.matcher, shape.handler, shape.timeout) for shape in KNOWN_LEGACY_HOOK_SHAPES] == [
        ("SessionStart", None, "session-start", None),
        ("PreToolUse", "Read", "read-hygiene", 5),
        ("PreToolUse", "ExitPlanMode", "exit-plan-mode", None),
        ("PreToolUse", "Write", "policy-check", 60),
        ("PreToolUse", "Edit", "policy-check", 60),
        ("PostToolUse", "Write", "plan-write", None),
        ("Stop", None, "stop", None),
        ("StopFailure", None, "stop-failure", None),
        ("UserPromptSubmit", None, "user-prompt-submit", None),
        ("PreCompact", None, "pre-compact", 10),
        ("PostCompact", None, "post-compact", 5),
        ("WorktreeCreate", None, "worktree-create", 30),
        ("SubagentStop", None, "subagent-stop", 10),
        ("TeammateIdle", None, "teammate-idle", 60),
        ("TaskCompleted", None, "task-completed", 60),
        ("SessionEnd", None, "session-end", 5),
    ]


def test_candidate_discovery_never_enrolls_or_opens_root_settings(
    tmp_path: Path,
) -> None:
    root = _forge_root(tmp_path)
    settings = get_settings_path(InstallScope.PROJECT, root)
    settings.write_text("{not json", encoding="utf-8")
    tracking = TrackingStore()
    entry = _legacy_entry()
    tracking.set_installation(InstallScope.PROJECT.value, _installation(root, entry), str(root))

    candidates = list_hook_migration_candidates(tracking)

    assert len(candidates) == 1
    assert candidates[0].root == str(root.resolve())
    assert candidates[0].cleanup_command == f"forge extension cleanup-project --root {root.resolve()}"
    assert not get_project_registry_path().exists()


def test_stale_candidate_is_report_only(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    tracking = TrackingStore()
    tracking.set_installation(
        InstallScope.PROJECT.value,
        _installation(missing, _legacy_entry()),
        str(missing),
    )

    (candidate,) = list_hook_migration_candidates(tracking)

    assert candidate.stale is True
    assert candidate.cleanup_command is None
    assert candidate.reason == "tracked root no longer exists"


def test_cleanup_preview_rejects_unsupported_tracking_before_settings_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _forge_root(tmp_path)
    tracking = TrackingStore()
    tracking.path.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps({"version": 999, "installations": {}}, indent=2)
    tracking.path.write_text(original, encoding="utf-8")
    settings_reads: list[Path] = []

    def reject_settings_read(path: Path, *_args: object, **_kwargs: object) -> None:
        settings_reads.append(path)
        raise AssertionError(f"cleanup read settings after invalid tracking: {path}")

    monkeypatch.setattr("forge.install.hook_migration._plan_settings_cleanup", reject_settings_read)

    with pytest.raises(TrackingCorruptedError, match="incompatible version"):
        plan_project_hook_migration(root, tracking=tracking)

    assert settings_reads == []
    assert tracking.path.read_text(encoding="utf-8") == original


def test_cleanup_v1_preview_is_read_only_then_apply_writes_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _forge_root(tmp_path)
    entry = _legacy_entry()
    settings = get_settings_path(InstallScope.PROJECT, root)
    settings.write_text(json.dumps({"hooks": {"SessionStart": [entry]}}), encoding="utf-8")
    installation = asdict(_installation(root, entry))
    installation.pop("skill_packages")
    legacy = {
        "version": 1,
        "installations": {f"project:{root}": installation},
    }
    tracking = TrackingStore()
    tracking.path.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps(legacy, indent=2)
    tracking.path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        "forge.install.hook_migration.diagnose_hook_dispatcher",
        lambda: SimpleNamespace(status="current"),
    )

    plan = plan_project_hook_migration(root, tracking=tracking)

    assert plan.root == root.resolve()
    assert tracking.path.read_text(encoding="utf-8") == original

    monkeypatch.setattr("forge.install.hook_migration.install_hook_dispatcher", lambda: None)
    apply_project_hook_migration(root, tracking=tracking)

    persisted = json.loads(tracking.path.read_text(encoding="utf-8"))
    assert persisted["version"] == 2
    assert persisted["installations"][f"project:{root}"]["skill_packages"] == []


def test_v1_candidate_without_recoverable_path_is_not_guessed(tmp_path: Path) -> None:
    tracking = TrackingStore()
    tracking.write(
        InstalledManifest(
            installations={
                InstallScope.PROJECT.value: _installation(tmp_path / "ignored", _legacy_entry()),
            }
        )
    )

    (candidate,) = list_hook_migration_candidates(tracking)

    assert candidate.root is None
    assert candidate.stale is True
    assert candidate.cleanup_command is None
    assert candidate.reason == "tracking row has no recoverable project path"
    assert not get_project_registry_path().exists()


def test_ambiguous_legacy_wrapper_blocks_the_selected_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _forge_root(tmp_path)
    settings = get_settings_path(InstallScope.PROJECT, root)
    settings.write_text(
        json.dumps({"hooks": {"SessionStart": [_legacy_entry(timeout=9)]}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "forge.install.hook_migration.diagnose_hook_dispatcher",
        lambda: SimpleNamespace(status="current"),
    )

    plan = plan_project_hook_migration(root)

    assert plan.blockers
    assert "not a known removable shape" in plan.blockers[0]
    with pytest.raises(HookMigrationError, match="migration is blocked"):
        apply_project_hook_migration(root)
    assert json.loads(settings.read_text(encoding="utf-8"))["hooks"]["SessionStart"]
    assert not get_project_registry_path().exists()


def test_modified_tracked_wrapper_is_preserved_and_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _forge_root(tmp_path)
    tracked_entry = _legacy_entry()
    modified_entry = _legacy_entry(timeout=9)
    settings = get_settings_path(InstallScope.PROJECT, root)
    settings.write_text(
        json.dumps({"hooks": {"SessionStart": [modified_entry]}}),
        encoding="utf-8",
    )
    tracking = TrackingStore()
    tracking.set_installation(
        InstallScope.PROJECT.value,
        _installation(root, tracked_entry),
        str(root),
    )
    monkeypatch.setattr(
        "forge.install.hook_migration.diagnose_hook_dispatcher",
        lambda: SimpleNamespace(status="current"),
    )

    plan = plan_project_hook_migration(root, tracking=tracking)

    assert any("not a known removable shape" in blocker for blocker in plan.blockers)
    with pytest.raises(HookMigrationError, match="migration is blocked"):
        apply_project_hook_migration(root, tracking=tracking)
    assert read_settings(settings)["hooks"]["SessionStart"] == [modified_entry]


def test_malformed_tracked_added_payload_aborts_before_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _forge_root(tmp_path)
    entry = _legacy_entry()
    settings = get_settings_path(InstallScope.PROJECT, root)
    settings.write_text(json.dumps({"hooks": {"SessionStart": [entry]}}), encoding="utf-8")
    tracking = TrackingStore()
    tracking.set_installation(InstallScope.PROJECT.value, _installation(root, entry), str(root))
    added_path = get_added_path(settings, "20990101-000000")
    added_path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(
        "forge.install.hook_migration.diagnose_hook_dispatcher",
        lambda: SimpleNamespace(status="current"),
    )

    with pytest.raises(HookMigrationError, match="cannot read settings"):
        apply_project_hook_migration(root, tracking=tracking)

    assert read_settings(settings)["hooks"]["SessionStart"] == [entry]
    assert not get_project_registry_path().exists()


def test_duplicate_user_dispatcher_blocks_before_selected_root_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from copy import deepcopy

    from forge.install.preset import get_builtin_preset

    root = _forge_root(tmp_path)
    entry = _legacy_entry()
    project_settings = get_settings_path(InstallScope.PROJECT, root)
    project_settings.write_text(json.dumps({"hooks": {"SessionStart": [entry]}}), encoding="utf-8")
    dispatcher_entry = deepcopy(get_builtin_preset()["hooks"]["SessionStart"][0])
    user_settings = get_settings_path(InstallScope.USER)
    user_settings.parent.mkdir(parents=True, exist_ok=True)
    user_settings.write_text(
        json.dumps({"hooks": {"SessionStart": [dispatcher_entry, dispatcher_entry]}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "forge.install.hook_migration.diagnose_hook_dispatcher",
        lambda: SimpleNamespace(status="current"),
    )

    plan = plan_project_hook_migration(root)

    assert any("registered more than once" in blocker for blocker in plan.blockers)
    with pytest.raises(HookMigrationError, match="migration is blocked"):
        apply_project_hook_migration(root)
    assert read_settings(project_settings)["hooks"]["SessionStart"] == [entry]
    assert not get_project_registry_path().exists()


def test_backup_failure_is_actionable_and_precedes_project_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _forge_root(tmp_path)
    entry = _legacy_entry()
    settings = get_settings_path(InstallScope.PROJECT, root)
    settings.write_text(json.dumps({"hooks": {"SessionStart": [entry]}}), encoding="utf-8")
    monkeypatch.setattr(
        "forge.install.hook_migration.diagnose_hook_dispatcher",
        lambda: SimpleNamespace(status="current"),
    )

    def fail_backup(_path: Path) -> None:
        raise PermissionError("read-only fixture")

    monkeypatch.setattr("forge.install.hook_migration.backup_settings", fail_backup)

    with pytest.raises(HookMigrationError, match="before hook/config changes"):
        apply_project_hook_migration(root)

    assert read_settings(settings)["hooks"]["SessionStart"] == [entry]
    assert not get_project_registry_path().exists()


def test_apply_removes_legacy_before_user_transition_and_enrollment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _forge_root(tmp_path)
    entry = _legacy_entry()
    settings = get_settings_path(InstallScope.PROJECT, root)
    settings.write_text(
        json.dumps(
            {
                "hooks": {"SessionStart": [entry]},
                "statusLine": {"type": "command", "command": "forge status-line"},
                "permissions": {"allow": ["Read"]},
            }
        ),
        encoding="utf-8",
    )
    tracking = TrackingStore()
    project_installation = _installation(root, entry)
    project_skill_path = root / ".claude" / "skills" / "challenge" / "SKILL.md"
    project_package = InstalledSkillPackage(
        runtime="claude_code",
        skill="challenge",
        target_dir=str(project_skill_path.parent),
        file_paths=[str(project_skill_path)],
    )
    project_installation.files = [
        InstalledFile(
            target_path=str(project_skill_path),
            source_path=str(project_skill_path),
            checksum="unchanged",
            mode=InstallMode.COPY.value,
            installed_at="2026-01-01T00:00:00Z",
        )
    ]
    project_installation.skill_packages = [project_package]
    tracking.set_installation(InstallScope.PROJECT.value, project_installation, str(root))
    added_path = save_added_settings(settings, entries_to_added_structure(project_installation.settings_entries))
    monkeypatch.setattr(
        "forge.install.hook_migration.diagnose_hook_dispatcher",
        lambda: SimpleNamespace(status="current"),
    )
    monkeypatch.setattr("forge.install.hook_migration.install_hook_dispatcher", lambda: None)

    result = apply_project_hook_migration(root, tracking=tracking)

    migrated = read_settings(settings)
    assert "hooks" not in migrated
    assert migrated["statusLine"]["command"] == "forge status-line"
    assert migrated["permissions"] == {"allow": ["Read"]}
    user_settings = read_settings(get_settings_path(InstallScope.USER))
    assert user_settings["hooks"]["SessionStart"]
    assert ProjectRegistryStore().contains_root(root)
    project_install = tracking.get_installation(InstallScope.PROJECT.value, str(root))
    assert project_install is not None
    assert InstallModule.HOOKS.value not in project_install.modules_enabled
    assert project_install.skill_packages == [project_package]
    assert not [entry for entry in project_install.settings_entries if entry.key_path.startswith("hooks.")]
    assert "hooks" not in load_added_settings(settings)
    user_install = tracking.get_installation(InstallScope.USER.value)
    assert user_install is not None
    assert InstallModule.HOOKS.value in user_install.modules_enabled
    assert len([entry for entry in user_install.settings_entries if entry.key_path.startswith("hooks.")]) == len(
        KNOWN_LEGACY_HOOK_SHAPES
    )
    assert result.removed_hooks == 1
    assert result.enrollment_created is True
    assert added_path in result.changed_paths
    assert tracking.path in result.changed_paths
    assert get_project_registry_path() in result.changed_paths
    assert result.backup_paths

    repeated = apply_project_hook_migration(root, tracking=tracking)
    assert repeated.removed_hooks == 0
    assert repeated.changed_paths == ()
    assert repeated.backup_paths == ()
    assert repeated.enrollment_created is False


def test_disable_after_migration_does_not_restore_or_re_remove_legacy_hooks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from forge.install.installer import Installer

    root = _forge_root(tmp_path)
    hook_entry = _legacy_entry()
    permission_entry = InstalledSettingsEntry(
        key_path="permissions.allow",
        value="Read",
        merge_type="union",
        stable_id="Read",
    )
    settings = get_settings_path(InstallScope.PROJECT, root)
    settings.write_text(
        json.dumps(
            {
                "hooks": {"SessionStart": [hook_entry]},
                "permissions": {"allow": ["Read", "UserOwned"]},
                "custom": True,
            }
        ),
        encoding="utf-8",
    )
    installation = _installation(root, hook_entry)
    installation.modules_enabled.append(InstallModule.PERMISSIONS.value)
    installation.settings_entries.append(permission_entry)
    tracking = TrackingStore()
    tracking.set_installation(InstallScope.PROJECT.value, installation, str(root))
    save_added_settings(settings, entries_to_added_structure(installation.settings_entries))
    monkeypatch.setattr(
        "forge.install.hook_migration.diagnose_hook_dispatcher",
        lambda: SimpleNamespace(status="current"),
    )
    monkeypatch.setattr("forge.install.hook_migration.install_hook_dispatcher", lambda: None)

    apply_project_hook_migration(root, tracking=tracking)
    assert "hooks" not in read_settings(settings)

    Installer(
        scope=InstallScope.PROJECT,
        project_root=root,
        tracking_store=tracking,
    ).uninstall()

    disabled = read_settings(settings)
    assert "hooks" not in disabled
    assert disabled["permissions"]["allow"] == ["UserOwned"]
    assert disabled["custom"] is True
    assert tracking.get_installation(InstallScope.PROJECT.value, str(root)) is None


def test_enrollment_observes_clean_root_and_current_user_dispatcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from forge.install.hooks import find_forge_hook_registrations

    root = _forge_root(tmp_path)
    settings = get_settings_path(InstallScope.PROJECT, root)
    settings.write_text(
        json.dumps({"hooks": {"SessionStart": [_legacy_entry()]}}),
        encoding="utf-8",
    )
    registry = ProjectRegistryStore()
    enroll = registry.enroll
    observed: list[str] = []
    monkeypatch.setattr(
        "forge.install.hook_migration.diagnose_hook_dispatcher",
        lambda: SimpleNamespace(status="current"),
    )
    monkeypatch.setattr("forge.install.hook_migration.install_hook_dispatcher", lambda: None)

    def assert_transition_complete(selected_root: Path, source: EnrollmentSource):
        assert "hooks" not in read_settings(settings)
        registrations = find_forge_hook_registrations(root)
        assert registrations
        assert {registration.scope for registration in registrations} == {InstallScope.USER.value}
        assert all("forge-hook" in registration.command for registration in registrations)
        observed.append("enroll")
        return enroll(selected_root, source)

    monkeypatch.setattr(registry, "enroll", assert_transition_complete)

    apply_project_hook_migration(root, registry=registry)

    assert observed == ["enroll"]


def test_user_runtime_transition_preserves_unrelated_tracked_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    root = _forge_root(tmp_path)
    settings = get_settings_path(InstallScope.PROJECT, root)
    settings.write_text(json.dumps({"hooks": {"SessionStart": [_legacy_entry()]}}), encoding="utf-8")
    user_file = tmp_path / "command.md"
    user_file.write_text("keep", encoding="utf-8")
    permission_entry = InstalledSettingsEntry(
        key_path="permissions.allow",
        value="Read",
        merge_type="union",
        stable_id="Read",
    )
    package_file = tmp_path / ".agents" / "skills" / "challenge" / "SKILL.md"
    user_install = Installation(
        scope=InstallScope.USER.value,
        mode=InstallMode.COPY.value,
        profile=InstallProfile.MINIMAL.value,
        modules_enabled=[InstallModule.COMMANDS.value, InstallModule.PERMISSIONS.value],
        files=[
            InstalledFile(
                target_path=str(user_file),
                source_path=str(user_file),
                checksum="unchanged",
                mode=InstallMode.COPY.value,
                installed_at="2026-01-01T00:00:00Z",
            ),
            InstalledFile(
                target_path=str(package_file),
                source_path=str(package_file),
                checksum="unchanged",
                mode=InstallMode.COPY.value,
                installed_at="2026-01-01T00:00:00Z",
            ),
        ],
        skill_packages=[
            InstalledSkillPackage(
                runtime="codex",
                skill="challenge",
                target_dir=str(package_file.parent),
                file_paths=[str(package_file)],
            )
        ],
        settings_entries=[permission_entry],
        installed_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    tracking = TrackingStore()
    tracking.set_installation(InstallScope.USER.value, user_install)
    monkeypatch.setattr(
        "forge.install.hook_migration.diagnose_hook_dispatcher",
        lambda: SimpleNamespace(status="current"),
    )
    monkeypatch.setattr("forge.install.hook_migration.install_hook_dispatcher", lambda: None)

    apply_project_hook_migration(root, tracking=tracking)

    updated = tracking.get_installation(InstallScope.USER.value)
    assert updated is not None
    assert set(updated.modules_enabled) == {
        InstallModule.COMMANDS.value,
        InstallModule.PERMISSIONS.value,
        InstallModule.HOOKS.value,
    }
    assert updated.files == user_install.files
    assert updated.skill_packages == user_install.skill_packages
    assert permission_entry in updated.settings_entries


def test_codex_block_moves_to_user_scope_after_project_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    root = _forge_root(tmp_path)
    project_config = get_codex_config_path(InstallScope.PROJECT, root)
    project_config.parent.mkdir()
    project_config.write_text('model = "gpt-5"\n', encoding="utf-8")
    apply_codex_merge(project_config, get_builtin_codex_entries())
    tracking = TrackingStore()
    tracking.set_installation(
        InstallScope.PROJECT.value,
        Installation(
            scope=InstallScope.PROJECT.value,
            project_path=str(root),
            mode=InstallMode.COPY.value,
            profile=InstallProfile.STANDARD.value,
            modules_enabled=[InstallModule.CODEX_HOOKS.value],
            codex_config_path=str(project_config),
            installed_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        ),
        str(root),
    )
    monkeypatch.setattr(
        "forge.install.hook_migration.diagnose_hook_dispatcher",
        lambda: SimpleNamespace(status="current"),
    )
    monkeypatch.setattr("forge.install.hook_migration.install_hook_dispatcher", lambda: None)

    result = apply_project_hook_migration(root, tracking=tracking)

    assert "# >>> forge hooks >>>" not in project_config.read_text(encoding="utf-8")
    assert 'model = "gpt-5"' in project_config.read_text(encoding="utf-8")
    assert "# >>> forge hooks >>>" in get_codex_config_path(InstallScope.USER).read_text(encoding="utf-8")
    updated_project = tracking.get_installation(InstallScope.PROJECT.value, str(root))
    assert updated_project is not None
    assert updated_project.codex_config_path is None
    assert InstallModule.CODEX_HOOKS.value not in updated_project.modules_enabled
    updated_user = tracking.get_installation(InstallScope.USER.value)
    assert updated_user is not None
    assert InstallModule.CODEX_HOOKS.value in updated_user.modules_enabled
    assert any(".config.toml.forge.backup." in path.name for path in result.backup_paths)
    assert result.user_codex_action == "install"


def test_enrollment_failure_reports_hooks_off_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    root = _forge_root(tmp_path)
    entry = _legacy_entry()
    settings = get_settings_path(InstallScope.PROJECT, root)
    settings.write_text(json.dumps({"hooks": {"SessionStart": [entry]}}), encoding="utf-8")
    tracking = TrackingStore()
    tracking.set_installation(InstallScope.PROJECT.value, _installation(root, entry), str(root))
    registry = ProjectRegistryStore()
    monkeypatch.setattr(
        "forge.install.hook_migration.diagnose_hook_dispatcher",
        lambda: SimpleNamespace(status="current"),
    )
    monkeypatch.setattr("forge.install.hook_migration.install_hook_dispatcher", lambda: None)

    def fail_enrollment(_root: Path, _source: str) -> None:
        raise OSError("injected registry failure")

    monkeypatch.setattr(registry, "enroll", fail_enrollment)

    with pytest.raises(HookMigrationError, match="hooks may be temporarily off") as exc_info:
        apply_project_hook_migration(root, tracking=tracking, registry=registry)

    assert "cleanup-project --root" in str(exc_info.value)
    assert "hooks" not in read_settings(settings)
    assert not get_project_registry_path().exists()


def test_dispatcher_write_failure_keeps_backups_and_reports_hooks_off_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _forge_root(tmp_path)
    entry = _legacy_entry()
    settings = get_settings_path(InstallScope.PROJECT, root)
    settings.write_text(json.dumps({"hooks": {"SessionStart": [entry]}}), encoding="utf-8")
    tracking = TrackingStore()
    tracking.set_installation(InstallScope.PROJECT.value, _installation(root, entry), str(root))
    monkeypatch.setattr(
        "forge.install.hook_migration.diagnose_hook_dispatcher",
        lambda: SimpleNamespace(status="missing"),
    )

    def fail_dispatcher_write() -> None:
        raise OSError("injected dispatcher write failure")

    monkeypatch.setattr("forge.install.hook_migration.install_hook_dispatcher", fail_dispatcher_write)

    with pytest.raises(HookMigrationError, match="hooks may be temporarily off") as exc_info:
        apply_project_hook_migration(root, tracking=tracking)

    assert "cleanup-project --root" in str(exc_info.value)
    assert "injected dispatcher write failure" in str(exc_info.value)
    assert "hooks" not in read_settings(settings)
    backups = find_backup_files(settings)
    assert backups
    assert read_settings(backups[0])["hooks"]["SessionStart"] == [entry]
    assert not get_project_registry_path().exists()

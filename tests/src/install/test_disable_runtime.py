"""Runtime-scoped extension disable tests."""

from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path

import pytest

from forge.core.runtime_vocab import CLAUDE_CODE_RUNTIME, CODEX_RUNTIME
from forge.install import path_policy as path_policy_module
from forge.install import runtime_removal as runtime_removal_module
from forge.install.codex_hooks import (
    CODEX_BLOCK_BEGIN,
    apply_codex_merge,
    get_builtin_codex_entries,
)
from forge.install.exceptions import (
    CodexConfigScopeMismatchError,
    ForgeInstallError,
    PathBoundaryViolationError,
)
from forge.install.installer import Installer
from forge.install.models import (
    TRACKING_VERSION,
    Installation,
    InstalledFile,
    InstalledManifest,
    InstalledSettingsEntry,
    InstalledSkillPackage,
    InstallModule,
    InstallScope,
    ModuleOwner,
)
from forge.install.ownership import attributed, unattributed
from forge.install.runtime_removal import build_runtime_removal_plan
from forge.install.settings_merge import (
    entries_to_added_structure,
    find_added_files,
    read_settings,
    save_added_settings,
    write_settings,
)
from forge.install.tracking import TrackingStore, _validate_current_manifest


def _tracked_file(path: Path, module: InstallModule, runtime: str) -> InstalledFile:
    return InstalledFile(
        target_path=str(path),
        source_path=str(path.parent / f"source-{path.name}"),
        checksum=f"checksum-{path.name}",
        mode="copy",
        installed_at="2026-01-01T00:00:00+00:00",
        attribution=attributed(module, runtime),
    )


def _settings_entry(
    key_path: str,
    module: InstallModule,
    value: object,
    *,
    merge_type: str,
) -> InstalledSettingsEntry:
    return InstalledSettingsEntry(
        key_path=key_path,
        value=value,
        merge_type=merge_type,
        stable_id=key_path,
        attribution=attributed(module, CLAUDE_CODE_RUNTIME),
    )


def _dual_installation(tmp_path: Path) -> Installation:
    claude_skill = tmp_path / ".claude" / "skills" / "review" / "SKILL.md"
    codex_skill = tmp_path / ".agents" / "skills" / "review" / "SKILL.md"
    files = [
        _tracked_file(
            tmp_path / ".claude" / "commands" / "review.md",
            InstallModule.COMMANDS,
            CLAUDE_CODE_RUNTIME,
        ),
        _tracked_file(
            tmp_path / ".claude" / "agents" / "review.md",
            InstallModule.AGENTS,
            CLAUDE_CODE_RUNTIME,
        ),
        _tracked_file(claude_skill, InstallModule.SKILLS, CLAUDE_CODE_RUNTIME),
        _tracked_file(codex_skill, InstallModule.SKILLS, CODEX_RUNTIME),
    ]
    settings_entries = [
        _settings_entry(
            "hooks.PreToolUse",
            InstallModule.HOOKS,
            {"hooks": [{"type": "command", "command": "forge-hook pre-tool-use"}]},
            merge_type="append",
        ),
        _settings_entry(
            "statusLine",
            InstallModule.STATUSLINE,
            {"type": "command", "command": "forge status-line"},
            merge_type="scalar",
        ),
        _settings_entry(
            "permissions.allow",
            InstallModule.PERMISSIONS,
            "Bash(forge:*)",
            merge_type="union",
        ),
    ]
    owners = [
        attributed(module, runtime)
        for module, runtimes in {
            InstallModule.COMMANDS: (CLAUDE_CODE_RUNTIME,),
            InstallModule.AGENTS: (CLAUDE_CODE_RUNTIME,),
            InstallModule.SKILLS: (CLAUDE_CODE_RUNTIME, CODEX_RUNTIME),
            InstallModule.HOOKS: (CLAUDE_CODE_RUNTIME, CODEX_RUNTIME),
            InstallModule.STATUSLINE: (CLAUDE_CODE_RUNTIME,),
            InstallModule.PERMISSIONS: (CLAUDE_CODE_RUNTIME,),
        }.items()
        for runtime in runtimes
    ]
    return Installation(
        scope="project",
        project_path=str(tmp_path),
        mode="copy",
        profile="standard",
        module_owners=sorted(owners),
        files=files,
        skill_packages=[
            InstalledSkillPackage(
                runtime=CLAUDE_CODE_RUNTIME,
                skill="review",
                target_dir=str(claude_skill.parent),
                file_paths=[str(claude_skill)],
            ),
            InstalledSkillPackage(
                runtime=CODEX_RUNTIME,
                skill="review",
                target_dir=str(codex_skill.parent),
                file_paths=[str(codex_skill)],
            ),
        ],
        settings_entries=settings_entries,
        settings_backup_path=str(tmp_path / ".claude" / ".settings.json.forge.backup.20260101-000000"),
        codex_config_path=str(tmp_path / ".codex" / "config.toml"),
        codex_commands=["forge-hook codex-session-start"],
        installed_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def _materialize_dual_installation(
    tmp_path: Path,
) -> tuple[Installation, TrackingStore, Path, Path, Path]:
    installation = _dual_installation(tmp_path)
    for file_record in installation.files:
        target = Path(file_record.target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        assert isinstance(file_record.attribution, ModuleOwner)
        target.write_text(
            f"owned:{file_record.attribution.module}:{file_record.attribution.runtime}\n",
            encoding="utf-8",
        )

    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = Path(installation.settings_backup_path or "")
    baseline = {"userSetting": "preserve"}
    added = entries_to_added_structure(installation.settings_entries)
    current = deepcopy(baseline)
    current.update(added)
    write_settings(settings_path, current)
    write_settings(backup_path, baseline)
    added_path = save_added_settings(settings_path, added)

    config_path = Path(installation.codex_config_path or "")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text('model = "gpt-5.5-codex"\n', encoding="utf-8")
    apply_codex_merge(config_path, get_builtin_codex_entries())

    tracking = TrackingStore(tmp_path / ".forge" / "installed.json")
    tracking.set_installation(InstallScope.PROJECT.value, installation, str(tmp_path))
    return installation, tracking, settings_path, added_path, backup_path


def test_removal_plan_selects_every_claude_surface_and_preserves_codex(
    tmp_path: Path,
) -> None:
    installation = _dual_installation(tmp_path)

    plan = build_runtime_removal_plan(installation, (CLAUDE_CODE_RUNTIME,))

    assert plan.disposition == "partial"
    assert {getattr(record.attribution, "module", None) for record in plan.files} == {
        InstallModule.COMMANDS.value,
        InstallModule.AGENTS.value,
        InstallModule.SKILLS.value,
    }
    assert {getattr(record.attribution, "module", None) for record in plan.settings_entries} == {
        InstallModule.HOOKS.value,
        InstallModule.STATUSLINE.value,
        InstallModule.PERMISSIONS.value,
    }
    assert [(package.runtime, package.skill) for package in plan.skill_packages] == [(CLAUDE_CODE_RUNTIME, "review")]
    assert {(owner.module, owner.runtime) for owner in plan.module_owners} == {
        (InstallModule.COMMANDS.value, CLAUDE_CODE_RUNTIME),
        (InstallModule.AGENTS.value, CLAUDE_CODE_RUNTIME),
        (InstallModule.SKILLS.value, CLAUDE_CODE_RUNTIME),
        (InstallModule.HOOKS.value, CLAUDE_CODE_RUNTIME),
        (InstallModule.STATUSLINE.value, CLAUDE_CODE_RUNTIME),
        (InstallModule.PERMISSIONS.value, CLAUDE_CODE_RUNTIME),
    }
    assert not plan.remove_codex_block
    assert plan.post_installation.codex_config_path == installation.codex_config_path
    assert plan.post_installation.codex_commands == installation.codex_commands


def test_removal_plan_returns_selected_and_surviving_settings(tmp_path: Path) -> None:
    installation = _dual_installation(tmp_path)

    claude_plan = build_runtime_removal_plan(installation, (CLAUDE_CODE_RUNTIME,))
    codex_plan = build_runtime_removal_plan(installation, (CODEX_RUNTIME,))

    assert claude_plan.settings_entries == tuple(installation.settings_entries)
    assert claude_plan.surviving_settings_entries == ()
    assert codex_plan.settings_entries == ()
    assert codex_plan.surviving_settings_entries == tuple(installation.settings_entries)
    assert codex_plan.post_installation.settings_backup_path == installation.settings_backup_path


def test_removal_plan_post_installation_satisfies_v3_invariants(tmp_path: Path) -> None:
    installation = _dual_installation(tmp_path)

    plan = build_runtime_removal_plan(installation, (CODEX_RUNTIME,))
    manifest = InstalledManifest(
        version=TRACKING_VERSION,
        installations={"project:" + str(tmp_path): plan.post_installation},
    )

    _validate_current_manifest(tmp_path / "installed.json", manifest)
    assert plan.post_installation.codex_config_path is None
    assert plan.post_installation.codex_commands == []
    assert all(package.runtime != CODEX_RUNTIME for package in plan.post_installation.skill_packages)
    assert all(getattr(record.attribution, "runtime", None) != CODEX_RUNTIME for record in plan.post_installation.files)


def test_runtime_selection_intersects_with_tracked_ownership(tmp_path: Path) -> None:
    installation = _dual_installation(tmp_path)
    claude_only = build_runtime_removal_plan(installation, (CODEX_RUNTIME,)).post_installation

    plan = build_runtime_removal_plan(claude_only, (CODEX_RUNTIME,))

    assert plan.disposition == "no-op"
    assert plan.files == ()
    assert plan.settings_entries == ()
    assert plan.skill_packages == ()
    assert plan.module_owners == ()
    assert plan.post_installation == claude_only


def test_partial_removal_retains_and_reports_unattributed_rows(tmp_path: Path) -> None:
    installation = _dual_installation(tmp_path)
    legacy_file = InstalledFile(
        target_path=str(tmp_path / "legacy" / "unknown"),
        source_path=str(tmp_path / "source" / "unknown"),
        checksum="legacy",
        mode="copy",
        installed_at="2026-01-01T00:00:00+00:00",
        attribution=unattributed("legacy_path_unmapped"),
    )
    legacy_setting = InstalledSettingsEntry(
        key_path="legacy.unknown",
        value="owned-before-v3",
        merge_type="scalar",
        stable_id="legacy.unknown",
        attribution=unattributed("legacy_key_unmapped"),
    )
    installation.files.append(legacy_file)
    installation.settings_entries.append(legacy_setting)

    plan = build_runtime_removal_plan(installation, (CLAUDE_CODE_RUNTIME,))

    assert legacy_file not in plan.files
    assert legacy_setting not in plan.settings_entries
    assert legacy_file in plan.post_installation.files
    assert legacy_setting in plan.surviving_settings_entries
    assert plan.retained_unattributed_count == 2
    assert plan.retained_unattributed_reasons == (
        "legacy_key_unmapped",
        "legacy_path_unmapped",
    )


@pytest.mark.parametrize(
    "runtime_ids,from_installation",
    [
        ((CLAUDE_CODE_RUNTIME, CODEX_RUNTIME), "dual"),
        ((CLAUDE_CODE_RUNTIME, CODEX_RUNTIME, CLAUDE_CODE_RUNTIME), "dual"),
        ((CODEX_RUNTIME,), "codex-only"),
    ],
)
def test_removal_plan_detects_full_coverage(
    tmp_path: Path,
    runtime_ids: tuple[str, ...],
    from_installation: str,
) -> None:
    installation = _dual_installation(tmp_path)
    if from_installation == "codex-only":
        installation = build_runtime_removal_plan(installation, (CLAUDE_CODE_RUNTIME,)).post_installation
    legacy_file = InstalledFile(
        target_path=str(tmp_path / "legacy" / "unknown"),
        source_path=str(tmp_path / "source" / "unknown"),
        checksum="legacy",
        mode="copy",
        installed_at="2026-01-01T00:00:00+00:00",
        attribution=unattributed("legacy_path_unmapped"),
    )
    installation.files.append(legacy_file)

    plan = build_runtime_removal_plan(installation, runtime_ids)

    assert plan.full_coverage
    assert plan.disposition == "full"
    assert legacy_file in plan.files
    assert plan.retained_unattributed_count == 0
    assert plan.post_installation.files == []
    assert plan.post_installation.module_owners == []


def test_codex_removal_leaves_every_claude_surface_byte_identical(
    tmp_path: Path,
) -> None:
    installation, tracking, settings_path, added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    claude_paths = [
        Path(record.target_path)
        for record in installation.files
        if getattr(record.attribution, "runtime", None) == CLAUDE_CODE_RUNTIME
    ]
    claude_bytes = {path: path.read_bytes() for path in claude_paths}
    settings_bytes = settings_path.read_bytes()
    added_bytes = added_path.read_bytes()

    plan = installer.uninstall_runtimes((CODEX_RUNTIME,))

    assert plan.disposition == "partial"
    assert {path: path.read_bytes() for path in claude_paths} == claude_bytes
    assert settings_path.read_bytes() == settings_bytes
    assert added_path.read_bytes() == added_bytes
    assert not any(
        Path(record.target_path).exists()
        for record in installation.files
        if getattr(record.attribution, "runtime", None) == CODEX_RUNTIME
    )
    config_path = Path(installation.codex_config_path or "")
    assert config_path.read_text(encoding="utf-8") == 'model = "gpt-5.5-codex"\n'
    surviving = tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path))
    assert surviving is not None
    assert surviving.profile == installation.profile
    assert {owner.runtime for owner in surviving.module_owners} == {CLAUDE_CODE_RUNTIME}
    assert surviving.codex_config_path is None
    assert surviving.codex_commands == []


def test_claude_removal_is_symmetric_and_clears_settings_ownership(
    tmp_path: Path,
) -> None:
    installation, tracking, settings_path, added_path, backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    codex_paths = [
        Path(record.target_path)
        for record in installation.files
        if getattr(record.attribution, "runtime", None) == CODEX_RUNTIME
    ]
    codex_bytes = {path: path.read_bytes() for path in codex_paths}
    config_path = Path(installation.codex_config_path or "")
    config_bytes = config_path.read_bytes()

    plan = installer.uninstall_runtimes((CLAUDE_CODE_RUNTIME,))

    assert plan.disposition == "partial"
    assert {path: path.read_bytes() for path in codex_paths} == codex_bytes
    assert config_path.read_bytes() == config_bytes
    assert not any(
        Path(record.target_path).exists()
        for record in installation.files
        if getattr(record.attribution, "runtime", None) == CLAUDE_CODE_RUNTIME
    )
    assert settings_path.read_text(encoding="utf-8") == '{\n  "userSetting": "preserve"\n}\n'
    assert not added_path.exists()
    assert backup_path.exists()
    surviving = tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path))
    assert surviving is not None
    assert surviving.settings_entries == []
    assert surviving.settings_backup_path is None
    assert {owner.runtime for owner in surviving.module_owners} == {CODEX_RUNTIME}


def test_user_runtime_removal_uses_environment_target(
    tmp_path: Path,
    isolate_claude_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _settings_entry(
        "statusLine",
        InstallModule.STATUSLINE,
        {"type": "command", "command": "forge status-line"},
        merge_type="scalar",
    )
    installation = Installation(
        scope=InstallScope.USER.value,
        mode="copy",
        profile="standard",
        module_owners=[attributed(InstallModule.STATUSLINE, CLAUDE_CODE_RUNTIME)],
        settings_entries=[entry],
        installed_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    settings_path = isolate_claude_home / "settings.json"
    write_settings(settings_path, {"statusLine": entry.value})
    save_added_settings(settings_path, entries_to_added_structure([entry]))
    tracking = TrackingStore(tmp_path / "forge-home" / "installed.json")
    tracking.set_installation(InstallScope.USER.value, installation)

    validations: list[tuple[Path, Path, str]] = []
    real_validate = runtime_removal_module.validate_path_within_boundary

    def capture_validation(path: Path, boundary: Path, operation: str = "delete") -> None:
        validations.append((path, boundary, operation))
        real_validate(path, boundary, operation)

    monkeypatch.setattr(runtime_removal_module, "validate_path_within_boundary", capture_validation)

    plan = Installer(scope=InstallScope.USER, tracking_store=tracking).uninstall_runtimes((CLAUDE_CODE_RUNTIME,))

    assert plan.full_coverage
    assert (settings_path, isolate_claude_home, "update settings") in validations
    assert all(boundary == isolate_claude_home for _path, boundary, _operation in validations)
    assert tracking.get_installation(InstallScope.USER.value) is None


def test_claude_removal_reads_recorded_baseline_instead_of_newest_history(tmp_path: Path) -> None:
    installation, tracking, settings_path, _added_path, baseline_path = _materialize_dual_installation(tmp_path)
    newer_backup = settings_path.parent / ".settings.json.forge.backup.20270101-000000"
    write_settings(newer_backup, read_settings(settings_path))
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )

    installer.uninstall_runtimes((CLAUDE_CODE_RUNTIME,))

    assert read_settings(settings_path) == {"userSetting": "preserve"}
    assert baseline_path.exists()
    assert newer_backup.exists()
    surviving = tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path))
    assert surviving is not None
    assert surviving.settings_backup_path is None
    assert {owner.runtime for owner in surviving.module_owners} == {CODEX_RUNTIME}


def test_null_legacy_baseline_does_not_adopt_newest_history(tmp_path: Path) -> None:
    installation, tracking, settings_path, _added_path, baseline_path = _materialize_dual_installation(tmp_path)
    newer_backup = settings_path.parent / ".settings.json.forge.backup.20270101-000000"
    write_settings(newer_backup, read_settings(settings_path))
    installation.settings_backup_path = None
    tracking.set_installation(InstallScope.PROJECT.value, installation, str(tmp_path))
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )

    installer.uninstall_runtimes((CLAUDE_CODE_RUNTIME,))

    assert read_settings(settings_path) == {"userSetting": "preserve"}
    assert baseline_path.exists()
    assert newer_backup.exists()
    surviving = tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path))
    assert surviving is not None
    assert surviving.settings_backup_path is None


@pytest.mark.parametrize("baseline_state", ["missing", "unreadable", "unsafe"])
def test_invalid_recorded_baseline_refuses_runtime_removal_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    baseline_state: str,
) -> None:
    installation, tracking, settings_path, added_path, baseline_path = _materialize_dual_installation(tmp_path)
    if baseline_state == "missing":
        baseline_path.unlink()
    elif baseline_state == "unreadable":
        real_read_baseline = runtime_removal_module.read_tracked_settings_baseline

        def fail_read(path: Path | None) -> dict[str, object]:
            if path == baseline_path:
                raise PermissionError("injected unreadable baseline")
            return real_read_baseline(path)

        monkeypatch.setattr(runtime_removal_module, "read_tracked_settings_baseline", fail_read)
    else:
        unsafe_path = tmp_path / "outside-settings-baseline.json"
        write_settings(unsafe_path, {"userSetting": "preserve"})
        installation.settings_backup_path = str(unsafe_path)
        tracking.set_installation(InstallScope.PROJECT.value, installation, str(tmp_path))

    settings_before = settings_path.read_bytes()
    added_before = added_path.read_bytes()
    tracked_paths = [Path(record.target_path) for record in installation.files]
    expected_error = PathBoundaryViolationError if baseline_state == "unsafe" else ForgeInstallError
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )

    with pytest.raises(expected_error):
        installer.uninstall_runtimes((CLAUDE_CODE_RUNTIME,))

    assert all(path.exists() for path in tracked_paths)
    assert settings_path.read_bytes() == settings_before
    assert added_path.read_bytes() == added_before
    assert tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path)) == installation


def test_zero_row_claude_settings_ownership_clears_sidecars_without_rewriting_settings(
    tmp_path: Path,
) -> None:
    installation, tracking, settings_path, added_path, backup_path = _materialize_dual_installation(tmp_path)
    installation.settings_entries = []
    tracking.set_installation(InstallScope.PROJECT.value, installation, str(tmp_path))
    settings_bytes = b'{ "userSetting": "preserve" }\n'
    settings_path.write_bytes(settings_bytes)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )

    plan = installer.uninstall_runtimes((CLAUDE_CODE_RUNTIME,))

    assert not plan.full_coverage
    assert settings_path.read_bytes() == settings_bytes
    assert not added_path.exists()
    assert backup_path.exists()
    surviving = tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path))
    assert surviving is not None
    assert surviving.settings_backup_path is None


def test_codex_only_full_removal_preserves_unowned_malformed_claude_settings(
    tmp_path: Path,
) -> None:
    installation, tracking, settings_path, added_path, _backup_path = _materialize_dual_installation(tmp_path)
    codex_only = build_runtime_removal_plan(
        installation,
        (CLAUDE_CODE_RUNTIME,),
    ).post_installation
    tracking.set_installation(InstallScope.PROJECT.value, codex_only, str(tmp_path))
    settings_bytes = b"{ not valid json\n"
    settings_path.write_bytes(settings_bytes)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )

    plan = installer.uninstall_runtimes((CODEX_RUNTIME,))

    assert plan.full_coverage
    assert settings_path.read_bytes() == settings_bytes
    assert not added_path.exists()
    assert tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path)) is None


def test_user_readded_setting_survives_later_last_runtime_removal(
    tmp_path: Path,
) -> None:
    _installation, tracking, settings_path, _added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    installer.uninstall_runtimes((CLAUDE_CODE_RUNTIME,))
    write_settings(
        settings_path,
        {
            "userSetting": "preserve",
            "permissions": {"allow": ["Bash(forge:*)"]},
        },
    )

    plan = installer.uninstall_runtimes((CODEX_RUNTIME,))

    assert plan.full_coverage
    assert tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path)) is None
    assert settings_path.read_text(encoding="utf-8") == (
        "{\n"
        '  "userSetting": "preserve",\n'
        '  "permissions": {\n'
        '    "allow": [\n'
        '      "Bash(forge:*)"\n'
        "    ]\n"
        "  }\n"
        "}\n"
    )


def test_partial_retains_unattributed_surfaces_and_full_removal_clears_them(
    tmp_path: Path,
) -> None:
    installation, tracking, settings_path, added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    legacy_path = tmp_path / ".claude" / "legacy" / "unknown"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text("legacy managed\n", encoding="utf-8")
    legacy_file = InstalledFile(
        target_path=str(legacy_path),
        source_path=str(tmp_path / "source" / "legacy"),
        checksum="legacy",
        mode="copy",
        installed_at="2026-01-01T00:00:00+00:00",
        attribution=unattributed("legacy_path_unmapped"),
    )
    legacy_setting = InstalledSettingsEntry(
        key_path="legacySetting",
        value="managed",
        merge_type="scalar",
        stable_id="legacySetting",
        attribution=unattributed("legacy_key_unmapped"),
    )
    installation.files.append(legacy_file)
    installation.settings_entries.append(legacy_setting)
    current_settings = {
        "userSetting": "preserve",
        **entries_to_added_structure(installation.settings_entries),
    }
    write_settings(settings_path, current_settings)
    write_settings(added_path, entries_to_added_structure(installation.settings_entries))
    tracking.set_installation(InstallScope.PROJECT.value, installation, str(tmp_path))

    partial = installer.uninstall_runtimes((CLAUDE_CODE_RUNTIME,))

    assert not partial.full_coverage
    assert partial.retained_unattributed_count == 2
    assert legacy_path.exists()
    surviving = tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path))
    assert surviving is not None
    assert legacy_file in surviving.files
    assert legacy_setting in surviving.settings_entries
    assert surviving.settings_backup_path == installation.settings_backup_path
    assert read_settings(added_path) == {"legacySetting": "managed"}

    full = installer.uninstall_runtimes((CODEX_RUNTIME,))

    assert full.full_coverage
    assert not legacy_path.exists()
    assert tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path)) is None
    assert "legacySetting" not in settings_path.read_text(encoding="utf-8")


def test_runtime_full_removal_preserves_modified_legacy_scalar_and_env(
    tmp_path: Path,
) -> None:
    installation, tracking, settings_path, added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    installation = build_runtime_removal_plan(installation, (CODEX_RUNTIME,)).post_installation
    installation.settings_entries = [
        InstalledSettingsEntry(
            key_path="statusLine",
            value="forge status-line",
            merge_type="scalar",
            stable_id="statusLine",
            attribution=attributed(InstallModule.STATUSLINE, CLAUDE_CODE_RUNTIME),
        ),
        InstalledSettingsEntry(
            key_path="env.FORGE_MODE",
            value="managed",
            merge_type="scalar",
            stable_id="env.FORGE_MODE",
            attribution=attributed(InstallModule.PERMISSIONS, CLAUDE_CODE_RUNTIME),
        ),
    ]
    installation.codex_config_path = None
    installation.codex_commands = []
    tracking.set_installation(InstallScope.PROJECT.value, installation, str(tmp_path))
    added_path.unlink()
    write_settings(
        settings_path,
        {
            "userSetting": "preserve",
            "statusLine": "user replacement",
            "env": {"FORGE_MODE": "user replacement"},
        },
    )

    plan = installer.uninstall_runtimes((CLAUDE_CODE_RUNTIME,))

    assert plan.full_coverage
    assert tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path)) is None
    assert settings_path.read_text(encoding="utf-8") == (
        "{\n"
        '  "userSetting": "preserve",\n'
        '  "statusLine": "user replacement",\n'
        '  "env": {\n'
        '    "FORGE_MODE": "user replacement"\n'
        "  }\n"
        "}\n"
    )


def test_settings_write_fault_restores_settings_and_reconciles_removed_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation, tracking, settings_path, added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    settings_before = settings_path.read_bytes()
    added_before = added_path.read_bytes()
    settings_mode = settings_path.stat().st_mode
    added_mode = added_path.stat().st_mode
    real_write_settings = runtime_removal_module.write_settings

    def fail_settings_write(path: Path, settings: dict[str, object]) -> None:
        if path == settings_path:
            raise OSError("injected settings write fault")
        real_write_settings(path, settings)

    monkeypatch.setattr(runtime_removal_module, "write_settings", fail_settings_write)

    with pytest.raises(ForgeInstallError, match="Settings and ownership sidecars were restored exactly"):
        installer.uninstall_runtimes((CLAUDE_CODE_RUNTIME,))

    assert settings_path.read_bytes() == settings_before
    assert added_path.read_bytes() == added_before
    assert settings_path.stat().st_mode == settings_mode
    assert added_path.stat().st_mode == added_mode
    reconciled = tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path))
    assert reconciled is not None
    assert reconciled.settings_entries == installation.settings_entries
    assert all(getattr(record.attribution, "runtime", None) != CLAUDE_CODE_RUNTIME for record in reconciled.files)
    assert any(owner.runtime == CLAUDE_CODE_RUNTIME for owner in reconciled.module_owners)


def test_sidecar_fault_rolls_back_settings_and_every_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation, tracking, settings_path, added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    settings_before = settings_path.read_bytes()
    older_added_path = settings_path.parent / ".settings.json.forge.added.20250101-000000"
    write_settings(older_added_path, {"older": "ownership"})
    older_added_path.chmod(0o640)
    added_before = {path: (path.read_bytes(), path.stat().st_mode) for path in find_added_files(settings_path)}
    real_unlink = Path.unlink

    def fail_added_unlink(path: Path, missing_ok: bool = False) -> None:
        if path == added_path:
            raise OSError("injected sidecar unlink fault")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_added_unlink)

    with pytest.raises(ForgeInstallError, match="Settings and ownership sidecars were restored exactly"):
        installer.uninstall_runtimes((CLAUDE_CODE_RUNTIME,))

    assert settings_path.read_bytes() == settings_before
    assert {path: (path.read_bytes(), path.stat().st_mode) for path in find_added_files(settings_path)} == added_before
    reconciled = tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path))
    assert reconciled is not None
    assert reconciled.settings_entries == installation.settings_entries


def test_incomplete_settings_rollback_names_manual_recovery_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation, tracking, settings_path, added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    real_unlink = Path.unlink

    def fail_added_unlink(path: Path, missing_ok: bool = False) -> None:
        if path == added_path:
            raise OSError("injected sidecar unlink fault")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_added_unlink)
    monkeypatch.setattr(
        runtime_removal_module,
        "restore_settings_rollback_state",
        lambda _state: [str(settings_path), str(added_path)],
    )

    with pytest.raises(ForgeInstallError) as exc_info:
        installer.uninstall_runtimes((CLAUDE_CODE_RUNTIME,))

    assert str(settings_path) in str(exc_info.value)
    assert str(added_path) in str(exc_info.value)
    reconciled = tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path))
    assert reconciled is not None
    assert reconciled.settings_entries == installation.settings_entries


def test_reconciliation_fault_preserves_incomplete_settings_rollback_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation, tracking, settings_path, added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    real_unlink = Path.unlink

    def fail_added_unlink(path: Path, missing_ok: bool = False) -> None:
        if path == added_path:
            raise OSError("injected sidecar unlink fault")
        real_unlink(path, missing_ok=missing_ok)

    def fail_tracking_write(
        _scope: str,
        _installation: Installation,
        _project_path: str | None,
    ) -> None:
        raise OSError("injected reconciliation write fault")

    monkeypatch.setattr(Path, "unlink", fail_added_unlink)
    monkeypatch.setattr(
        runtime_removal_module,
        "restore_settings_rollback_state",
        lambda _state: [str(settings_path), str(added_path)],
    )
    monkeypatch.setattr(tracking, "set_installation", fail_tracking_write)

    with pytest.raises(ForgeInstallError) as exc_info:
        installer.uninstall_runtimes((CLAUDE_CODE_RUNTIME,))

    message = str(exc_info.value)
    assert str(tracking.path) in message
    assert str(settings_path) in message
    assert str(added_path) in message
    assert tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path)) == installation


def test_malformed_codex_markers_refuse_before_any_mutation(tmp_path: Path) -> None:
    installation, tracking, settings_path, added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    config_path = Path(installation.codex_config_path or "")
    config_path.write_text(
        config_path.read_text(encoding="utf-8") + f"\n{CODEX_BLOCK_BEGIN}\n",
        encoding="utf-8",
    )
    path_bytes = {Path(record.target_path): Path(record.target_path).read_bytes() for record in installation.files}
    settings_before = settings_path.read_bytes()
    added_before = added_path.read_bytes()
    config_before = config_path.read_bytes()

    with pytest.raises(ForgeInstallError, match="partial, duplicated, or unbalanced"):
        installer.uninstall_runtimes((CODEX_RUNTIME,))

    assert {path: path.read_bytes() for path in path_bytes} == path_bytes
    assert settings_path.read_bytes() == settings_before
    assert added_path.read_bytes() == added_before
    assert config_path.read_bytes() == config_before
    assert tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path)) == installation


def test_codex_only_full_removal_refuses_malformed_markers_before_files(
    tmp_path: Path,
) -> None:
    installation, tracking, _settings_path, _added_path, _backup_path = _materialize_dual_installation(tmp_path)
    codex_only = build_runtime_removal_plan(installation, (CLAUDE_CODE_RUNTIME,)).post_installation
    tracking.set_installation(InstallScope.PROJECT.value, codex_only, str(tmp_path))
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    config_path = Path(codex_only.codex_config_path or "")
    config_path.write_text(
        config_path.read_text(encoding="utf-8") + f"\n{CODEX_BLOCK_BEGIN}\n",
        encoding="utf-8",
    )
    codex_paths = [Path(record.target_path) for record in codex_only.files]
    config_before = config_path.read_bytes()

    with pytest.raises(ForgeInstallError, match="partial, duplicated, or unbalanced"):
        installer.uninstall_runtimes((CODEX_RUNTIME,))

    assert all(path.exists() for path in codex_paths)
    assert config_path.read_bytes() == config_before
    assert tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path)) == codex_only


def test_unreadable_codex_config_refuses_before_any_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation, tracking, _settings_path, _added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    config_path = Path(installation.codex_config_path or "")
    codex_skill = next(
        Path(record.target_path)
        for record in installation.files
        if getattr(record.attribution, "runtime", None) == CODEX_RUNTIME
    )
    real_read_text = Path.read_text

    def fail_config_read(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        if path == config_path:
            raise PermissionError("injected unreadable config")
        return real_read_text(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", fail_config_read)

    with pytest.raises(ForgeInstallError, match="cannot read"):
        installer.uninstall_runtimes((CODEX_RUNTIME,))

    assert codex_skill.exists()
    assert tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path)) == installation


@pytest.mark.parametrize("config_state", ["absent", "no-markers"])
def test_stale_codex_block_state_clears_tracking(
    tmp_path: Path,
    config_state: str,
) -> None:
    installation, tracking, _settings_path, _added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    config_path = Path(installation.codex_config_path or "")
    if config_state == "absent":
        config_path.unlink()
        expected_content = None
    else:
        expected_content = 'model = "user-owned"\n'
        config_path.write_text(expected_content, encoding="utf-8")

    installer.uninstall_runtimes((CODEX_RUNTIME,))

    surviving = tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path))
    assert surviving is not None
    assert surviving.codex_config_path is None
    assert surviving.codex_commands == []
    assert all(
        not (owner.module == InstallModule.HOOKS.value and owner.runtime == CODEX_RUNTIME)
        for owner in surviving.module_owners
    )
    if expected_content is None:
        assert not config_path.exists()
    else:
        assert config_path.read_text(encoding="utf-8") == expected_content


def test_manual_codex_sibling_is_preserved_and_warned(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    installation, tracking, _settings_path, _added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    config_path = Path(installation.codex_config_path or "")
    manual = (
        "\n[[hooks.Stop]]\n" "[[hooks.Stop.hooks]]\n" 'type = "command"\n' 'command = "forge-hook custom-handler"\n'
    )
    config_path.write_text(config_path.read_text(encoding="utf-8") + manual, encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        installer.uninstall_runtimes((CODEX_RUNTIME,))

    assert manual in config_path.read_text(encoding="utf-8")
    assert "forge-hook custom-handler" in caplog.text
    surviving = tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path))
    assert surviving is not None
    assert surviving.codex_config_path is None


def test_codex_scope_drift_blocks_codex_but_not_claude_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation, tracking, _settings_path, _added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    monkeypatch.setattr(
        path_policy_module,
        "get_codex_config_path",
        lambda _scope, _project_root: tmp_path / "drifted" / "config.toml",
    )
    codex_skill = next(
        Path(record.target_path)
        for record in installation.files
        if getattr(record.attribution, "runtime", None) == CODEX_RUNTIME
    )

    with pytest.raises(CodexConfigScopeMismatchError):
        installer.uninstall_runtimes((CODEX_RUNTIME,))
    assert codex_skill.exists()

    installer.uninstall_runtimes((CLAUDE_CODE_RUNTIME,))

    surviving = tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path))
    assert surviving is not None
    assert surviving.codex_config_path == installation.codex_config_path
    assert codex_skill.exists()


def test_leaf_symlinked_codex_config_refuses_before_any_mutation(
    tmp_path: Path,
) -> None:
    installation, tracking, settings_path, added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    config_path = Path(installation.codex_config_path or "")
    config_target = tmp_path / "codex-config-target.toml"
    config_path.replace(config_target)
    config_path.symlink_to(config_target)
    file_bytes = {Path(record.target_path): Path(record.target_path).read_bytes() for record in installation.files}
    settings_before = settings_path.read_bytes()
    added_before = added_path.read_bytes()
    config_before = config_target.read_bytes()

    with pytest.raises(ForgeInstallError, match="symbolic link"):
        installer.uninstall_runtimes((CODEX_RUNTIME,))

    assert config_path.is_symlink()
    assert config_target.read_bytes() == config_before
    assert {path: path.read_bytes() for path in file_bytes} == file_bytes
    assert settings_path.read_bytes() == settings_before
    assert added_path.read_bytes() == added_before
    assert tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path)) == installation


def test_symlink_replaced_skill_package_root_refuses_before_mutation(
    tmp_path: Path,
) -> None:
    installation, tracking, settings_path, added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    codex_package = next(package for package in installation.skill_packages if package.runtime == CODEX_RUNTIME)
    package_dir = Path(codex_package.target_dir)
    Path(codex_package.file_paths[0]).unlink()
    package_dir.rmdir()
    outside = tmp_path / "outside-package"
    outside.mkdir()
    (outside / "SKILL.md").write_text("outside\n", encoding="utf-8")
    package_dir.symlink_to(outside, target_is_directory=True)
    settings_before = settings_path.read_bytes()
    added_before = added_path.read_bytes()
    config_path = Path(installation.codex_config_path or "")
    config_before = config_path.read_bytes()

    with pytest.raises(PathBoundaryViolationError):
        installer.uninstall_runtimes((CODEX_RUNTIME,))

    assert package_dir.is_symlink()
    assert settings_path.read_bytes() == settings_before
    assert added_path.read_bytes() == added_before
    assert config_path.read_bytes() == config_before
    assert tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path)) == installation


def test_file_removal_fault_reconciles_only_files_actually_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation, tracking, settings_path, added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    command_path = next(
        Path(record.target_path)
        for record in installation.files
        if getattr(record.attribution, "module", None) == InstallModule.COMMANDS.value
    )
    agent_path = next(
        Path(record.target_path)
        for record in installation.files
        if getattr(record.attribution, "module", None) == InstallModule.AGENTS.value
    )
    settings_before = settings_path.read_bytes()
    added_before = added_path.read_bytes()
    real_unlink = Path.unlink

    def fail_agent_unlink(path: Path, missing_ok: bool = False) -> None:
        if path == agent_path:
            raise OSError("injected file removal fault")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_agent_unlink)

    with pytest.raises(ForgeInstallError, match="Tracking was reconciled.*rerun"):
        installer.uninstall_runtimes((CLAUDE_CODE_RUNTIME,))

    assert not command_path.exists()
    assert agent_path.exists()
    assert settings_path.read_bytes() == settings_before
    assert added_path.read_bytes() == added_before
    reconciled = tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path))
    assert reconciled is not None
    assert command_path.as_posix() not in {record.target_path for record in reconciled.files}
    assert agent_path.as_posix() in {record.target_path for record in reconciled.files}
    _validate_current_manifest(
        tracking.path,
        InstalledManifest(
            version=TRACKING_VERSION,
            installations={"project:" + str(tmp_path): reconciled},
        ),
    )


def test_codex_apply_race_reconciles_earlier_file_removal_and_retains_codex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation, tracking, _settings_path, _added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    codex_skill = next(
        Path(record.target_path)
        for record in installation.files
        if getattr(record.attribution, "runtime", None) == CODEX_RUNTIME
    )

    def fail_codex_apply(*_args: object, **_kwargs: object) -> None:
        raise ForgeInstallError("injected concurrent Codex change")

    monkeypatch.setattr(runtime_removal_module, "apply_codex_runtime_remove", fail_codex_apply)

    with pytest.raises(ForgeInstallError, match="Codex ownership was retained"):
        installer.uninstall_runtimes((CODEX_RUNTIME,))

    assert not codex_skill.exists()
    reconciled = tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path))
    assert reconciled is not None
    assert reconciled.codex_config_path == installation.codex_config_path
    assert any(
        owner.module == InstallModule.HOOKS.value and owner.runtime == CODEX_RUNTIME
        for owner in reconciled.module_owners
    )
    assert all(package.runtime != CODEX_RUNTIME for package in reconciled.skill_packages)


def test_tracking_write_fault_restores_settings_but_reports_file_and_codex_overclaim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation, tracking, settings_path, added_path, _backup_path = _materialize_dual_installation(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=tmp_path,
        tracking_store=tracking,
    )
    settings_before = settings_path.read_bytes()
    added_before = added_path.read_bytes()
    config_path = Path(installation.codex_config_path or "")

    def fail_tracking_remove(_scope: str, _project_path: str | None) -> bool:
        raise OSError("injected tracking write fault")

    monkeypatch.setattr(tracking, "remove_installation", fail_tracking_remove)

    with pytest.raises(ForgeInstallError) as exc_info:
        installer.uninstall_runtimes((CLAUDE_CODE_RUNTIME, CODEX_RUNTIME))

    message = str(exc_info.value)
    assert str(tracking.path) in message
    assert "already changed the filesystem" in message
    assert "settings and ownership sidecars were restored" in message
    assert settings_path.read_bytes() == settings_before
    assert added_path.read_bytes() == added_before
    assert CODEX_BLOCK_BEGIN not in config_path.read_text(encoding="utf-8")
    assert all(not Path(record.target_path).exists() for record in installation.files)
    assert tracking.get_installation(InstallScope.PROJECT.value, str(tmp_path)) == installation

"""Tests for forge.install.models."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from forge.core.runtime_vocab import (
    AGENT_RUNTIME_IDS,
    CLAUDE_CODE_RUNTIME,
    CODEX_RUNTIME,
)
from forge.install.models import (
    FILE_MODULES,
    MODULE_DEPENDENCIES,
    MODULE_RUNTIME_OWNERS,
    PROFILE_MODULES,
    SETTINGS_ONLY_MODULES,
    TRACKING_VERSION,
    FilePlan,
    Installation,
    InstalledFile,
    InstalledManifest,
    InstalledSettingsEntry,
    InstalledSkillPackage,
    InstallMode,
    InstallModule,
    InstallPlan,
    InstallProfile,
    InstallScope,
    SettingsPlan,
)
from forge.install.ownership import attributed


class TestEnums:
    """Tests for enum definitions."""

    def test_install_scope_values(self) -> None:
        assert InstallScope.USER.value == "user"
        assert InstallScope.PROJECT.value == "project"
        assert InstallScope.LOCAL.value == "local"

    def test_install_mode_values(self) -> None:
        assert InstallMode.COPY.value == "copy"
        assert InstallMode.SYMLINK.value == "symlink"

    def test_install_profile_values(self) -> None:
        assert InstallProfile.MINIMAL.value == "minimal"
        assert InstallProfile.STANDARD.value == "standard"
        assert InstallProfile.FULL.value == "full"

    def test_install_module_values(self) -> None:
        assert InstallModule.COMMANDS.value == "commands"
        assert InstallModule.AGENTS.value == "agents"
        assert InstallModule.SKILLS.value == "skills"
        assert InstallModule.HOOKS.value == "hooks"
        assert InstallModule.STATUSLINE.value == "status-line"
        assert InstallModule.PERMISSIONS.value == "permissions"


class TestProfileModules:
    """Tests for profile -> modules mapping."""

    def test_minimal_profile(self) -> None:
        assert PROFILE_MODULES[InstallProfile.MINIMAL] == {InstallModule.COMMANDS}

    def test_standard_profile(self) -> None:
        expected = {
            InstallModule.COMMANDS,
            InstallModule.AGENTS,
            InstallModule.SKILLS,
            InstallModule.HOOKS,
            InstallModule.PERMISSIONS,
            InstallModule.STATUSLINE,
        }
        assert PROFILE_MODULES[InstallProfile.STANDARD] == expected

    def test_standard_profile_includes_skills(self) -> None:
        """Skills are included in standard profile."""
        assert InstallModule.SKILLS in PROFILE_MODULES[InstallProfile.STANDARD]

    def test_minimal_profile_excludes_skills(self) -> None:
        assert InstallModule.SKILLS not in PROFILE_MODULES[InstallProfile.MINIMAL]

    def test_full_profile(self) -> None:
        assert PROFILE_MODULES[InstallProfile.FULL] == set(InstallModule)

    def test_full_profile_includes_all_modules(self) -> None:
        full_modules = PROFILE_MODULES[InstallProfile.FULL]
        for module in InstallModule:
            assert module in full_modules


class TestModuleDependencies:
    """Tests for module dependencies."""

    def test_no_forced_dependencies(self) -> None:
        assert MODULE_DEPENDENCIES == {}


class TestModuleRuntimeOwners:
    """Tests for the install-module runtime ownership vocabulary."""

    def test_every_module_declares_only_known_runtime_owners(self) -> None:
        assert set(MODULE_RUNTIME_OWNERS) == set(InstallModule)
        assert all(MODULE_RUNTIME_OWNERS[module] for module in InstallModule)
        assert {runtime for owners in MODULE_RUNTIME_OWNERS.values() for runtime in owners} <= set(AGENT_RUNTIME_IDS)

    def test_hooks_declares_both_runtime_owners(self) -> None:
        assert MODULE_RUNTIME_OWNERS[InstallModule.HOOKS] == set(AGENT_RUNTIME_IDS)


class TestModuleCategories:
    """Tests for module categorization."""

    def test_file_modules(self) -> None:
        assert InstallModule.COMMANDS in FILE_MODULES
        assert InstallModule.AGENTS in FILE_MODULES
        assert InstallModule.SKILLS in FILE_MODULES
        # HOOKS is settings-only (all hooks are dispatcher commands)
        assert InstallModule.HOOKS not in FILE_MODULES
        # STATUSLINE is now settings-only (uses `forge status-line` command)
        assert InstallModule.STATUSLINE not in FILE_MODULES

    def test_settings_only_modules(self) -> None:
        assert InstallModule.PERMISSIONS in SETTINGS_ONLY_MODULES
        # HOOKS is settings-only (no files to copy)
        assert InstallModule.HOOKS in SETTINGS_ONLY_MODULES
        # STATUSLINE is settings-only (uses `forge status-line` command)
        assert InstallModule.STATUSLINE in SETTINGS_ONLY_MODULES

    def test_no_overlap_between_categories(self) -> None:
        assert not (FILE_MODULES & SETTINGS_ONLY_MODULES)


class TestInstalledFile:
    """Tests for InstalledFile dataclass."""

    def test_create_installed_file(self) -> None:
        f = InstalledFile(
            target_path="/target/path",
            source_path="/source/path",
            checksum="abc123",
            mode="copy",
            installed_at="2024-01-01T00:00:00+00:00",
            attribution=attributed(InstallModule.COMMANDS, "claude_code"),
        )
        assert f.target_path == "/target/path"
        assert f.source_path == "/source/path"
        assert f.checksum == "abc123"
        assert f.mode == "copy"


class TestInstalledSettingsEntry:
    """Tests for InstalledSettingsEntry dataclass."""

    def test_create_entry(self) -> None:
        entry = InstalledSettingsEntry(
            key_path="hooks.PreToolUse",
            value={"hooks": []},
            merge_type="append",
            stable_id="/path/to/command",
            attribution=attributed(InstallModule.HOOKS, "claude_code"),
        )
        assert entry.key_path == "hooks.PreToolUse"
        assert entry.merge_type == "append"
        assert entry.stable_id == "/path/to/command"


class TestInstallation:
    """Tests for Installation dataclass."""

    def test_create_installation(self) -> None:
        inst = Installation(
            scope="user",
            mode="copy",
            profile="standard",
        )
        assert inst.scope == "user"
        assert inst.mode == "copy"
        assert inst.profile == "standard"
        assert inst.module_owners == []
        assert inst.files == []
        assert inst.settings_entries == []

    def test_installation_defaults(self) -> None:
        inst = Installation(scope="user", mode="copy", profile="standard")
        assert inst.settings_backup_path is None
        assert inst.skill_packages == []
        assert inst.installed_at == ""
        assert inst.updated_at == ""

    def test_runtime_skill_package_tracks_group_without_duplicating_file_metadata(self) -> None:
        package = InstalledSkillPackage(
            runtime="codex",
            skill="challenge",
            target_dir="/home/user/.agents/skills/challenge",
            file_paths=[
                "/home/user/.agents/skills/challenge/SKILL.md",
                "/home/user/.agents/skills/challenge/agents/openai.yaml",
            ],
        )

        inst = Installation(scope="user", mode="copy", profile="standard", skill_packages=[package])

        assert inst.skill_packages == [package]
        assert inst.files == []


class TestInstalledManifest:
    """Tests for InstalledManifest dataclass."""

    def test_create_manifest(self) -> None:
        manifest = InstalledManifest()
        assert manifest.version == TRACKING_VERSION
        assert manifest.installations == {}

    def test_manifest_with_installation(self, sample_installation: Installation) -> None:
        manifest = InstalledManifest(installations={"user": sample_installation})
        assert "user" in manifest.installations
        assert manifest.installations["user"].scope == "user"


class TestFilePlan:
    """Tests for FilePlan dataclass."""

    def test_create_file_plan(self) -> None:
        plan = FilePlan(
            action="install",
            target_path="/target",
            effective_mode=InstallMode.COPY,
            source_path="/source",
            module=InstallModule.COMMANDS.value,
            runtime=CLAUDE_CODE_RUNTIME,
        )
        assert plan.action == "install"
        assert plan.effective_mode == InstallMode.COPY
        assert plan.reason is None
        assert plan.module == InstallModule.COMMANDS.value

    def test_file_plan_with_reason(self) -> None:
        plan = FilePlan(
            action="conflict",
            target_path="/target",
            effective_mode=InstallMode.SYMLINK,
            reason="file exists",
            module=InstallModule.SKILLS.value,
            runtime=CODEX_RUNTIME,
        )
        assert plan.reason == "file exists"

    def test_file_plan_requires_provenance(self) -> None:
        with pytest.raises(TypeError, match="module.*runtime"):
            FilePlan(  # type: ignore[call-arg]
                action="install",
                target_path="/target",
                effective_mode=InstallMode.COPY,
            )

    @pytest.mark.parametrize(
        ("module", "runtime", "message"),
        [
            ("", "", "unknown file-plan module"),
            (InstallModule.COMMANDS.value, CODEX_RUNTIME, "cannot be owned"),
        ],
    )
    def test_file_plan_rejects_invalid_provenance(self, module: str, runtime: str, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            FilePlan(
                action="install",
                target_path="/target",
                effective_mode=InstallMode.COPY,
                module=module,
                runtime=runtime,
            )

    def test_file_plan_is_immutable(self) -> None:
        plan = FilePlan(
            action="install",
            target_path="/target",
            effective_mode=InstallMode.COPY,
            module=InstallModule.COMMANDS.value,
            runtime=CLAUDE_CODE_RUNTIME,
        )

        with pytest.raises(FrozenInstanceError):
            setattr(plan, "runtime", CODEX_RUNTIME)


class TestSettingsPlan:
    """Tests for SettingsPlan dataclass."""

    def test_create_settings_plan(self) -> None:
        plan = SettingsPlan(
            action="merge",
            key_path="hooks.PreToolUse",
            value="(append)",
        )
        assert plan.action == "merge"
        assert plan.key_path == "hooks.PreToolUse"


class TestInstallPlan:
    """Tests for InstallPlan dataclass."""

    def test_create_install_plan(self) -> None:
        plan = InstallPlan(
            scope="user",
            mode="copy",
            profile="standard",
            modules=["commands", "agents"],
        )
        assert plan.scope == "user"
        assert not plan.has_conflicts
        assert plan.conflicts == []

    def test_install_plan_with_conflicts(self) -> None:
        plan = InstallPlan(
            scope="user",
            mode="copy",
            profile="standard",
            has_conflicts=True,
            conflicts=["File: /path - exists"],
        )
        assert plan.has_conflicts
        assert len(plan.conflicts) == 1

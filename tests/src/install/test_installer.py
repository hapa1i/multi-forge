"""Tests for forge.install.installer."""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from forge.core.paths import get_forge_home
from forge.core.runtime import get_runtime
from forge.core.runtime_vocab import CLAUDE_CODE_RUNTIME, CODEX_RUNTIME
from forge.install.exceptions import (
    CodexConfigScopeMismatchError,
    ForgeInstallError,
    NoClaudeDirectoryError,
    NoForgeInstallationError,
    NotInstalledError,
    PathBoundaryViolationError,
)
from forge.install.hook_dispatcher import render_dispatcher_command
from forge.install.installer import (
    Installer,
    find_claude_root,
    find_forge_installation,
    get_extensions_root,
    get_forge_source_root,
    resolve_modules,
)
from forge.install.models import (
    FilePlan,
    Installation,
    InstalledFile,
    InstalledSettingsEntry,
    InstallMode,
    InstallModule,
    InstallPlan,
    InstallProfile,
    InstallScope,
)
from forge.install.ownership import attributed, module_values
from forge.install.settings_merge import (
    entries_to_added_structure,
    load_added_settings,
    read_settings,
    save_added_settings,
    write_settings,
)
from forge.install.tracking import TrackingStore


def _normalize_forge_home(command: str) -> str:
    return command.replace(str(get_forge_home()), "$FORGE_HOME")


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


class TestGetForgeSourceRoot:
    """Tests for get_forge_source_root function."""

    def test_returns_path(self) -> None:
        root = get_forge_source_root()
        assert isinstance(root, Path)
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
    def setup_installer(
        self,
        tmp_path: Path,
        isolate_claude_home: Path,
    ) -> Generator[tuple[Installer, Path, Path, Path], None, None]:
        """Set up installer with all temp directories."""
        forge_home = tmp_path / ".forge"
        forge_home.mkdir()

        claude_home = isolate_claude_home

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
            installer.init(profile=InstallProfile.MINIMAL)

        assert (forge_home / "installed.json").exists()

    def test_init_installs_files(self, setup_installer: tuple[Installer, Path, Path, Path]) -> None:
        installer, forge_home, claude_home, src = setup_installer

        with patch(
            "forge.install.installer.get_forge_source_root",
            return_value=src.parent,
        ):
            installer.init(profile=InstallProfile.MINIMAL)

        assert (claude_home / "commands" / "test.md").exists()

    def test_init_runs_apply_phases_in_transaction_order(
        self,
        setup_installer: tuple[Installer, Path, Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        installer, _forge_home, _claude_home, src = setup_installer
        calls: list[str] = []

        def record_method(name: str, original: Any) -> Any:
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                calls.append(name)
                return original(*args, **kwargs)

            return wrapped

        phase_methods = (
            ("prepare", "_prepare_install_apply"),
            ("cache", "_materialize_install_skill_cache"),
            ("dispatcher", "_apply_install_dispatcher"),
            ("files", "_apply_install_files"),
            ("settings", "_apply_install_settings"),
            ("stale", "_reconcile_install_stale_files"),
            ("codex", "_apply_install_codex"),
            ("assembly", "_assemble_installation"),
        )
        for phase, method_name in phase_methods:
            monkeypatch.setattr(
                installer,
                method_name,
                record_method(phase, getattr(installer, method_name)),
            )
        monkeypatch.setattr(
            installer._tracking,
            "set_installation",
            record_method("tracking", installer._tracking.set_installation),
        )

        with patch("forge.install.installer.get_forge_source_root", return_value=src.parent):
            installer.init(profile=InstallProfile.MINIMAL)

        assert calls == [
            "prepare",
            "cache",
            "dispatcher",
            "files",
            "settings",
            "stale",
            "codex",
            "assembly",
            "tracking",
        ]

    def test_init_rejects_file_ownership_outside_resolved_plan_before_writes(
        self,
        setup_installer: tuple[Installer, Path, Path, Path],
    ) -> None:
        installer, forge_home, claude_home, src = setup_installer
        target = claude_home / "commands" / "test.md"
        invalid_plan = InstallPlan(
            scope=InstallScope.USER.value,
            mode=InstallMode.COPY.value,
            profile=InstallProfile.MINIMAL.value,
            modules=[InstallModule.COMMANDS.value],
            selected_runtimes=[CLAUDE_CODE_RUNTIME],
            files=[
                FilePlan(
                    action="install",
                    target_path=str(target),
                    effective_mode=InstallMode.COPY,
                    source_path=str(src / "commands" / "test.md"),
                    module=InstallModule.SKILLS.value,
                    runtime=CODEX_RUNTIME,
                )
            ],
        )

        with (
            patch.object(installer, "plan", return_value=invalid_plan),
            pytest.raises(ForgeInstallError, match="outside the resolved module/runtime set"),
        ):
            installer.init(profile=InstallProfile.MINIMAL)

        assert not target.exists()
        assert not (forge_home / "installed.json").exists()

    def test_init_is_idempotent(self, setup_installer: tuple[Installer, Path, Path, Path]) -> None:
        installer, forge_home, claude_home, src = setup_installer

        with patch(
            "forge.install.installer.get_forge_source_root",
            return_value=src.parent,
        ):
            installer.init(profile=InstallProfile.MINIMAL)
            plan2 = installer.init(profile=InstallProfile.MINIMAL)

        skip_count = sum(1 for f in plan2.files if f.action == "skip")
        install_count = sum(1 for f in plan2.files if f.action == "install")

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
            installer.init(profile=InstallProfile.STANDARD)

        settings = json.loads((claude_home / "settings.json").read_text())
        allow = settings["permissions"]["allow"]
        assert "Bash(npm test)" in allow
        assert "Write" in allow
        assert "Edit" in allow

    def test_init_gates_settings_by_selected_modules(
        self,
        setup_installer: tuple[Installer, Path, Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A hooks-only module set writes hooks without permissions or env."""
        import json

        from forge.install.preset import get_builtin_preset, get_preset_path

        installer, forge_home, claude_home, src = setup_installer

        monkeypatch.setenv("FORGE_HOME", str(forge_home))
        monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
        preset = get_builtin_preset()
        preset["env"] = {"CUSTOM": "1"}
        get_preset_path().write_text(json.dumps(preset), encoding="utf-8")

        with patch(
            "forge.install.installer.get_forge_source_root",
            return_value=src.parent,
        ):
            plan = installer.init(
                profile=InstallProfile.MINIMAL,
                with_modules={InstallModule.HOOKS},
                without_modules={InstallModule.COMMANDS},
            )

        settings = json.loads((claude_home / "settings.json").read_text())
        assert settings["hooks"] == get_builtin_preset()["hooks"]
        assert "permissions" not in settings
        assert "env" not in settings
        installation = installer._tracking.get_installation("user", None)
        assert installation is not None
        assert module_values(installation) == {"hooks"}
        assert {entry.key_path.split(".", 1)[0] for entry in installation.settings_entries} == {"hooks"}
        assert plan.modules == ["hooks"]
        assert {entry.key_path.split(".", 1)[0] for entry in plan.settings} == {"hooks"}

    def test_standard_profile_still_writes_hooks_permissions_and_env(
        self,
        setup_installer: tuple[Installer, Path, Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Standard remains the no-regression anchor for normal installs."""
        import json

        from forge.install.preset import get_builtin_preset, get_preset_path

        installer, forge_home, claude_home, src = setup_installer

        monkeypatch.setenv("FORGE_HOME", str(forge_home))
        monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
        preset = get_builtin_preset()
        preset["env"] = {"CUSTOM": "1"}
        get_preset_path().write_text(json.dumps(preset), encoding="utf-8")

        with patch(
            "forge.install.installer.get_forge_source_root",
            return_value=src.parent,
        ):
            installer.init(profile=InstallProfile.STANDARD)

        settings = json.loads((claude_home / "settings.json").read_text())
        assert settings["hooks"] == get_builtin_preset()["hooks"]
        assert settings["permissions"]["allow"]
        assert settings["env"] == {"CUSTOM": "1"}


class TestInstallerScopeModulePolicy:
    """Tests the ownership split between user runtime hooks and project settings."""

    @staticmethod
    def _source_root(tmp_path: Path) -> Path:
        src = tmp_path / "src"
        src.mkdir(parents=True)
        (src / "forge").mkdir()
        commands = src / "commands"
        commands.mkdir()
        (commands / "test.md").write_text("# Test Command\n")
        (src / "agents").mkdir()
        (src / "skills").mkdir()
        return tmp_path

    def test_local_standard_filters_runtime_hooks_but_keeps_statusline(self, tmp_path: Path) -> None:
        import json

        project = tmp_path / "repo"
        (project / ".claude").mkdir(parents=True)
        source_root = self._source_root(tmp_path / "forge-src")
        tracking = TrackingStore(tracking_path=tmp_path / "forge-home" / "installed.json")
        installer = Installer(scope=InstallScope.LOCAL, project_root=project, tracking_store=tracking)

        with (
            patch(
                "forge.install.installer.get_forge_source_root",
                return_value=source_root,
            ),
            patch("forge.install.installer._codex_available", return_value=True),
        ):
            plan = installer.init(profile=InstallProfile.STANDARD)

        settings = json.loads((project / ".claude" / "settings.local.json").read_text())
        assert "hooks" not in settings
        assert "statusLine" in settings
        assert plan.codex is None
        installation = tracking.get_installation("local", str(project))
        assert installation is not None
        assert "hooks" not in module_values(installation)
        assert "status-line" in module_values(installation)

    def test_local_standard_still_renders_hook_dispatcher_for_lifecycle_compatibility(self, tmp_path: Path) -> None:
        project = tmp_path / "repo"
        (project / ".claude").mkdir(parents=True)
        source_root = self._source_root(tmp_path / "forge-src")
        tracking = TrackingStore(tracking_path=tmp_path / "forge-home" / "installed.json")
        installer = Installer(scope=InstallScope.LOCAL, project_root=project, tracking_store=tracking)

        with (
            patch(
                "forge.install.installer.get_forge_source_root",
                return_value=source_root,
            ),
            patch("forge.install.installer._codex_available", return_value=True),
            patch("forge.install.installer.install_hook_dispatcher") as render,
        ):
            installer.init(profile=InstallProfile.STANDARD)

        render.assert_called_once()

    def test_user_standard_filters_statusline_but_keeps_runtime_hooks(
        self,
        tmp_path: Path,
        isolate_claude_home: Path,
    ) -> None:
        import json

        claude_home = isolate_claude_home
        source_root = self._source_root(tmp_path / "forge-src")
        tracking = TrackingStore(tracking_path=tmp_path / "forge-home" / "installed.json")
        installer = Installer(scope=InstallScope.USER, tracking_store=tracking)

        with (
            patch(
                "forge.install.installer.get_forge_source_root",
                return_value=source_root,
            ),
            patch("forge.install.installer._codex_available", return_value=False),
        ):
            plan = installer.init(profile=InstallProfile.STANDARD)

        settings = json.loads((claude_home / "settings.json").read_text())
        assert "hooks" in settings
        assert "statusLine" not in settings
        assert "status-line" not in plan.modules
        installation = tracking.get_installation("user", None)
        assert installation is not None
        assert "hooks" in module_values(installation)
        assert "status-line" not in module_values(installation)

    def test_explicit_scope_contradictions_are_rejected(self, tmp_path: Path) -> None:
        project = tmp_path / "repo"
        (project / ".claude").mkdir(parents=True)
        local = Installer(
            scope=InstallScope.LOCAL,
            project_root=project,
            tracking_store=TrackingStore(tracking_path=tmp_path / "local" / "installed.json"),
        )
        user = Installer(
            scope=InstallScope.USER,
            tracking_store=TrackingStore(tracking_path=tmp_path / "user" / "installed.json"),
        )

        with pytest.raises(ForgeInstallError, match="user-scope only"):
            local.plan(profile=InstallProfile.MINIMAL, with_modules={InstallModule.HOOKS})
        with pytest.raises(ForgeInstallError, match="install it at project/local scope"):
            user.plan(profile=InstallProfile.MINIMAL, with_modules={InstallModule.STATUSLINE})

    def test_filtered_local_update_preserves_legacy_hook_tracking_for_disable(self, tmp_path: Path) -> None:
        import json

        project = tmp_path / "repo"
        (project / ".claude").mkdir(parents=True)
        settings_path = project / ".claude" / "settings.local.json"
        legacy_hook = {"hooks": [{"type": "command", "command": "forge hook session-start"}]}
        settings_path.write_text(
            json.dumps({"hooks": {"SessionStart": [legacy_hook]}}),
            encoding="utf-8",
        )

        source_root = self._source_root(tmp_path / "forge-src")
        tracking = TrackingStore(tracking_path=tmp_path / "forge-home" / "installed.json")
        legacy_entry = InstalledSettingsEntry(
            key_path="hooks.SessionStart",
            value=legacy_hook,
            merge_type="append",
            stable_id='{"hooks":[{"command":"forge hook session-start","type":"command"}]}',
            attribution=attributed(InstallModule.HOOKS, "claude_code"),
        )
        tracking.set_installation(
            "local",
            Installation(
                scope="local",
                mode="copy",
                profile="standard",
                module_owners=[attributed(InstallModule.HOOKS, "claude_code")],
                settings_entries=[legacy_entry],
                installed_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
            ),
            str(project),
        )
        installer = Installer(scope=InstallScope.LOCAL, project_root=project, tracking_store=tracking)

        with patch("forge.install.installer.get_forge_source_root", return_value=source_root):
            plan = installer.update()

        assert "hooks" not in plan.modules
        assert read_settings(settings_path)["hooks"]["SessionStart"] == [legacy_hook]
        assert load_added_settings(settings_path)["hooks"]["SessionStart"] == [legacy_hook]
        updated = tracking.get_installation("local", str(project))
        assert updated is not None
        assert module_values(updated) == {"hooks"}
        assert updated.settings_entries == [legacy_entry]

        installer.uninstall()

        assert read_settings(settings_path) == {}
        assert tracking.get_installation("local", str(project)) is None

    def test_user_update_replaces_legacy_hook_entry_with_dispatcher(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        claude_home = tmp_path / "claude-home"
        claude_home.mkdir()
        monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
        settings_path = claude_home / "settings.json"
        legacy_hook = {"hooks": [{"type": "command", "command": "forge hook session-start"}]}
        settings_path.write_text(
            json.dumps({"hooks": {"SessionStart": [legacy_hook]}}),
            encoding="utf-8",
        )

        source_root = self._source_root(tmp_path / "forge-src")
        tracking = TrackingStore(tracking_path=tmp_path / "forge-home" / "installed.json")
        tracking.set_installation(
            "user",
            Installation(
                scope="user",
                mode="copy",
                profile="standard",
                module_owners=[attributed(InstallModule.HOOKS, "claude_code")],
                settings_entries=[
                    InstalledSettingsEntry(
                        key_path="hooks.SessionStart",
                        value=legacy_hook,
                        merge_type="append",
                        stable_id='{"hooks":[{"command":"forge hook session-start","type":"command"}]}',
                        attribution=attributed(InstallModule.HOOKS, "claude_code"),
                    )
                ],
                installed_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
            ),
            None,
        )
        installer = Installer(scope=InstallScope.USER, tracking_store=tracking)

        with (
            patch(
                "forge.install.installer.get_forge_source_root",
                return_value=source_root,
            ),
            patch("forge.install.installer._codex_available", return_value=False),
        ):
            installer.update()

        settings = read_settings(settings_path)
        assert settings["hooks"]["SessionStart"] == [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": render_dispatcher_command("session-start"),
                    }
                ]
            }
        ]
        added = load_added_settings(settings_path)
        assert added["hooks"]["SessionStart"] == settings["hooks"]["SessionStart"]
        updated = tracking.get_installation("user", None)
        assert updated is not None
        assert all("forge hook" not in entry.stable_id for entry in updated.settings_entries)

    def test_user_update_dispatcher_failure_does_not_unmerge_legacy_hook(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        claude_home = tmp_path / "claude-home"
        claude_home.mkdir()
        monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
        settings_path = claude_home / "settings.json"
        legacy_hook = {"hooks": [{"type": "command", "command": "forge hook session-start"}]}
        settings_path.write_text(
            json.dumps({"hooks": {"SessionStart": [legacy_hook]}}),
            encoding="utf-8",
        )

        source_root = self._source_root(tmp_path / "forge-src")
        tracking = TrackingStore(tracking_path=tmp_path / "forge-home" / "installed.json")
        legacy_entry = InstalledSettingsEntry(
            key_path="hooks.SessionStart",
            value=legacy_hook,
            merge_type="append",
            stable_id='{"hooks":[{"command":"forge hook session-start","type":"command"}]}',
            attribution=attributed(InstallModule.HOOKS, "claude_code"),
        )
        tracking.set_installation(
            "user",
            Installation(
                scope="user",
                mode="copy",
                profile="standard",
                module_owners=[attributed(InstallModule.HOOKS, "claude_code")],
                settings_entries=[legacy_entry],
                installed_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
            ),
            None,
        )
        installer = Installer(scope=InstallScope.USER, tracking_store=tracking)

        with (
            patch(
                "forge.install.installer.get_forge_source_root",
                return_value=source_root,
            ),
            patch("forge.install.installer._codex_available", return_value=False),
            patch(
                "forge.install.installer.install_hook_dispatcher",
                side_effect=RuntimeError("boom"),
            ),
            pytest.raises(ForgeInstallError, match="Failed to render hook dispatcher"),
        ):
            installer.update()

        assert read_settings(settings_path)["hooks"]["SessionStart"] == [legacy_hook]
        updated = tracking.get_installation("user", None)
        assert updated is not None
        assert updated.settings_entries == [legacy_entry]


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

    @pytest.fixture
    def settings_uninstall_setup(
        self,
        tmp_path: Path,
    ) -> tuple[Installer, TrackingStore, Installation, Path, Path, Path, Path]:
        project_root = tmp_path / "project"
        claude_root = project_root / ".claude"
        settings_path = claude_root / "settings.json"
        tracked_file = claude_root / "commands" / "review.md"
        tracked_file.parent.mkdir(parents=True)
        tracked_file.write_text("# Review\n", encoding="utf-8")
        baseline_path = claude_root / ".settings.json.forge.backup.20260101-000000"
        baseline = {"theme": "dark"}
        statusline = {"type": "command", "command": "forge status-line"}
        entry = InstalledSettingsEntry(
            key_path="statusLine",
            value=statusline,
            merge_type="scalar",
            stable_id="statusLine",
            attribution=attributed(InstallModule.STATUSLINE, CLAUDE_CODE_RUNTIME),
        )
        write_settings(baseline_path, baseline)
        write_settings(settings_path, {**baseline, "statusLine": statusline})
        added_path = save_added_settings(settings_path, entries_to_added_structure([entry]))
        installation = Installation(
            scope=InstallScope.PROJECT.value,
            project_path=str(project_root),
            mode=InstallMode.COPY.value,
            profile=InstallProfile.MINIMAL.value,
            module_owners=[
                attributed(InstallModule.COMMANDS, CLAUDE_CODE_RUNTIME),
                attributed(InstallModule.STATUSLINE, CLAUDE_CODE_RUNTIME),
            ],
            files=[
                InstalledFile(
                    target_path=str(tracked_file),
                    source_path=str(tmp_path / "source" / "review.md"),
                    checksum="tracked",
                    mode=InstallMode.COPY.value,
                    installed_at="2026-01-01T00:00:00+00:00",
                    attribution=attributed(InstallModule.COMMANDS, CLAUDE_CODE_RUNTIME),
                )
            ],
            settings_entries=[entry],
            settings_backup_path=str(baseline_path),
            installed_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
        tracking = TrackingStore(tmp_path / ".forge" / "installed.json")
        tracking.set_installation(InstallScope.PROJECT.value, installation, str(project_root))
        installer = Installer(
            scope=InstallScope.PROJECT,
            project_root=project_root,
            tracking_store=tracking,
        )
        return installer, tracking, installation, settings_path, added_path, baseline_path, tracked_file

    def test_uninstall_raises_when_not_installed(self, temp_forge_home: Path) -> None:
        tracking = TrackingStore(tracking_path=temp_forge_home / "installed.json")
        installer = Installer(
            scope=InstallScope.USER,
            tracking_store=tracking,
        )

        with pytest.raises(NotInstalledError) as exc_info:
            installer.uninstall()

        assert exc_info.value.scope == "user"

    @pytest.mark.parametrize("baseline_state", ["missing", "unreadable", "unsafe"])
    def test_invalid_recorded_baseline_refuses_full_uninstall_before_mutation(
        self,
        settings_uninstall_setup: tuple[Installer, TrackingStore, Installation, Path, Path, Path, Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        baseline_state: str,
    ) -> None:
        installer, tracking, installation, settings_path, added_path, baseline_path, tracked_file = (
            settings_uninstall_setup
        )
        if baseline_state == "missing":
            baseline_path.unlink()
        elif baseline_state == "unreadable":

            def fail_baseline_read(_path: Path | None) -> dict[str, Any]:
                raise PermissionError("injected unreadable baseline")

            monkeypatch.setattr(
                "forge.install.installer.read_tracked_settings_baseline",
                fail_baseline_read,
            )
        else:
            unsafe_path = tmp_path / "outside-settings-baseline.json"
            write_settings(unsafe_path, {"theme": "dark"})
            installation.settings_backup_path = str(unsafe_path)
            tracking.set_installation(InstallScope.PROJECT.value, installation, str(installation.project_path))

        settings_before = settings_path.read_bytes()
        added_before = added_path.read_bytes()
        expected_error = PathBoundaryViolationError if baseline_state == "unsafe" else ForgeInstallError

        with pytest.raises(expected_error):
            installer.uninstall()

        assert tracked_file.exists()
        assert settings_path.read_bytes() == settings_before
        assert added_path.read_bytes() == added_before
        assert tracking.get_installation(InstallScope.PROJECT.value, str(installation.project_path)) == installation

    def test_null_legacy_baseline_does_not_adopt_newest_history_on_full_uninstall(
        self,
        settings_uninstall_setup: tuple[Installer, TrackingStore, Installation, Path, Path, Path, Path],
    ) -> None:
        installer, tracking, installation, settings_path, _added_path, baseline_path, tracked_file = (
            settings_uninstall_setup
        )
        current = read_settings(settings_path)
        current["theme"] = "light"
        write_settings(settings_path, current)
        newer_backup = settings_path.parent / ".settings.json.forge.backup.20270101-000000"
        write_settings(newer_backup, current)
        installation.settings_backup_path = None
        tracking.set_installation(InstallScope.PROJECT.value, installation, str(installation.project_path))

        installer.uninstall()

        assert read_settings(settings_path) == {"theme": "light"}
        assert baseline_path.exists()
        assert newer_backup.exists()
        assert not tracked_file.exists()
        assert tracking.get_installation(InstallScope.PROJECT.value, str(installation.project_path)) is None

    @pytest.mark.parametrize("with_baseline", [False, True], ids=["without-baseline", "with-baseline"])
    def test_legacy_full_uninstall_preserves_modified_scalar_and_environment_values(
        self,
        tmp_path: Path,
        with_baseline: bool,
    ) -> None:
        project_root = tmp_path / "project"
        settings_path = project_root / ".claude" / "settings.json"
        baseline_path = project_root / ".claude" / ".settings.json.forge.backup.20260101-000000"
        tracked_statusline = {"type": "command", "command": "forge status-line"}
        user_statusline = {"type": "command", "command": "my status-line"}
        write_settings(
            settings_path,
            {
                "statusLine": user_statusline,
                "env": {
                    "EDITED": "user-value",
                    "OWNED": "forge-value",
                    "USER_ONLY": "keep-me",
                },
            },
        )
        if with_baseline:
            write_settings(baseline_path, {"theme": "dark"})

        statusline_owner = attributed(InstallModule.STATUSLINE, CLAUDE_CODE_RUNTIME)
        permissions_owner = attributed(InstallModule.PERMISSIONS, CLAUDE_CODE_RUNTIME)
        entries = [
            InstalledSettingsEntry(
                key_path="statusLine",
                value=tracked_statusline,
                merge_type="scalar",
                stable_id="statusLine",
                attribution=statusline_owner,
            ),
            InstalledSettingsEntry(
                key_path="env.EDITED",
                value="forge-value",
                merge_type="env",
                stable_id="EDITED",
                attribution=permissions_owner,
            ),
            InstalledSettingsEntry(
                key_path="env.OWNED",
                value="forge-value",
                merge_type="env",
                stable_id="OWNED",
                attribution=permissions_owner,
            ),
        ]
        installation = Installation(
            scope=InstallScope.PROJECT.value,
            project_path=str(project_root),
            mode=InstallMode.COPY.value,
            profile=InstallProfile.MINIMAL.value,
            module_owners=sorted({statusline_owner, permissions_owner}),
            settings_entries=entries,
            settings_backup_path=str(baseline_path) if with_baseline else None,
            installed_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
        tracking = TrackingStore(tmp_path / ".forge" / "installed.json")
        tracking.set_installation(InstallScope.PROJECT.value, installation, str(project_root))

        Installer(
            scope=InstallScope.PROJECT,
            project_root=project_root,
            tracking_store=tracking,
        ).uninstall()

        assert read_settings(settings_path) == {
            "statusLine": user_statusline,
            "env": {"EDITED": "user-value", "USER_ONLY": "keep-me"},
        }
        assert baseline_path.exists() is with_baseline
        assert tracking.get_installation(InstallScope.PROJECT.value, str(project_root)) is None


class TestInstallerSymlinkMode:
    """Tests for symlink installation mode."""

    @pytest.fixture
    def setup_symlink_installer(
        self,
        tmp_path: Path,
        isolate_claude_home: Path,
    ) -> tuple[Installer, Path, Path, Path]:
        """Set up installer for symlink mode testing."""
        forge_home = tmp_path / ".forge"
        forge_home.mkdir()

        claude_home = isolate_claude_home

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
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        scope, project_root = find_claude_root(start=fake_home)

        assert scope == InstallScope.USER
        assert project_root is None

    def test_raises_when_no_claude_and_not_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should raise NoClaudeDirectoryError when no .claude found and not at home."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        other_dir = tmp_path / "other" / "deep" / "path"
        other_dir.mkdir(parents=True)

        with pytest.raises(NoClaudeDirectoryError) as exc_info:
            find_claude_root(start=other_dir)

        assert "other/deep/path" in str(exc_info.value) or "other" in str(exc_info.value)

    def test_finds_first_claude_going_up(self, tmp_path: Path) -> None:
        """Should find the nearest .claude, not a higher one."""
        outer = tmp_path / "outer"
        inner = outer / "inner"
        (outer / ".claude").mkdir(parents=True)
        (inner / ".claude").mkdir(parents=True)
        deepest = inner / "src"
        deepest.mkdir()

        scope, project_root = find_claude_root(start=deepest)

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

        (claude_home / ".settings.json.forge.added.20250101-120000").write_text("{}")

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


class TestInstallerCodexHooks:
    """Tests for Codex-owned hooks wiring (plan/init/uninstall/update)."""

    @pytest.fixture
    def setup_installer(
        self,
        tmp_path: Path,
        isolate_claude_home: Path,
    ) -> Generator[tuple[Installer, Path, Path, Path], None, None]:
        """Installer with temp dirs; codex config lands in the isolated CODEX_HOME."""
        forge_home = tmp_path / ".forge"
        forge_home.mkdir()
        claude_home = isolate_claude_home

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
        assert claude_home == Path(os.environ["CLAUDE_HOME"])
        with (
            patch("forge.install.installer.get_forge_source_root", return_value=src.parent),
            patch(
                "forge.install.installer.installed_runtimes",
                return_value=[get_runtime(CLAUDE_CODE_RUNTIME), get_runtime(CODEX_RUNTIME)],
            ),
            patch("forge.install.installer._codex_available", return_value=available),
        ):
            return getattr(installer, method)(**kwargs)

    @staticmethod
    def _codex_config(monkeypatch_free_env: None = None) -> Path:
        return Path(os.environ["CODEX_HOME"]) / "config.toml"

    def test_plan_standard_includes_codex_install(self, setup_installer: tuple[Installer, Path, Path, Path]) -> None:
        installer, _, claude_home, src = setup_installer
        plan = self._run(installer, src, claude_home, method="plan")
        assert plan.codex is not None
        assert plan.codex.action == "install"
        assert plan.codex.config_path == str(self._codex_config())
        assert [_normalize_forge_home(command) for command in plan.codex.commands] == [
            "$FORGE_HOME/bin/forge-hook codex-session-start",
            "$FORGE_HOME/bin/forge-hook codex-policy-check",
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
        assert [_normalize_forge_home(command) for command in installation.codex_commands] == [
            "$FORGE_HOME/bin/forge-hook codex-policy-check",
            "$FORGE_HOME/bin/forge-hook codex-session-start",
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
        """A tampered tracking path refuses the operation and preserves ownership."""
        installer, _, claude_home, src = setup_installer
        self._run(installer, src, claude_home)
        victim = tmp_path / "victim.toml"
        victim.write_text("# >>> forge hooks >>>\n# <<< forge hooks <<<\n")
        installation = installer._tracking.get_installation("user", None)
        assert installation is not None
        installation.codex_config_path = str(victim)
        installer._tracking.set_installation("user", installation, None)

        with pytest.raises(CodexConfigScopeMismatchError) as exc_info:
            self._run(installer, src, claude_home, method="uninstall")

        error = exc_info.value
        assert error.tracked_path == str(victim)
        assert error.expected_path == str(self._codex_config())
        assert str(victim) in str(error)
        assert str(self._codex_config()) in str(error)
        assert "Restore the original CODEX_HOME and retry" in str(error)
        assert "remove the Forge-managed hook block" in str(error)
        assert victim.read_text() == "# >>> forge hooks >>>\n# <<< forge hooks <<<\n"
        preserved = installer._tracking.get_installation("user", None)
        assert preserved is not None
        assert preserved.codex_config_path == str(victim)

    def test_uninstall_accepts_null_tracked_codex_path(
        self, setup_installer: tuple[Installer, Path, Path, Path]
    ) -> None:
        installer, _, claude_home, src = setup_installer
        self._run(installer, src, claude_home)
        self._codex_config().unlink()
        installation = installer._tracking.get_installation("user", None)
        assert installation is not None
        installation.codex_config_path = None
        installation.module_owners = [
            owner for owner in installation.module_owners if owner != attributed(InstallModule.HOOKS, "codex")
        ]
        installer._tracking.set_installation("user", installation, None)

        self._run(installer, src, claude_home, method="uninstall")

        assert installer._tracking.get_installation("user", None) is None

    def test_uninstall_with_leftover_codex_command_still_warns_and_succeeds(
        self,
        setup_installer: tuple[Installer, Path, Path, Path],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        installer, _, claude_home, src = setup_installer
        self._run(installer, src, claude_home)
        config = self._codex_config()
        manual = (
            "\n[[hooks.SessionStart]]\n"
            "[[hooks.SessionStart.hooks]]\n"
            'type = "command"\n'
            'command = "forge hook codex-session-start"\n'
            "timeout = 60\n"
        )
        config.write_text(config.read_text() + manual)

        with caplog.at_level(logging.WARNING, logger="forge.install.installer"):
            self._run(installer, src, claude_home, method="uninstall")

        assert "# >>> forge hooks >>>" not in config.read_text()
        assert "forge hook codex-session-start" in config.read_text()
        assert "Forge hook commands remain outside the managed block" in caplog.text
        assert installer._tracking.get_installation("user", None) is None

    def test_module_dropped_preserves_tracking(self, setup_installer: tuple[Installer, Path, Path, Path]) -> None:
        """Re-enabling without selected Codex hooks keeps tracking for disable."""
        installer, _, claude_home, src = setup_installer
        self._run(installer, src, claude_home)
        self._run(installer, src, claude_home, profile=InstallProfile.MINIMAL)
        installation = installer._tracking.get_installation("user", None)
        assert installation is not None
        assert installation.codex_config_path == str(self._codex_config())

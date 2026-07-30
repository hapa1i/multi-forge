"""Acceptance coverage for runtime-scoped extension module ownership."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.core.runtime import get_runtime
from forge.install.installer import Installer
from forge.install.models import (
    MODULE_RUNTIME_OWNERS,
    Installation,
    InstallMode,
    InstallModule,
    InstallProfile,
    InstallScope,
    ModuleOwner,
)
from forge.install.tracking import TrackingStore

CLAUDE = "claude_code"
CODEX = "codex"


def _write_extension_sources(tmp_path: Path, *, empty_file_modules: bool = False) -> Path:
    extensions = tmp_path / "extensions"
    commands = extensions / "commands"
    agents = extensions / "agents"
    skill = extensions / "skills" / "portable"
    commands.mkdir(parents=True)
    agents.mkdir()
    skill.mkdir(parents=True)
    if not empty_file_modules:
        (commands / "review.md").write_text("# Review\n", encoding="utf-8")
        (agents / "reviewer.md").write_text("# Reviewer\n", encoding="utf-8")
    (skill / "forge-skill.yaml").write_text(
        """\
schema_version: 1
name: portable
description: Portable fixture for runtime-scoped module acceptance tests.
runtimes: [claude_code, codex]
""",
        encoding="utf-8",
    )
    (skill / "content.md").write_text("# Portable\n\nRuntime-neutral body.\n", encoding="utf-8")
    return extensions


@contextmanager
def _isolated_sources(extensions: Path, *runtime_ids: str, codex_available: bool = True) -> Iterator[None]:
    with (
        patch("forge.install.installer.get_extensions_root", return_value=extensions),
        patch("forge.install.installer.get_forge_source_root", return_value=extensions.parent / "wheel-root"),
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=[get_runtime(runtime_id) for runtime_id in runtime_ids],
        ),
        patch("forge.install.installer._codex_available", return_value=codex_available),
        patch("forge.install.installer._ensure_hook_dispatcher"),
    ):
        yield


def _tracking(tmp_path: Path) -> TrackingStore:
    return TrackingStore(tmp_path / "tracking" / "installed.json")


def _owner_pairs(installation: Installation) -> set[tuple[str, str]]:
    return {(owner.module, owner.runtime) for owner in installation.module_owners}


def test_user_claude_selection_never_writes_codex_surfaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extensions = _write_extension_sources(tmp_path)
    claude_home = tmp_path / "selected-claude"
    codex_home = tmp_path / "unselected-codex"
    monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    tracking = _tracking(tmp_path)

    with _isolated_sources(extensions, CLAUDE, CODEX):
        plan = Installer(scope=InstallScope.USER, tracking_store=tracking).init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CLAUDE,),
        )

    assert not plan.has_conflicts
    assert plan.codex is None
    assert (claude_home / "commands" / "review.md").is_file()
    assert (claude_home / "skills" / "portable" / "SKILL.md").is_file()
    assert not codex_home.exists()
    assert not (Path.home() / ".agents" / "skills" / "portable").exists()
    installation = tracking.get_installation("user")
    assert installation is not None
    assert all(runtime == CLAUDE for _, runtime in _owner_pairs(installation))


def test_user_codex_selection_writes_no_claude_surface_or_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extensions = _write_extension_sources(tmp_path)
    claude_home = tmp_path / "unselected-claude"
    codex_home = tmp_path / "selected-codex"
    monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    tracking = _tracking(tmp_path)

    with _isolated_sources(extensions, CODEX):
        plan = Installer(scope=InstallScope.USER, tracking_store=tracking).init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CODEX,),
        )

    assert not plan.has_conflicts
    assert not plan.requires_claude_version
    assert plan.codex is not None and plan.codex.action == "install"
    assert (Path.home() / ".agents" / "skills" / "portable" / "SKILL.md").is_file()
    assert "# >>> forge hooks >>>" in (codex_home / "config.toml").read_text(encoding="utf-8")
    assert not claude_home.exists()
    installation = tracking.get_installation("user")
    assert installation is not None
    assert _owner_pairs(installation) == {
        (InstallModule.HOOKS.value, CODEX),
        (InstallModule.SKILLS.value, CODEX),
    }


def test_user_all_tracks_every_fresh_row_with_declared_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extensions = _write_extension_sources(tmp_path)
    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / "claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    tracking = _tracking(tmp_path)

    with _isolated_sources(extensions, CLAUDE, CODEX):
        plan = Installer(scope=InstallScope.USER, tracking_store=tracking).init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CLAUDE, CODEX),
        )

    assert not plan.has_conflicts
    installation = tracking.get_installation("user")
    assert installation is not None
    owners = _owner_pairs(installation)
    assert installation.files
    assert installation.settings_entries
    attributions = [record.attribution for record in installation.files]
    attributions.extend(record.attribution for record in installation.settings_entries)
    for attribution in attributions:
        assert isinstance(attribution, ModuleOwner)
        pair = (attribution.module, attribution.runtime)
        assert pair in owners
        assert attribution.runtime in MODULE_RUNTIME_OWNERS[InstallModule(attribution.module)]


def test_project_codex_selection_installs_skills_and_omits_hooks(
    tmp_path: Path,
) -> None:
    extensions = _write_extension_sources(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    tracking = _tracking(tmp_path)

    with _isolated_sources(extensions, CODEX):
        plan = Installer(
            scope=InstallScope.PROJECT,
            project_root=project,
            tracking_store=tracking,
        ).init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CODEX,),
        )

    assert not plan.has_conflicts
    assert plan.codex is None
    assert (project / ".agents" / "skills" / "portable" / "SKILL.md").is_file()
    assert not (project / ".claude").exists()
    installation = tracking.get_installation("project", str(project))
    assert installation is not None
    assert _owner_pairs(installation) == {(InstallModule.SKILLS.value, CODEX)}


def test_project_claude_selection_installs_every_project_owned_surface(
    tmp_path: Path,
) -> None:
    extensions = _write_extension_sources(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    tracking = _tracking(tmp_path)

    with _isolated_sources(extensions, CLAUDE):
        plan = Installer(
            scope=InstallScope.PROJECT,
            project_root=project,
            tracking_store=tracking,
        ).init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CLAUDE,),
        )

    assert not plan.has_conflicts
    assert plan.codex is None
    assert (project / ".claude" / "commands" / "review.md").is_file()
    assert (project / ".claude" / "agents" / "reviewer.md").is_file()
    assert (project / ".claude" / "skills" / "portable" / "SKILL.md").is_file()
    assert (project / ".claude" / "settings.json").is_file()
    installation = tracking.get_installation("project", str(project))
    assert installation is not None
    assert _owner_pairs(installation) == {
        (InstallModule.AGENTS.value, CLAUDE),
        (InstallModule.COMMANDS.value, CLAUDE),
        (InstallModule.PERMISSIONS.value, CLAUDE),
        (InstallModule.SKILLS.value, CLAUDE),
        (InstallModule.STATUSLINE.value, CLAUDE),
    }


def test_profile_sourced_wrong_owner_modules_are_reported_as_skips(
    tmp_path: Path,
) -> None:
    extensions = _write_extension_sources(tmp_path)
    tracking = _tracking(tmp_path)

    with _isolated_sources(extensions, CODEX):
        plan = Installer(scope=InstallScope.USER, tracking_store=tracking).plan(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CODEX,),
        )

    outcomes = {outcome.module: (outcome.action, outcome.reason) for outcome in plan.module_outcomes}
    assert not plan.has_conflicts
    assert outcomes[InstallModule.HOOKS.value] == ("install", "runtime_selected")
    assert outcomes[InstallModule.SKILLS.value] == ("install", "runtime_selected")
    for module in (InstallModule.AGENTS, InstallModule.COMMANDS, InstallModule.PERMISSIONS):
        assert outcomes[module.value] == ("skip", "runtime_excluded")


def test_hooks_only_install_keeps_codex_owner_across_unavailable_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extensions = _write_extension_sources(tmp_path)
    codex_home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)

    with _isolated_sources(extensions, CODEX):
        enabled = installer.init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CODEX,),
            _modules_override={InstallModule.HOOKS},
        )
    assert not enabled.has_conflicts
    initial = tracking.get_installation("user")
    assert initial is not None
    assert _owner_pairs(initial) == {(InstallModule.HOOKS.value, CODEX)}

    with _isolated_sources(extensions, codex_available=False):
        synced = installer.update()

    assert not synced.has_conflicts
    assert synced.codex is not None and synced.codex.action == "unavailable"
    after = tracking.get_installation("user")
    assert after is not None
    assert _owner_pairs(after) == {(InstallModule.HOOKS.value, CODEX)}
    assert after.codex_config_path == str(codex_home / "config.toml")


def test_successful_empty_modules_preserve_sync_intent_for_future_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extensions = _write_extension_sources(tmp_path, empty_file_modules=True)
    claude_home = tmp_path / "claude"
    monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)

    with _isolated_sources(extensions, CLAUDE):
        enabled = installer.init(
            profile=InstallProfile.MINIMAL,
            mode=InstallMode.COPY,
            skill_runtimes=(CLAUDE,),
            _modules_override={InstallModule.COMMANDS, InstallModule.AGENTS},
        )

    assert not enabled.has_conflicts
    initial = tracking.get_installation("user")
    assert initial is not None
    assert _owner_pairs(initial) == {
        (InstallModule.AGENTS.value, CLAUDE),
        (InstallModule.COMMANDS.value, CLAUDE),
    }
    assert initial.files == []

    new_command = extensions / "commands" / "new.md"
    new_command.write_text("# Newly shipped\n", encoding="utf-8")
    with _isolated_sources(extensions):
        synced = installer.update()

    assert not synced.has_conflicts
    assert (claude_home / "commands" / "new.md").is_file()
    after = tracking.get_installation("user")
    assert after is not None
    assert _owner_pairs(after) == _owner_pairs(initial)


def test_explicit_narrowing_preserves_omitted_runtime_rows_and_owners(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extensions = _write_extension_sources(tmp_path)
    claude_home = tmp_path / "claude"
    monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)

    with _isolated_sources(extensions, CLAUDE, CODEX):
        installer.init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CLAUDE, CODEX),
        )
        narrowed = installer.init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CODEX,),
        )

    assert narrowed.preserved_runtime_ids == [CLAUDE]
    assert (claude_home / "commands" / "review.md").is_file()
    installation = tracking.get_installation("user")
    assert installation is not None
    assert (InstallModule.COMMANDS.value, CLAUDE) in _owner_pairs(installation)
    assert any(record.target_path == str(claude_home / "commands" / "review.md") for record in installation.files)

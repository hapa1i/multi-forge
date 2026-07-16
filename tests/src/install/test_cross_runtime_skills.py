"""Runtime/scope/profile planning tests for cross-runtime skill packages."""

from __future__ import annotations

import json
from itertools import product
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.extensions import _parse_skill_runtimes, extensions
from forge.core.runtime import get_runtime
from forge.install.installer import Installer, find_forge_installation, inspect_skill_package_status
from forge.install.models import (
    Installation,
    InstalledSkillPackage,
    InstallMode,
    InstallModule,
    InstallProfile,
    InstallScope,
)
from forge.install.skill_planning import (
    CLAUDE_CODE_RUNTIME,
    CODEX_RUNTIME,
    RuntimeSelectionOrigin,
    SkillCandidate,
    SkillPlanAction,
    SkillPlanReason,
    UnsupportedRuntimeSkillScope,
    plan_runtime_skills,
    runtime_skill_root,
    scan_codex_skill_duplicates,
    select_skill_runtimes,
)
from forge.install.tracking import TrackingStore

_PORTABLE = SkillCandidate(
    name="portable",
    supported_runtimes=(CLAUDE_CODE_RUNTIME, CODEX_RUNTIME),
)
_FULL_PORTABLE = SkillCandidate(
    name="full-portable",
    supported_runtimes=(CLAUDE_CODE_RUNTIME, CODEX_RUNTIME),
    minimum_profile=InstallProfile.FULL,
)
_CLAUDE_ONLY = SkillCandidate(
    name="claude-only",
    supported_runtimes=(CLAUDE_CODE_RUNTIME,),
)


def test_cli_runtime_selection_is_repeatable_and_all_is_canonical() -> None:
    assert _parse_skill_runtimes(()) is None
    assert _parse_skill_runtimes(("codex", "claude")) == (CLAUDE_CODE_RUNTIME, CODEX_RUNTIME)
    assert _parse_skill_runtimes(("all", "codex")) == (CLAUDE_CODE_RUNTIME, CODEX_RUNTIME)


def test_status_degrades_unknown_tracked_runtime_to_invalid_target(tmp_path: Path) -> None:
    target = tmp_path / "unknown" / "portable"
    installation = Installation(
        scope="user",
        mode="copy",
        profile="standard",
        skill_packages=[
            InstalledSkillPackage(
                runtime="unknown-runtime",
                skill="portable",
                target_dir=str(target),
                file_paths=[str(target / "SKILL.md")],
            )
        ],
    )

    status = inspect_skill_package_status(installation, InstallScope.USER, None)

    assert status[0].state == "invalid-target"
    assert status[0].target_present is False
    assert status[0].recovery is not None


def _paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "user_home": tmp_path / "home",
        "claude_home": tmp_path / "claude-home",
        "project_root": tmp_path / "project",
    }


def _decision(plan, runtime: str, skill: str):
    return next(decision for decision in plan.decisions if decision.runtime == runtime and decision.skill == skill)


def test_runtime_selection_distinguishes_auto_explicit_and_managed() -> None:
    auto_claude = select_skill_runtimes(installed_runtime_ids=())
    auto_both = select_skill_runtimes(installed_runtime_ids=(CODEX_RUNTIME, "future-runtime"))
    explicit = select_skill_runtimes(
        installed_runtime_ids=(CLAUDE_CODE_RUNTIME,),
        explicit_runtime_ids=(CODEX_RUNTIME,),
    )
    managed = select_skill_runtimes(
        installed_runtime_ids=(),
        managed_runtime_ids=(CODEX_RUNTIME,),
    )

    assert auto_claude.runtime_ids == (CLAUDE_CODE_RUNTIME,)
    assert auto_claude.origin == RuntimeSelectionOrigin.AUTO
    assert auto_both.runtime_ids == (CLAUDE_CODE_RUNTIME, CODEX_RUNTIME)
    assert explicit.runtime_ids == (CODEX_RUNTIME,)
    assert explicit.unavailable_runtime_ids == (CODEX_RUNTIME,)
    assert managed.runtime_ids == (CODEX_RUNTIME,)
    assert managed.origin == RuntimeSelectionOrigin.MANAGED
    assert managed.unavailable_runtime_ids == ()


def test_runtime_selection_rejects_ambiguous_or_unknown_requests() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        select_skill_runtimes(
            installed_runtime_ids=(),
            explicit_runtime_ids=(CODEX_RUNTIME,),
            managed_runtime_ids=(CODEX_RUNTIME,),
        )
    with pytest.raises(ValueError, match="cannot be empty"):
        select_skill_runtimes(installed_runtime_ids=(), explicit_runtime_ids=())
    with pytest.raises(ValueError, match="Unknown skill runtime"):
        select_skill_runtimes(installed_runtime_ids=(), managed_runtime_ids=("future-runtime",))


def test_managed_empty_runtime_set_is_authoritative() -> None:
    selection = select_skill_runtimes(
        installed_runtime_ids=(CLAUDE_CODE_RUNTIME, CODEX_RUNTIME),
        managed_runtime_ids=(),
    )

    assert selection.runtime_ids == ()
    assert selection.origin == RuntimeSelectionOrigin.MANAGED


@pytest.mark.parametrize(
    ("scope", "runtime", "expected"),
    [
        (InstallScope.USER, CLAUDE_CODE_RUNTIME, Path("/claude/skills")),
        (InstallScope.PROJECT, CLAUDE_CODE_RUNTIME, Path("/project/.claude/skills")),
        (InstallScope.LOCAL, CLAUDE_CODE_RUNTIME, Path("/project/.claude/skills")),
        (InstallScope.USER, CODEX_RUNTIME, Path("/home/.agents/skills")),
        (InstallScope.PROJECT, CODEX_RUNTIME, Path("/project/.agents/skills")),
    ],
)
def test_runtime_skill_roots_match_reviewed_scope_contract(
    scope: InstallScope,
    runtime: str,
    expected: Path,
) -> None:
    assert (
        runtime_skill_root(
            runtime,
            scope,
            user_home=Path("/home"),
            claude_home=Path("/claude"),
            project_root=Path("/project"),
        )
        == expected
    )


def test_codex_local_scope_has_no_target() -> None:
    with pytest.raises(UnsupportedRuntimeSkillScope, match="does not support local"):
        runtime_skill_root(
            CODEX_RUNTIME,
            InstallScope.LOCAL,
            user_home=Path("/home"),
            claude_home=Path("/claude"),
            project_root=Path("/project"),
        )


def test_scope_runtime_profile_skill_matrix_is_explicit(tmp_path: Path) -> None:
    candidates = (_PORTABLE, _FULL_PORTABLE, _CLAUDE_ONLY)
    for scope, runtime, profile in product(InstallScope, (CLAUDE_CODE_RUNTIME, CODEX_RUNTIME), InstallProfile):
        selection = select_skill_runtimes(
            installed_runtime_ids=(CLAUDE_CODE_RUNTIME, CODEX_RUNTIME),
            explicit_runtime_ids=(runtime,),
        )
        plan = plan_runtime_skills(
            scope=scope,
            profile=profile,
            skills_module_selected=True,
            candidates=candidates,
            selection=selection,
            **_paths(tmp_path),
        )

        assert len(plan.decisions) == len(candidates)
        portable = _decision(plan, runtime, "portable")
        full = _decision(plan, runtime, "full-portable")
        claude_only = _decision(plan, runtime, "claude-only")

        if runtime == CODEX_RUNTIME and scope == InstallScope.LOCAL:
            assert portable.action == SkillPlanAction.CONFLICT
            assert portable.reason == SkillPlanReason.SCOPE_UNSUPPORTED
        else:
            assert portable.action == SkillPlanAction.INSTALL
            assert portable.target_dir is not None

        if profile != InstallProfile.FULL:
            assert full.action == SkillPlanAction.SKIP
            assert full.reason == SkillPlanReason.PROFILE_EXCLUDED
        elif runtime == CODEX_RUNTIME and scope == InstallScope.LOCAL:
            assert full.action == SkillPlanAction.CONFLICT
            assert full.reason == SkillPlanReason.SCOPE_UNSUPPORTED
        else:
            assert full.action == SkillPlanAction.INSTALL

        if runtime == CODEX_RUNTIME:
            assert claude_only.action == SkillPlanAction.SKIP
            assert claude_only.reason == SkillPlanReason.RUNTIME_EXCLUDED
        else:
            assert claude_only.action == SkillPlanAction.INSTALL


def test_automatic_local_enable_skips_codex_without_suppressing_claude(
    tmp_path: Path,
) -> None:
    selection = select_skill_runtimes(installed_runtime_ids=(CLAUDE_CODE_RUNTIME, CODEX_RUNTIME))
    plan = plan_runtime_skills(
        scope=InstallScope.LOCAL,
        profile=InstallProfile.STANDARD,
        skills_module_selected=True,
        candidates=(_PORTABLE,),
        selection=selection,
        **_paths(tmp_path),
    )

    assert _decision(plan, CLAUDE_CODE_RUNTIME, "portable").action == SkillPlanAction.INSTALL
    codex = _decision(plan, CODEX_RUNTIME, "portable")
    assert codex.action == SkillPlanAction.SKIP
    assert codex.reason == SkillPlanReason.SCOPE_UNSUPPORTED
    assert not plan.has_conflicts


def test_module_selection_is_reported_instead_of_silently_omitting_skills(
    tmp_path: Path,
) -> None:
    selection = select_skill_runtimes(
        installed_runtime_ids=(CLAUDE_CODE_RUNTIME,),
        explicit_runtime_ids=(CLAUDE_CODE_RUNTIME,),
    )
    plan = plan_runtime_skills(
        scope=InstallScope.USER,
        profile=InstallProfile.MINIMAL,
        skills_module_selected=False,
        candidates=(_PORTABLE,),
        selection=selection,
        **_paths(tmp_path),
    )

    assert plan.decisions[0].action == SkillPlanAction.SKIP
    assert plan.decisions[0].reason == SkillPlanReason.SKILLS_MODULE_EXCLUDED


def test_lower_profile_preservation_is_runtime_package_specific(tmp_path: Path) -> None:
    selection = select_skill_runtimes(
        installed_runtime_ids=(),
        managed_runtime_ids=(CLAUDE_CODE_RUNTIME, CODEX_RUNTIME),
    )
    plan = plan_runtime_skills(
        scope=InstallScope.USER,
        profile=InstallProfile.STANDARD,
        skills_module_selected=True,
        candidates=(_FULL_PORTABLE,),
        selection=selection,
        managed_packages={(CLAUDE_CODE_RUNTIME, "full-portable")},
        **_paths(tmp_path),
    )

    claude = _decision(plan, CLAUDE_CODE_RUNTIME, "full-portable")
    codex = _decision(plan, CODEX_RUNTIME, "full-portable")
    assert claude.action == SkillPlanAction.INSTALL
    assert claude.reason == SkillPlanReason.MANAGED_PROFILE_PRESERVATION
    assert codex.action == SkillPlanAction.SKIP
    assert codex.reason == SkillPlanReason.PROFILE_EXCLUDED


def test_managed_codex_package_survives_temporary_binary_absence(
    tmp_path: Path,
) -> None:
    selection = select_skill_runtimes(installed_runtime_ids=(), managed_runtime_ids=(CODEX_RUNTIME,))
    plan = plan_runtime_skills(
        scope=InstallScope.USER,
        profile=InstallProfile.STANDARD,
        skills_module_selected=True,
        candidates=(_PORTABLE,),
        selection=selection,
        managed_packages={(CODEX_RUNTIME, "portable")},
        **_paths(tmp_path),
    )

    assert plan.installable[0].runtime == CODEX_RUNTIME
    assert plan.installable[0].target_dir == tmp_path / "home" / ".agents" / "skills" / "portable"


def test_explicit_unavailable_runtime_is_a_conflict(tmp_path: Path) -> None:
    selection = select_skill_runtimes(installed_runtime_ids=(), explicit_runtime_ids=(CODEX_RUNTIME,))
    plan = plan_runtime_skills(
        scope=InstallScope.USER,
        profile=InstallProfile.STANDARD,
        skills_module_selected=True,
        candidates=(_PORTABLE,),
        selection=selection,
        **_paths(tmp_path),
    )

    assert plan.has_conflicts
    assert plan.conflicts[0].reason == SkillPlanReason.RUNTIME_UNAVAILABLE


def test_duplicate_scan_is_read_only_and_excludes_tracked_package(
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "home" / ".agents" / "skills"
    project_root = tmp_path / "project" / ".agents" / "skills"
    admin_root = tmp_path / "etc" / "codex" / "skills"
    for root, marker in (
        (user_root, "managed"),
        (project_root, "project-user"),
        (admin_root, "admin-user"),
    ):
        package = root / "portable"
        package.mkdir(parents=True)
        (package / "SKILL.md").write_text(marker, encoding="utf-8")
    before = (project_root / "portable" / "SKILL.md").read_text(encoding="utf-8")

    scan = scan_codex_skill_duplicates(
        "portable",
        scan_roots=(user_root, project_root, admin_root),
        managed_package_dirs=(user_root / "portable",),
    )

    assert scan.package_dirs == tuple(
        sorted(
            (
                user_root / "portable",
                project_root / "portable",
                admin_root / "portable",
            ),
            key=str,
        )
    )
    assert scan.untracked_package_dirs == tuple(sorted((project_root / "portable", admin_root / "portable"), key=str))
    assert (project_root / "portable" / "SKILL.md").read_text(encoding="utf-8") == before


def test_duplicate_scan_reports_symlink_at_scan_location_without_resolving_it(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source" / "portable"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("linked", encoding="utf-8")
    scan_root = tmp_path / "home" / ".agents" / "skills"
    scan_root.mkdir(parents=True)
    (scan_root / "portable").symlink_to(source, target_is_directory=True)

    scan = scan_codex_skill_duplicates("portable", scan_roots=(scan_root,))

    assert scan.package_dirs == (scan_root / "portable",)
    assert (scan_root / "portable").is_symlink()


@pytest.mark.parametrize(
    ("origin", "expected_action"),
    [
        (RuntimeSelectionOrigin.AUTO, SkillPlanAction.SKIP),
        (RuntimeSelectionOrigin.EXPLICIT, SkillPlanAction.CONFLICT),
        (RuntimeSelectionOrigin.MANAGED, SkillPlanAction.CONFLICT),
    ],
)
def test_duplicate_policy_depends_on_selection_origin(
    tmp_path: Path,
    origin: RuntimeSelectionOrigin,
    expected_action: SkillPlanAction,
) -> None:
    if origin == RuntimeSelectionOrigin.AUTO:
        selection = select_skill_runtimes(installed_runtime_ids=(CODEX_RUNTIME,))
    elif origin == RuntimeSelectionOrigin.EXPLICIT:
        selection = select_skill_runtimes(
            installed_runtime_ids=(CODEX_RUNTIME,),
            explicit_runtime_ids=(CODEX_RUNTIME,),
        )
    else:
        selection = select_skill_runtimes(installed_runtime_ids=(), managed_runtime_ids=(CODEX_RUNTIME,))
    duplicate = tmp_path / "elsewhere" / ".agents" / "skills" / "portable"

    plan = plan_runtime_skills(
        scope=InstallScope.USER,
        profile=InstallProfile.STANDARD,
        skills_module_selected=True,
        candidates=(_PORTABLE,),
        selection=selection,
        untracked_codex_packages={"portable": (duplicate,)},
        **_paths(tmp_path),
    )

    codex = _decision(plan, CODEX_RUNTIME, "portable")
    assert codex.action == expected_action
    assert codex.reason == SkillPlanReason.DUPLICATE_SCAN_CHAIN
    assert codex.duplicate_dirs == (duplicate,)


def test_automatic_duplicate_conflicts_when_the_codex_package_is_already_managed(
    tmp_path: Path,
) -> None:
    selection = select_skill_runtimes(installed_runtime_ids=(CODEX_RUNTIME,))
    duplicate = tmp_path / "elsewhere" / ".agents" / "skills" / "portable"

    plan = plan_runtime_skills(
        scope=InstallScope.USER,
        profile=InstallProfile.STANDARD,
        skills_module_selected=True,
        candidates=(_PORTABLE,),
        selection=selection,
        managed_packages=((CODEX_RUNTIME, "portable"),),
        untracked_codex_packages={"portable": (duplicate,)},
        **_paths(tmp_path),
    )

    codex = _decision(plan, CODEX_RUNTIME, "portable")
    assert codex.action == SkillPlanAction.CONFLICT
    assert codex.reason == SkillPlanReason.DUPLICATE_SCAN_CHAIN
    assert codex.duplicate_dirs == (duplicate,)


def test_duplicate_candidate_names_are_rejected(tmp_path: Path) -> None:
    selection = select_skill_runtimes(installed_runtime_ids=())

    with pytest.raises(ValueError, match="Duplicate skill candidate"):
        plan_runtime_skills(
            scope=InstallScope.USER,
            profile=InstallProfile.STANDARD,
            skills_module_selected=True,
            candidates=(_PORTABLE, _PORTABLE),
            selection=selection,
            **_paths(tmp_path),
        )


def test_unknown_candidate_runtime_is_rejected(tmp_path: Path) -> None:
    selection = select_skill_runtimes(installed_runtime_ids=())
    candidate = SkillCandidate(name="future", supported_runtimes=(CLAUDE_CODE_RUNTIME, "future-runtime"))

    with pytest.raises(ValueError, match="declares unknown runtime"):
        plan_runtime_skills(
            scope=InstallScope.USER,
            profile=InstallProfile.STANDARD,
            skills_module_selected=True,
            candidates=(candidate,),
            selection=selection,
            **_paths(tmp_path),
        )


def _write_portable_source(tmp_path: Path, *, name: str = "portable") -> tuple[Path, Path]:
    extensions_root = tmp_path / "extensions"
    package = extensions_root / "skills" / name
    (package / "references").mkdir(parents=True)
    (package / "forge-skill.yaml").write_text(
        f"""\
schema_version: 1
name: {name}
description: Portable installer fixture. Use when testing runtime lifecycle behavior.
runtimes: [claude_code, codex]
""",
        encoding="utf-8",
    )
    (package / "content.md").write_text("# Portable\n\nInitial body.\n", encoding="utf-8")
    (package / "references" / "note.md").write_text("tracked auxiliary\n", encoding="utf-8")
    return extensions_root, package


def _tracking(tmp_path: Path) -> TrackingStore:
    return TrackingStore(tracking_path=tmp_path / "tracking" / "installed.json")


def _runtime_specs(*runtime_ids: str):
    return [get_runtime(runtime_id) for runtime_id in runtime_ids]


def test_runtime_packages_copy_sync_stale_cleanup_and_disable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    extensions_root, source_package = _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)

    with (
        patch("forge.install.installer.get_extensions_root", return_value=extensions_root),
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CLAUDE_CODE_RUNTIME, CODEX_RUNTIME),
        ),
        patch("forge.install.installer._ensure_hook_dispatcher") as dispatcher,
    ):
        plan = installer.init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CLAUDE_CODE_RUNTIME, CODEX_RUNTIME),
            _modules_override={InstallModule.SKILLS},
        )

    dispatcher.assert_not_called()
    assert not plan.has_conflicts
    claude_target = Path(str(next(p.target_dir for p in plan.skill_packages if p.runtime == CLAUDE_CODE_RUNTIME)))
    codex_target = home / ".agents" / "skills" / "portable"
    assert (claude_target / "SKILL.md").is_file()
    assert (codex_target / "SKILL.md").is_file()
    assert "name: forge:portable" in (claude_target / "SKILL.md").read_text(encoding="utf-8")
    assert "name: portable" in (codex_target / "SKILL.md").read_text(encoding="utf-8")
    assert not (home / ".codex" / "skills" / "portable").exists()

    installed = tracking.get_installation("user", None)
    assert installed is not None
    assert {(package.runtime, package.skill) for package in installed.skill_packages} == {
        (CLAUDE_CODE_RUNTIME, "portable"),
        (CODEX_RUNTIME, "portable"),
    }
    assert all(package.file_paths == sorted(package.file_paths) for package in installed.skill_packages)

    (source_package / "content.md").write_text("# Portable\n\nUpdated body.\n", encoding="utf-8")
    (source_package / "references" / "note.md").unlink()
    with (
        patch("forge.install.installer.get_extensions_root", return_value=extensions_root),
        patch("forge.install.installer.installed_runtimes", return_value=[]),
        patch("forge.install.installer._ensure_hook_dispatcher"),
    ):
        sync_plan = installer.update()

    assert {package.runtime for package in sync_plan.skill_packages if package.cache_dir} == {
        CLAUDE_CODE_RUNTIME,
        CODEX_RUNTIME,
    }
    assert "Updated body" in (codex_target / "SKILL.md").read_text(encoding="utf-8")
    assert not (codex_target / "references" / "note.md").exists()
    untracked = codex_target.parent / "user-owned" / "SKILL.md"
    untracked.parent.mkdir(parents=True)
    untracked.write_text("user owned\n", encoding="utf-8")

    installer.uninstall()

    assert not codex_target.exists()
    assert not claude_target.exists()
    assert untracked.read_text(encoding="utf-8") == "user owned\n"
    assert tracking.get_installation("user", None) is None


def test_dry_run_does_not_materialize_cache_and_symlinks_use_stable_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    extensions_root, _source_package = _write_portable_source(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=_tracking(tmp_path))
    kwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.SYMLINK,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS},
    }

    with (
        patch("forge.install.installer.get_extensions_root", return_value=extensions_root),
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
    ):
        dry_run = installer.plan(**kwargs)
        cache_dir = Path(next(package.cache_dir for package in dry_run.skill_packages if package.cache_dir))
        assert not cache_dir.exists()
        assert not (Path.home() / ".agents" / "skills" / "portable").exists()
        applied = installer.init(**kwargs)

    package = next(package for package in applied.skill_packages if package.cache_dir)
    target = Path(package.target_dir) / "SKILL.md"  # type: ignore[arg-type]
    assert target.is_symlink()
    assert target.resolve().is_relative_to(Path(package.cache_dir).resolve())  # type: ignore[arg-type]
    assert "/cache/compiled-skills/v1/codex/portable/" in str(target.resolve())


def test_explicit_duplicate_blocks_all_targets_even_with_force_but_auto_skips_codex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    extensions_root, _source_package = _write_portable_source(tmp_path)
    duplicate = home / ".agents" / "skills" / "portable" / "SKILL.md"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text("user-owned\n", encoding="utf-8")
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)

    with (
        patch("forge.install.installer.get_extensions_root", return_value=extensions_root),
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CLAUDE_CODE_RUNTIME, CODEX_RUNTIME),
        ),
    ):
        blocked = installer.init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            force=True,
            skill_runtimes=(CLAUDE_CODE_RUNTIME, CODEX_RUNTIME),
            _modules_override={InstallModule.SKILLS},
        )

    assert blocked.has_conflicts
    assert any("duplicate_scan_chain" in conflict for conflict in blocked.conflicts)
    assert duplicate.read_text(encoding="utf-8") == "user-owned\n"
    assert all(not Path(package.cache_dir).exists() for package in blocked.skill_packages if package.cache_dir)
    assert tracking.get_installation("user", None) is None

    with (
        patch("forge.install.installer.get_extensions_root", return_value=extensions_root),
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CLAUDE_CODE_RUNTIME, CODEX_RUNTIME),
        ),
    ):
        automatic = installer.init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            _modules_override={InstallModule.SKILLS},
        )

    assert not automatic.has_conflicts
    assert any(
        package.runtime == CODEX_RUNTIME and package.action == "skip" and package.reason == "duplicate_scan_chain"
        for package in automatic.skill_packages
    )
    assert duplicate.read_text(encoding="utf-8") == "user-owned\n"
    installed = tracking.get_installation("user", None)
    assert installed is not None
    assert {package.runtime for package in installed.skill_packages} == {CLAUDE_CODE_RUNTIME}


def test_codex_only_project_install_is_detectable_in_status_and_disable_without_claude_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "repo"
    nested = project / "src" / "nested"
    nested.mkdir(parents=True)
    extensions_root, _source_package = _write_portable_source(tmp_path)
    tracking = TrackingStore()
    installer = Installer(scope=InstallScope.PROJECT, project_root=project, tracking_store=tracking)

    with (
        patch("forge.install.installer.get_extensions_root", return_value=extensions_root),
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
        patch("forge.install.installer._ensure_hook_dispatcher") as dispatcher,
    ):
        plan = installer.init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CODEX_RUNTIME,),
            _modules_override={InstallModule.SKILLS},
        )

    dispatcher.assert_not_called()
    assert not plan.requires_claude_version
    target = project / ".agents" / "skills" / "portable" / "SKILL.md"
    assert target.is_file()
    assert not (project / ".claude").exists()
    assert find_forge_installation(start=nested, tracking=tracking) == (
        InstallScope.PROJECT,
        project,
    )

    monkeypatch.chdir(nested)
    with (
        patch("forge.install.installer.get_extensions_root", return_value=extensions_root),
        patch("forge.install.installer.installed_runtimes", return_value=[]),
        patch("forge.install.version.check_minimum_version") as version_check,
    ):
        synced = CliRunner().invoke(extensions, ["sync"])
    assert synced.exit_code == 0, synced.output
    version_check.assert_not_called()
    assert not (project / ".claude").exists()

    status = CliRunner().invoke(extensions, ["status", "--json"])
    assert status.exit_code == 0, status.output
    payload = json.loads(status.output)
    assert payload[0]["skill_packages"][0]["runtime"] == CODEX_RUNTIME
    assert payload[0]["skill_packages"][0]["target_dir"] == str(target.parent)
    assert payload[0]["skill_packages"][0]["state"] == "present"
    assert payload[0]["skill_packages"][0]["target_present"] is True
    assert payload[0]["skill_packages"][0]["missing_file_paths"] == []
    assert payload[0]["skill_packages"][0]["duplicate_dirs"] == []
    assert payload[0]["skill_packages"][0]["recovery"] is None

    duplicate = home / ".agents" / "skills" / "portable" / "SKILL.md"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text("user-owned\n", encoding="utf-8")
    duplicate_status = CliRunner().invoke(extensions, ["status", "--json"])
    duplicate_payload = json.loads(duplicate_status.output)
    observed = duplicate_payload[0]["skill_packages"][0]
    assert observed["state"] == "duplicate"
    assert observed["target_present"] is True
    assert observed["duplicate_dirs"] == [str(duplicate.parent)]
    assert "Remove or rename" in observed["recovery"]
    human_status = CliRunner().invoke(extensions, ["status"])
    assert human_status.exit_code == 0, human_status.output
    assert "duplicate" in human_status.output
    assert "Remove or rename" in human_status.output

    duplicate.unlink()
    missing_resource = target.parent / "references" / "note.md"
    missing_resource.unlink()
    missing_status = CliRunner().invoke(extensions, ["status", "--json"])
    missing_payload = json.loads(missing_status.output)
    observed = missing_payload[0]["skill_packages"][0]
    assert observed["state"] == "missing"
    assert observed["target_present"] is True
    assert observed["missing_file_paths"] == [str(missing_resource)]
    assert "extension sync" in observed["recovery"]
    missing_human = CliRunner().invoke(extensions, ["status"])
    assert missing_human.exit_code == 0, missing_human.output
    assert "missing files" in missing_human.output

    disabled = CliRunner().invoke(extensions, ["disable", "--yes"])
    assert disabled.exit_code == 0, disabled.output
    assert "Skill packages" in disabled.output
    assert not target.exists()
    assert tracking.get_installation("project", str(project)) is None


def test_enable_codex_only_skips_claude_version_gate_and_claude_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "repo"
    project.mkdir()
    extensions_root, _source_package = _write_portable_source(tmp_path)

    with (
        patch("forge.install.installer.get_extensions_root", return_value=extensions_root),
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
        patch("forge.install.version.check_minimum_version") as version_check,
    ):
        result = CliRunner().invoke(
            extensions,
            [
                "enable",
                "--scope",
                "project",
                "--root",
                str(project),
                "--profile",
                "minimal",
                "--with",
                "skills",
                "--without",
                "commands",
                "--runtime",
                "codex",
            ],
        )

    assert result.exit_code == 0, result.output
    version_check.assert_not_called()
    assert (project / ".agents" / "skills" / "portable" / "SKILL.md").is_file()
    assert not (project / ".claude").exists()
    assert "forge claude preset edit" not in result.output


def test_runtime_option_filters_skills_but_mixed_profile_still_runs_claude_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "repo"
    project.mkdir()
    extensions_root, _source_package = _write_portable_source(tmp_path)

    with (
        patch("forge.install.installer.get_extensions_root", return_value=extensions_root),
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
        patch("forge.install.version.check_minimum_version") as version_check,
    ):
        version_check.return_value.ok = True
        result = CliRunner().invoke(
            extensions,
            [
                "enable",
                "--scope",
                "project",
                "--root",
                str(project),
                "--profile",
                "standard",
                "--runtime",
                "codex",
            ],
        )

    assert result.exit_code == 0, result.output
    version_check.assert_called_once_with()
    assert (project / ".agents" / "skills" / "portable" / "SKILL.md").is_file()
    assert (project / ".claude" / "settings.json").is_file()

"""Runtime/scope/profile planning tests for cross-runtime skill packages."""

from __future__ import annotations

import json
import shutil
import subprocess
from itertools import product
from pathlib import Path
from typing import TypedDict
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.extensions import _parse_skill_runtimes, extensions
from forge.core.runtime import get_runtime
from forge.core.state import FileLockTimeoutError
from forge.install.exceptions import ForgeInstallError, TrackingCorruptedError
from forge.install.installer import (
    Installer,
    find_forge_installation,
    inspect_skill_package_status,
)
from forge.install.models import (
    FilePlan,
    Installation,
    InstalledFile,
    InstalledSkillPackage,
    InstallMode,
    InstallModule,
    InstallProfile,
    InstallScope,
)
from forge.install.settings_merge import find_added_files
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
from forge.install.tracking import TrackingStore, compute_checksum

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


class _PlanningPaths(TypedDict):
    user_home: Path
    claude_home: Path
    project_root: Path


class _InstallerSkillKwargs(TypedDict):
    profile: InstallProfile
    mode: InstallMode
    skill_runtimes: tuple[str, ...]
    _modules_override: set[InstallModule]


class _InstallerBaseSkillKwargs(TypedDict):
    profile: InstallProfile
    mode: InstallMode
    _modules_override: set[InstallModule]


def test_cli_runtime_selection_is_repeatable_and_all_is_canonical() -> None:
    assert _parse_skill_runtimes(()) is None
    assert _parse_skill_runtimes(("codex", "claude")) == (
        CLAUDE_CODE_RUNTIME,
        CODEX_RUNTIME,
    )
    assert _parse_skill_runtimes(("all", "codex")) == (
        CLAUDE_CODE_RUNTIME,
        CODEX_RUNTIME,
    )


def test_status_degrades_unknown_tracked_runtime_to_invalid_target(
    tmp_path: Path,
) -> None:
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


def _paths(tmp_path: Path) -> _PlanningPaths:
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
    auto_existing = select_skill_runtimes(
        installed_runtime_ids=(CLAUDE_CODE_RUNTIME,),
        existing_runtime_ids=(CLAUDE_CODE_RUNTIME, CODEX_RUNTIME),
    )
    explicit = select_skill_runtimes(
        installed_runtime_ids=(CLAUDE_CODE_RUNTIME,),
        explicit_runtime_ids=(CODEX_RUNTIME,),
        existing_runtime_ids=(CLAUDE_CODE_RUNTIME, CODEX_RUNTIME),
    )
    managed = select_skill_runtimes(
        installed_runtime_ids=(),
        managed_runtime_ids=(CODEX_RUNTIME,),
    )

    assert auto_claude.runtime_ids == (CLAUDE_CODE_RUNTIME,)
    assert auto_claude.origin == RuntimeSelectionOrigin.AUTO
    assert auto_both.runtime_ids == (CLAUDE_CODE_RUNTIME, CODEX_RUNTIME)
    assert auto_existing.runtime_ids == (CLAUDE_CODE_RUNTIME, CODEX_RUNTIME)
    assert explicit.runtime_ids == (CODEX_RUNTIME,)
    assert explicit.unavailable_runtime_ids == (CODEX_RUNTIME,)
    assert explicit.preserved_runtime_ids == (CLAUDE_CODE_RUNTIME,)
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


def test_duplicate_scan_is_read_only_and_classifies_managed_provenance(
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
        managed_package_dirs=(user_root / "portable", project_root / "portable"),
        current_package_dirs=(user_root / "portable",),
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
    assert scan.forge_managed_duplicate_dirs == (project_root / "portable",)
    assert scan.untracked_package_dirs == (admin_root / "portable",)
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


@pytest.fixture(autouse=True)
def use_isolated_install_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Use per-test sources and no ambient runtime binaries unless a test opts in."""

    monkeypatch.setattr(
        "forge.install.installer.get_extensions_root",
        lambda: tmp_path / "extensions",
    )
    monkeypatch.setattr("forge.install.installer.installed_runtimes", lambda: [])


def test_runtime_packages_copy_sync_stale_cleanup_and_disable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path.home()
    _, source_package = _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)

    with (
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


def test_checkout_git_eligibility_filters_runtime_skill_files_and_packages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, fixture_package = _write_portable_source(tmp_path)
    repo = tmp_path / "repo"
    source_root = repo / "src"
    package = source_root / "skills" / "portable"
    (source_root / "forge").mkdir(parents=True)
    shutil.copytree(fixture_package, package)
    ignored_file = package / "token.secret"
    ignored_file.write_text("must not enter compiled output\n", encoding="utf-8")

    ignored_package = source_root / "skills" / "ignored-package"
    shutil.copytree(package, ignored_package)
    (ignored_package / "forge-skill.yaml").write_text(
        """\
schema_version: 1
name: ignored-package
description: Ignored checkout-only package.
runtimes: [codex]
""",
        encoding="utf-8",
    )

    eligible_paths = {path for path in package.rglob("*") if path.is_file() and path != ignored_file}
    monkeypatch.setattr("forge.install.installer.get_forge_source_root", lambda: repo)
    monkeypatch.setattr("forge.install.installer.get_extensions_root", lambda: source_root)
    monkeypatch.setattr(
        "forge.install.installer._get_git_tracked_files",
        lambda _repo: eligible_paths,
    )

    project = tmp_path / "project"
    project.mkdir()
    tracking = _tracking(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=project,
        tracking_store=tracking,
    )
    with patch(
        "forge.install.installer.installed_runtimes",
        return_value=_runtime_specs(CODEX_RUNTIME),
    ):
        plan = installer.init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CODEX_RUNTIME,),
            _modules_override={InstallModule.SKILLS},
        )

    target = project / ".agents" / "skills" / "portable"
    assert (target / "SKILL.md").is_file()
    assert (target / "references" / "note.md").is_file()
    assert not (target / ignored_file.name).exists()
    assert not (project / ".agents" / "skills" / "ignored-package").exists()
    package_plan = next(item for item in plan.skill_packages if item.skill == "portable")
    assert package_plan.cache_dir is not None
    assert not (Path(package_plan.cache_dir) / ignored_file.name).exists()
    installation = tracking.get_installation("project", str(project))
    assert installation is not None
    assert [(item.runtime, item.skill) for item in installation.skill_packages] == [(CODEX_RUNTIME, "portable")]
    assert all(not path.target_path.endswith(ignored_file.name) for path in installation.files)


def test_checkout_git_eligibility_probe_failure_blocks_skill_planning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, fixture_package = _write_portable_source(tmp_path)
    repo = tmp_path / "checkout"
    source_root = repo / "src"
    (repo / ".git").mkdir(parents=True)
    (source_root / "forge").mkdir(parents=True)
    shutil.copytree(fixture_package, source_root / "skills" / "portable")

    monkeypatch.setattr("forge.install.installer.get_forge_source_root", lambda: repo)
    monkeypatch.setattr("forge.install.installer.get_extensions_root", lambda: source_root)
    monkeypatch.setattr("forge.install.installer._get_git_tracked_files", lambda _repo: None)

    project = tmp_path / "project"
    project.mkdir()
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=project,
        tracking_store=_tracking(tmp_path),
    )
    with (
        patch("forge.install.installer.installed_runtimes", return_value=_runtime_specs(CODEX_RUNTIME)),
        pytest.raises(ForgeInstallError, match="Git-eligible extension sources"),
    ):
        installer.plan(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CODEX_RUNTIME,),
            _modules_override={InstallModule.SKILLS},
        )


def test_checkout_source_root_symlink_substitution_blocks_skill_planning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, fixture_package = _write_portable_source(tmp_path)
    repo = tmp_path / "checkout"
    source_root = repo / "src"
    (source_root / "forge").mkdir(parents=True)
    shutil.copytree(fixture_package, source_root / "skills" / "portable")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "src"], check=True)

    external_source_root = tmp_path / "substituted-src"
    source_root.rename(external_source_root)
    source_root.symlink_to(external_source_root, target_is_directory=True)
    (external_source_root / "skills" / "portable" / "token.secret").write_text(
        "must not be read\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("forge.install.installer.get_forge_source_root", lambda: repo)
    monkeypatch.setattr("forge.install.installer.get_extensions_root", lambda: source_root)
    project = tmp_path / "project"
    project.mkdir()
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=project,
        tracking_store=_tracking(tmp_path),
    )
    with (
        patch("forge.install.installer.installed_runtimes", return_value=_runtime_specs(CODEX_RUNTIME)),
        pytest.raises(ForgeInstallError, match="source root must be a real directory"),
    ):
        installer.plan(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CODEX_RUNTIME,),
            _modules_override={InstallModule.SKILLS},
        )


def test_fresh_enable_rejects_substituted_skill_package_symlink(
    tmp_path: Path,
) -> None:
    _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    package_dir = Path.home() / ".agents" / "skills" / "portable"
    sibling_dir = package_dir.parent / "sibling"
    sibling_dir.mkdir(parents=True)
    sentinel = sibling_dir / "owner.txt"
    sentinel.write_text("not Forge-owned\n", encoding="utf-8")
    package_dir.symlink_to(sibling_dir, target_is_directory=True)

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
        pytest.raises(ForgeInstallError, match="security violation"),
    ):
        installer.init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CODEX_RUNTIME,),
            _modules_override={InstallModule.SKILLS},
        )

    assert package_dir.is_symlink()
    assert sentinel.read_text(encoding="utf-8") == "not Forge-owned\n"
    assert not (sibling_dir / "SKILL.md").exists()
    assert tracking.get_installation("user", None) is None


def test_apply_recheck_does_not_rollback_through_substituted_package_root(
    tmp_path: Path,
) -> None:
    _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    package_dir = Path.home() / ".agents" / "skills" / "portable"
    sibling_dir = package_dir.parent / "sibling"
    real_execute = installer._execute_file
    written_relative: list[Path] = []

    def substitute_after_first_write(file_plan: FilePlan, mode: InstallMode) -> InstalledFile:
        record = real_execute(file_plan, mode)
        if not written_relative:
            written_relative.append(Path(record.target_path).relative_to(package_dir))
            package_dir.rename(sibling_dir)
            package_dir.symlink_to(sibling_dir, target_is_directory=True)
        return record

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
        patch.object(installer, "_execute_file", side_effect=substitute_after_first_write),
        pytest.raises(ForgeInstallError, match="Refusing unsafe skill package write") as exc_info,
    ):
        installer.init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CODEX_RUNTIME,),
            _modules_override={InstallModule.SKILLS},
        )

    assert "Could not roll back" in str(exc_info.value)
    assert package_dir.is_symlink()
    assert written_relative and (sibling_dir / written_relative[0]).is_file()
    assert tracking.get_installation("user", None) is None


def test_status_sync_and_disable_reject_substituted_nested_package_directory(
    tmp_path: Path,
) -> None:
    _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)

    with patch(
        "forge.install.installer.installed_runtimes",
        return_value=_runtime_specs(CODEX_RUNTIME),
    ):
        installer.init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CODEX_RUNTIME,),
            _modules_override={InstallModule.SKILLS},
        )

    installation = tracking.get_installation("user", None)
    assert installation is not None
    package = installation.skill_packages[0]
    package_dir = Path(package.target_dir)
    nested_dir = package_dir / "references"
    sibling_dir = package_dir / "sibling"
    shutil.copytree(nested_dir, sibling_dir)
    sibling_files = tuple(sibling_dir.iterdir())
    shutil.rmtree(nested_dir)
    nested_dir.symlink_to(sibling_dir, target_is_directory=True)

    status = inspect_skill_package_status(
        installation,
        InstallScope.USER,
        None,
        tracked_installations=tracking.list_installations(),
    )

    assert status[0].state == "invalid-target"
    assert status[0].target_present is True
    assert status[0].recovery is not None and "unexpected package entry" in status[0].recovery
    with pytest.raises(ForgeInstallError, match="Cannot change extensions"):
        installer.update()
    with pytest.raises(ForgeInstallError, match="security violation"):
        installer.uninstall()
    assert nested_dir.is_symlink()
    assert all(path.is_file() for path in sibling_files)
    assert tracking.get_installation("user", None) is not None


def test_enable_rerun_refreshes_absent_managed_runtime_and_explicit_filter_preserves_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path.home()
    _, source_package = _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    shared: _InstallerBaseSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.COPY,
        "_modules_override": {InstallModule.SKILLS},
    }

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CLAUDE_CODE_RUNTIME, CODEX_RUNTIME),
        ),
    ):
        installer.init(
            **shared,
            skill_runtimes=(CLAUDE_CODE_RUNTIME, CODEX_RUNTIME),
        )

    codex_skill = home / ".agents" / "skills" / "portable" / "SKILL.md"
    (source_package / "content.md").write_text("# Portable\n\nRe-enabled body.\n", encoding="utf-8")
    (source_package / "references" / "note.md").unlink()
    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CLAUDE_CODE_RUNTIME),
        ),
    ):
        automatic = installer.init(**shared)

    assert not automatic.has_conflicts
    assert {package.runtime for package in automatic.skill_packages if package.cache_dir is not None} == {
        CLAUDE_CODE_RUNTIME,
        CODEX_RUNTIME,
    }
    assert codex_skill.is_file()
    assert "Re-enabled body" in codex_skill.read_text(encoding="utf-8")
    assert not (codex_skill.parent / "references" / "note.md").exists()

    edited = codex_skill.read_text(encoding="utf-8") + "\noperator note\n"
    codex_skill.write_text(edited, encoding="utf-8")
    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CLAUDE_CODE_RUNTIME),
        ),
    ):
        narrowed = installer.init(
            **shared,
            skill_runtimes=(CLAUDE_CODE_RUNTIME,),
        )

    preserved = next(package for package in narrowed.skill_packages if package.runtime == CODEX_RUNTIME)
    assert preserved.action == "skip"
    assert preserved.reason == SkillPlanReason.MANAGED_RUNTIME_PRESERVATION.value
    assert str(codex_skill) in preserved.file_paths
    assert codex_skill.read_text(encoding="utf-8") == edited
    installation = tracking.get_installation("user", None)
    assert installation is not None
    assert {package.runtime for package in installation.skill_packages} == {
        CLAUDE_CODE_RUNTIME,
        CODEX_RUNTIME,
    }
    assert str(codex_skill) in {tracked.target_path for tracked in installation.files}


def test_explicit_codex_enable_preserves_and_upgrades_legacy_claude_package_tracking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    shared: _InstallerBaseSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.COPY,
        "_modules_override": {InstallModule.SKILLS},
    }

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CLAUDE_CODE_RUNTIME),
        ),
    ):
        initial = installer.init(
            **shared,
            skill_runtimes=(CLAUDE_CODE_RUNTIME,),
        )
    claude_target = Path(next(package.target_dir for package in initial.skill_packages if package.target_dir))
    legacy_payload = json.loads(tracking.path.read_text(encoding="utf-8"))
    legacy_payload["version"] = 1
    legacy_payload["installations"]["user"].pop("skill_packages")
    tracking.path.write_text(json.dumps(legacy_payload), encoding="utf-8")
    assert tracking.read().installations["user"].skill_packages == []

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
    ):
        plan = installer.init(
            **shared,
            skill_runtimes=(CODEX_RUNTIME,),
        )

    preserved = next(package for package in plan.skill_packages if package.runtime == CLAUDE_CODE_RUNTIME)
    assert preserved.reason == SkillPlanReason.MANAGED_RUNTIME_PRESERVATION.value
    assert (claude_target / "SKILL.md").is_file()
    upgraded = tracking.get_installation("user", None)
    assert upgraded is not None
    assert {(package.runtime, package.skill) for package in upgraded.skill_packages} == {
        (CLAUDE_CODE_RUNTIME, "portable"),
        (CODEX_RUNTIME, "portable"),
    }


def test_user_codex_install_checks_tracked_project_packages_outside_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path.home()
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    _write_portable_source(tmp_path)
    tracking = TrackingStore()
    project_installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=project,
        tracking_store=tracking,
    )
    user_installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    kwargs: _InstallerSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.COPY,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS},
    }

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
    ):
        project_installer.init(**kwargs)
        monkeypatch.chdir(outside)
        blocked = user_installer.init(**kwargs)

        project_package = project / ".agents" / "skills" / "portable"
        conflict = next(package for package in blocked.skill_packages if package.runtime == CODEX_RUNTIME)
        assert blocked.has_conflicts
        assert conflict.reason == SkillPlanReason.FORGE_MANAGED_SCOPE_DUPLICATE.value
        assert conflict.duplicate_dirs == [str(project_package)]
        assert tracking.get_installation("user", None) is None
        assert not (home / ".agents" / "skills" / "portable").exists()


def test_user_codex_install_ignores_untracked_projects_outside_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside"
    unrelated_package = tmp_path / "unrelated" / ".agents" / "skills" / "portable"
    outside.mkdir()
    unrelated_package.mkdir(parents=True)
    unrelated_skill = unrelated_package / "SKILL.md"
    unrelated_skill.write_text("untracked project package\n", encoding="utf-8")
    _write_portable_source(tmp_path)
    tracking = TrackingStore()
    user_installer = Installer(scope=InstallScope.USER, tracking_store=tracking)

    monkeypatch.chdir(outside)
    with patch(
        "forge.install.installer.installed_runtimes",
        return_value=_runtime_specs(CODEX_RUNTIME),
    ):
        result = user_installer.init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CODEX_RUNTIME,),
            _modules_override={InstallModule.SKILLS},
        )

    assert not result.has_conflicts
    assert (Path.home() / ".agents" / "skills" / "portable" / "SKILL.md").is_file()
    assert unrelated_skill.read_text(encoding="utf-8") == "untracked project package\n"


def test_cross_scope_codex_duplicate_keeps_managed_provenance_and_safe_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path.home()
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    _write_portable_source(tmp_path)
    tracking = TrackingStore()
    project_installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=project,
        tracking_store=tracking,
    )
    user_installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    kwargs: _InstallerSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.COPY,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS},
    }

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
    ):
        project_installer.init(**kwargs)

        # Reconstruct a pre-existing ambiguous state so both directions of
        # status/recovery remain covered without bypassing the new preflight.
        project_installation = tracking.get_installation("project", str(project))
        assert project_installation is not None
        assert tracking.remove_installation("project", str(project))
        monkeypatch.chdir(outside)
        user_installer.init(**kwargs)
        tracking.set_installation("project", project_installation, str(project))

    preview = project_installer.plan_update()

    conflict = next(package for package in preview.skill_packages if package.runtime == CODEX_RUNTIME)
    user_package = home / ".agents" / "skills" / "portable"
    assert preview.has_conflicts
    assert conflict.reason == SkillPlanReason.FORGE_MANAGED_SCOPE_DUPLICATE.value
    assert conflict.duplicate_dirs == [str(user_package)]

    project_installation = tracking.get_installation("project", str(project))
    assert project_installation is not None
    status = inspect_skill_package_status(
        project_installation,
        InstallScope.PROJECT,
        project,
        tracked_installations=tracking.list_installations(),
    )
    assert status[0].state == "duplicate"
    assert status[0].duplicate_dirs == (str(user_package),)
    assert status[0].recovery is not None
    assert "forge extension disable --scope user" in status[0].recovery
    assert f"cd {project} && forge extension sync --scope project" in status[0].recovery
    assert "Remove or rename untracked" not in status[0].recovery

    json_status = CliRunner().invoke(
        extensions,
        ["status", "--scope", "project", "--root", str(project), "--json"],
    )
    assert json_status.exit_code == 0, json_status.output
    json_package = json.loads(json_status.output)[0]["skill_packages"][0]
    assert json_package["state"] == "duplicate"
    assert "forge extension disable --scope user" in json_package["recovery"]
    human_status = CliRunner().invoke(
        extensions,
        ["status", "--scope", "project", "--root", str(project)],
    )
    assert human_status.exit_code == 0, human_status.output
    assert "forge extension disable --scope user" in " ".join(human_status.output.split())

    user_installation = tracking.get_installation("user", None)
    assert user_installation is not None
    assert Path.cwd() == outside
    user_status = inspect_skill_package_status(
        user_installation,
        InstallScope.USER,
        None,
        tracked_installations=tracking.list_installations(),
    )
    assert user_status[0].recovery is not None
    assert f"cd {project} && forge extension disable --scope project" in user_status[0].recovery
    assert "forge extension sync --scope user" in user_status[0].recovery


@pytest.mark.parametrize(
    ("project_key", "with_coherent_files", "row_mismatch"),
    [
        ("relative", True, False),
        ("absolute", False, False),
        ("absolute", True, True),
    ],
    ids=["relative-project-key", "empty-package-ownership", "key-row-mismatch"],
)
def test_malformed_tracking_cannot_claim_codex_duplicate_provenance(
    project_key: str,
    with_coherent_files: bool,
    row_mismatch: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    monkeypatch.chdir(project)
    _write_portable_source(tmp_path)
    duplicate_file = project / ".agents" / "skills" / "portable" / "SKILL.md"
    duplicate_file.parent.mkdir(parents=True)
    duplicate_file.write_text("operator-owned\n", encoding="utf-8")
    package_files = [str(duplicate_file)] if with_coherent_files else []
    installed_files = (
        [
            InstalledFile(
                target_path=str(duplicate_file),
                source_path=str(tmp_path / "claimed-source"),
                checksum=compute_checksum(duplicate_file),
                mode="copy",
                installed_at="2026-07-17T00:00:00+00:00",
            )
        ]
        if with_coherent_files
        else []
    )
    project_path = "." if project_key == "relative" else str(project)
    tracking = _tracking(tmp_path)
    if not with_coherent_files:
        with pytest.raises(TrackingCorruptedError, match="file_paths must not be empty"):
            tracking.set_installation(
                "project",
                Installation(
                    scope="project",
                    mode="copy",
                    profile="standard",
                    modules_enabled=[InstallModule.SKILLS.value],
                    files=installed_files,
                    skill_packages=[
                        InstalledSkillPackage(
                            runtime=CODEX_RUNTIME,
                            skill="portable",
                            target_dir=str(duplicate_file.parent),
                            file_paths=package_files,
                        )
                    ],
                ),
                project_path,
            )
        return
    tracking.set_installation(
        "project",
        Installation(
            scope="project",
            mode="copy",
            profile="standard",
            modules_enabled=[InstallModule.SKILLS.value],
            files=installed_files,
            skill_packages=[
                InstalledSkillPackage(
                    runtime=CODEX_RUNTIME,
                    skill="portable",
                    target_dir=str(duplicate_file.parent),
                    file_paths=package_files,
                )
            ],
        ),
        project_path,
    )
    if row_mismatch:
        manifest = tracking.read()
        manifest.installations[f"project:{project}"].project_path = str(tmp_path / "different-project")
        tracking.write(manifest)

    with patch(
        "forge.install.installer.installed_runtimes",
        return_value=_runtime_specs(CODEX_RUNTIME),
    ):
        plan = Installer(scope=InstallScope.USER, tracking_store=tracking).plan(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CODEX_RUNTIME,),
            _modules_override={InstallModule.SKILLS},
        )

    package = next(item for item in plan.skill_packages if item.runtime == CODEX_RUNTIME)
    assert package.action == "conflict"
    assert package.reason == SkillPlanReason.DUPLICATE_SCAN_CHAIN.value
    assert package.duplicate_dirs == [str(duplicate_file.parent)]


def test_project_package_with_symlinked_parent_is_not_its_own_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_project = tmp_path / "real-project"
    project_alias = tmp_path / "project-alias"
    real_project.mkdir()
    project_alias.symlink_to(real_project, target_is_directory=True)
    _write_portable_source(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=project_alias,
        tracking_store=_tracking(tmp_path),
    )
    kwargs: _InstallerSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.COPY,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS},
    }

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
    ):
        installer.init(**kwargs)
    preview = installer.plan_update()

    assert not preview.has_conflicts
    package = next(item for item in preview.skill_packages if item.runtime == CODEX_RUNTIME)
    assert package.duplicate_dirs == []


def test_dry_run_does_not_materialize_cache_and_symlinks_use_stable_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_portable_source(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=_tracking(tmp_path))
    kwargs: _InstallerSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.SYMLINK,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS},
    }

    with (
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


@pytest.mark.parametrize(
    "failure",
    [
        OSError("cache denied"),
        FileLockTimeoutError(Path("/tmp/compiled-skill.lock"), 5.0),
    ],
    ids=["os-error", "lock-timeout"],
)
def test_cache_materialization_failure_maps_to_clean_retryable_error(
    failure: Exception,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path.home()
    _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    kwargs: _InstallerSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.COPY,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS},
    }

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
        patch("forge.install.installer.materialize_compiled_skill", side_effect=failure),
        pytest.raises(
            ForgeInstallError,
            match="Failed to materialize compiled skill cache.*tracking was not updated",
        ),
    ):
        installer.init(**kwargs)

    assert tracking.get_installation("user", None) is None
    assert not (home / ".agents" / "skills" / "portable").exists()


def test_mid_apply_failure_rolls_back_new_files_and_remains_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path.home()
    _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    kwargs: _InstallerSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.COPY,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS},
    }
    original_record = installer._installed_file_record
    recorded_targets: list[Path] = []

    def fail_second_ownership_record(file_plan: FilePlan, mode: InstallMode) -> InstalledFile:
        if recorded_targets:
            raise OSError("injected post-write checksum failure")
        installed = original_record(file_plan, mode)
        recorded_targets.append(Path(file_plan.target_path))
        return installed

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
        patch.object(
            installer,
            "_installed_file_record",
            side_effect=fail_second_ownership_record,
        ),
        pytest.raises(ForgeInstallError, match="tracking was not updated") as exc_info,
    ):
        installer.init(**kwargs)

    assert "Newly created extension files were rolled back" in str(exc_info.value)
    assert tracking.get_installation("user", None) is None
    package_dir = home / ".agents" / "skills" / "portable"
    assert recorded_targets == [package_dir / "SKILL.md"]
    assert not package_dir.exists()

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
    ):
        recovered = installer.init(**kwargs)

    assert not recovered.has_conflicts
    assert tracking.get_installation("user", None) is not None


def test_skip_record_refresh_failure_rolls_back_earlier_new_file_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path.home()
    _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    kwargs: _InstallerSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.COPY,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS},
    }
    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
    ):
        installer.init(**kwargs)

    target = home / ".agents" / "skills" / "portable" / "SKILL.md"
    target.unlink()
    tracking_before = tracking.path.read_bytes()
    original_record = installer._installed_file_record

    def fail_skip_record(file_plan: FilePlan, mode: InstallMode) -> InstalledFile:
        if file_plan.action == "skip":
            raise OSError("injected checksum refresh failure")
        return original_record(file_plan, mode)

    with (
        patch("forge.install.installer.installed_runtimes", return_value=[]),
        patch.object(installer, "_installed_file_record", side_effect=fail_skip_record),
        pytest.raises(ForgeInstallError, match="Failed to refresh extension file ownership") as exc_info,
    ):
        installer.update()

    assert "Newly created extension files were rolled back" in str(exc_info.value)
    assert not target.exists()
    assert tracking.path.read_bytes() == tracking_before

    with (patch("forge.install.installer.installed_runtimes", return_value=[]),):
        recovered = installer.update()

    assert not recovered.has_conflicts
    assert target.is_file()


def test_unchanged_sync_preserves_file_install_timestamps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    kwargs: _InstallerSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.COPY,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS},
    }
    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
    ):
        installer.init(**kwargs)

    before = tracking.get_installation("user", None)
    assert before is not None
    installed_at_by_target = {record.target_path: record.installed_at for record in before.files}

    with (
        patch("forge.install.installer.installed_runtimes", return_value=[]),
        patch("forge.install.installer.now_iso", return_value="2099-01-01T00:00:00+00:00"),
    ):
        plan = installer.update()

    assert {file_plan.action for file_plan in plan.files} == {"skip"}
    after = tracking.get_installation("user", None)
    assert after is not None
    assert {record.target_path: record.installed_at for record in after.files} == installed_at_by_target


def test_package_directory_symlink_blocks_before_writing_outside_runtime_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path.home()
    _write_portable_source(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    package_dir = home / ".agents" / "skills" / "portable"
    package_dir.parent.mkdir(parents=True)
    package_dir.symlink_to(external, target_is_directory=True)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
        pytest.raises(ForgeInstallError, match="security violation"),
    ):
        installer.init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CODEX_RUNTIME,),
            _modules_override={InstallModule.SKILLS},
        )

    assert list(external.iterdir()) == []
    assert tracking.get_installation("user", None) is None


def test_invalid_tracked_runtime_blocks_sync_without_dropping_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    kwargs: _InstallerSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.COPY,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS},
    }
    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
    ):
        installer.init(**kwargs)

    installation = tracking.get_installation("user", None)
    assert installation is not None
    target = Path(installation.skill_packages[0].target_dir) / "SKILL.md"
    installation.skill_packages[0].runtime = "unknown-runtime"
    tracking.set_installation("user", installation, None)
    before = tracking.path.read_bytes()

    with (pytest.raises(ForgeInstallError, match="tracked skill package ownership is invalid"),):
        installer.update()

    assert target.is_file()
    assert tracking.path.read_bytes() == before


def test_stale_unlink_failure_preserves_tracking_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path.home()
    _, source_package = _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    kwargs: _InstallerSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.COPY,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS},
    }
    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
    ):
        installer.init(**kwargs)

    stale_target = home / ".agents" / "skills" / "portable" / "references" / "note.md"
    (source_package / "references" / "note.md").unlink()
    before = tracking.path.read_bytes()
    real_unlink = Path.unlink

    def fail_stale_unlink(path: Path, *args, **kwargs) -> None:
        if path == stale_target:
            raise PermissionError("injected stale unlink failure")
        real_unlink(path, *args, **kwargs)

    with (
        patch("forge.install.installer.installed_runtimes", return_value=[]),
        patch.object(Path, "unlink", fail_stale_unlink),
        pytest.raises(ForgeInstallError, match="Failed to remove stale tracked extension file"),
    ):
        installer.update()

    assert stale_target.is_file()
    assert tracking.path.read_bytes() == before


def test_tracking_commit_failure_rolls_back_new_package_files_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path.home()
    _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    kwargs: _InstallerSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.COPY,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS},
    }
    package_dir = home / ".agents" / "skills" / "portable"

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
        patch.object(tracking, "set_installation", side_effect=OSError("disk full")),
        pytest.raises(ForgeInstallError, match="Failed to commit extension tracking"),
    ):
        installer.init(**kwargs)

    assert not package_dir.exists()
    assert tracking.get_installation("user", None) is None

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
    ):
        recovered = installer.init(**kwargs)
    assert not recovered.has_conflicts
    assert (package_dir / "SKILL.md").is_file()


def test_settings_failure_rolls_back_new_codex_package_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path.home()
    _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    kwargs: _InstallerSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.COPY,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS, InstallModule.PERMISSIONS},
    }
    package_dir = home / ".agents" / "skills" / "portable"

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
        patch("forge.install.installer._ensure_hook_dispatcher"),
        patch(
            "forge.install.installer.write_settings",
            side_effect=OSError("settings read-only"),
        ),
        pytest.raises(ForgeInstallError, match="Failed to write Claude settings"),
    ):
        installer.init(**kwargs)

    assert not package_dir.exists()
    assert tracking.get_installation("user", None) is None

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
        patch("forge.install.installer._ensure_hook_dispatcher"),
    ):
        recovered = installer.init(**kwargs)
    assert not recovered.has_conflicts
    assert (package_dir / "SKILL.md").is_file()


def test_settings_ownership_save_failure_restores_settings_sidecars_and_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path.home()
    monkeypatch.setenv("CLAUDE_HOME", str(home / ".claude"))
    _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    kwargs: _InstallerSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.COPY,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS, InstallModule.PERMISSIONS},
    }
    settings_path = home / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text('{"permissions": {"allow": ["User(*)"]}}\n', encoding="utf-8")
    prior_settings = settings_path.read_bytes()
    prior_added = settings_path.parent / ".settings.json.forge.added.20000101-000000"
    prior_added.write_text('{"permissions": {"allow": ["Prior(*)"]}}\n', encoding="utf-8")
    prior_added_content = prior_added.read_bytes()
    partial_added = settings_path.parent / ".settings.json.forge.added.20990101-000000"
    package_dir = home / ".agents" / "skills" / "portable"

    def corrupt_sidecars_then_fail(_settings_path: Path, _added: dict) -> Path:
        prior_added.write_text("corrupted\n", encoding="utf-8")
        partial_added.write_text("partial\n", encoding="utf-8")
        raise OSError("ownership sidecar read-only")

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
        patch("forge.install.installer._ensure_hook_dispatcher"),
        patch(
            "forge.install.installer.save_added_settings",
            side_effect=corrupt_sidecars_then_fail,
        ),
        pytest.raises(ForgeInstallError, match="Failed to save Claude settings ownership") as exc_info,
    ):
        installer.init(**kwargs)

    assert "settings ownership state were rolled back" in str(exc_info.value)
    assert settings_path.read_bytes() == prior_settings
    assert prior_added.read_bytes() == prior_added_content
    assert not partial_added.exists()
    assert find_added_files(settings_path) == [prior_added]
    assert not package_dir.exists()
    assert tracking.get_installation("user", None) is None

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
        patch("forge.install.installer._ensure_hook_dispatcher"),
    ):
        recovered = installer.init(**kwargs)
    assert not recovered.has_conflicts

    installer.uninstall()
    assert json.loads(settings_path.read_bytes()) == json.loads(prior_settings)


def test_tracking_commit_failure_restores_settings_sidecars_and_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path.home()
    monkeypatch.setenv("CLAUDE_HOME", str(home / ".claude"))
    _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    kwargs: _InstallerSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.COPY,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS, InstallModule.PERMISSIONS},
    }
    settings_path = home / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text('{"permissions": {"allow": ["User(*)"]}}\n', encoding="utf-8")
    prior_settings = settings_path.read_bytes()
    prior_added = settings_path.parent / ".settings.json.forge.added.20000101-000000"
    prior_added.write_text('{"permissions": {"allow": ["Prior(*)"]}}\n', encoding="utf-8")
    prior_added_content = prior_added.read_bytes()
    package_dir = home / ".agents" / "skills" / "portable"

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
        patch("forge.install.installer._ensure_hook_dispatcher"),
        patch.object(tracking, "set_installation", side_effect=OSError("disk full")),
        pytest.raises(ForgeInstallError, match="Failed to commit extension tracking") as exc_info,
    ):
        installer.init(**kwargs)

    assert "settings ownership state were rolled back" in str(exc_info.value)
    assert settings_path.read_bytes() == prior_settings
    assert prior_added.read_bytes() == prior_added_content
    assert find_added_files(settings_path) == [prior_added]
    assert not package_dir.exists()
    assert tracking.get_installation("user", None) is None

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
        patch("forge.install.installer._ensure_hook_dispatcher"),
    ):
        recovered = installer.init(**kwargs)
    assert not recovered.has_conflicts

    installer.uninstall()
    assert json.loads(settings_path.read_bytes()) == json.loads(prior_settings)


def test_stale_failure_with_new_file_rolls_back_addition_and_remains_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path.home()
    _, source_package = _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    kwargs: _InstallerSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.COPY,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS},
    }
    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
    ):
        installer.init(**kwargs)

    package_dir = home / ".agents" / "skills" / "portable"
    stale_target = package_dir / "references" / "note.md"
    new_target = package_dir / "references" / "new.md"
    (source_package / "references" / "note.md").unlink()
    (source_package / "references" / "new.md").write_text("new\n", encoding="utf-8")
    before = tracking.path.read_bytes()
    real_unlink = Path.unlink

    def fail_stale_unlink(path: Path, *args, **kwargs) -> None:
        if path == stale_target:
            raise PermissionError("injected stale unlink failure")
        real_unlink(path, *args, **kwargs)

    with (
        patch("forge.install.installer.installed_runtimes", return_value=[]),
        patch.object(Path, "unlink", fail_stale_unlink),
        pytest.raises(ForgeInstallError, match="Failed to remove stale tracked extension file"),
    ):
        installer.update()

    assert stale_target.is_file()
    assert not new_target.exists()
    assert tracking.path.read_bytes() == before

    with (patch("forge.install.installer.installed_runtimes", return_value=[]),):
        recovered = installer.update()
    assert not recovered.has_conflicts
    assert not stale_target.exists()
    assert new_target.is_file()


def test_failed_update_commit_refreshes_checksum_on_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path.home()
    _, source_package = _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    kwargs: _InstallerSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.COPY,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS},
    }
    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
    ):
        installer.init(**kwargs)

    target = home / ".agents" / "skills" / "portable" / "SKILL.md"
    before = tracking.get_installation("user", None)
    assert before is not None
    old_checksum = next(file.checksum for file in before.files if file.target_path == str(target))
    (source_package / "content.md").write_text("# Portable\n\nUpdated body.\n", encoding="utf-8")

    with (
        patch("forge.install.installer.installed_runtimes", return_value=[]),
        patch.object(tracking, "set_installation", side_effect=OSError("disk full")),
        pytest.raises(ForgeInstallError, match="Failed to commit extension tracking"),
    ):
        installer.update()
    assert compute_checksum(target) != old_checksum

    with (patch("forge.install.installer.installed_runtimes", return_value=[]),):
        retry = installer.update()
    assert not retry.has_conflicts
    refreshed = tracking.get_installation("user", None)
    assert refreshed is not None
    refreshed_checksum = next(file.checksum for file in refreshed.files if file.target_path == str(target))
    assert refreshed_checksum == compute_checksum(target)


def test_explicit_project_root_does_not_scan_unrelated_process_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unrelated = tmp_path / "repo-a"
    target_project = tmp_path / "repo-b"
    unrelated.mkdir()
    target_project.mkdir()
    (unrelated / ".git").mkdir()
    (target_project / ".git").mkdir()
    duplicate = unrelated / ".agents" / "skills" / "portable" / "SKILL.md"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text("unrelated\n", encoding="utf-8")
    monkeypatch.chdir(unrelated)
    _write_portable_source(tmp_path)
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=target_project,
        tracking_store=_tracking(tmp_path),
    )

    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
    ):
        plan = installer.plan(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=(CODEX_RUNTIME,),
            _modules_override={InstallModule.SKILLS},
        )

    package = next(item for item in plan.skill_packages if item.runtime == CODEX_RUNTIME)
    assert package.action == "install"
    assert package.duplicate_dirs == []


def test_missing_symlink_cache_is_planned_as_update_and_repaired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path.home()
    _write_portable_source(tmp_path)
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    kwargs: _InstallerSkillKwargs = {
        "profile": InstallProfile.STANDARD,
        "mode": InstallMode.SYMLINK,
        "skill_runtimes": (CODEX_RUNTIME,),
        "_modules_override": {InstallModule.SKILLS},
    }
    with (
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=_runtime_specs(CODEX_RUNTIME),
        ),
    ):
        installer.init(**kwargs)

    target = home / ".agents" / "skills" / "portable" / "SKILL.md"
    cache_file = target.resolve()
    cache_file.unlink()
    assert target.is_symlink() and not target.exists()

    preview = installer.plan_update()
    target_plan = next(file for file in preview.files if file.target_path == str(target))
    assert target_plan.action == "update"
    assert target_plan.reason == "compiled cache missing or invalid"

    repaired = installer.update()
    assert not repaired.has_conflicts
    assert target.is_symlink()
    assert target.resolve().is_file()


def test_explicit_duplicate_blocks_all_targets_even_with_force_but_auto_skips_codex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = Path.home()
    _write_portable_source(tmp_path)
    duplicate = home / ".agents" / "skills" / "portable" / "SKILL.md"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text("user-owned\n", encoding="utf-8")
    tracking = _tracking(tmp_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)

    with (
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
    home = Path.home()
    project = tmp_path / "repo"
    nested = project / "src" / "nested"
    nested.mkdir(parents=True)
    _write_portable_source(tmp_path)
    tracking = TrackingStore()
    installer = Installer(scope=InstallScope.PROJECT, project_root=project, tracking_store=tracking)

    with (
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
    with patch.object(tracking, "read", wraps=tracking.read) as read_tracking:
        assert find_forge_installation(start=nested, tracking=tracking) == (
            InstallScope.PROJECT,
            project,
        )
    read_tracking.assert_called_once()

    monkeypatch.chdir(nested)
    with (
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

    missing_resource.symlink_to(missing_resource.with_name("gone.md"))
    dangling_status = CliRunner().invoke(extensions, ["status", "--json"])
    dangling_payload = json.loads(dangling_status.output)
    observed = dangling_payload[0]["skill_packages"][0]
    assert observed["state"] == "missing"
    assert observed["missing_file_paths"] == [str(missing_resource)]

    disabled = CliRunner().invoke(extensions, ["disable", "--yes"])
    assert disabled.exit_code == 0, disabled.output
    assert "Skill packages" in disabled.output
    assert not target.exists()
    assert tracking.get_installation("project", str(project)) is None


def test_enable_codex_only_skips_claude_version_gate_and_claude_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    _write_portable_source(tmp_path)

    with (
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


@pytest.mark.parametrize("scope", (InstallScope.USER, InstallScope.PROJECT, InstallScope.LOCAL))
def test_minimal_profile_preserves_legacy_claude_anchor_when_commands_are_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scope: InstallScope,
) -> None:
    home = Path.home()
    # This case asserts the legacy USER anchor specifically, so align the
    # runtime override with HOME instead of the root autouse fixture's sibling.
    monkeypatch.setenv("CLAUDE_HOME", str(home / ".claude"))
    project = tmp_path / "repo" if scope != InstallScope.USER else None
    if project is not None:
        project.mkdir()
    extensions_root = tmp_path / "extensions"
    (extensions_root / "commands").mkdir(parents=True)
    tracking = TrackingStore()

    with (patch("forge.install.installer._ensure_hook_dispatcher"),):
        plan = Installer(scope=scope, project_root=project, tracking_store=tracking).init(
            profile=InstallProfile.MINIMAL,
            mode=InstallMode.COPY,
        )

    expected = home / ".claude" if project is None else project / ".claude"
    assert plan.requires_claude_version
    assert expected.is_dir()


def test_runtime_option_filters_skills_but_mixed_profile_still_runs_claude_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "repo"
    project.mkdir()
    _write_portable_source(tmp_path)

    with (
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

"""Runtime/scope/profile planning tests for cross-runtime skill packages."""

from __future__ import annotations

from itertools import product
from pathlib import Path

import pytest

from forge.install.models import InstallProfile, InstallScope
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


def test_automatic_local_enable_skips_codex_without_suppressing_claude(tmp_path: Path) -> None:
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


def test_module_selection_is_reported_instead_of_silently_omitting_skills(tmp_path: Path) -> None:
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


def test_managed_codex_package_survives_temporary_binary_absence(tmp_path: Path) -> None:
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


def test_duplicate_scan_is_read_only_and_excludes_tracked_package(tmp_path: Path) -> None:
    user_root = tmp_path / "home" / ".agents" / "skills"
    project_root = tmp_path / "project" / ".agents" / "skills"
    admin_root = tmp_path / "etc" / "codex" / "skills"
    for root, marker in ((user_root, "managed"), (project_root, "project-user"), (admin_root, "admin-user")):
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
        sorted((user_root / "portable", project_root / "portable", admin_root / "portable"), key=str)
    )
    assert scan.untracked_package_dirs == tuple(sorted((project_root / "portable", admin_root / "portable"), key=str))
    assert (project_root / "portable" / "SKILL.md").read_text(encoding="utf-8") == before


def test_duplicate_scan_reports_symlink_at_scan_location_without_resolving_it(tmp_path: Path) -> None:
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

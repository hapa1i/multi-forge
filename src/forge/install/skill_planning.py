"""Pure policy and read-only discovery for runtime-specific skill installs.

The compiler owns package bytes; the installer owns writes. This module sits at
their boundary and answers which ``(scope, runtime, profile, skill)`` packages
are eligible and where each package belongs. Every selected-runtime omission is
represented as a decision, while explicit narrowing separately names preserved
runtimes so the installer can emit package-level preservation rows.

Runtime selection has three distinct origins:

* automatic enable keeps Claude, adds Codex when its binary is present, and
  retains runtimes already managed by an existing installation;
* explicit selection retains unavailable runtimes so the plan can fail clearly;
* managed update/sync uses the persisted runtime set and never consults current
  binary presence.

Codex duplicate discovery is intentionally read-only. User-owned packages are
reported to planning and are never removed or rewritten here.
"""

from __future__ import annotations

import os
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TypedDict

from forge.core.runtime import get_runtime, list_runtimes

from .models import PROFILE_RANK, InstallProfile, InstallScope

CLAUDE_CODE_RUNTIME = "claude_code"
CODEX_RUNTIME = "codex"


class RuntimeSelectionOrigin(str, Enum):
    """Why a runtime is in a skill plan."""

    AUTO = "auto"
    EXPLICIT = "explicit"
    MANAGED = "managed"


class SkillPlanAction(str, Enum):
    """One package-level planning outcome."""

    INSTALL = "install"
    SKIP = "skip"
    CONFLICT = "conflict"


class SkillPlanReason(str, Enum):
    """Stable reasons for package inclusion or omission."""

    ELIGIBLE = "eligible"
    MANAGED_PROFILE_PRESERVATION = "managed_profile_preservation"
    MANAGED_RUNTIME_PRESERVATION = "managed_runtime_preservation"
    SKILLS_MODULE_EXCLUDED = "skills_module_excluded"
    RUNTIME_EXCLUDED = "runtime_excluded"
    PROFILE_EXCLUDED = "profile_excluded"
    SCOPE_UNSUPPORTED = "scope_unsupported"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    DUPLICATE_SCAN_CHAIN = "duplicate_scan_chain"
    FORGE_MANAGED_SCOPE_DUPLICATE = "forge_managed_scope_duplicate"


class UnsupportedRuntimeSkillScope(ValueError):
    """Raised when a direct target lookup has no safe runtime/scope mapping."""


@dataclass(frozen=True)
class RuntimeSelection:
    """Deterministic runtime ids plus the selection policy that produced them."""

    runtime_ids: tuple[str, ...]
    origin: RuntimeSelectionOrigin
    unavailable_runtime_ids: tuple[str, ...] = ()
    preserved_runtime_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillCandidate:
    """Installer-facing eligibility metadata for one neutral skill source."""

    name: str
    supported_runtimes: tuple[str, ...]
    minimum_profile: InstallProfile = InstallProfile.MINIMAL


@dataclass(frozen=True)
class CodexDuplicateScan:
    """Existing same-name Codex packages found across supplied scan roots."""

    skill: str
    package_dirs: tuple[Path, ...]
    forge_managed_duplicate_dirs: tuple[Path, ...]
    untracked_package_dirs: tuple[Path, ...]


@dataclass(frozen=True)
class RuntimeSkillDecision:
    """One explicit point in the scope x runtime x profile x skill matrix."""

    scope: InstallScope
    runtime: str
    profile: InstallProfile
    skill: str
    action: SkillPlanAction
    reason: SkillPlanReason
    target_dir: Path | None = None
    duplicate_dirs: tuple[Path, ...] = ()


@dataclass(frozen=True)
class RuntimeSkillPlan:
    """Complete deterministic skill-package policy result."""

    selection: RuntimeSelection
    decisions: tuple[RuntimeSkillDecision, ...]

    @property
    def installable(self) -> tuple[RuntimeSkillDecision, ...]:
        """Packages that may proceed to compile/file planning."""

        return tuple(decision for decision in self.decisions if decision.action == SkillPlanAction.INSTALL)

    @property
    def conflicts(self) -> tuple[RuntimeSkillDecision, ...]:
        """Policy conflicts that must block installer writes."""

        return tuple(decision for decision in self.decisions if decision.action == SkillPlanAction.CONFLICT)

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)


class _DecisionBase(TypedDict):
    scope: InstallScope
    runtime: str
    profile: InstallProfile
    skill: str


def _canonical_runtime_ids(runtime_ids: Iterable[str], *, ignore_unknown: bool = False) -> tuple[str, ...]:
    requested = set(runtime_ids)
    known = {spec.id for spec in list_runtimes()}
    unknown = requested - known
    if unknown and not ignore_unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown skill runtime(s): {names}")
    return tuple(spec.id for spec in list_runtimes() if spec.id in requested)


def select_skill_runtimes(
    *,
    installed_runtime_ids: Collection[str],
    explicit_runtime_ids: Collection[str] | None = None,
    managed_runtime_ids: Collection[str] | None = None,
    existing_runtime_ids: Collection[str] = (),
) -> RuntimeSelection:
    """Select runtime candidates without conflating enable and sync semantics.

    ``managed_runtime_ids`` is authoritative even when empty. It is mutually
    exclusive with an explicit request because update/sync must not silently
    expand or shrink persisted ownership. ``existing_runtime_ids`` is the
    persisted set observed by enable: automatic selection refreshes its union
    with currently detected runtimes, while explicit selection preserves but
    does not update omitted runtimes.
    """

    if explicit_runtime_ids is not None and managed_runtime_ids is not None:
        raise ValueError("explicit and managed runtime selections are mutually exclusive")

    installed = set(_canonical_runtime_ids(installed_runtime_ids, ignore_unknown=True))
    existing = set(_canonical_runtime_ids(existing_runtime_ids))
    if managed_runtime_ids is not None:
        return RuntimeSelection(
            runtime_ids=_canonical_runtime_ids(managed_runtime_ids),
            origin=RuntimeSelectionOrigin.MANAGED,
        )

    if explicit_runtime_ids is not None:
        runtime_ids = _canonical_runtime_ids(explicit_runtime_ids)
        if not runtime_ids:
            raise ValueError("explicit runtime selection cannot be empty")
        unavailable = tuple(runtime for runtime in runtime_ids if runtime not in installed)
        return RuntimeSelection(
            runtime_ids=runtime_ids,
            origin=RuntimeSelectionOrigin.EXPLICIT,
            unavailable_runtime_ids=unavailable,
            preserved_runtime_ids=_canonical_runtime_ids(existing - set(runtime_ids)),
        )

    automatic = {CLAUDE_CODE_RUNTIME, *existing}
    if CODEX_RUNTIME in installed:
        automatic.add(CODEX_RUNTIME)
    return RuntimeSelection(
        runtime_ids=_canonical_runtime_ids(automatic),
        origin=RuntimeSelectionOrigin.AUTO,
    )


def runtime_skill_root(
    runtime: str,
    scope: InstallScope,
    *,
    user_home: Path,
    claude_home: Path,
    project_root: Path | None,
) -> Path:
    """Return the reviewed skill root for one runtime/scope pair.

    Paths are composed lexically and no directory is created. In particular,
    Codex skills never use ``CODEX_HOME`` and Codex local scope is rejected
    rather than mapped to the shared project directory.
    """

    spec = get_runtime(runtime)
    if scope.value not in spec.skill_scopes:
        raise UnsupportedRuntimeSkillScope(f"runtime '{runtime}' does not support {scope.value} skill scope")

    if runtime == CLAUDE_CODE_RUNTIME:
        root = claude_home if scope == InstallScope.USER else _require_project_root(scope, project_root) / ".claude"
        return root / "skills"
    if runtime == CODEX_RUNTIME:
        if scope == InstallScope.USER:
            return user_home / ".agents" / "skills"
        return _require_project_root(scope, project_root) / ".agents" / "skills"
    raise ValueError(f"runtime '{runtime}' declares skill scopes but has no Forge target mapping")


def _require_project_root(scope: InstallScope, project_root: Path | None) -> Path:
    if project_root is None:
        raise ValueError(f"project_root required for {scope.value} skill scope")
    return project_root


def scan_codex_skill_duplicates(
    skill: str,
    *,
    scan_roots: Iterable[Path],
    managed_package_dirs: Collection[Path] = (),
    current_package_dirs: Collection[Path] | None = None,
) -> CodexDuplicateScan:
    """Read Codex scan roots and report same-name packages without mutation.

    A candidate counts only when it is a directory containing ``SKILL.md``.
    ``managed_package_dirs`` identifies packages from all valid Forge tracking
    rows. ``current_package_dirs`` identifies the target(s) belonging to the
    installation being planned or inspected: those are self matches, while a
    managed match from another scope remains an ambiguous duplicate with safe
    disable provenance. When omitted, current dirs default to all managed dirs
    for compatibility with callers that inspect a single installation.
    """

    managed = {_absolute_path(path) for path in managed_package_dirs}
    current = managed if current_package_dirs is None else {_absolute_path(path) for path in current_package_dirs}
    package_dirs: list[Path] = []
    for scan_root in scan_roots:
        candidate = _absolute_path(scan_root / skill)
        if candidate.is_dir() and (candidate / "SKILL.md").is_file():
            package_dirs.append(candidate)
    unique = tuple(sorted(set(package_dirs), key=str))
    return CodexDuplicateScan(
        skill=skill,
        package_dirs=unique,
        forge_managed_duplicate_dirs=tuple(path for path in unique if path in managed and path not in current),
        untracked_package_dirs=tuple(path for path in unique if path not in managed and path not in current),
    )


def _absolute_path(path: Path) -> Path:
    """Canonicalize parent components while preserving the final entry itself."""

    absolute = Path(os.path.abspath(path.expanduser()))
    return absolute.parent.resolve() / absolute.name


def plan_runtime_skills(
    *,
    scope: InstallScope,
    profile: InstallProfile,
    skills_module_selected: bool,
    candidates: Iterable[SkillCandidate],
    selection: RuntimeSelection,
    user_home: Path,
    claude_home: Path,
    project_root: Path | None,
    managed_packages: Collection[tuple[str, str]] = (),
    untracked_codex_packages: Mapping[str, Collection[Path]] | None = None,
    managed_codex_duplicates: Mapping[str, Collection[Path]] | None = None,
) -> RuntimeSkillPlan:
    """Plan every selected runtime/skill pair with an explicit policy result."""

    ordered_candidates = sorted(candidates, key=lambda candidate: candidate.name)
    names = [candidate.name for candidate in ordered_candidates]
    if len(names) != len(set(names)):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        raise ValueError(f"Duplicate skill candidate(s): {', '.join(duplicates)}")
    known_runtimes = {spec.id for spec in list_runtimes()}
    for candidate in ordered_candidates:
        unknown = set(candidate.supported_runtimes) - known_runtimes
        if unknown:
            raise ValueError(f"Skill '{candidate.name}' declares unknown runtime(s): {', '.join(sorted(unknown))}")

    managed = set(managed_packages)
    untracked = untracked_codex_packages or {}
    managed_duplicates = managed_codex_duplicates or {}
    decisions: list[RuntimeSkillDecision] = []
    for runtime in selection.runtime_ids:
        spec = get_runtime(runtime)
        for candidate in ordered_candidates:
            base: _DecisionBase = {
                "scope": scope,
                "runtime": runtime,
                "profile": profile,
                "skill": candidate.name,
            }
            if not skills_module_selected:
                decisions.append(
                    RuntimeSkillDecision(
                        **base,
                        action=SkillPlanAction.SKIP,
                        reason=SkillPlanReason.SKILLS_MODULE_EXCLUDED,
                    )
                )
                continue
            if runtime not in candidate.supported_runtimes:
                decisions.append(
                    RuntimeSkillDecision(
                        **base,
                        action=SkillPlanAction.SKIP,
                        reason=SkillPlanReason.RUNTIME_EXCLUDED,
                    )
                )
                continue

            already_managed = (runtime, candidate.name) in managed
            if PROFILE_RANK[profile] < PROFILE_RANK[candidate.minimum_profile] and not already_managed:
                decisions.append(
                    RuntimeSkillDecision(
                        **base,
                        action=SkillPlanAction.SKIP,
                        reason=SkillPlanReason.PROFILE_EXCLUDED,
                    )
                )
                continue
            if scope.value not in spec.skill_scopes:
                action = (
                    SkillPlanAction.SKIP
                    if selection.origin == RuntimeSelectionOrigin.AUTO
                    else SkillPlanAction.CONFLICT
                )
                decisions.append(
                    RuntimeSkillDecision(
                        **base,
                        action=action,
                        reason=SkillPlanReason.SCOPE_UNSUPPORTED,
                    )
                )
                continue

            target_dir = (
                runtime_skill_root(
                    runtime,
                    scope,
                    user_home=user_home,
                    claude_home=claude_home,
                    project_root=project_root,
                )
                / candidate.name
            )
            if runtime in selection.unavailable_runtime_ids:
                decisions.append(
                    RuntimeSkillDecision(
                        **base,
                        action=SkillPlanAction.CONFLICT,
                        reason=SkillPlanReason.RUNTIME_UNAVAILABLE,
                        target_dir=target_dir,
                    )
                )
                continue

            untracked_duplicate_dirs = {_absolute_path(path) for path in untracked.get(candidate.name, ())}
            forge_managed_duplicate_dirs = {_absolute_path(path) for path in managed_duplicates.get(candidate.name, ())}
            duplicate_dirs = tuple(sorted(untracked_duplicate_dirs | forge_managed_duplicate_dirs, key=str))
            if runtime == CODEX_RUNTIME and duplicate_dirs:
                action = (
                    SkillPlanAction.SKIP
                    if selection.origin == RuntimeSelectionOrigin.AUTO and not already_managed
                    else SkillPlanAction.CONFLICT
                )
                decisions.append(
                    RuntimeSkillDecision(
                        **base,
                        action=action,
                        reason=(
                            SkillPlanReason.FORGE_MANAGED_SCOPE_DUPLICATE
                            if forge_managed_duplicate_dirs and not untracked_duplicate_dirs
                            else SkillPlanReason.DUPLICATE_SCAN_CHAIN
                        ),
                        target_dir=target_dir,
                        duplicate_dirs=duplicate_dirs,
                    )
                )
                continue

            decisions.append(
                RuntimeSkillDecision(
                    **base,
                    action=SkillPlanAction.INSTALL,
                    reason=(
                        SkillPlanReason.MANAGED_PROFILE_PRESERVATION
                        if already_managed and PROFILE_RANK[profile] < PROFILE_RANK[candidate.minimum_profile]
                        else SkillPlanReason.ELIGIBLE
                    ),
                    target_dir=target_dir,
                )
            )

    return RuntimeSkillPlan(selection=selection, decisions=tuple(decisions))

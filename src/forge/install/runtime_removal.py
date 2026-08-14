"""Planning and fail-closed execution for runtime-scoped extension removal."""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge.core.runtime_vocab import (
    AGENT_RUNTIME_IDS,
    CLAUDE_CODE_RUNTIME,
    CODEX_RUNTIME,
)
from forge.core.state import now_iso

from .codex_hooks import (
    CodexRuntimeRemovePlan,
    apply_codex_runtime_remove,
    get_builtin_codex_entries,
    plan_codex_runtime_remove,
)
from .exceptions import ForgeInstallError, NotInstalledError, PathBoundaryViolationError
from .models import (
    MODULE_RUNTIME_OWNERS,
    Installation,
    InstalledFile,
    InstalledSettingsEntry,
    InstalledSkillPackage,
    InstallModule,
    InstallScope,
    ModuleOwner,
    UnattributedSurface,
)
from .ownership import attribution_pair
from .path_policy import (
    get_target_root,
    tracked_file_boundary,
    validate_codex_config_scope,
    validate_path_within_boundary,
)
from .settings_merge import (
    cleanup_empty_settings,
    entries_to_added_structure,
    find_added_files,
    get_settings_path,
    read_settings,
    read_tracked_settings_baseline,
    save_added_settings,
    settings_equal,
    smart_unmerge,
    write_settings,
)
from .settings_rollback import (
    SettingsRollbackState,
    capture_settings_rollback_state,
    restore_settings_rollback_state,
)
from .tracking import TrackingStore

logger = logging.getLogger(__name__)

_CLAUDE_SETTINGS_MODULES = frozenset(
    {
        InstallModule.HOOKS.value,
        InstallModule.STATUSLINE.value,
        InstallModule.PERMISSIONS.value,
    }
)


@dataclass(frozen=True)
class RuntimeRemovalPlan:
    """Tracked surfaces selected by one runtime-scoped disable operation."""

    runtime_ids: tuple[str, ...]
    source_installation: Installation
    files: tuple[InstalledFile, ...]
    settings_entries: tuple[InstalledSettingsEntry, ...]
    surviving_settings_entries: tuple[InstalledSettingsEntry, ...]
    skill_packages: tuple[InstalledSkillPackage, ...]
    module_owners: tuple[ModuleOwner, ...]
    remove_claude_settings_ownership: bool
    remove_codex_block: bool
    retained_unattributed_count: int
    retained_unattributed_reasons: tuple[str, ...]
    post_installation: Installation
    full_coverage: bool

    @property
    def disposition(self) -> str:
        """Return the batch/UI disposition for this removal."""

        if self.full_coverage:
            return "full"
        if self.module_owners:
            return "partial"
        return "no-op"


@dataclass(frozen=True)
class _RuntimeSettingsPreflight:
    """Validated settings inputs and the exact state needed for rollback."""

    settings_path: Path
    current: dict[str, Any]
    backup: dict[str, Any]
    added_files: tuple[Path, ...]
    rollback_state: SettingsRollbackState


@dataclass(frozen=True)
class _RuntimeRemovalPreflight:
    """All knowable runtime-removal safety checks, captured before mutation."""

    files: tuple[tuple[InstalledFile, Path, Path], ...]
    settings: _RuntimeSettingsPreflight | None
    codex: CodexRuntimeRemovePlan | None


def build_runtime_removal_plan(
    installation: Installation,
    runtime_ids: tuple[str, ...],
) -> RuntimeRemovalPlan:
    """Select only tracked surfaces owned by ``runtime_ids``.

    Runtime/module eligibility comes from ``MODULE_RUNTIME_OWNERS``, while
    deletion authority comes from the installation's durable owner relation.
    Legacy-unattributed rows are selected only when the request covers the
    complete installation.
    """

    selected_runtime_ids = tuple(runtime_id for runtime_id in AGENT_RUNTIME_IDS if runtime_id in set(runtime_ids))
    unknown_runtime_ids = set(runtime_ids) - set(AGENT_RUNTIME_IDS)
    if unknown_runtime_ids:
        unknown = ", ".join(sorted(unknown_runtime_ids))
        raise ValueError(f"unknown runtime id(s): {unknown}")

    tracked_pairs = {(owner.module, owner.runtime) for owner in installation.module_owners}
    eligible_pairs = {
        (module.value, runtime_id)
        for module, owner_runtime_ids in MODULE_RUNTIME_OWNERS.items()
        for runtime_id in owner_runtime_ids
        if runtime_id in selected_runtime_ids
    }
    selected_pairs = tracked_pairs & eligible_pairs

    managed_runtime_ids = {runtime for _module, runtime in tracked_pairs}
    selects_every_runtime = set(AGENT_RUNTIME_IDS).issubset(selected_runtime_ids)
    full_coverage = selects_every_runtime or (
        bool(managed_runtime_ids) and managed_runtime_ids.issubset(selected_runtime_ids)
    )

    def row_is_selected(row: InstalledFile | InstalledSettingsEntry) -> bool:
        pair = attribution_pair(row.attribution)
        if pair is None:
            return full_coverage
        return pair in selected_pairs

    selected_files = tuple(file_record for file_record in installation.files if row_is_selected(file_record))
    surviving_files = [file_record for file_record in installation.files if not row_is_selected(file_record)]
    selected_settings_entries = tuple(
        settings_entry for settings_entry in installation.settings_entries if row_is_selected(settings_entry)
    )
    surviving_settings_entries = tuple(
        settings_entry for settings_entry in installation.settings_entries if not row_is_selected(settings_entry)
    )
    selected_skill_packages = tuple(
        package
        for package in installation.skill_packages
        if (InstallModule.SKILLS.value, package.runtime) in selected_pairs
    )
    surviving_skill_packages = [
        package
        for package in installation.skill_packages
        if (InstallModule.SKILLS.value, package.runtime) not in selected_pairs
    ]
    selected_module_owners = tuple(
        owner for owner in installation.module_owners if (owner.module, owner.runtime) in selected_pairs
    )
    surviving_module_owners = [
        owner for owner in installation.module_owners if (owner.module, owner.runtime) not in selected_pairs
    ]

    remove_claude_settings_ownership = any(
        module in _CLAUDE_SETTINGS_MODULES and runtime == CLAUDE_CODE_RUNTIME for module, runtime in selected_pairs
    )
    remove_codex_block = (InstallModule.HOOKS.value, CODEX_RUNTIME) in selected_pairs
    retained_unattributed_reasons_all = [
        row.attribution.unattributed_reason
        for row in surviving_files
        if isinstance(row.attribution, UnattributedSurface)
    ]
    retained_unattributed_reasons_all.extend(
        row.attribution.unattributed_reason
        for row in surviving_settings_entries
        if isinstance(row.attribution, UnattributedSurface)
    )
    retained_unattributed_reasons = tuple(sorted(set(retained_unattributed_reasons_all)))

    post_installation = deepcopy(installation)
    post_installation.module_owners = surviving_module_owners
    post_installation.files = surviving_files
    post_installation.skill_packages = surviving_skill_packages
    post_installation.settings_entries = list(surviving_settings_entries)
    if full_coverage or (remove_claude_settings_ownership and not surviving_settings_entries):
        post_installation.settings_backup_path = None
    if remove_codex_block:
        post_installation.codex_config_path = None
        post_installation.codex_commands = []

    return RuntimeRemovalPlan(
        runtime_ids=selected_runtime_ids,
        source_installation=deepcopy(installation),
        files=selected_files,
        settings_entries=selected_settings_entries,
        surviving_settings_entries=surviving_settings_entries,
        skill_packages=selected_skill_packages,
        module_owners=selected_module_owners,
        remove_claude_settings_ownership=remove_claude_settings_ownership,
        remove_codex_block=remove_codex_block,
        retained_unattributed_count=len(retained_unattributed_reasons_all),
        retained_unattributed_reasons=retained_unattributed_reasons,
        post_installation=post_installation,
        full_coverage=full_coverage,
    )


class RuntimeRemovalExecutor:
    """Apply runtime-removal plans through shared install safety boundaries."""

    def __init__(
        self,
        *,
        scope: InstallScope,
        project_root: Path | None,
        project_path: str | None,
        tracking: TrackingStore,
    ) -> None:
        self._scope = scope
        self._project_root = project_root
        self._project_path = project_path
        self._tracking = tracking

    def plan(self, runtime_ids: tuple[str, ...]) -> RuntimeRemovalPlan:
        """Plan removal of the tracked surfaces owned by ``runtime_ids``."""

        return build_runtime_removal_plan(self._get_installation(), runtime_ids)

    def validate(self, plan: RuntimeRemovalPlan) -> None:
        """Run every knowable runtime-removal safety check without mutation."""

        existing = self._get_installation()
        if existing != plan.source_installation:
            raise ForgeInstallError(
                "extension tracking changed after runtime removal was planned; rerun the disable command"
            )
        if plan.disposition != "no-op":
            self._preflight(existing, plan)

    def uninstall(
        self,
        runtime_ids: tuple[str, ...],
        *,
        expected_plan: RuntimeRemovalPlan | None = None,
    ) -> RuntimeRemovalPlan:
        """Remove selected runtime surfaces and reconcile tracking after faults."""

        existing = self._get_installation()
        plan = build_runtime_removal_plan(existing, runtime_ids)
        if expected_plan is not None and plan != expected_plan:
            raise ForgeInstallError(
                "extension tracking changed after runtime removal was planned; rerun the disable command"
            )
        if plan.disposition == "no-op":
            return plan

        preflight = self._preflight(existing, plan)
        removed_file_paths: set[str] = set()
        dirs_to_clean: set[tuple[Path, Path]] = set()
        # SKILL.md is the package identity, so remove it last. While any sibling
        # remains, fault reconciliation retains the package row; once SKILL.md is
        # gone, every other tracked package file has already been removed.
        ordered_files = sorted(
            preflight.files,
            key=lambda removal: Path(removal[0].target_path).name == "SKILL.md",
        )
        for file_record, target, boundary in ordered_files:
            try:
                if target.exists() or target.is_symlink():
                    target.unlink()
            except OSError as e:
                partial = self._reconciled_installation(
                    existing,
                    plan,
                    removed_file_paths=removed_file_paths,
                    settings_applied=False,
                )
                if removed_file_paths:
                    self._commit_reconciliation(
                        partial,
                        mutation_description="extension files were already removed",
                    )
                raise ForgeInstallError(
                    f"Failed to remove tracked extension file '{target}': {e}. "
                    "Tracking was reconciled to the files removed so far; rerun the same disable command."
                ) from e

            removed_file_paths.add(file_record.target_path)
            parent = target.parent
            while parent != boundary and parent.is_relative_to(boundary):
                dirs_to_clean.add((parent, boundary))
                parent = parent.parent

        for dir_path, _boundary in sorted(dirs_to_clean, key=lambda item: len(item[0].parts), reverse=True):
            try:
                dir_path.rmdir()
            except OSError:
                pass

        settings_applied = False
        settings_rollback_state: SettingsRollbackState | None = None
        if preflight.settings is not None:
            settings_rollback_state = preflight.settings.rollback_state
            try:
                current_settings_state = capture_settings_rollback_state(preflight.settings.settings_path)
            except Exception as e:
                partial = self._reconciled_installation(
                    existing,
                    plan,
                    removed_file_paths=removed_file_paths,
                    settings_applied=False,
                )
                if removed_file_paths:
                    self._commit_reconciliation(
                        partial,
                        mutation_description="extension files were already removed",
                    )
                raise ForgeInstallError(
                    f"Cannot revalidate selected Claude settings at '{preflight.settings.settings_path}': {e}. "
                    "No settings ownership was removed; rerun the same disable command."
                ) from e
            if current_settings_state != settings_rollback_state:
                partial = self._reconciled_installation(
                    existing,
                    plan,
                    removed_file_paths=removed_file_paths,
                    settings_applied=False,
                )
                if removed_file_paths:
                    self._commit_reconciliation(
                        partial,
                        mutation_description="extension files were already removed",
                    )
                raise ForgeInstallError(
                    f"Claude settings ownership changed after removal was planned: "
                    f"'{preflight.settings.settings_path}'. No settings ownership was removed; "
                    "rerun the same disable command."
                )
            try:
                self._apply_settings(plan, preflight.settings)
                settings_applied = True
            except Exception as e:
                rollback_failures = restore_settings_rollback_state(settings_rollback_state)
                partial = self._reconciled_installation(
                    existing,
                    plan,
                    removed_file_paths=removed_file_paths,
                    settings_applied=False,
                )
                if removed_file_paths:
                    self._commit_reconciliation(
                        partial,
                        mutation_description="extension files were already removed",
                        prior_settings_rollback_failures=tuple(rollback_failures),
                    )
                if rollback_failures:
                    recovery = (
                        " Settings ownership could not be restored at: "
                        f"{', '.join(rollback_failures)}. Inspect those paths before retrying."
                    )
                else:
                    recovery = " Settings and ownership sidecars were restored exactly."
                raise ForgeInstallError(
                    f"Failed to remove selected Claude settings at '{preflight.settings.settings_path}': {e}."
                    f"{recovery} Rerun the same disable command after repairing the failure."
                ) from e

        if preflight.codex is not None:
            try:
                codex_result = apply_codex_runtime_remove(preflight.codex, get_builtin_codex_entries())
            except Exception as e:
                partial = self._reconciled_installation(
                    existing,
                    plan,
                    removed_file_paths=removed_file_paths,
                    settings_applied=settings_applied,
                )
                if removed_file_paths or settings_applied:
                    self._commit_reconciliation(
                        partial,
                        mutation_description="extension files or Claude settings were already removed",
                        settings_rollback_state=settings_rollback_state,
                        settings_landed=settings_applied,
                    )
                raise ForgeInstallError(
                    f"Failed to remove the tracked Codex hook block at '{preflight.codex.config_path}': {e}. "
                    "Codex ownership was retained; rerun the same disable command."
                ) from e
            if codex_result.leftover_commands:
                logger.warning(
                    "Forge hook commands remain outside the managed block in %s: %s",
                    preflight.codex.config_path,
                    ", ".join(codex_result.leftover_commands),
                )

        final_installation = deepcopy(plan.post_installation)
        final_installation.updated_at = now_iso()
        try:
            if plan.full_coverage:
                self._tracking.remove_installation(self._scope.value, self._project_path)
            else:
                self._tracking.set_installation(
                    self._scope.value,
                    final_installation,
                    self._project_path,
                )
        except Exception as e:
            rollback_failures = (
                restore_settings_rollback_state(settings_rollback_state)
                if settings_applied and settings_rollback_state is not None
                else []
            )
            if settings_applied:
                settings_note = (
                    f" Settings rollback was incomplete at: {', '.join(rollback_failures)}."
                    if rollback_failures
                    else " Claude settings and ownership sidecars were restored to their prior state."
                )
            else:
                settings_note = ""
            raise ForgeInstallError(
                f"Failed to commit runtime removal tracking at '{self._tracking.path}': {e}. "
                "Extension removal already changed the filesystem, so the prior tracking row may over-claim removed "
                f"files or the Codex block.{settings_note} Repair the tracking path and rerun the same disable command."
            ) from e

        return plan

    def _get_installation(self) -> Installation:
        existing = self._tracking.get_installation(self._scope.value, self._project_path)
        if existing is None:
            raise NotInstalledError(self._scope.value)
        return existing

    def _preflight(
        self,
        existing: Installation,
        plan: RuntimeRemovalPlan,
    ) -> _RuntimeRemovalPreflight:
        """Validate all file, settings, sidecar, and Codex boundaries."""

        removals: list[tuple[InstalledFile, Path, Path]] = []
        for file_record in plan.files:
            target = Path(file_record.target_path)
            boundary = tracked_file_boundary(
                existing,
                target,
                "delete file",
                scope=self._scope,
                project_root=self._project_root,
            )
            validate_path_within_boundary(target, boundary, "delete file")
            removals.append((file_record, target, boundary))

        settings_preflight: _RuntimeSettingsPreflight | None = None
        if plan.remove_claude_settings_ownership or plan.full_coverage:
            settings_path = get_settings_path(self._scope, self._project_root)
            base_dir = get_target_root(self._scope, self._project_root)
            try:
                added_files = tuple(find_added_files(settings_path))
                needs_settings_transition = bool(
                    plan.settings_entries
                    or plan.surviving_settings_entries
                    or existing.settings_backup_path is not None
                    or added_files
                )
                if needs_settings_transition:
                    validate_path_within_boundary(settings_path, base_dir, "update settings")
                    for added_file in added_files:
                        validate_path_within_boundary(
                            added_file,
                            base_dir,
                            "update settings ownership",
                        )
                    baseline_path = (
                        Path(existing.settings_backup_path) if existing.settings_backup_path is not None else None
                    )
                    if baseline_path is not None:
                        validate_path_within_boundary(
                            baseline_path,
                            base_dir,
                            "read settings baseline",
                        )
                    rollback_state = capture_settings_rollback_state(settings_path)
                    current = read_settings(settings_path) if plan.settings_entries else {}
                    tracked_baseline = read_tracked_settings_baseline(baseline_path)
                    backup = tracked_baseline if plan.settings_entries else {}
                    settings_preflight = _RuntimeSettingsPreflight(
                        settings_path=settings_path,
                        current=current,
                        backup=backup,
                        added_files=added_files,
                        rollback_state=rollback_state,
                    )
            except PathBoundaryViolationError:
                raise
            except (OSError, ValueError) as e:
                raise ForgeInstallError(
                    f"Cannot safely prepare selected Claude settings at '{settings_path}': {e}"
                ) from e

        codex_preflight: CodexRuntimeRemovePlan | None = None
        if plan.remove_codex_block:
            validate_codex_config_scope(existing, scope=self._scope, project_root=self._project_root)
            tracked = Path(existing.codex_config_path)  # type: ignore[arg-type]
            codex_preflight = plan_codex_runtime_remove(tracked, get_builtin_codex_entries())
            if codex_preflight.action == "conflict":
                raise ForgeInstallError(
                    f"Cannot safely remove the tracked Codex hook block at '{tracked}': "
                    f"{codex_preflight.reason}. Repair the file and retry."
                )

        return _RuntimeRemovalPreflight(
            files=tuple(removals),
            settings=settings_preflight,
            codex=codex_preflight,
        )

    @staticmethod
    def _apply_settings(
        plan: RuntimeRemovalPlan,
        preflight: _RuntimeSettingsPreflight,
    ) -> None:
        """Smart-unmerge selected settings and update their ownership sidecar."""

        if plan.settings_entries:
            selected_added = entries_to_added_structure(list(plan.settings_entries))
            result = smart_unmerge(preflight.current, preflight.backup, selected_added)
            result = cleanup_empty_settings(result)
            backup_cleaned = cleanup_empty_settings(preflight.backup)
            if settings_equal(result, backup_cleaned):
                if backup_cleaned:
                    write_settings(preflight.settings_path, backup_cleaned)
                else:
                    preflight.settings_path.unlink(missing_ok=True)
            else:
                write_settings(preflight.settings_path, result)

        if plan.surviving_settings_entries:
            surviving_added = entries_to_added_structure(list(plan.surviving_settings_entries))
            if preflight.added_files:
                write_settings(preflight.added_files[0], surviving_added)
            else:
                save_added_settings(preflight.settings_path, surviving_added)
        else:
            for added_file in preflight.added_files:
                added_file.unlink()

    @staticmethod
    def _reconciled_installation(
        existing: Installation,
        plan: RuntimeRemovalPlan,
        *,
        removed_file_paths: set[str],
        settings_applied: bool,
    ) -> Installation:
        """Build an internally coherent row for mutations completed before a fault."""

        reconciled = deepcopy(existing)
        reconciled.files = [
            file_record for file_record in reconciled.files if file_record.target_path not in removed_file_paths
        ]
        reconciled_packages: list[InstalledSkillPackage] = []
        for package in reconciled.skill_packages:
            surviving_paths = [path for path in package.file_paths if path not in removed_file_paths]
            if len(surviving_paths) == len(package.file_paths):
                reconciled_packages.append(package)
                continue
            skill_document = str(Path(package.target_dir) / "SKILL.md")
            if skill_document not in surviving_paths:
                continue
            package.file_paths = sorted(surviving_paths)
            reconciled_packages.append(package)
        reconciled.skill_packages = reconciled_packages

        if settings_applied:
            reconciled.settings_entries = list(plan.surviving_settings_entries)
            reconciled.settings_backup_path = plan.post_installation.settings_backup_path
        reconciled.updated_at = now_iso()
        return reconciled

    def _commit_reconciliation(
        self,
        installation: Installation,
        *,
        mutation_description: str,
        settings_rollback_state: SettingsRollbackState | None = None,
        settings_landed: bool = False,
        prior_settings_rollback_failures: tuple[str, ...] = (),
    ) -> None:
        """Persist a partial runtime-removal state or report honest over-claim."""

        try:
            self._tracking.set_installation(
                self._scope.value,
                installation,
                self._project_path,
            )
        except Exception as e:
            rollback_failures = list(prior_settings_rollback_failures)
            rollback_failures.extend(
                restore_settings_rollback_state(settings_rollback_state)
                if settings_landed and settings_rollback_state is not None
                else []
            )
            if rollback_failures:
                settings_note = f" Settings rollback was incomplete at: {', '.join(rollback_failures)}."
            elif settings_landed:
                settings_note = " Claude settings and ownership sidecars were restored to their prior state."
            else:
                settings_note = ""
            raise ForgeInstallError(
                f"Failed to reconcile runtime removal tracking at '{self._tracking.path}': {e}. "
                f"{mutation_description}, and the prior tracking row may over-claim them.{settings_note} "
                "Repair the tracking path and rerun the same disable command."
            ) from e

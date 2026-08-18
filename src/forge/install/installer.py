"""Core installer logic.

Provides plan(), init(), update(), and uninstall() operations for
managing Claude Code extensions.
"""

from __future__ import annotations

import hashlib
import logging
import shlex
import shutil
import stat
import subprocess
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from functools import partial
from importlib.resources import files
from pathlib import Path
from typing import Any, NoReturn

from forge.core.paths import find_git_root
from forge.core.runtime import installed_runtimes
from forge.core.state import StateError, now_iso

# Import for CLAUDE_HOME support
from forge.session.claude.paths import get_claude_home

from .codex_hooks import (
    CodexConfigRollbackState,
    CodexMergeMutationError,
    apply_codex_merge_transaction,
    get_builtin_codex_entries,
    get_codex_config_path,
    plan_codex_merge,
    read_codex_registration,
    remove_codex_block,
    restore_codex_config_rollback_state,
)
from .exceptions import (
    ForgeInstallError,
    NoClaudeDirectoryError,
    NoForgeInstallationError,
    NotInstalledError,
    PathBoundaryViolationError,
)
from .hook_dispatcher import install_hook_dispatcher
from .models import (
    MODULE_RUNTIME_OWNERS,
    SETTINGS_ONLY_MODULES,
    SKILL_PROFILE_REQUIREMENTS,
    CodexPlan,
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
    ModuleOwner,
    SettingsPlan,
    SkillPackagePlan,
    SkillPackageStatus,
    make_installation_key,
    parse_installation_key,
)
from .module_planning import (
    apply_scope_module_policy,
    filter_modules_by_runtime,
    resolve_modules,
    validate_file_plan_ownership,
)
from .ownership import (
    attributed,
    has_module_owner,
    legacy_claude_skill_packages,
)
from .ownership import managed_runtime_ids as owned_runtime_ids
from .ownership import module_values
from .path_policy import (
    canonical_package_path,
    get_runtime_skill_root,
    get_target_root,
    tracked_file_boundary,
    tracked_skill_package_target,
    validate_codex_config_scope,
    validate_path_within_boundary,
    validate_real_skill_package_directory,
    validate_skill_package_file_path,
    validate_tracked_skill_package_files,
)
from .runtime_removal import RuntimeRemovalExecutor, RuntimeRemovalPlan
from .settings_merge import (
    backup_settings,
    cleanup_empty_settings,
    entries_to_added_structure,
    find_added_files,
    find_backup_files,
    get_settings_path,
    hooks_already_present,
    merge,
    permissions_already_present,
    read_settings,
    read_tracked_settings_baseline,
    save_added_settings,
    scalar_already_set,
    settings_equal,
    smart_unmerge,
    unmerge,
    write_settings,
)
from .settings_rollback import SettingsRollbackState as _SettingsRollbackState
from .settings_rollback import (
    capture_settings_rollback_state,
    restore_settings_rollback_state,
)
from .skill_cache import compiled_skill_cache_dir, materialize_compiled_skill
from .skill_compiler import (
    CompiledSkillFile,
    CompiledSkillPackage,
    SkillRuntime,
    compile_skill_for_runtime,
    is_compiler_owned_file,
    load_skill_sources,
)
from .skill_planning import (
    CLAUDE_CODE_RUNTIME,
    CODEX_RUNTIME,
    RuntimeSelection,
    RuntimeSelectionOrigin,
    SkillCandidate,
    SkillPlanAction,
    SkillPlanReason,
    plan_runtime_skills,
    scan_codex_skill_duplicates,
    select_skill_runtimes,
)
from .tracking import TrackingStore, compute_checksum
from .unmanaged import (
    UnmanagedSkillPackage,
    render_unmanaged_conflict_recovery,
    runtime_skill_scan_roots,
    scan_unmanaged_skill_packages,
)

logger = logging.getLogger(__name__)


_EXTENSION_MODULE_NAMES = ("skills", "agents", "commands")
_INVALID_SKILL_PACKAGE_RECOVERY = (
    "Remove the unexpected package entry or repair the invalid tracking row before sync or disable."
)


class _CodexExecutionError(Exception):
    """Codex mutation/read-back failure carrying any state that must roll back."""

    def __init__(self, message: str, cause: OSError, rollback_state: CodexConfigRollbackState | None) -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause
        self.rollback_state = rollback_state


@dataclass(frozen=True)
class _InstallApplyInputs:
    """Stable inputs shared by each ordered install-apply phase."""

    plan: InstallPlan
    profile: InstallProfile
    mode: InstallMode
    force: bool
    skill_runtimes: tuple[str, ...] | None
    modules: set[InstallModule]
    selected_runtimes: set[str]
    claude_modules: set[InstallModule]


@dataclass
class _InstallFileApplyResult:
    """Files written or refreshed before settings mutation begins."""

    installed_files: list[InstalledFile]
    newly_created_files: list[InstalledFile]


@dataclass
class _InstallSettingsApplyResult:
    """Claude settings ownership and its rollback boundary."""

    entries: list[InstalledSettingsEntry]
    backup_path: Path | None
    rollback_state: _SettingsRollbackState | None


@dataclass
class _InstallStaleReconciliationResult:
    """Final tracked files after stale ownership reconciliation."""

    files: list[InstalledFile]
    updated_at: str


@dataclass
class _InstallCodexApplyResult:
    """Authoritative Codex tracking and its rollback boundary."""

    config_path: str | None
    commands: list[str]
    rollback_state: CodexConfigRollbackState | None


def get_forge_source_root() -> Path:
    """Get the forge repo source root (for git-tracked file filtering).

    Returns the repo root when running from a checkout; returns a
    best-effort path otherwise (git operations will gracefully fail).
    """
    return Path(__file__).parent.parent.parent.parent


def _is_repo_checkout(forge_source: Path) -> bool:
    """Return True if forge_source looks like the Forge dev repo.

    Requires both the Python package (src/forge/) AND at least one extension
    directory to be present. The two-signal check rules out false positives
    like a user project that happens to have src/skills/ but isn't a Forge
    checkout.
    """
    src = forge_source / "src"
    if not (src / "forge").is_dir():
        return False
    return any((src / name).is_dir() for name in _EXTENSION_MODULE_NAMES)


def _get_bundled_extensions_path() -> Path:
    """Return the path to bundled extensions inside the installed package.

    Uses importlib.resources to locate package data — robust against
    zip imports and namespace package layouts. Extracted as a separate
    function so tests can mock it cleanly.
    """
    return Path(str(files("forge") / "_extensions"))


def get_extensions_root() -> Path:
    """Get the directory containing extension modules (skills, agents, commands).

    Tries repo checkout first (editable/dev install), then falls back
    to bundled extensions inside the wheel (forge/_extensions/).
    """
    forge_source = get_forge_source_root()
    if _is_repo_checkout(forge_source):
        return forge_source / "src"

    bundled = _get_bundled_extensions_path()
    if bundled.is_dir():
        return bundled

    raise FileNotFoundError("Extension source files not found. Reinstall Forge or run from a repo checkout.")


_EXCLUDED_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
_EXCLUDED_EXTENSIONS = {".pyc", ".pyo"}
_CLAUDE_SETTINGS_MODULES = {
    InstallModule.HOOKS,
    InstallModule.STATUSLINE,
    InstallModule.PERMISSIONS,
}


def _ensure_hook_dispatcher() -> None:
    try:
        install_hook_dispatcher()
    except Exception as e:
        raise ForgeInstallError(f"Failed to render hook dispatcher: {e}") from e


def _is_installable(path: Path) -> bool:
    """Return False for build artifacts that should never be installed."""
    if path.name.startswith("."):
        return False
    if path.suffix in _EXCLUDED_EXTENSIONS:
        return False
    if _EXCLUDED_DIR_NAMES & set(path.parts):
        return False
    return True


def _get_git_tracked_files(repo_root: Path) -> set[Path] | None:
    """Return the set of git-tracked files under repo_root, or None if unavailable."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        return {repo_root / line for line in result.stdout.splitlines() if line}
    except (OSError, subprocess.TimeoutExpired):
        return None


def _codex_available() -> bool:
    """Presence gate for the Codex-owned half of hooks."""
    from forge.core.runtime import get_runtime

    return get_runtime("codex").is_installed()


def _codex_scan_roots(project_root: Path | None, *, include_cwd: bool = True) -> tuple[Path, ...]:
    """Codex user/admin roots plus applicable CWD-to-repository project roots."""

    roots: list[Path] = [Path.home() / ".agents" / "skills"]
    anchors = [anchor for anchor in (project_root, Path.cwd() if include_cwd else None) if anchor is not None]
    for anchor in anchors:
        resolved = anchor.resolve()
        git_root = find_git_root(resolved)
        stop = git_root or resolved
        current = resolved
        while True:
            roots.append(current / ".agents" / "skills")
            if current == stop or current == current.parent:
                break
            current = current.parent
    roots.append(Path("/etc/codex/skills"))
    return tuple(dict.fromkeys(roots))


@dataclass(frozen=True)
class _TrackedCodexPackageLocation:
    target: Path
    scope: InstallScope
    project_root: Path | None


def _tracked_codex_package_locations(
    installations: Iterable[tuple[str, str | None, Installation]],
    skill: str,
) -> tuple[_TrackedCodexPackageLocation, ...]:
    """Return key-validated Codex package locations owned by tracked scopes."""

    managed: set[_TrackedCodexPackageLocation] = set()
    for scope_value, project_path, installation in installations:
        if installation.scope != scope_value or installation.project_path != project_path:
            continue
        try:
            scope = InstallScope(scope_value)
        except ValueError:
            continue
        project_root = Path(project_path) if project_path is not None else None
        if scope != InstallScope.USER and (project_root is None or not project_root.is_absolute()):
            continue
        if not has_module_owner(installation, InstallModule.SKILLS):
            continue
        tracked_file_paths = {tracked.target_path for tracked in installation.files}
        for package in installation.skill_packages:
            if package.runtime != CODEX_RUNTIME or package.skill != skill:
                continue
            if (
                not Path(package.target_dir).is_absolute()
                or not package.file_paths
                or any(not Path(file_path).is_absolute() for file_path in package.file_paths)
                or not set(package.file_paths).issubset(tracked_file_paths)
            ):
                continue
            try:
                target, expected_target = tracked_skill_package_target(
                    package,
                    scope,
                    project_root,
                    "classify managed Codex package",
                )
                validate_tracked_skill_package_files(
                    package,
                    target,
                    expected_target,
                    "classify managed Codex package",
                )
            except (KeyError, PathBoundaryViolationError, ValueError):
                continue
            skill_document = expected_target / "SKILL.md"
            skill_document_location = skill_document.parent.resolve() / skill_document.name
            if not any(
                Path(file_path).parent.resolve() / Path(file_path).name == skill_document_location
                for file_path in package.file_paths
            ):
                continue
            managed.add(
                _TrackedCodexPackageLocation(
                    target=target.parent.resolve() / target.name,
                    scope=scope,
                    project_root=project_root,
                )
            )
    return tuple(sorted(managed, key=lambda item: (str(item.target), item.scope.value)))


def _codex_package_scan_roots(
    scope: InstallScope,
    project_root: Path | None,
    tracked_locations: Iterable[_TrackedCodexPackageLocation],
) -> tuple[Path, ...]:
    """Return visible roots plus tracked projects a user package would shadow.

    A user-scope Codex package is visible from every project.  Therefore a
    valid tracked project/local package must block creation of the same user
    package even when that project is outside the caller's current directory
    chain.  Project/local packages only need the normal Codex roots visible
    from their own project.
    """

    roots = list(_codex_scan_roots(project_root, include_cwd=project_root is None))
    if scope == InstallScope.USER:
        roots.extend(location.target.parent for location in tracked_locations if location.scope != InstallScope.USER)
    return tuple(dict.fromkeys(roots))


def _assert_tracked_skill_packages_syncable(
    installation: Installation,
    scope: InstallScope,
    project_root: Path | None,
) -> None:
    """Block mutation when persisted package ownership cannot be validated."""

    invalid: list[str] = []
    for package in installation.skill_packages:
        try:
            target, expected_target = tracked_skill_package_target(
                package,
                scope,
                project_root,
                "sync skill package",
            )
            validate_tracked_skill_package_files(package, target, expected_target, "sync skill package")
        except (KeyError, PathBoundaryViolationError, ValueError):
            invalid.append(f"{package.runtime}/{package.skill}")
    if invalid:
        names = ", ".join(sorted(invalid))
        raise ForgeInstallError(
            f"Cannot change extensions while tracked skill package ownership is invalid: {names}. "
            "Run 'forge extension status' for details, then repair or remove the invalid tracking row."
        )


def _extension_scope_command(verb: str, scope: InstallScope, project_root: Path | None) -> str:
    """Return an executable lifecycle command for one tracked installation."""

    command = f"forge extension {verb} --scope {scope.value}"
    if project_root is not None:
        command = f"cd {shlex.quote(str(project_root))} && {command}"
    return command


def inspect_skill_package_status(
    installation: Installation,
    scope: InstallScope,
    project_root: Path | None,
    *,
    tracked_installations: Iterable[tuple[str, str | None, Installation]] = (),
) -> tuple[SkillPackageStatus, ...]:
    """Read tracked package health and Codex duplicate discovery without mutation."""

    statuses: list[SkillPackageStatus] = []
    tracked_rows = tuple(tracked_installations)
    sync_command = _extension_scope_command("sync", scope, project_root)
    for package in sorted(installation.skill_packages, key=lambda item: (item.runtime, item.skill)):
        try:
            target, expected_target = tracked_skill_package_target(
                package,
                scope,
                project_root,
                "inspect skill package",
            )
        except (KeyError, PathBoundaryViolationError, ValueError):
            statuses.append(
                SkillPackageStatus(
                    runtime=package.runtime,
                    skill=package.skill,
                    target_dir=package.target_dir,
                    state="invalid-target",
                    target_present=False,
                    file_paths=tuple(package.file_paths),
                    recovery=_INVALID_SKILL_PACKAGE_RECOVERY,
                )
            )
            continue

        target_present = target.is_dir() and (target / "SKILL.md").is_file()
        try:
            validate_tracked_skill_package_files(package, target, expected_target, "inspect skill package")
        except PathBoundaryViolationError:
            statuses.append(
                SkillPackageStatus(
                    runtime=package.runtime,
                    skill=package.skill,
                    target_dir=package.target_dir,
                    state="invalid-target",
                    target_present=target_present,
                    file_paths=tuple(package.file_paths),
                    recovery=_INVALID_SKILL_PACKAGE_RECOVERY,
                )
            )
            continue
        missing_file_paths = tuple(
            sorted(tracked_file for tracked_file in package.file_paths if not Path(tracked_file).is_file())
        )
        duplicate_dirs: tuple[str, ...] = ()
        managed_owners: tuple[_TrackedCodexPackageLocation, ...] = ()
        has_untracked_duplicates = False
        if package.runtime == CODEX_RUNTIME:
            tracked_locations = _tracked_codex_package_locations(tracked_rows, package.skill)
            duplicate_scan = scan_codex_skill_duplicates(
                package.skill,
                scan_roots=_codex_package_scan_roots(scope, project_root, tracked_locations),
                managed_package_dirs=(
                    target,
                    *(location.target for location in tracked_locations),
                ),
                current_package_dirs=(target,),
            )
            duplicate_paths = tuple(
                sorted(
                    {
                        *duplicate_scan.forge_managed_duplicate_dirs,
                        *duplicate_scan.untracked_package_dirs,
                    },
                    key=str,
                )
            )
            duplicate_dirs = tuple(str(path) for path in duplicate_paths)
            managed_owners = tuple(
                location
                for location in tracked_locations
                if location.target in duplicate_scan.forge_managed_duplicate_dirs
            )
            has_untracked_duplicates = bool(duplicate_scan.untracked_package_dirs)
        if duplicate_dirs:
            state = "duplicate"
            recovery_steps: list[str] = []
            for owner in managed_owners:
                command = _extension_scope_command("disable", owner.scope, owner.project_root)
                step = f"Disable the other Forge-managed package with `{command}`"
                if step not in recovery_steps:
                    recovery_steps.append(step)
            if has_untracked_duplicates:
                recovery_steps.append("Remove or rename untracked duplicates")
            suffix = " to restore missing files" if not target_present or missing_file_paths else ""
            recovery = f"{'; '.join(recovery_steps)}, then run `{sync_command}`{suffix}."
        elif target_present and not missing_file_paths:
            state = "present"
            recovery = None
        else:
            state = "missing"
            recovery = f"Run `{sync_command}` to restore the tracked package."
        statuses.append(
            SkillPackageStatus(
                runtime=package.runtime,
                skill=package.skill,
                target_dir=package.target_dir,
                state=state,
                target_present=target_present,
                file_paths=tuple(package.file_paths),
                missing_file_paths=missing_file_paths,
                duplicate_dirs=duplicate_dirs,
                recovery=recovery,
            )
        )
    return tuple(statuses)


def find_claude_root(
    start: Path | None = None,
    *,
    max_depth: int = 100,
) -> tuple[InstallScope, Path | None]:
    """Find the nearest .claude directory walking up from start.

    Used by `forge extension enable` to auto-detect scope. Walks up from start
    directory looking for a .claude/ directory. If found, returns LOCAL scope
    at that project. If reaching home directory (~), returns USER scope.

    Args:
        start: Starting directory. Defaults to cwd.
        max_depth: Maximum directory levels to traverse (safety limit).

    Returns:
        Tuple of (scope, project_root). For USER scope, project_root is None.

    Raises:
        NoClaudeDirectoryError: If no .claude found and didn't reach home,
            or if max_depth is exceeded.
    """
    if start is None:
        start = Path.cwd()

    current = start.resolve()
    home = Path.home().resolve()

    for _ in range(max_depth):
        claude_dir = current / ".claude"
        if claude_dir.is_dir():
            if current == home:
                return (InstallScope.USER, None)
            return (InstallScope.LOCAL, current)

        if current == home:
            # Special case: at home, use USER scope
            return (InstallScope.USER, None)

        parent = current.parent
        if parent == current:
            raise NoClaudeDirectoryError(str(start))

        current = parent

    # Safety limit exceeded (symlink loop, permission issues, etc.)
    raise NoClaudeDirectoryError(f"{start} (exceeded max traversal depth of {max_depth})")


def find_forge_installation(
    start: Path | None = None,
    tracking: "TrackingStore | None" = None,
    *,
    tracking_snapshot: InstalledManifest | None = None,
) -> tuple[InstallScope, Path | None]:
    """Find the nearest Forge installation walking up from start.

    Used by `forge extension disable`, `forge extension sync`, etc. to
    auto-detect scope. Walks up from start directory, checking LOCAL then
    PROJECT at each level, then USER at home.

    Claude settings use file evidence when present. Runtime-only skill installs
    can have no ``.claude`` directory, so exact project/local tracking rows are
    also consulted at each walked directory.

    Args:
        start: Starting directory. Defaults to cwd.
        tracking: TrackingStore instance. Created if not provided.
        tracking_snapshot: Optional already-validated manifest for one coherent
            caller-owned read.

    Returns:
        Tuple of (scope, project_root). For USER scope, project_root is None.

    Raises:
        NoForgeInstallationError: If no installation found.
    """
    if start is None:
        start = Path.cwd()
    if tracking is None:
        tracking = TrackingStore()

    manifest: InstalledManifest | None = tracking_snapshot

    def is_tracked(scope: InstallScope, project_path: str | None) -> bool:
        nonlocal manifest
        if manifest is None:
            manifest = tracking.read()
        return make_installation_key(scope.value, project_path) in manifest.installations

    current = start.resolve()
    home = Path.home().resolve()

    while True:
        claude_dir = current / ".claude"
        if claude_dir.is_dir():
            # Check LOCAL installation first (most specific) - file-based detection
            local_settings = claude_dir / "settings.local.json"
            local_backups = find_backup_files(local_settings)
            local_added = find_added_files(local_settings)
            if local_backups or local_added:
                return (InstallScope.LOCAL, current)

            project_settings = claude_dir / "settings.json"
            project_backups = find_backup_files(project_settings)
            project_added = find_added_files(project_settings)
            # Only check project at non-home locations (home uses USER scope)
            if current != home and (project_backups or project_added):
                return (InstallScope.PROJECT, current)

        if current != home:
            current_key = str(current)
            if is_tracked(InstallScope.LOCAL, current_key):
                return (InstallScope.LOCAL, current)
            if is_tracked(InstallScope.PROJECT, current_key):
                return (InstallScope.PROJECT, current)

        if current == home:
            user_settings = home / ".claude" / "settings.json"
            user_backups = find_backup_files(user_settings)
            user_added = find_added_files(user_settings)
            if user_backups or user_added:
                return (InstallScope.USER, None)
            # Fallback to tracking store for USER (no project_path for user scope)
            if is_tracked(InstallScope.USER, None):
                return (InstallScope.USER, None)
            break

        parent = current.parent
        if parent == current:
            break

        current = parent

    # No installation found
    raise NoForgeInstallationError(str(start))


def get_module_source_dir(module: InstallModule) -> str:
    """Get source directory name for a module.

    Args:
        module: The module.

    Returns:
        Directory name (e.g., "commands", "agents").
    """
    return module.value


class Installer:
    """Main installer for Forge extensions.

    Handles plan, init, update, and uninstall operations.
    """

    def __init__(
        self,
        scope: InstallScope = InstallScope.USER,
        project_root: Path | None = None,
        tracking_store: TrackingStore | None = None,
    ) -> None:
        """Initialize installer.

        Args:
            scope: Installation scope.
            project_root: Project root (required for PROJECT/LOCAL).
            tracking_store: Override tracking store (for testing).
        """
        self._scope = scope
        self._project_root = project_root
        self._tracking = tracking_store or TrackingStore()
        self._compiled_skill_packages: dict[tuple[str, str], CompiledSkillPackage] = {}

    @property
    def _project_path_str(self) -> str | None:
        """Get project path as string for tracking (None for user scope)."""
        if self._scope == InstallScope.USER:
            return None
        return str(self._project_root) if self._project_root else None

    def plan(
        self,
        profile: InstallProfile = InstallProfile.STANDARD,
        mode: InstallMode = InstallMode.COPY,
        with_modules: set[InstallModule] | None = None,
        without_modules: set[InstallModule] | None = None,
        force: bool = False,
        skill_runtimes: tuple[str, ...] | None = None,
        *,
        _modules_override: set[InstallModule] | None = None,
        _managed_runtime_ids: tuple[str, ...] | None = None,
    ) -> InstallPlan:
        """Compute installation plan without making changes.

        Args:
            profile: Installation profile.
            mode: Installation mode.
            with_modules: Modules to add.
            without_modules: Modules to remove.
            force: If True, override conflicts.
            skill_runtimes: Explicit runtime ids for skill packages; None selects automatically.
            _modules_override: Internal. If provided, use exactly these modules
                instead of resolving from profile. Used by update() to ensure
                only tracked modules are touched.
            _managed_runtime_ids: Internal persisted runtime set used by update/sync.

        Returns:
            InstallPlan describing what would be done.
        """
        if _modules_override is not None:
            scoped_modules = _modules_override
        else:
            scoped_modules = resolve_modules(profile, with_modules, without_modules)
        scoped_modules = apply_scope_module_policy(
            scoped_modules,
            scope=self._scope,
            explicit_modules=None if _modules_override is not None else with_modules,
        )
        self._compiled_skill_packages = {}

        manifest = self._tracking.read()
        tracked_installations = [
            (*parse_installation_key(key), installation) for key, installation in manifest.installations.items()
        ]
        existing = next(
            (
                installation
                for scope, project_path, installation in tracked_installations
                if scope == self._scope.value and project_path == self._project_path_str
            ),
            None,
        )
        if existing is not None:
            _assert_tracked_skill_packages_syncable(existing, self._scope, self._project_root)

        try:
            selection = select_skill_runtimes(
                installed_runtime_ids=tuple(runtime.id for runtime in installed_runtimes()),
                explicit_runtime_ids=skill_runtimes,
                managed_runtime_ids=_managed_runtime_ids,
                existing_runtime_ids=(owned_runtime_ids(existing) if existing is not None else ()),
            )
        except ValueError as e:
            raise ForgeInstallError(f"Invalid runtime selection: {e}") from e

        modules, module_outcomes, module_conflicts = filter_modules_by_runtime(
            scoped_modules,
            selection=selection,
            explicit_modules=None if _modules_override is not None else with_modules,
        )
        plan = InstallPlan(
            scope=self._scope.value,
            mode=mode.value,
            profile=profile.value,
            modules=sorted(module.value for module in modules),
            module_outcomes=module_outcomes,
            selected_runtimes=list(selection.runtime_ids),
            preserved_runtime_ids=list(selection.preserved_runtime_ids),
            has_conflicts=bool(module_conflicts),
            conflicts=module_conflicts,
        )

        source_root = get_extensions_root()
        target_root = get_target_root(self._scope, self._project_root)
        claude_modules = (
            {module for module in modules if CLAUDE_CODE_RUNTIME in MODULE_RUNTIME_OWNERS[module]}
            if CLAUDE_CODE_RUNTIME in selection.runtime_ids
            else set()
        )

        # The legacy file-module contract creates the Claude anchor even when a
        # selected source directory currently contains no installable files
        # (the minimal profile's commands directory is intentionally empty).
        # A skills-only Codex plan has no legacy file modules and therefore
        # remains free of unrelated .claude writes and version gating.
        if modules & {InstallModule.COMMANDS, InstallModule.AGENTS} and not target_root.is_dir():
            plan.requires_claude_version = True

        # Only filter by git when extensions come from a repo checkout. When
        # running from a wheel install, source_root is forge/_extensions/ inside
        # site-packages — typically gitignored, so a git-tracked filter would
        # exclude every file. _is_installable() handles the wheel-install case.
        forge_source = get_forge_source_root()
        checkout_source_root = forge_source / "src"
        checkout_sources = _is_repo_checkout(forge_source) and source_root == checkout_source_root
        if checkout_sources:
            try:
                source_root_mode = source_root.lstat().st_mode
            except OSError as e:
                raise ForgeInstallError(f"Failed to inspect checkout extension source root '{source_root}': {e}") from e
            if not stat.S_ISDIR(source_root_mode):
                raise ForgeInstallError(
                    f"Checkout extension source root must be a real directory, not a symlink: {source_root}"
                )
        git_eligible = _get_git_tracked_files(forge_source) if checkout_sources else None
        if checkout_sources and (forge_source / ".git").exists() and git_eligible is None:
            raise ForgeInstallError(
                "Failed to determine Git-eligible extension sources; repair the checkout or Git command before retrying"
            )

        if InstallModule.SKILLS in modules:
            self._plan_runtime_skill_packages(
                plan,
                source_root=source_root,
                profile=profile,
                mode=mode,
                existing=existing,
                force=force,
                selection=selection,
                tracked_installations=tracked_installations,
                tracking=manifest,
                eligible_source_paths=git_eligible,
            )

        for module in sorted(modules, key=lambda m: m.value):
            if module in SETTINGS_ONLY_MODULES or module == InstallModule.SKILLS:
                continue

            source_dir = source_root / get_module_source_dir(module)
            if not source_dir.is_dir():
                # Source not yet in allowlist - silently skip
                continue

            target_dir = target_root / get_module_source_dir(module)

            # Find installable source files (sorted for determinism)
            # _is_installable excludes __pycache__/.pyc unconditionally (works in
            # sanitized source trees where Git metadata is intentionally absent).
            source_files = sorted(
                f
                for f in source_dir.rglob("*")
                if f.is_file() and _is_installable(f) and (git_eligible is None or f in git_eligible)
            )

            for source_file in source_files:
                rel_path = source_file.relative_to(source_dir)
                target_file = target_dir / rel_path

                file_plan = self._plan_file(
                    source_file,
                    target_file,
                    mode,
                    existing,
                    force,
                    module=module,
                    runtime=CLAUDE_CODE_RUNTIME,
                )
                plan.files.append(file_plan)
                if file_plan.action == "conflict":
                    plan.has_conflicts = True
                    plan.conflicts.append(f"File: {file_plan.target_path} - {file_plan.reason}")
                elif file_plan.action in {"install", "update"}:
                    plan.requires_claude_version = True

        # Sort files for deterministic output
        plan.files.sort(key=lambda f: f.target_path)

        settings_plans = self._plan_settings(claude_modules, force)
        plan.settings.extend(settings_plans)
        for sp in settings_plans:
            if sp.action == "conflict":
                plan.has_conflicts = True
                plan.conflicts.append(f"Setting: {sp.key_path} - {sp.reason}")
            elif sp.action != "skip":
                plan.requires_claude_version = True

        # Sort settings for determinism
        plan.settings.sort(key=lambda s: (s.key_path, str(s.value)))

        # Codex registration is best-effort: its conflicts degrade to a
        # visible skip and never set plan.has_conflicts (another tool's
        # config must not fail the Claude install).
        plan.codex = self._plan_codex(modules, selection)

        return plan

    def _plan_runtime_skill_packages(
        self,
        plan: InstallPlan,
        *,
        source_root: Path,
        profile: InstallProfile,
        mode: InstallMode,
        existing: Installation | None,
        force: bool,
        selection: RuntimeSelection,
        tracked_installations: list[tuple[str, str | None, Installation]],
        tracking: InstalledManifest,
        eligible_source_paths: set[Path] | None,
    ) -> None:
        try:
            sources = load_skill_sources(
                source_root / InstallModule.SKILLS.value,
                eligible_source_paths=eligible_source_paths,
            )
        except (OSError, ValueError) as e:
            raise ForgeInstallError(f"Failed to load skill sources: {e}") from e

        source_by_name = {source.manifest.name: source for source in sources}
        candidates = tuple(
            SkillCandidate(
                name=source.manifest.name,
                supported_runtimes=tuple(sorted(runtime.value for runtime in source.manifest.runtime_eligibility)),
                minimum_profile=SKILL_PROFILE_REQUIREMENTS.get(source.manifest.name, InstallProfile.MINIMAL),
            )
            for source in sources
        )
        tracked_codex_roots = {
            location.target.parent
            for candidate in candidates
            for location in _tracked_codex_package_locations(tracked_installations, candidate.name)
        }
        unmanaged_records = scan_unmanaged_skill_packages(
            runtime_skill_scan_roots(
                ((self._scope, self._project_root),),
                user_home=Path.home(),
                claude_home=get_claude_home(),
                additional_codex_visibility_roots=tracked_codex_roots,
                report_visibility_entries=True,
            ),
            current_skill_names=(candidate.name for candidate in candidates),
            tracking=tracking,
        )
        unmanaged_by_package: dict[tuple[str, str], list[Path]] = {}
        unmanaged_by_path: dict[Path, UnmanagedSkillPackage] = {}
        for record in unmanaged_records:
            target = canonical_package_path(Path(record.target_dir))
            # Preserve the existing security-violation boundary for blocking
            # files and package-root symlinks. A real package directory can
            # still contain an unsafe marker or descendant; those entries go
            # through duplicate planning so their manual recovery is visible.
            try:
                target_is_real_directory = stat.S_ISDIR(target.lstat().st_mode)
            except OSError:
                target_is_real_directory = False
            if target_is_real_directory:
                unmanaged_by_package.setdefault((record.runtime, record.skill), []).append(target)
            unmanaged_by_path[target] = record
        managed_packages = {
            (package.runtime, package.skill) for package in (existing.skill_packages if existing is not None else [])
        }
        managed_packages |= legacy_claude_skill_packages(existing, self._scope, self._project_root)
        for unavailable_runtime in selection.unavailable_runtime_ids:
            plan.has_conflicts = True
            plan.conflicts.append(
                f"Skill runtime: {unavailable_runtime} - explicitly requested runtime is not installed"
            )

        untracked_codex: dict[str, tuple[Path, ...]] = {}
        managed_codex_duplicates: dict[str, tuple[Path, ...]] = {}
        if CODEX_RUNTIME in selection.runtime_ids:
            for candidate in candidates:
                current_dirs = tuple(
                    Path(package.target_dir)
                    for package in (existing.skill_packages if existing is not None else [])
                    if package.runtime == CODEX_RUNTIME and package.skill == candidate.name
                )
                tracked_locations = _tracked_codex_package_locations(tracked_installations, candidate.name)
                scan = scan_codex_skill_duplicates(
                    candidate.name,
                    scan_roots=_codex_package_scan_roots(self._scope, self._project_root, tracked_locations),
                    managed_package_dirs=tuple(location.target for location in tracked_locations),
                    current_package_dirs=current_dirs,
                )
                if scan.untracked_package_dirs:
                    untracked_codex[candidate.name] = scan.untracked_package_dirs
                if scan.forge_managed_duplicate_dirs:
                    managed_codex_duplicates[candidate.name] = scan.forge_managed_duplicate_dirs

        try:
            runtime_plan = plan_runtime_skills(
                scope=self._scope,
                profile=profile,
                skills_module_selected=True,
                candidates=candidates,
                selection=selection,
                user_home=Path.home(),
                claude_home=get_claude_home(),
                project_root=self._project_root,
                managed_packages=managed_packages,
                unmanaged_runtime_packages=unmanaged_by_package,
                untracked_codex_packages=untracked_codex,
                managed_codex_duplicates=managed_codex_duplicates,
            )
        except ValueError as e:
            raise ForgeInstallError(f"Invalid runtime skill plan: {e}") from e

        for decision in runtime_plan.decisions:
            if decision.action != SkillPlanAction.INSTALL:
                package_plan = SkillPackagePlan(
                    runtime=decision.runtime,
                    skill=decision.skill,
                    action=decision.action.value,
                    target_dir=(str(decision.target_dir) if decision.target_dir is not None else None),
                    reason=decision.reason.value,
                    duplicate_dirs=[str(path) for path in decision.duplicate_dirs],
                    recovery=render_unmanaged_conflict_recovery(
                        decision.duplicate_dirs,
                        unmanaged_by_path,
                        operation=("sync" if selection.origin == RuntimeSelectionOrigin.MANAGED else "enable"),
                        project_root=self._project_root,
                    ),
                )
                plan.skill_packages.append(package_plan)
                if decision.action == SkillPlanAction.CONFLICT:
                    plan.has_conflicts = True
                    detail = (
                        f"; duplicates: {', '.join(package_plan.duplicate_dirs)}" if package_plan.duplicate_dirs else ""
                    )
                    plan.conflicts.append(
                        f"Skill package: {decision.runtime}/{decision.skill} - {decision.reason.value}{detail}"
                    )
                continue

            if decision.target_dir is None:
                raise ForgeInstallError(
                    f"Skill planner omitted target for eligible package {decision.runtime}/{decision.skill}"
                )
            validate_real_skill_package_directory(
                decision.target_dir,
                decision.target_dir,
                "write skill package",
            )

            source = source_by_name[decision.skill]
            try:
                compiled = compile_skill_for_runtime(source, SkillRuntime(decision.runtime))
            except (OSError, ValueError) as e:
                raise ForgeInstallError(
                    f"Failed to compile skill '{decision.skill}' for runtime '{decision.runtime}': {e}"
                ) from e

            cache_dir = compiled_skill_cache_dir(compiled)
            runtime_root = get_runtime_skill_root(decision.runtime, self._scope, self._project_root)
            file_plans: list[FilePlan] = []
            for package_file in compiled.files:
                source_file = cache_dir.joinpath(*package_file.path.parts)
                target_file = decision.target_dir.joinpath(*package_file.path.parts)
                # Keep provenance metadata readable after a compiled-cache reset.
                effective_mode = InstallMode.COPY if is_compiler_owned_file(package_file.path) else mode
                validate_path_within_boundary(target_file, runtime_root, "write skill package")
                validate_skill_package_file_path(
                    target_file,
                    decision.target_dir,
                    decision.target_dir,
                    "write skill package",
                )
                file_plan = self._plan_compiled_file(
                    package_file,
                    source_file,
                    target_file,
                    effective_mode,
                    existing,
                    force,
                    runtime=decision.runtime,
                )
                file_plans.append(file_plan)
                plan.files.append(file_plan)
                if file_plan.action == "conflict":
                    plan.has_conflicts = True
                    plan.conflicts.append(f"File: {file_plan.target_path} - {file_plan.reason}")

            actions = {file_plan.action for file_plan in file_plans}
            if "conflict" in actions:
                package_action = "conflict"
            elif "update" in actions:
                package_action = "update"
            elif "install" in actions:
                package_action = "install"
            else:
                package_action = "skip"
            package_plan = SkillPackagePlan(
                runtime=decision.runtime,
                skill=decision.skill,
                action=package_action,
                target_dir=str(decision.target_dir),
                cache_dir=str(cache_dir),
                file_paths=sorted(file_plan.target_path for file_plan in file_plans),
                reason=("files unchanged" if package_action == "skip" else decision.reason.value),
            )
            plan.skill_packages.append(package_plan)
            self._compiled_skill_packages[(decision.runtime, decision.skill)] = compiled
            if decision.runtime == CLAUDE_CODE_RUNTIME and actions & {
                "install",
                "update",
            }:
                plan.requires_claude_version = True

        if existing is not None:
            existing_packages = {(package.runtime, package.skill): package for package in existing.skill_packages}
            for runtime, skill in sorted(managed_packages):
                if runtime not in selection.preserved_runtime_ids:
                    continue
                installed_package = existing_packages.get((runtime, skill))
                if installed_package is not None:
                    target_dir = installed_package.target_dir
                    file_paths = sorted(installed_package.file_paths)
                else:
                    target = get_runtime_skill_root(runtime, self._scope, self._project_root) / skill
                    target_dir = str(target)
                    file_paths = sorted(
                        tracked_file.target_path
                        for tracked_file in existing.files
                        if Path(tracked_file.target_path).is_relative_to(target)
                    )
                plan.skill_packages.append(
                    SkillPackagePlan(
                        runtime=runtime,
                        skill=skill,
                        action=SkillPlanAction.SKIP.value,
                        target_dir=target_dir,
                        file_paths=file_paths,
                        reason=SkillPlanReason.MANAGED_RUNTIME_PRESERVATION.value,
                    )
                )

        plan.skill_packages.sort(key=lambda package: (package.runtime, package.skill))

    def _plan_compiled_file(
        self,
        package_file: CompiledSkillFile,
        source: Path,
        target: Path,
        mode: InstallMode,
        existing: Installation | None,
        force: bool,
        *,
        runtime: str,
    ) -> FilePlan:
        """Plan compiled bytes against a future cache path without materializing it."""

        make_plan = partial(FilePlan, module=InstallModule.SKILLS.value, runtime=runtime)
        if not target.exists() and not target.is_symlink():
            return make_plan(
                action="install",
                target_path=str(target),
                effective_mode=mode,
                source_path=str(source),
            )

        target_location = target.parent.resolve() / target.name
        is_managed = existing is not None and any(
            Path(tracked.target_path).parent.resolve() / Path(tracked.target_path).name == target_location
            for tracked in existing.files
        )
        if is_managed:
            if mode == InstallMode.SYMLINK:
                if target.is_symlink() and target.resolve(strict=False) == source.resolve(strict=False):
                    if not source.is_file() or source.is_symlink():
                        return make_plan(
                            action="update",
                            target_path=str(target),
                            effective_mode=mode,
                            source_path=str(source),
                            reason="compiled cache missing or invalid",
                        )
                    return make_plan(
                        action="skip",
                        target_path=str(target),
                        effective_mode=mode,
                        source_path=str(source),
                        reason="symlink already correct",
                    )
            elif target.is_file() and not target.is_symlink():
                target_checksum = compute_checksum(target)
                source_checksum = hashlib.sha256(package_file.content).hexdigest()
                target_mode = stat.S_IMODE(target.stat().st_mode)
                if source_checksum == target_checksum and target_mode == package_file.mode:
                    return make_plan(
                        action="skip",
                        target_path=str(target),
                        effective_mode=mode,
                        source_path=str(source),
                        reason="file unchanged",
                    )
            return make_plan(
                action="update",
                target_path=str(target),
                effective_mode=mode,
                source_path=str(source),
            )

        if force:
            return make_plan(
                action="install",
                target_path=str(target),
                effective_mode=mode,
                source_path=str(source),
                reason="force overwrite",
            )
        return make_plan(
            action="conflict",
            target_path=str(target),
            effective_mode=mode,
            source_path=str(source),
            reason="file exists and is not Forge-managed",
        )

    def _plan_codex(
        self,
        modules: set[InstallModule],
        selection: RuntimeSelection,
    ) -> CodexPlan | None:
        """Plan the Codex hook registration for the scope-mapped config.toml."""
        if InstallModule.HOOKS not in modules or CODEX_RUNTIME not in selection.runtime_ids:
            return None
        entries = get_builtin_codex_entries()
        commands = [e.command for e in entries]
        if not _codex_available():
            # System-boundary degrade: codex is another tool; absence is a
            # visible skip, not an error.
            return CodexPlan(
                action="unavailable",
                reason="codex binary not found on PATH",
                commands=commands,
            )
        config_path = get_codex_config_path(self._scope, self._project_root)
        merge_plan = plan_codex_merge(config_path, entries)
        return CodexPlan(
            action=merge_plan.action,
            config_path=merge_plan.config_path,
            reason=merge_plan.reason,
            commands=commands,
        )

    def _execute_codex(
        self,
        codex_plan: CodexPlan | None,
    ) -> tuple[tuple[str | None, list[str]] | None, CodexConfigRollbackState | None]:
        """Execute the planned Codex merge; return tracking and rollback state.

        Returns ``(tracking_result, rollback_state)``. A resolved tracking
        result is ``(codex_config_path, codex_commands)`` read back from disk;
        ``(None, [])`` means a manual registration left nothing Forge-owned.
        A ``None`` tracking result means the module was omitted, Codex was
        unavailable, or a conflict prevented action. With no authoritative
        read, the caller keeps previous tracking because a prior managed block
        may still be on disk. Planned/apply-time conflicts remain best-effort;
        unexpected filesystem failures carry config state to roll back.
        """
        if codex_plan is None or codex_plan.action == "unavailable" or codex_plan.config_path is None:
            return None, None
        if codex_plan.action == "conflict":
            logger.warning("Codex hook registration skipped: %s", codex_plan.reason)
            return None, None

        entries = get_builtin_codex_entries()
        config_path = Path(codex_plan.config_path)
        rollback_state: CodexConfigRollbackState | None = None
        if codex_plan.action in ("install", "update"):
            try:
                merge_result = apply_codex_merge_transaction(config_path, entries)
            except CodexMergeMutationError as e:
                raise _CodexExecutionError(
                    "Failed to apply Codex hook registration",
                    e.cause,
                    e.rollback_state,
                ) from e
            except ForgeInstallError as e:
                # Race between plan and apply (config changed under us).
                logger.warning("Codex hook registration skipped: %s", e)
                codex_plan.action = "conflict"
                codex_plan.reason = str(e)
                return None, None
            except OSError as e:
                raise _CodexExecutionError("Failed to apply Codex hook registration", e, None) from e
            rollback_state = merge_result.rollback_state

        try:
            status = read_codex_registration(config_path, entries)
        except OSError as e:
            raise _CodexExecutionError("Failed to verify Codex hook registration", e, rollback_state) from e
        if status.block_present:
            return (str(config_path), list(status.commands_registered)), rollback_state
        # skip due to manual registration: user-owned, not tracked
        return (None, []), rollback_state

    def _plan_file(
        self,
        source: Path,
        target: Path,
        mode: InstallMode,
        existing: Installation | None,
        force: bool,
        *,
        module: InstallModule,
        runtime: str,
    ) -> FilePlan:
        """Plan a single file operation.

        Args:
            source: Source file path.
            target: Target file path.
            mode: Installation mode.
            existing: Existing installation (if any).
            force: If True, override conflicts.

        Returns:
            FilePlan for this file.
        """
        make_plan = partial(FilePlan, module=module.value, runtime=runtime)
        if not target.exists() and not target.is_symlink():
            return make_plan(
                action="install",
                target_path=str(target),
                effective_mode=mode,
                source_path=str(source),
            )

        is_managed = existing is not None and any(
            Path(f.target_path).resolve() == target.resolve() for f in existing.files
        )

        if is_managed:
            if mode == InstallMode.SYMLINK:
                if target.is_symlink() and target.resolve() == source.resolve():
                    return make_plan(
                        action="skip",
                        target_path=str(target),
                        effective_mode=mode,
                        source_path=str(source),
                        reason="symlink already correct",
                    )
            else:
                if target.is_file():
                    source_checksum = compute_checksum(source)
                    target_checksum = compute_checksum(target)
                    if source_checksum == target_checksum:
                        return make_plan(
                            action="skip",
                            target_path=str(target),
                            effective_mode=mode,
                            source_path=str(source),
                            reason="file unchanged",
                        )

            return make_plan(
                action="update",
                target_path=str(target),
                effective_mode=mode,
                source_path=str(source),
            )

        if force:
            return make_plan(
                action="install",
                target_path=str(target),
                effective_mode=mode,
                source_path=str(source),
                reason="force overwrite",
            )

        return make_plan(
            action="conflict",
            target_path=str(target),
            effective_mode=mode,
            source_path=str(source),
            reason="file exists and is not Forge-managed",
        )

    def _plan_settings(
        self,
        modules: set[InstallModule],
        force: bool,
    ) -> list[SettingsPlan]:
        """Plan settings merge operations.

        Args:
            modules: Modules being installed.
            force: If True, override scalar conflicts.

        Returns:
            List of SettingsPlan.
        """
        plans: list[SettingsPlan] = []

        settings_path = get_settings_path(self._scope, self._project_root)
        current_settings = read_settings(settings_path)

        forge_settings = self._load_forge_settings()

        include_statusline = InstallModule.STATUSLINE in modules
        if include_statusline and "statusLine" in forge_settings:
            current = current_settings.get("statusLine")
            forge_value = forge_settings["statusLine"]
            if scalar_already_set(current_settings, "statusLine", forge_value):
                plans.append(
                    SettingsPlan(
                        action="skip",
                        key_path="statusLine",
                        value=forge_value,
                        reason="already set",
                    )
                )
            elif current is not None and current != forge_value and not force:
                plans.append(
                    SettingsPlan(
                        action="conflict",
                        key_path="statusLine",
                        value=forge_value,
                        current_value=current,
                        reason="statusLine already set to different value",
                    )
                )
            else:
                plans.append(
                    SettingsPlan(
                        action="merge",
                        key_path="statusLine",
                        value=forge_value,
                    )
                )

        # Hooks and permissions don't conflict (append/union)
        if InstallModule.HOOKS in modules:
            forge_hooks = forge_settings.get("hooks", {})
            for hook_type in sorted(forge_hooks):
                # Skip empty arrays (no entries to add)
                if not forge_hooks[hook_type]:
                    continue
                if hooks_already_present(current_settings, hook_type, forge_hooks[hook_type]):
                    plans.append(
                        SettingsPlan(
                            action="skip",
                            key_path=f"hooks.{hook_type}",
                            value="(already present)",
                            reason="hooks already installed",
                        )
                    )
                else:
                    plans.append(
                        SettingsPlan(
                            action="merge",
                            key_path=f"hooks.{hook_type}",
                            value="(append + dedupe)",
                        )
                    )

        if InstallModule.PERMISSIONS in modules:
            for perm_type in ["allow", "deny"]:
                forge_perms = forge_settings.get("permissions", {}).get(perm_type)
                if forge_perms:
                    if permissions_already_present(current_settings, perm_type, forge_perms):
                        plans.append(
                            SettingsPlan(
                                action="skip",
                                key_path=f"permissions.{perm_type}",
                                value="(already present)",
                                reason="permissions already installed",
                            )
                        )
                    else:
                        plans.append(
                            SettingsPlan(
                                action="merge",
                                key_path=f"permissions.{perm_type}",
                                value="(union unique)",
                            )
                        )

        # Env vars currently ride with permissions until they have a first-class module.
        if InstallModule.PERMISSIONS in modules:
            if forge_env := forge_settings.get("env"):
                for key in sorted(forge_env):
                    if scalar_already_set(current_settings.get("env", {}), key, forge_env[key]):
                        plans.append(
                            SettingsPlan(
                                action="skip",
                                key_path=f"env.{key}",
                                value=forge_env[key],
                                reason="already set",
                            )
                        )
                    else:
                        plans.append(
                            SettingsPlan(
                                action="merge",
                                key_path=f"env.{key}",
                                value=forge_env[key],
                            )
                        )

        return plans

    def _load_forge_settings(self) -> dict[str, Any]:
        """Load settings from the user-editable preset.

        Reads ~/.forge/claude.preset.json (auto-created from built-in defaults
        on first access). Users customize via ``forge claude preset edit``.

        Hooks are Forge-managed infrastructure, so they always come from the
        built-in preset regardless of preset file content. This ensures
        upgraded installs pick up new hooks even when the user's preset file
        predates them. Infrastructure permissions (Write/Edit) are also
        backfilled from the built-in preset. User-added permissions and env
        vars are preserved.
        """
        from forge.install.preset import get_builtin_preset, load_preset

        settings = load_preset()
        builtin = get_builtin_preset()

        # Hooks are Forge-managed infrastructure, not user-customizable preset state.
        settings["hooks"] = deepcopy(builtin.get("hooks", {}))

        # Backfill infrastructure permissions from builtin (upgrade path)
        builtin_allow = builtin.get("permissions", {}).get("allow", [])
        if builtin_allow:
            current_allow = settings.setdefault("permissions", {}).setdefault("allow", [])
            for perm in builtin_allow:
                if perm not in current_allow:
                    current_allow.append(perm)
        return settings

    def init(
        self,
        profile: InstallProfile = InstallProfile.STANDARD,
        mode: InstallMode = InstallMode.COPY,
        with_modules: set[InstallModule] | None = None,
        without_modules: set[InstallModule] | None = None,
        force: bool = False,
        skill_runtimes: tuple[str, ...] | None = None,
        *,
        _modules_override: set[InstallModule] | None = None,
        _managed_runtime_ids: tuple[str, ...] | None = None,
    ) -> InstallPlan:
        """Install extensions.

        Args:
            profile: Installation profile.
            mode: Installation mode.
            with_modules: Modules to add.
            without_modules: Modules to remove.
            force: If True, override conflicts.
            skill_runtimes: Explicit runtime ids for skill packages; None selects automatically.
            _modules_override: Internal. If provided, use exactly these modules.
            _managed_runtime_ids: Internal persisted runtime set used by update/sync.

        Returns:
            The executed plan.
        """
        plan = self.plan(
            profile,
            mode,
            with_modules,
            without_modules,
            force,
            skill_runtimes,
            _modules_override=_modules_override,
            _managed_runtime_ids=_managed_runtime_ids,
        )

        validate_file_plan_ownership(plan)
        if plan.has_conflicts:
            return plan  # Planning conflicts are a hard preflight boundary.

        # plan.modules is process-generated from the live enum after all
        # profile, scope, and runtime filters have run.
        modules = {InstallModule(module) for module in plan.modules}
        selected_runtimes = set(plan.selected_runtimes)
        claude_modules = (
            {module for module in modules if CLAUDE_CODE_RUNTIME in MODULE_RUNTIME_OWNERS[module]}
            if CLAUDE_CODE_RUNTIME in selected_runtimes
            else set()
        )
        inputs = _InstallApplyInputs(
            plan=plan,
            profile=profile,
            mode=mode,
            force=force,
            skill_runtimes=skill_runtimes,
            modules=modules,
            selected_runtimes=selected_runtimes,
            claude_modules=claude_modules,
        )
        existing = self._prepare_install_apply(inputs)
        self._materialize_install_skill_cache()
        self._apply_install_dispatcher(inputs)
        file_result = self._apply_install_files(inputs, existing)
        settings_result = self._apply_install_settings(inputs, existing, file_result)
        stale_result = self._reconcile_install_stale_files(inputs, existing, file_result, settings_result)
        codex_result = self._apply_install_codex(inputs, existing, file_result, settings_result)
        installation = self._assemble_installation(
            inputs,
            existing,
            settings_result,
            stale_result,
            codex_result,
        )
        try:
            self._tracking.set_installation(self._scope.value, installation, self._project_path_str)
        except (OSError, StateError) as e:
            self._raise_post_file_failure(
                "Failed to commit extension tracking",
                e,
                file_result.newly_created_files,
                plan,
                settings_rollback_state=settings_result.rollback_state,
                codex_rollback_state=codex_result.rollback_state,
            )

        return plan

    def _prepare_install_apply(self, inputs: _InstallApplyInputs) -> Installation | None:
        """Materialize the scope anchor and run read-only apply preflights."""

        # Planning treats creation of a missing Claude anchor as a Claude
        # surface mutation. Materialize it only after the conflict preflight;
        # project CLI flows may already have created it after the version gate.
        if inputs.plan.requires_claude_version:
            get_target_root(self._scope, self._project_root).mkdir(parents=True, exist_ok=True)

        existing = self._tracking.get_installation(self._scope.value, self._project_path_str)
        if self._scope == InstallScope.USER and InstallModule.HOOKS in inputs.claude_modules:
            # Read both user settings targets before rendering the dispatcher or
            # changing tracking. The later cleanup can then fail only on a new
            # race or an environmental write error, not known malformed input.
            from .hook_migration import plan_user_legacy_hook_files

            plan_user_legacy_hook_files(tuple(existing.settings_entries) if existing is not None else ())
        return existing

    def _materialize_install_skill_cache(self) -> None:
        """Materialize compiled skills after every planning conflict has cleared."""

        # Dry-run calls plan() directly and therefore cannot create or repair
        # cache entries.
        for compiled in self._compiled_skill_packages.values():
            try:
                materialize_compiled_skill(compiled)
            except (OSError, StateError) as e:
                raise ForgeInstallError(
                    f"Failed to materialize compiled skill cache for "
                    f"'{compiled.runtime.value}/{compiled.name}'; extension targets were not changed "
                    f"and tracking was not updated: {e}"
                ) from e

    @staticmethod
    def _apply_install_dispatcher(inputs: _InstallApplyInputs) -> None:
        """Preserve the historical dispatcher lifecycle before file writes."""

        # Historical extension installs rendered the dispatcher even when
        # scope policy filtered hook modules. Preserve that lifecycle contract,
        # while a skills-only Codex install stays free of unrelated writes.
        if inputs.modules - {InstallModule.SKILLS}:
            _ensure_hook_dispatcher()

    def _apply_install_files(
        self,
        inputs: _InstallApplyInputs,
        existing: Installation | None,
    ) -> _InstallFileApplyResult:
        """Apply planned extension files and retain the rollback-owned subset."""

        installed_files: list[InstalledFile] = []
        newly_created_files: list[InstalledFile] = []
        existing_files_by_target = {record.target_path: record for record in existing.files} if existing else {}
        skill_package_dirs_by_file = {
            file_path: Path(package.target_dir)
            for package in inputs.plan.skill_packages
            if package.target_dir is not None
            for file_path in package.file_paths
        }
        for file_plan in inputs.plan.files:
            target = Path(file_plan.target_path)
            package_dir = skill_package_dirs_by_file.get(file_plan.target_path)
            if package_dir is not None:
                try:
                    validate_real_skill_package_directory(package_dir, package_dir, "write skill package")
                    validate_skill_package_file_path(target, package_dir, package_dir, "write skill package")
                except PathBoundaryViolationError as e:
                    self._raise_post_file_failure(
                        f"Refusing unsafe skill package write '{file_plan.target_path}'; tracking was not updated",
                        e,
                        newly_created_files,
                        inputs.plan,
                    )
            if file_plan.action in ("install", "update"):
                target_existed = target.exists() or target.is_symlink()
                try:
                    installed_file = self._execute_file(file_plan)
                except OSError as e:
                    self._raise_post_file_failure(
                        f"Failed to write extension file '{file_plan.target_path}'; tracking was not updated",
                        e,
                        newly_created_files,
                        inputs.plan,
                        unrecorded_targets=() if target_existed else (target,),
                    )
                installed_files.append(installed_file)
                if not target_existed:
                    newly_created_files.append(installed_file)
            elif file_plan.action == "skip" and file_plan.source_path is not None:
                try:
                    installed_file = self._installed_file_record(file_plan)
                except OSError as e:
                    self._raise_post_file_failure(
                        f"Failed to refresh extension file ownership '{file_plan.target_path}'",
                        e,
                        newly_created_files,
                        inputs.plan,
                    )
                previous = existing_files_by_target.get(installed_file.target_path)
                if previous is not None:
                    installed_file.installed_at = previous.installed_at
                installed_files.append(installed_file)
        return _InstallFileApplyResult(
            installed_files=installed_files,
            newly_created_files=newly_created_files,
        )

    def _apply_install_settings(
        self,
        inputs: _InstallApplyInputs,
        existing: Installation | None,
        file_result: _InstallFileApplyResult,
    ) -> _InstallSettingsApplyResult:
        """Apply Claude settings and persist the matching ownership sidecar."""

        backup_path: Path | None = None
        rollback_state: _SettingsRollbackState | None = None
        if inputs.claude_modules & _CLAUDE_SETTINGS_MODULES:
            settings_path = get_settings_path(self._scope, self._project_root)
            try:
                rollback_state = capture_settings_rollback_state(settings_path)
                backup_path = backup_settings(settings_path)
                settings = read_settings(settings_path)
            except OSError as e:
                self._raise_post_file_failure(
                    "Failed to prepare Claude settings",
                    e,
                    file_result.newly_created_files,
                    inputs.plan,
                    settings_rollback_state=rollback_state,
                )
            removed_entry_ids: set[tuple[str, str]] = set()
            if (
                existing is not None
                and self._scope == InstallScope.USER
                and InstallModule.HOOKS in inputs.claude_modules
            ):
                old_hook_entries = [entry for entry in existing.settings_entries if entry.key_path.startswith("hooks.")]
                if old_hook_entries:
                    unmerge(settings, old_hook_entries)
                    removed_entry_ids = {(entry.key_path, entry.stable_id) for entry in old_hook_entries}
            if self._scope == InstallScope.USER and InstallModule.HOOKS in inputs.claude_modules:
                # T6 migration: stage safe same-file legacy cleanup with the
                # dispatcher merge so settings.json changes in one atomic write.
                from .hook_migration import remove_known_legacy_hook_entries

                settings, removed_legacy_count = remove_known_legacy_hook_entries(settings)
                if removed_legacy_count:
                    inputs.plan.legacy_hook_cleanup_paths.append(str(settings_path))
            forge_settings = self._load_forge_settings()
            include_permissions = InstallModule.PERMISSIONS in inputs.claude_modules
            entries = merge(
                settings,
                forge_settings,
                attributions={
                    InstallModule.HOOKS.value: attributed(InstallModule.HOOKS, CLAUDE_CODE_RUNTIME),
                    InstallModule.STATUSLINE.value: attributed(InstallModule.STATUSLINE, CLAUDE_CODE_RUNTIME),
                    InstallModule.PERMISSIONS.value: attributed(InstallModule.PERMISSIONS, CLAUDE_CODE_RUNTIME),
                },
                force=inputs.force,
                include_statusline=InstallModule.STATUSLINE in inputs.claude_modules,
                include_hooks=InstallModule.HOOKS in inputs.claude_modules,
                include_permissions=include_permissions,
                include_env=include_permissions,
            )
            try:
                write_settings(settings_path, settings)
            except OSError as e:
                self._raise_post_file_failure(
                    f"Failed to write Claude settings '{settings_path}'",
                    e,
                    file_result.newly_created_files,
                    inputs.plan,
                    settings_rollback_state=rollback_state,
                )

            entry_ids = {(entry.key_path, entry.stable_id) for entry in entries}
            final_entries = list(entries)
            if existing:
                for existing_entry in existing.settings_entries:
                    existing_entry_id = (
                        existing_entry.key_path,
                        existing_entry.stable_id,
                    )
                    if existing_entry_id not in entry_ids and existing_entry_id not in removed_entry_ids:
                        final_entries.append(existing_entry)

            # Save everything Forge still needs to remove on disable before the
            # potentially long stale-file cleanup walk. This includes legacy entries
            # preserved for cleanup after scope filtering.
            added_structure = entries_to_added_structure(final_entries)
            try:
                save_added_settings(settings_path, added_structure)
            except OSError as e:
                self._raise_post_file_failure(
                    f"Failed to save Claude settings ownership '{settings_path}'",
                    e,
                    file_result.newly_created_files,
                    inputs.plan,
                    settings_rollback_state=rollback_state,
                )
        else:
            final_entries = list(existing.settings_entries) if existing else []
            if final_entries:
                settings_path = get_settings_path(self._scope, self._project_root)
                try:
                    rollback_state = capture_settings_rollback_state(settings_path)
                    save_added_settings(settings_path, entries_to_added_structure(final_entries))
                except OSError as e:
                    self._raise_post_file_failure(
                        f"Failed to preserve Claude settings ownership '{settings_path}'",
                        e,
                        file_result.newly_created_files,
                        inputs.plan,
                        settings_rollback_state=rollback_state,
                    )
        return _InstallSettingsApplyResult(
            entries=final_entries,
            backup_path=backup_path,
            rollback_state=rollback_state,
        )

    def _reconcile_install_stale_files(
        self,
        inputs: _InstallApplyInputs,
        existing: Installation | None,
        file_result: _InstallFileApplyResult,
        settings_result: _InstallSettingsApplyResult,
    ) -> _InstallStaleReconciliationResult:
        """Remove verified stale targets and assemble the final file ownership."""

        # Preserve the historical timestamp boundary before stale cleanup and
        # Codex mutation.
        updated_at = now_iso()

        # All targets the current source scan knows about, plus packages intentionally
        # preserved when an explicit runtime filter narrows an existing installation.
        planned_targets = {file_plan.target_path for file_plan in inputs.plan.files}
        planned_targets.update(
            target
            for package in inputs.plan.skill_packages
            if package.reason == SkillPlanReason.MANAGED_RUNTIME_PRESERVATION.value
            for target in package.file_paths
        )
        if existing is not None and inputs.skill_runtimes is not None:
            preserved_runtimes = set(inputs.plan.preserved_runtime_ids)
            planned_targets.update(
                record.target_path
                for record in existing.files
                if not isinstance(record.attribution, ModuleOwner) or record.attribution.runtime in preserved_runtimes
            )

        # Remove stale tracked files whose source no longer exists (e.g., after renames).
        # A file is stale if it was tracked in the previous installation but isn't in the
        # current plan's target set — meaning no source file maps to that target anymore.
        # Only auto-delete if ownership is verified (symlink target or checksum matches);
        # otherwise drop from manifest silently — the user may have repurposed the path.
        dirs_to_clean: set[tuple[Path, Path]] = set()
        if existing:
            for existing_file in existing.files:
                if existing_file.target_path not in planned_targets:
                    target = Path(existing_file.target_path)
                    try:
                        boundary = tracked_file_boundary(
                            existing,
                            target,
                            "remove stale file",
                            scope=self._scope,
                            project_root=self._project_root,
                        )
                        validate_path_within_boundary(target, boundary, "remove stale file")
                    except PathBoundaryViolationError:
                        continue
                    if not self._is_forge_owned(target, existing_file):
                        logger.debug(
                            "Stale target not Forge-owned, dropping from manifest: %s",
                            target,
                        )
                        continue
                    try:
                        target.unlink(missing_ok=True)
                        logger.debug("Removed stale tracked file: %s", target)
                    except OSError as e:
                        self._raise_post_file_failure(
                            f"Failed to remove stale tracked extension file '{target}'",
                            e,
                            file_result.newly_created_files,
                            inputs.plan,
                            settings_rollback_state=settings_result.rollback_state,
                        )
                    # Collect parent dirs for empty-directory cleanup
                    parent = target.parent
                    while parent != boundary and parent.is_relative_to(boundary):
                        dirs_to_clean.add((parent, boundary))
                        parent = parent.parent

        # Clean up empty directories left by stale file removal (deepest first)
        for dir_path, _boundary in sorted(dirs_to_clean, key=lambda item: len(item[0].parts), reverse=True):
            try:
                dir_path.rmdir()
            except OSError:
                pass  # Not empty or doesn't exist

        # Build final files list: start with newly installed, add existing tracked files
        # that were skipped (not re-installed this run) AND still in the plan
        installed_paths = {file_record.target_path for file_record in file_result.installed_files}
        final_files = list(file_result.installed_files)
        if existing:
            for existing_file in existing.files:
                if existing_file.target_path not in installed_paths:
                    if existing_file.target_path in planned_targets:
                        # Keep existing tracked file that was skipped (source still exists)
                        final_files.append(existing_file)
        return _InstallStaleReconciliationResult(files=final_files, updated_at=updated_at)

    def _apply_install_codex(
        self,
        inputs: _InstallApplyInputs,
        existing: Installation | None,
        file_result: _InstallFileApplyResult,
        settings_result: _InstallSettingsApplyResult,
    ) -> _InstallCodexApplyResult:
        """Apply Codex registration and resolve authoritative tracking state."""

        try:
            tracking_result, rollback_state = self._execute_codex(inputs.plan.codex)
        except _CodexExecutionError as e:
            self._raise_post_file_failure(
                e.message,
                e.cause,
                file_result.newly_created_files,
                inputs.plan,
                settings_rollback_state=settings_result.rollback_state,
                codex_rollback_state=e.rollback_state,
            )
        if tracking_result is not None:
            config_path, commands = tracking_result
        elif existing is not None:
            # No authoritative outcome (module not selected, codex binary
            # unavailable, or planned/apply-time conflict): preserve prior
            # tracking -- the previously written managed block may still be
            # on disk and disable must keep knowing to remove it.
            config_path = existing.codex_config_path
            commands = list(existing.codex_commands)
        else:
            config_path, commands = None, []
        return _InstallCodexApplyResult(
            config_path=config_path,
            commands=commands,
            rollback_state=rollback_state,
        )

    def _assemble_installation(
        self,
        inputs: _InstallApplyInputs,
        existing: Installation | None,
        settings_result: _InstallSettingsApplyResult,
        stale_result: _InstallStaleReconciliationResult,
        codex_result: _InstallCodexApplyResult,
    ) -> Installation:
        """Assemble the final tracking row without changing external state."""

        final_skill_packages = [
            InstalledSkillPackage(
                runtime=package.runtime,
                skill=package.skill,
                target_dir=package.target_dir,
                file_paths=list(package.file_paths),
            )
            for package in inputs.plan.skill_packages
            if package.target_dir is not None
            and (package.cache_dir is not None or package.reason == SkillPlanReason.MANAGED_RUNTIME_PRESERVATION.value)
            and package.action in {"install", "update", "skip"}
        ]
        if existing is not None and inputs.plan.preserved_runtime_ids:
            final_package_keys = {(package.runtime, package.skill) for package in final_skill_packages}
            final_skill_packages.extend(
                package
                for package in existing.skill_packages
                if package.runtime in inputs.plan.preserved_runtime_ids
                and (package.runtime, package.skill) not in final_package_keys
            )

        module_owners: set[ModuleOwner] = {
            attributed(module, runtime)
            for module in inputs.modules
            for runtime in MODULE_RUNTIME_OWNERS[module]
            if runtime in inputs.selected_runtimes and not (module == InstallModule.HOOKS and runtime == CODEX_RUNTIME)
        }
        if existing is not None and inputs.plan.preserved_runtime_ids:
            module_owners.update(
                owner for owner in existing.module_owners if owner.runtime in inputs.plan.preserved_runtime_ids
            )
        module_owners.update(
            file_record.attribution
            for file_record in stale_result.files
            if isinstance(file_record.attribution, ModuleOwner)
        )
        module_owners.update(
            settings_record.attribution
            for settings_record in settings_result.entries
            if isinstance(settings_record.attribution, ModuleOwner)
        )
        module_owners.update(attributed(InstallModule.SKILLS, package.runtime) for package in final_skill_packages)
        codex_owner = attributed(InstallModule.HOOKS, CODEX_RUNTIME)
        if codex_result.config_path is not None:
            module_owners.add(codex_owner)
        else:
            module_owners.discard(codex_owner)

        # An earlier no-file enable establishes authoritative null; later Forge-bearing snapshots stay history.
        settings_baseline_established = existing is not None and (
            existing.settings_backup_path is not None
            or bool(existing.settings_entries)
            or any(has_module_owner(existing, module, CLAUDE_CODE_RUNTIME) for module in _CLAUDE_SETTINGS_MODULES)
        )
        return Installation(
            scope=self._scope.value,
            mode=inputs.mode.value,
            profile=inputs.profile.value,
            module_owners=sorted(module_owners),
            files=stale_result.files,
            skill_packages=final_skill_packages,
            settings_entries=settings_result.entries,
            settings_backup_path=(
                existing.settings_backup_path
                if settings_baseline_established and existing is not None
                else str(settings_result.backup_path) if settings_result.backup_path else None
            ),
            codex_config_path=codex_result.config_path,
            codex_commands=codex_result.commands,
            installed_at=existing.installed_at if existing else stale_result.updated_at,
            updated_at=stale_result.updated_at,
        )

    def _raise_post_file_failure(
        self,
        message: str,
        cause: Exception,
        newly_created_files: list[InstalledFile],
        plan: InstallPlan,
        *,
        unrecorded_targets: tuple[Path, ...] = (),
        settings_rollback_state: _SettingsRollbackState | None = None,
        codex_rollback_state: CodexConfigRollbackState | None = None,
    ) -> NoReturn:
        rollback_failures = self._rollback_newly_created_files(
            newly_created_files,
            plan,
            unrecorded_targets=unrecorded_targets,
        )
        if settings_rollback_state is not None:
            rollback_failures.extend(restore_settings_rollback_state(settings_rollback_state))
        if codex_rollback_state is not None:
            rollback_failures.extend(restore_codex_config_rollback_state(codex_rollback_state))
        rolled_back = ["Newly created extension files"]
        if settings_rollback_state is not None:
            rolled_back.append("settings ownership state")
        if codex_rollback_state is not None:
            rolled_back.append("Codex config")
        rollback_note = (
            f" Could not roll back: {', '.join(rollback_failures)}; inspect and restore those paths before retrying."
            if rollback_failures
            else f" {' and '.join(rolled_back)} were rolled back; "
            "rerun the same command after repairing the failure."
        )
        raise ForgeInstallError(f"{message}: {cause}.{rollback_note}") from cause

    def _rollback_newly_created_files(
        self,
        installed_files: list[InstalledFile],
        plan: InstallPlan,
        *,
        unrecorded_targets: tuple[Path, ...] = (),
    ) -> list[str]:
        """Best-effort rollback for files created before tracking commits.

        Unrecorded targets are paths that were absent immediately before an
        attempted write but whose ownership record could not be built because
        that write failed. Existing targets are never passed through this path.
        """

        package_directories = {
            file_path: Path(package.target_dir)
            for package in plan.skill_packages
            if package.target_dir is not None
            for file_path in package.file_paths
        }
        package_boundaries = {file_path: package_dir.parent for file_path, package_dir in package_directories.items()}
        failures: list[str] = []
        dirs_to_clean: set[tuple[Path, Path]] = set()
        for target in reversed(unrecorded_targets):
            boundary = package_boundaries.get(str(target), get_target_root(self._scope, self._project_root))
            try:
                package_dir = package_directories.get(str(target))
                if package_dir is not None:
                    validate_real_skill_package_directory(
                        package_dir,
                        package_dir,
                        "roll back partial extension file",
                    )
                    validate_skill_package_file_path(
                        target,
                        package_dir,
                        package_dir,
                        "roll back partial extension file",
                    )
                else:
                    validate_path_within_boundary(target, boundary, "roll back partial extension file")
                target.unlink(missing_ok=True)
            except (OSError, PathBoundaryViolationError):
                if target.exists() or target.is_symlink():
                    failures.append(str(target))
                continue
            parent = target.parent
            while parent != boundary and parent.is_relative_to(boundary):
                dirs_to_clean.add((parent, boundary))
                parent = parent.parent

        for record in reversed(installed_files):
            target = Path(record.target_path)
            boundary = package_boundaries.get(record.target_path, get_target_root(self._scope, self._project_root))
            try:
                package_dir = package_directories.get(record.target_path)
                if package_dir is not None:
                    validate_real_skill_package_directory(package_dir, package_dir, "roll back extension file")
                    validate_skill_package_file_path(
                        target,
                        package_dir,
                        package_dir,
                        "roll back extension file",
                    )
                else:
                    validate_path_within_boundary(target, boundary, "roll back extension file")
                if self._is_forge_owned(target, record):
                    target.unlink(missing_ok=True)
                elif target.exists() or target.is_symlink():
                    failures.append(str(target))
                    continue
            except (OSError, PathBoundaryViolationError):
                failures.append(str(target))
                continue
            parent = target.parent
            while parent != boundary and parent.is_relative_to(boundary):
                dirs_to_clean.add((parent, boundary))
                parent = parent.parent

        for directory, _boundary in sorted(dirs_to_clean, key=lambda item: len(item[0].parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        return failures

    def _execute_file(self, file_plan: FilePlan) -> InstalledFile:
        """Execute a file operation.

        Args:
            file_plan: Plan for the file to execute.

        Returns:
            The resulting installed-file ledger record.
        """
        source = Path(file_plan.source_path)  # type: ignore[arg-type]  # source_path is always non-None in execute context
        target = Path(file_plan.target_path)

        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists() or target.is_symlink():
            target.unlink()

        if file_plan.effective_mode == InstallMode.SYMLINK:
            target.symlink_to(source)
        else:
            shutil.copy2(source, target)

        return self._installed_file_record(file_plan)

    @staticmethod
    def _installed_file_record(file_plan: FilePlan) -> InstalledFile:
        """Build current ownership metadata for an installed or unchanged file."""

        source = Path(file_plan.source_path)  # type: ignore[arg-type]
        target = Path(file_plan.target_path)
        return InstalledFile(
            target_path=str(target),
            source_path=str(source),
            checksum=compute_checksum(source),
            mode=file_plan.effective_mode.value,
            installed_at=now_iso(),
            attribution=attributed(file_plan.module, file_plan.runtime),
        )

    @staticmethod
    def _is_forge_owned(target: Path, record: InstalledFile) -> bool:
        """Check if a stale target still matches Forge ownership expectations.

        Returns True only if the on-disk object was clearly installed by Forge
        (symlink pointing to the recorded source, or copy with matching checksum).
        Returns False if the target was replaced by the user or doesn't exist.
        """
        if not target.exists() and not target.is_symlink():
            return False
        if record.mode == "symlink":
            if not target.is_symlink():
                return False
            try:
                return target.resolve() == Path(record.source_path).resolve()
            except OSError:
                return False
        else:
            # Copy mode: checksum must match what Forge installed
            if not target.is_file() or target.is_symlink():
                return False
            try:
                return compute_checksum(target) == record.checksum
            except OSError:
                return False

    def update(self, force: bool = False) -> InstallPlan:
        """Update existing installation.

        Uses the exact modules from the existing installation (not re-resolved
        from profile) to ensure only tracked items are touched.

        Args:
            force: If True, override conflicts.

        Returns:
            The executed plan.

        Raises:
            NotInstalledError: If no existing installation.
        """
        existing = self._tracking.get_installation(self._scope.value, self._project_path_str)
        if existing is None:
            raise NotInstalledError(self._scope.value)

        # Persisted values have already passed TrackingStore's strict ownership
        # validation; this conversion is not a compatibility/ignore boundary.
        existing_modules = {InstallModule(module) for module in module_values(existing)}
        managed_runtime_ids = owned_runtime_ids(existing)

        return self.init(
            profile=InstallProfile(existing.profile),
            mode=InstallMode(existing.mode),
            force=force,
            _modules_override=existing_modules,
            _managed_runtime_ids=managed_runtime_ids,
        )

    def plan_update(self, force: bool = False) -> InstallPlan:
        """Plan sync using the persisted runtime set without applying changes."""

        existing = self._tracking.get_installation(self._scope.value, self._project_path_str)
        if existing is None:
            raise NotInstalledError(self._scope.value)
        # Persisted values have already passed TrackingStore's strict ownership
        # validation; this conversion is not a compatibility/ignore boundary.
        existing_modules = {InstallModule(module) for module in module_values(existing)}
        managed_runtime_ids = owned_runtime_ids(existing)
        return self.plan(
            profile=InstallProfile(existing.profile),
            mode=InstallMode(existing.mode),
            force=force,
            _modules_override=existing_modules,
            _managed_runtime_ids=managed_runtime_ids,
        )

    def plan_runtime_removal(self, runtime_ids: tuple[str, ...]) -> RuntimeRemovalPlan:
        """Plan removal of the tracked surfaces owned by ``runtime_ids``."""

        return self._runtime_removal_executor().plan(runtime_ids)

    def validate_runtime_removal(self, plan: RuntimeRemovalPlan) -> None:
        """Run every knowable runtime-removal safety check without mutation."""

        self._runtime_removal_executor().validate(plan)

    def uninstall_runtimes(
        self,
        runtime_ids: tuple[str, ...],
        *,
        expected_plan: RuntimeRemovalPlan | None = None,
    ) -> RuntimeRemovalPlan:
        """Remove selected runtime surfaces and reconcile tracking after faults."""

        return self._runtime_removal_executor().uninstall(runtime_ids, expected_plan=expected_plan)

    def _runtime_removal_executor(self) -> RuntimeRemovalExecutor:
        return RuntimeRemovalExecutor(
            scope=self._scope,
            project_root=self._project_root,
            project_path=self._project_path_str,
            tracking=self._tracking,
        )

    def uninstall(self) -> None:
        """Remove the tracked Forge installation."""
        existing = self._tracking.get_installation(self._scope.value, self._project_path_str)
        if existing is None:
            raise NotInstalledError(self._scope.value)

        validate_codex_config_scope(existing, scope=self._scope, project_root=self._project_root)

        base_dir = get_target_root(self._scope, self._project_root)
        removals: list[tuple[InstalledFile, Path, Path]] = []
        for file_record in existing.files:
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

        settings_path = get_settings_path(self._scope, self._project_root)
        added_files = find_added_files(settings_path)
        has_settings_state = bool(existing.settings_entries or added_files) or existing.settings_backup_path is not None
        current: dict[str, Any] = {}
        backup: dict[str, Any] = {}
        added: dict[str, Any] = {}
        baseline_path = Path(existing.settings_backup_path) if existing.settings_backup_path is not None else None
        if has_settings_state:
            try:
                validate_path_within_boundary(settings_path, base_dir, "delete settings")
                for added_file in added_files:
                    validate_path_within_boundary(added_file, base_dir, "delete added file")
                if baseline_path is not None:
                    validate_path_within_boundary(baseline_path, base_dir, "read settings baseline")
                current = read_settings(settings_path)
                backup = read_tracked_settings_baseline(baseline_path)
                added = read_settings(added_files[0]) if added_files else {}
            except PathBoundaryViolationError:
                raise
            except (OSError, ValueError) as e:
                raise ForgeInstallError(f"Cannot safely prepare Claude settings at '{settings_path}': {e}") from e

        dirs_to_clean: set[tuple[Path, Path]] = set()
        for _file_record, target, boundary in removals:
            tracked_file_boundary(
                existing,
                target,
                "delete file",
                scope=self._scope,
                project_root=self._project_root,
            )
            if target.exists() or target.is_symlink():
                target.unlink()
            parent = target.parent
            while parent != boundary and parent.is_relative_to(boundary):
                dirs_to_clean.add((parent, boundary))
                parent = parent.parent

        for dir_path, _boundary in sorted(dirs_to_clean, key=lambda item: len(item[0].parts), reverse=True):
            try:
                dir_path.rmdir()
            except OSError:
                pass  # Directory not empty or doesn't exist

        if has_settings_state:
            if added:
                result = smart_unmerge(current, backup, added)
                result = cleanup_empty_settings(result)

                backup_cleaned = cleanup_empty_settings(backup)
                if settings_equal(result, backup_cleaned):
                    if baseline_path is not None and backup_cleaned:
                        write_settings(settings_path, backup_cleaned)
                    elif settings_path.is_file():
                        settings_path.unlink()
                else:
                    write_settings(settings_path, result)
            else:
                # Fallback to old unmerge if no .forge-added file
                unmerge(current, existing.settings_entries)
                write_settings(settings_path, current)

            # Clean up .forge.added files only (keep .forge.backup files for history)
            for added_file in added_files:
                added_file.unlink()

        self._remove_codex_registration(existing)

        self._tracking.remove_installation(self._scope.value, self._project_path_str)

    def _remove_codex_registration(self, existing: Installation) -> None:
        """Remove tracked Forge-managed Codex hooks after scope validation."""
        if not existing.codex_config_path:
            return
        tracked = Path(existing.codex_config_path)
        result = remove_codex_block(tracked, get_builtin_codex_entries())
        if result.leftover_commands:
            logger.warning(
                "Forge hook commands remain outside the managed block in %s: %s",
                tracked,
                ", ".join(result.leftover_commands),
            )

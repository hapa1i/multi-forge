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
from importlib.resources import files
from pathlib import Path
from typing import Any, NoReturn

from forge.core.paths import find_git_root
from forge.core.runtime import installed_runtimes
from forge.core.state import StateError, atomic_write_bytes, now_iso

# Import for CLAUDE_HOME support
from forge.session.claude.paths import get_claude_home

from .codex_hooks import (
    apply_codex_merge,
    get_builtin_codex_entries,
    get_codex_config_path,
    plan_codex_merge,
    read_codex_registration,
    remove_codex_block,
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
    MODULE_DEPENDENCIES,
    PROFILE_MODULES,
    SETTINGS_ONLY_MODULES,
    SKILL_PROFILE_REQUIREMENTS,
    CodexPlan,
    FilePlan,
    Installation,
    InstalledFile,
    InstalledManifest,
    InstalledSkillPackage,
    InstallMode,
    InstallModule,
    InstallPlan,
    InstallProfile,
    InstallScope,
    SettingsPlan,
    SkillPackagePlan,
    SkillPackageStatus,
    make_installation_key,
)
from .settings_merge import (
    backup_settings,
    cleanup_empty_settings,
    entries_to_added_structure,
    find_added_files,
    find_backup_files,
    get_settings_path,
    hooks_already_present,
    load_added_settings,
    merge,
    permissions_already_present,
    read_settings,
    save_added_settings,
    scalar_already_set,
    settings_equal,
    smart_unmerge,
    unmerge,
    write_settings,
)
from .skill_cache import compiled_skill_cache_dir, materialize_compiled_skill
from .skill_compiler import (
    CompiledSkillFile,
    CompiledSkillPackage,
    SkillRuntime,
    compile_skill_for_runtime,
    load_skill_sources,
)
from .skill_planning import (
    CLAUDE_CODE_RUNTIME,
    CODEX_RUNTIME,
    SkillCandidate,
    SkillPlanAction,
    SkillPlanReason,
    plan_runtime_skills,
    runtime_skill_root,
    scan_codex_skill_duplicates,
    select_skill_runtimes,
)
from .tracking import TrackingStore, compute_checksum

logger = logging.getLogger(__name__)


_EXTENSION_MODULE_NAMES = ("skills", "agents", "commands")
_INVALID_SKILL_PACKAGE_RECOVERY = (
    "Remove the unexpected package entry or repair the invalid tracking row before sync or disable."
)


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
_RUNTIME_HOOK_MODULES = {InstallModule.HOOKS, InstallModule.CODEX_HOOKS}
_USER_SCOPE_OMITTED_MODULES = {InstallModule.STATUSLINE}
_CLAUDE_SETTINGS_MODULES = {
    InstallModule.HOOKS,
    InstallModule.STATUSLINE,
    InstallModule.PERMISSIONS,
}


@dataclass(frozen=True)
class _SettingsRollbackState:
    """Exact pre-apply settings and ownership-sidecar state."""

    settings_path: Path
    settings_content: bytes | None
    settings_mode: int | None
    added_files: tuple[tuple[Path, bytes, int], ...]


def _format_modules(modules: set[InstallModule]) -> str:
    return ", ".join(sorted(module.value for module in modules))


def _scope_omitted_modules(scope: InstallScope) -> set[InstallModule]:
    if scope == InstallScope.USER:
        return set(_USER_SCOPE_OMITTED_MODULES)
    return set(_RUNTIME_HOOK_MODULES)


def _apply_scope_module_policy(
    modules: set[InstallModule],
    *,
    scope: InstallScope,
    explicit_modules: set[InstallModule] | None = None,
) -> set[InstallModule]:
    """Return modules that are actually writable at *scope*.

    Implicit profile modules are filtered by scope. Explicit `--with` modules
    that contradict the ownership model are rejected so the CLI does not appear
    to honor a request while silently dropping it.
    """

    omitted = _scope_omitted_modules(scope)
    explicit_conflicts = omitted & (explicit_modules or set())
    if explicit_conflicts:
        if scope == InstallScope.USER:
            raise ForgeInstallError(
                f"module(s) {_format_modules(explicit_conflicts)} are project/local-scope only; "
                "statusLine stays project-scoped; install it at project/local scope."
            )
        raise ForgeInstallError(
            f"module(s) {_format_modules(explicit_conflicts)} are user-scope only; "
            "run 'forge extension enable --scope user' to install runtime hooks."
        )
    return modules - omitted


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
    """Presence gate for the codex-hooks module (PATH check via the runtime registry)."""
    from forge.core.runtime import get_runtime

    return get_runtime("codex").is_installed()


def get_target_root(scope: InstallScope, project_root: Path | None = None) -> Path:
    """Get target directory for extensions.

    Args:
        scope: Installation scope.
        project_root: Project root (required for PROJECT/LOCAL).

    Returns:
        Path to target .claude directory.

    Raises:
        ValueError: If project_root required but not provided.
        NestedClaudeDirectoryError: If project_root is inside a .claude directory.
    """
    if scope == InstallScope.USER:
        return get_claude_home()
    else:
        if project_root is None:
            raise ValueError("project_root required for PROJECT/LOCAL scope")

        # Guard against nested .claude directories (e.g., running from .claude/)
        resolved = project_root.resolve()
        if ".claude" in resolved.parts:
            from .exceptions import NestedClaudeDirectoryError

            raise NestedClaudeDirectoryError(str(project_root))

        return project_root / ".claude"


def _runtime_skill_root(runtime: str, scope: InstallScope, project_root: Path | None) -> Path:
    return runtime_skill_root(
        runtime,
        scope,
        user_home=Path.home(),
        claude_home=get_claude_home(),
        project_root=project_root,
    )


def _legacy_claude_skill_packages(
    installation: Installation | None,
    scope: InstallScope,
    project_root: Path | None,
) -> set[tuple[str, str]]:
    """Derive only provable v1 Claude package ownership from tracked paths."""

    if installation is None or installation.skill_packages:
        return set()
    skills_root = _runtime_skill_root(CLAUDE_CODE_RUNTIME, scope, project_root)
    result: set[tuple[str, str]] = set()
    for tracked_file in installation.files:
        target = Path(tracked_file.target_path)
        try:
            relative = target.relative_to(skills_root)
        except ValueError:
            continue
        if len(relative.parts) >= 2:
            result.add((CLAUDE_CODE_RUNTIME, relative.parts[0]))
    return result


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
        if InstallModule.SKILLS.value not in installation.modules_enabled:
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
                target, expected_target = _tracked_skill_package_target(
                    package,
                    scope,
                    project_root,
                    "classify managed Codex package",
                )
                _validate_tracked_skill_package_files(
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


def _tracked_skill_package_target(
    package: InstalledSkillPackage,
    scope: InstallScope,
    project_root: Path | None,
    operation: str,
) -> tuple[Path, Path]:
    """Validate one tracked package location and return target/expected paths."""

    runtime_root = _runtime_skill_root(package.runtime, scope, project_root)
    expected_target = runtime_root / package.skill
    validate_path_within_boundary(expected_target, runtime_root, operation)
    target = Path(package.target_dir)
    if not target.is_absolute():
        raise PathBoundaryViolationError(str(target), str(expected_target), operation)
    expected_location = expected_target.parent.resolve() / expected_target.name
    target_location = target.parent.resolve() / target.name
    if target_location != expected_location:
        raise PathBoundaryViolationError(str(target), str(expected_target), operation)
    _validate_real_skill_package_directory(target, expected_target, operation)
    return target, expected_target


def _validate_real_skill_package_directory(path: Path, expected_target: Path, operation: str) -> None:
    """Require an existing package directory entry to be real, never a symlink."""

    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    except OSError as e:
        raise PathBoundaryViolationError(str(path), str(expected_target), operation) from e
    if not stat.S_ISDIR(mode):
        raise PathBoundaryViolationError(str(path), f"{expected_target} (real directory)", operation)


def _validate_skill_package_file_path(
    tracked_file: Path,
    package_dir: Path,
    expected_target: Path,
    operation: str,
) -> None:
    """Validate one package file path without traversing substituted directories."""

    if not tracked_file.is_absolute():
        raise PathBoundaryViolationError(str(tracked_file), str(expected_target), operation)
    validate_path_within_boundary(tracked_file, expected_target, operation)
    try:
        relative = tracked_file.relative_to(package_dir)
    except ValueError as e:
        raise PathBoundaryViolationError(str(tracked_file), str(expected_target), operation) from e
    if not relative.parts or ".." in relative.parts:
        raise PathBoundaryViolationError(str(tracked_file), str(expected_target), operation)

    current = package_dir
    for component in relative.parts[:-1]:
        current /= component
        _validate_real_skill_package_directory(current, expected_target, operation)


def _validate_tracked_skill_package_files(
    package: InstalledSkillPackage,
    package_dir: Path,
    expected_target: Path,
    operation: str,
) -> None:
    for tracked_file in package.file_paths:
        _validate_skill_package_file_path(Path(tracked_file), package_dir, expected_target, operation)


def _assert_tracked_skill_packages_syncable(
    installation: Installation,
    scope: InstallScope,
    project_root: Path | None,
) -> None:
    """Block mutation when persisted package ownership cannot be validated."""

    invalid: list[str] = []
    for package in installation.skill_packages:
        try:
            target, expected_target = _tracked_skill_package_target(
                package,
                scope,
                project_root,
                "sync skill package",
            )
            _validate_tracked_skill_package_files(package, target, expected_target, "sync skill package")
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
            target, expected_target = _tracked_skill_package_target(
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
            _validate_tracked_skill_package_files(package, target, expected_target, "inspect skill package")
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


def validate_path_within_boundary(
    path: Path,
    boundary: Path,
    operation: str = "delete",
) -> None:
    """Validate that a path is within the expected boundary.

    Security check to prevent malicious tracking file modifications
    from causing deletion of arbitrary system files.

    Args:
        path: The path to validate.
        boundary: The expected parent directory.
        operation: Description of the operation (for error messages).

    Raises:
        PathBoundaryViolationError: If path is not within boundary.
    """
    # Always use parent.resolve() / name to get the absolute path of the entry
    # itself, without following symlinks on the final component. This:
    # 1. Handles symlinks correctly (checks location, not target)
    # 2. Handles non-existent paths consistently (is_symlink() returns False
    #    for non-existent paths, so we'd otherwise fall back to resolve())
    # 3. Still canonicalizes any symlink directories in the parent chain
    resolved_path = path.parent.resolve() / path.name
    resolved_boundary = boundary.resolve()

    if not resolved_path.is_relative_to(resolved_boundary):
        raise PathBoundaryViolationError(str(path), str(boundary), operation)


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

    Returns:
        Tuple of (scope, project_root). For USER scope, project_root is None.

    Raises:
        NoForgeInstallationError: If no installation found.
    """
    if start is None:
        start = Path.cwd()
    if tracking is None:
        tracking = TrackingStore()

    manifest: InstalledManifest | None = None

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


def resolve_modules(
    profile: InstallProfile,
    with_modules: set[InstallModule] | None = None,
    without_modules: set[InstallModule] | None = None,
) -> set[InstallModule]:
    """Resolve final module set from profile and toggles.

    Args:
        profile: Base profile.
        with_modules: Modules to add.
        without_modules: Modules to remove.

    Returns:
        Final set of modules to install.
    """
    modules = PROFILE_MODULES[profile].copy()

    if with_modules:
        modules |= with_modules

    if without_modules:
        modules -= without_modules

    for module in list(modules):
        if deps := MODULE_DEPENDENCIES.get(module):
            modules |= deps

    return modules


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
            modules = _modules_override
        else:
            modules = resolve_modules(profile, with_modules, without_modules)
        modules = _apply_scope_module_policy(
            modules,
            scope=self._scope,
            explicit_modules=None if _modules_override is not None else with_modules,
        )

        # Sort modules for deterministic output
        sorted_modules = sorted(m.value for m in modules)

        plan = InstallPlan(
            scope=self._scope.value,
            mode=mode.value,
            profile=profile.value,
            modules=sorted_modules,
        )
        self._compiled_skill_packages = {}

        source_root = get_extensions_root()
        target_root = get_target_root(self._scope, self._project_root)
        tracked_installations = self._tracking.list_installations()
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
                explicit_runtime_ids=skill_runtimes,
                managed_runtime_ids=_managed_runtime_ids,
                tracked_installations=tracked_installations,
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

                file_plan = self._plan_file(source_file, target_file, mode, existing, force)
                plan.files.append(file_plan)
                if file_plan.action == "conflict":
                    plan.has_conflicts = True
                    plan.conflicts.append(f"File: {file_plan.target_path} - {file_plan.reason}")
                elif file_plan.action in {"install", "update"}:
                    plan.requires_claude_version = True

        # Sort files for deterministic output
        plan.files.sort(key=lambda f: f.target_path)

        settings_plans = self._plan_settings(modules, force)
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
        plan.codex = self._plan_codex(modules)

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
        explicit_runtime_ids: tuple[str, ...] | None,
        managed_runtime_ids: tuple[str, ...] | None,
        tracked_installations: list[tuple[str, str | None, Installation]],
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
        managed_packages = {
            (package.runtime, package.skill) for package in (existing.skill_packages if existing is not None else [])
        }
        managed_packages |= _legacy_claude_skill_packages(existing, self._scope, self._project_root)
        existing_runtime_ids = tuple(
            runtime
            for runtime in (CLAUDE_CODE_RUNTIME, CODEX_RUNTIME)
            if any(package_runtime == runtime for package_runtime, _skill in managed_packages)
        )
        try:
            selection = select_skill_runtimes(
                installed_runtime_ids=tuple(runtime.id for runtime in installed_runtimes()),
                explicit_runtime_ids=explicit_runtime_ids,
                managed_runtime_ids=managed_runtime_ids,
                existing_runtime_ids=existing_runtime_ids,
            )
        except ValueError as e:
            raise ForgeInstallError(f"Invalid skill runtime selection: {e}") from e
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
                    target_dir=str(decision.target_dir) if decision.target_dir is not None else None,
                    reason=decision.reason.value,
                    duplicate_dirs=[str(path) for path in decision.duplicate_dirs],
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
            _validate_real_skill_package_directory(
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
            runtime_root = _runtime_skill_root(decision.runtime, self._scope, self._project_root)
            file_plans: list[FilePlan] = []
            for package_file in compiled.files:
                source_file = cache_dir.joinpath(*package_file.path.parts)
                target_file = decision.target_dir.joinpath(*package_file.path.parts)
                validate_path_within_boundary(target_file, runtime_root, "write skill package")
                _validate_skill_package_file_path(
                    target_file,
                    decision.target_dir,
                    decision.target_dir,
                    "write skill package",
                )
                file_plan = self._plan_compiled_file(
                    package_file,
                    source_file,
                    target_file,
                    mode,
                    existing,
                    force,
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
                reason="files unchanged" if package_action == "skip" else decision.reason.value,
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
                    target = _runtime_skill_root(runtime, self._scope, self._project_root) / skill
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
    ) -> FilePlan:
        """Plan compiled bytes against a future cache path without materializing it."""

        if not target.exists() and not target.is_symlink():
            return FilePlan(action="install", target_path=str(target), source_path=str(source))

        target_location = target.parent.resolve() / target.name
        is_managed = existing is not None and any(
            Path(tracked.target_path).parent.resolve() / Path(tracked.target_path).name == target_location
            for tracked in existing.files
        )
        if is_managed:
            if mode == InstallMode.SYMLINK:
                if target.is_symlink() and target.resolve(strict=False) == source.resolve(strict=False):
                    if not source.is_file() or source.is_symlink():
                        return FilePlan(
                            action="update",
                            target_path=str(target),
                            source_path=str(source),
                            reason="compiled cache missing or invalid",
                        )
                    return FilePlan(
                        action="skip",
                        target_path=str(target),
                        source_path=str(source),
                        reason="symlink already correct",
                    )
            elif target.is_file() and not target.is_symlink():
                target_checksum = compute_checksum(target)
                source_checksum = hashlib.sha256(package_file.content).hexdigest()
                target_mode = stat.S_IMODE(target.stat().st_mode)
                if source_checksum == target_checksum and target_mode == package_file.mode:
                    return FilePlan(
                        action="skip",
                        target_path=str(target),
                        source_path=str(source),
                        reason="file unchanged",
                    )
            return FilePlan(action="update", target_path=str(target), source_path=str(source))

        if force:
            return FilePlan(
                action="install",
                target_path=str(target),
                source_path=str(source),
                reason="force overwrite",
            )
        return FilePlan(
            action="conflict",
            target_path=str(target),
            source_path=str(source),
            reason="file exists and is not Forge-managed",
        )

    def _plan_codex(self, modules: set[InstallModule]) -> CodexPlan | None:
        """Plan the Codex hook registration for the scope-mapped config.toml."""
        if InstallModule.CODEX_HOOKS not in modules:
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

    def _execute_codex(self, codex_plan: CodexPlan | None) -> tuple[str | None, list[str]] | None:
        """Execute the planned Codex merge; return fresh tracking fields.

        Returns (codex_config_path, codex_commands) read back from disk after
        a resolved outcome -- where (None, []) legitimately means "nothing
        Forge-owned on disk" (skip due to a manual registration: ownership
        transferred to the user). Returns None when the merge could NOT act
        (module not selected, no codex binary, conflict, apply failure):
        there is no authoritative read, so the caller must keep its previous
        tracking -- a managed block written by an earlier enable may still be
        on disk and disable must keep knowing about it. Apply failures
        degrade to a warning recorded on the plan (best-effort module; never
        fails the install).
        """
        if codex_plan is None or codex_plan.action == "unavailable" or codex_plan.config_path is None:
            return None
        if codex_plan.action == "conflict":
            logger.warning("Codex hook registration skipped: %s", codex_plan.reason)
            return None

        entries = get_builtin_codex_entries()
        config_path = Path(codex_plan.config_path)
        if codex_plan.action in ("install", "update"):
            try:
                apply_codex_merge(config_path, entries)
            except ForgeInstallError as e:
                # Race between plan and apply (config changed under us).
                logger.warning("Codex hook registration skipped: %s", e)
                codex_plan.action = "conflict"
                codex_plan.reason = str(e)
                return None

        status = read_codex_registration(config_path, entries)
        if status.block_present:
            return (str(config_path), list(status.commands_registered))
        # skip due to manual registration: user-owned, not tracked
        return (None, [])

    def _plan_file(
        self,
        source: Path,
        target: Path,
        mode: InstallMode,
        existing: Installation | None,
        force: bool,
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
        if not target.exists() and not target.is_symlink():
            return FilePlan(
                action="install",
                target_path=str(target),
                source_path=str(source),
            )

        is_managed = existing is not None and any(
            Path(f.target_path).resolve() == target.resolve() for f in existing.files
        )

        if is_managed:
            if mode == InstallMode.SYMLINK:
                if target.is_symlink() and target.resolve() == source.resolve():
                    return FilePlan(
                        action="skip",
                        target_path=str(target),
                        source_path=str(source),
                        reason="symlink already correct",
                    )
            else:
                if target.is_file():
                    source_checksum = compute_checksum(source)
                    target_checksum = compute_checksum(target)
                    if source_checksum == target_checksum:
                        return FilePlan(
                            action="skip",
                            target_path=str(target),
                            source_path=str(source),
                            reason="file unchanged",
                        )

            return FilePlan(
                action="update",
                target_path=str(target),
                source_path=str(source),
            )

        if force:
            return FilePlan(
                action="install",
                target_path=str(target),
                source_path=str(source),
                reason="force overwrite",
            )

        return FilePlan(
            action="conflict",
            target_path=str(target),
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

        if plan.has_conflicts:
            return plan  # Planning conflicts are a hard preflight boundary.

        if _modules_override is not None:
            modules = _modules_override
        else:
            modules = resolve_modules(profile, with_modules, without_modules)
        modules = _apply_scope_module_policy(
            modules,
            scope=self._scope,
            explicit_modules=None if _modules_override is not None else with_modules,
        )

        # Planning treats creation of a missing Claude anchor as a Claude
        # surface mutation. Materialize it only after the conflict preflight;
        # project CLI flows may already have created it after the version gate.
        if plan.requires_claude_version:
            get_target_root(self._scope, self._project_root).mkdir(parents=True, exist_ok=True)

        existing = self._tracking.get_installation(self._scope.value, self._project_path_str)
        if self._scope == InstallScope.USER and InstallModule.HOOKS in modules:
            # Read both user settings targets before rendering the dispatcher or
            # changing tracking. The later cleanup can then fail only on a new
            # race or an environmental write error, not known malformed input.
            from .hook_migration import plan_user_legacy_hook_files

            plan_user_legacy_hook_files(tuple(existing.settings_entries) if existing is not None else ())

        # Materialize only after all conflicts have cleared.  Dry-run calls
        # plan() directly and therefore cannot create or repair cache entries.
        for compiled in self._compiled_skill_packages.values():
            try:
                materialize_compiled_skill(compiled)
            except (OSError, StateError) as e:
                raise ForgeInstallError(
                    f"Failed to materialize compiled skill cache for "
                    f"'{compiled.runtime.value}/{compiled.name}'; extension targets were not changed "
                    f"and tracking was not updated: {e}"
                ) from e

        # Historical extension installs rendered the dispatcher even when
        # scope policy filtered hook modules. Preserve that lifecycle contract,
        # while a skills-only Codex install stays free of unrelated writes.
        if modules - {InstallModule.SKILLS}:
            _ensure_hook_dispatcher()

        installed_files: list[InstalledFile] = []
        newly_created_files: list[InstalledFile] = []
        existing_files_by_target = {record.target_path: record for record in existing.files} if existing else {}
        skill_package_dirs_by_file = {
            file_path: Path(package.target_dir)
            for package in plan.skill_packages
            if package.target_dir is not None
            for file_path in package.file_paths
        }
        for file_plan in plan.files:
            target = Path(file_plan.target_path)
            package_dir = skill_package_dirs_by_file.get(file_plan.target_path)
            if package_dir is not None:
                try:
                    _validate_real_skill_package_directory(package_dir, package_dir, "write skill package")
                    _validate_skill_package_file_path(target, package_dir, package_dir, "write skill package")
                except PathBoundaryViolationError as e:
                    self._raise_post_file_failure(
                        f"Refusing unsafe skill package write '{file_plan.target_path}'; tracking was not updated",
                        e,
                        newly_created_files,
                        plan,
                    )
            if file_plan.action in ("install", "update"):
                target_existed = target.exists() or target.is_symlink()
                try:
                    installed_file = self._execute_file(file_plan, mode)
                except OSError as e:
                    self._raise_post_file_failure(
                        f"Failed to write extension file '{file_plan.target_path}'; tracking was not updated",
                        e,
                        newly_created_files,
                        plan,
                        unrecorded_targets=() if target_existed else (target,),
                    )
                installed_files.append(installed_file)
                if not target_existed:
                    newly_created_files.append(installed_file)
            elif file_plan.action == "skip" and file_plan.source_path is not None:
                try:
                    installed_file = self._installed_file_record(file_plan, mode)
                except OSError as e:
                    self._raise_post_file_failure(
                        f"Failed to refresh extension file ownership '{file_plan.target_path}'",
                        e,
                        newly_created_files,
                        plan,
                    )
                previous = existing_files_by_target.get(installed_file.target_path)
                if previous is not None:
                    installed_file.installed_at = previous.installed_at
                installed_files.append(installed_file)

        backup_path: Path | None = None
        settings_rollback_state: _SettingsRollbackState | None = None
        if modules & _CLAUDE_SETTINGS_MODULES:
            settings_path = get_settings_path(self._scope, self._project_root)
            try:
                settings_rollback_state = self._capture_settings_rollback_state(settings_path)
                backup_path = backup_settings(settings_path)
                settings = read_settings(settings_path)
            except OSError as e:
                self._raise_post_file_failure(
                    "Failed to prepare Claude settings",
                    e,
                    newly_created_files,
                    plan,
                    settings_rollback_state=settings_rollback_state,
                )
            removed_entry_ids: set[tuple[str, str]] = set()
            if existing is not None and self._scope == InstallScope.USER and InstallModule.HOOKS in modules:
                old_hook_entries = [entry for entry in existing.settings_entries if entry.key_path.startswith("hooks.")]
                if old_hook_entries:
                    unmerge(settings, old_hook_entries)
                    removed_entry_ids = {(entry.key_path, entry.stable_id) for entry in old_hook_entries}
            if self._scope == InstallScope.USER and InstallModule.HOOKS in modules:
                # T6 migration: stage safe same-file legacy cleanup with the
                # dispatcher merge so settings.json changes in one atomic write.
                from .hook_migration import remove_known_legacy_hook_entries

                settings, removed_legacy_count = remove_known_legacy_hook_entries(settings)
                if removed_legacy_count:
                    plan.legacy_hook_cleanup_paths.append(str(settings_path))
            forge_settings = self._load_forge_settings()
            include_permissions = InstallModule.PERMISSIONS in modules
            entries = merge(
                settings,
                forge_settings,
                force=force,
                include_statusline=InstallModule.STATUSLINE in modules,
                include_hooks=InstallModule.HOOKS in modules,
                include_permissions=include_permissions,
                include_env=include_permissions,
            )
            try:
                write_settings(settings_path, settings)
            except OSError as e:
                self._raise_post_file_failure(
                    f"Failed to write Claude settings '{settings_path}'",
                    e,
                    newly_created_files,
                    plan,
                    settings_rollback_state=settings_rollback_state,
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
                    newly_created_files,
                    plan,
                    settings_rollback_state=settings_rollback_state,
                )
        else:
            final_entries = list(existing.settings_entries) if existing else []
            if final_entries:
                settings_path = get_settings_path(self._scope, self._project_root)
                try:
                    settings_rollback_state = self._capture_settings_rollback_state(settings_path)
                    save_added_settings(settings_path, entries_to_added_structure(final_entries))
                except OSError as e:
                    self._raise_post_file_failure(
                        f"Failed to preserve Claude settings ownership '{settings_path}'",
                        e,
                        newly_created_files,
                        plan,
                        settings_rollback_state=settings_rollback_state,
                    )

        # Merge newly installed files with existing tracked files (for idempotent re-runs)
        now = now_iso()

        # All targets the current source scan knows about, plus packages intentionally
        # preserved when an explicit runtime filter narrows an existing installation.
        planned_targets = {f.target_path for f in plan.files}
        planned_targets.update(
            target
            for package in plan.skill_packages
            if package.reason == SkillPlanReason.MANAGED_RUNTIME_PRESERVATION.value
            for target in package.file_paths
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
                        boundary = self._tracked_file_boundary(existing, target, "remove stale file")
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
                            newly_created_files,
                            plan,
                            settings_rollback_state=settings_rollback_state,
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
        installed_paths = {f.target_path for f in installed_files}
        final_files = list(installed_files)
        if existing:
            for existing_file in existing.files:
                if existing_file.target_path not in installed_paths:
                    if existing_file.target_path in planned_targets:
                        # Keep existing tracked file that was skipped (source still exists)
                        final_files.append(existing_file)

        codex_result = self._execute_codex(plan.codex)
        if codex_result is not None:
            codex_path, codex_commands = codex_result
        elif existing is not None:
            # No authoritative outcome (module not selected, codex binary
            # unavailable, conflict, or apply failure): preserve prior
            # tracking -- the previously written managed block may still be
            # on disk and disable must keep knowing to remove it.
            codex_path = existing.codex_config_path
            codex_commands = list(existing.codex_commands)
        else:
            codex_path, codex_commands = None, []

        final_skill_packages = [
            InstalledSkillPackage(
                runtime=package.runtime,
                skill=package.skill,
                target_dir=package.target_dir,
                file_paths=list(package.file_paths),
            )
            for package in plan.skill_packages
            if package.target_dir is not None
            and (package.cache_dir is not None or package.reason == SkillPlanReason.MANAGED_RUNTIME_PRESERVATION.value)
            and package.action in {"install", "update", "skip"}
        ]

        installation = Installation(
            scope=self._scope.value,
            mode=mode.value,
            profile=profile.value,
            modules_enabled=[m.value for m in sorted(modules, key=lambda m: m.value)],
            files=final_files,
            skill_packages=final_skill_packages,
            settings_entries=final_entries,
            settings_backup_path=(
                str(backup_path) if backup_path else existing.settings_backup_path if existing is not None else None
            ),
            codex_config_path=codex_path,
            codex_commands=codex_commands,
            installed_at=existing.installed_at if existing else now,
            updated_at=now,
        )
        try:
            self._tracking.set_installation(self._scope.value, installation, self._project_path_str)
        except (OSError, StateError) as e:
            self._raise_post_file_failure(
                "Failed to commit extension tracking",
                e,
                newly_created_files,
                plan,
                settings_rollback_state=settings_rollback_state,
            )

        return plan

    def _raise_post_file_failure(
        self,
        message: str,
        cause: Exception,
        newly_created_files: list[InstalledFile],
        plan: InstallPlan,
        *,
        unrecorded_targets: tuple[Path, ...] = (),
        settings_rollback_state: _SettingsRollbackState | None = None,
    ) -> NoReturn:
        rollback_failures = self._rollback_newly_created_files(
            newly_created_files,
            plan,
            unrecorded_targets=unrecorded_targets,
        )
        if settings_rollback_state is not None:
            rollback_failures.extend(self._restore_settings_rollback_state(settings_rollback_state))
        rollback_note = (
            f" Could not roll back: {', '.join(rollback_failures)}; remove only those generated files before retry."
            if rollback_failures
            else (
                " Newly created extension files and settings ownership state were rolled back; "
                "rerun the same command after repairing the failure."
                if settings_rollback_state is not None
                else " Newly created extension files were rolled back; rerun the same command after repairing the failure."
            )
        )
        raise ForgeInstallError(f"{message}: {cause}.{rollback_note}") from cause

    @staticmethod
    def _capture_settings_rollback_state(settings_path: Path) -> _SettingsRollbackState:
        """Capture settings and all ownership sidecars before an apply mutation."""

        if settings_path.is_file():
            settings_content = settings_path.read_bytes()
            settings_mode = stat.S_IMODE(settings_path.stat().st_mode)
        else:
            settings_content = None
            settings_mode = None
        added_files = tuple(
            (path, path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) for path in find_added_files(settings_path)
        )
        return _SettingsRollbackState(
            settings_path=settings_path,
            settings_content=settings_content,
            settings_mode=settings_mode,
            added_files=added_files,
        )

    @staticmethod
    def _restore_settings_rollback_state(state: _SettingsRollbackState) -> list[str]:
        """Best-effort restore of settings and ownership sidecars after apply failure."""

        failures: list[str] = []
        try:
            if state.settings_content is None:
                state.settings_path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(
                    state.settings_path,
                    state.settings_content,
                    mode=state.settings_mode,
                )
        except OSError:
            failures.append(str(state.settings_path))

        prior_added_paths = {path for path, _content, _mode in state.added_files}
        try:
            current_added_files = find_added_files(state.settings_path)
        except OSError:
            failures.append(f"{state.settings_path} ownership sidecars")
            current_added_files = []
        for path in current_added_files:
            if path in prior_added_paths:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                failures.append(str(path))
        for path, content, mode in state.added_files:
            try:
                atomic_write_bytes(path, content, mode=mode)
            except OSError:
                failures.append(str(path))
        return failures

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
                    _validate_real_skill_package_directory(
                        package_dir,
                        package_dir,
                        "roll back partial extension file",
                    )
                    _validate_skill_package_file_path(
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
                    _validate_real_skill_package_directory(package_dir, package_dir, "roll back extension file")
                    _validate_skill_package_file_path(
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

    def _execute_file(self, file_plan: FilePlan, mode: InstallMode) -> InstalledFile:
        """Execute a file operation.

        Args:
            file_plan: Plan for the file.
            mode: Installation mode.

        Returns:
            InstalledFile record.
        """
        source = Path(file_plan.source_path)  # type: ignore[arg-type]  # source_path is always non-None in execute context
        target = Path(file_plan.target_path)

        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists() or target.is_symlink():
            target.unlink()

        if mode == InstallMode.SYMLINK:
            target.symlink_to(source)
        else:
            shutil.copy2(source, target)

        return self._installed_file_record(file_plan, mode)

    @staticmethod
    def _installed_file_record(file_plan: FilePlan, mode: InstallMode) -> InstalledFile:
        """Build current ownership metadata for an installed or unchanged file."""

        source = Path(file_plan.source_path)  # type: ignore[arg-type]
        target = Path(file_plan.target_path)
        return InstalledFile(
            target_path=str(target),
            source_path=str(source),
            checksum=compute_checksum(source),
            mode=mode.value,
            installed_at=now_iso(),
        )

    def _tracked_file_boundary(self, installation: Installation, target: Path, operation: str) -> Path:
        """Return the runtime boundary for a tracked file and validate package ownership.

        Legacy rows have no package grouping and remain constrained to the
        historical Claude target.  A v2 package row narrows the file to the
        reviewed runtime root and its exact package directory.
        """

        target_key = str(target)
        package_matches = [package for package in installation.skill_packages if target_key in package.file_paths]
        if not package_matches:
            return get_target_root(self._scope, self._project_root)
        if len(package_matches) != 1:
            raise PathBoundaryViolationError(target_key, "one tracked skill package", operation)

        package = package_matches[0]
        try:
            runtime_root = _runtime_skill_root(package.runtime, self._scope, self._project_root)
        except (KeyError, ValueError) as e:
            raise PathBoundaryViolationError(
                target_key, f"known {self._scope.value} runtime skill root", operation
            ) from e
        try:
            tracked_package_dir, expected_package_dir = _tracked_skill_package_target(
                package,
                self._scope,
                self._project_root,
                operation,
            )
        except (KeyError, ValueError) as e:
            raise PathBoundaryViolationError(
                target_key, f"known {self._scope.value} runtime skill root", operation
            ) from e
        _validate_skill_package_file_path(target, tracked_package_dir, expected_package_dir, operation)
        return runtime_root

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

        existing_modules = {InstallModule(m) for m in existing.modules_enabled}
        managed_runtime_ids = self._managed_skill_runtime_ids(existing, existing_modules)

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
        existing_modules = {InstallModule(module) for module in existing.modules_enabled}
        managed_runtime_ids = self._managed_skill_runtime_ids(existing, existing_modules)
        return self.plan(
            profile=InstallProfile(existing.profile),
            mode=InstallMode(existing.mode),
            force=force,
            _modules_override=existing_modules,
            _managed_runtime_ids=managed_runtime_ids,
        )

    def _managed_skill_runtime_ids(
        self,
        existing: Installation,
        modules: set[InstallModule],
    ) -> tuple[str, ...] | None:
        if InstallModule.SKILLS not in modules:
            return None
        packages = {(package.runtime, package.skill) for package in existing.skill_packages}
        packages |= _legacy_claude_skill_packages(existing, self._scope, self._project_root)
        return tuple(
            runtime
            for runtime in (CLAUDE_CODE_RUNTIME, CODEX_RUNTIME)
            if any(package_runtime == runtime for package_runtime, _skill in packages)
        )

    def uninstall(self) -> None:
        """Remove Forge installation.

        Raises:
            NotInstalledError: If no existing installation.
        """
        existing = self._tracking.get_installation(self._scope.value, self._project_path_str)
        if existing is None:
            raise NotInstalledError(self._scope.value)

        base_dir = get_target_root(self._scope, self._project_root)
        removals: list[tuple[InstalledFile, Path, Path]] = []
        for file_record in existing.files:
            target = Path(file_record.target_path)
            boundary = self._tracked_file_boundary(existing, target, "delete file")
            validate_path_within_boundary(target, boundary, "delete file")
            removals.append((file_record, target, boundary))

        settings_path = get_settings_path(self._scope, self._project_root)
        backup_files = find_backup_files(settings_path)
        added_files = find_added_files(settings_path)
        has_settings_state = bool(existing.settings_entries or existing.settings_backup_path or added_files)
        if has_settings_state:
            validate_path_within_boundary(settings_path, base_dir, "delete settings")
            for added_file in added_files:
                validate_path_within_boundary(added_file, base_dir, "delete added file")

        dirs_to_clean: set[tuple[Path, Path]] = set()
        for _file_record, target, boundary in removals:
            self._tracked_file_boundary(existing, target, "delete file")
            if target.exists() or target.is_symlink():
                target.unlink()
            parent = target.parent
            while parent != boundary and parent.is_relative_to(boundary):
                dirs_to_clean.add((parent, boundary))
                parent = parent.parent

        # Clean up empty directories (deepest first)
        for dir_path, _boundary in sorted(dirs_to_clean, key=lambda item: len(item[0].parts), reverse=True):
            try:
                dir_path.rmdir()
            except OSError:
                pass  # Directory not empty or doesn't exist

        if has_settings_state:
            current = read_settings(settings_path)
            backup = read_settings(backup_files[0]) if backup_files else {}
            added = load_added_settings(settings_path)  # Already finds most recent

            if added:
                # Use smart unmerge: removes our additions, preserves user changes
                result = smart_unmerge(current, backup, added)
                result = cleanup_empty_settings(result)

                backup_cleaned = cleanup_empty_settings(backup)
                if settings_equal(result, backup_cleaned):
                    if backup_files and backup_cleaned:
                        # Had content before, restore it (use cleaned for consistency)
                        write_settings(settings_path, backup_cleaned)
                    elif settings_path.is_file():
                        # Was empty/non-existent before, delete
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
        """Remove the Forge-managed Codex hook block recorded in tracking.

        The tracked path must match the current scope mapping (guards against
        a tampered tracking file, and against a CODEX_HOME that changed since
        install -- in either case Forge refuses to edit the unexpected file).
        """
        if not existing.codex_config_path:
            return
        tracked = Path(existing.codex_config_path)
        expected = get_codex_config_path(self._scope, self._project_root)
        if tracked.resolve() != expected.resolve():
            logger.warning(
                "tracked Codex config %s does not match the scope mapping %s; not modifying it",
                tracked,
                expected,
            )
            return
        result = remove_codex_block(tracked, get_builtin_codex_entries())
        if result.leftover_commands:
            logger.warning(
                "Forge hook commands remain outside the managed block in %s: %s",
                tracked,
                ", ".join(result.leftover_commands),
            )

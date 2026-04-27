"""Core installer logic.

Provides plan(), init(), update(), and uninstall() operations for
managing Claude Code extensions.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

# Import for CLAUDE_HOME support
from forge.session.claude.paths import get_claude_home

from .exceptions import (
    NoClaudeDirectoryError,
    NoForgeInstallationError,
    NotInstalledError,
    PathBoundaryViolationError,
)
from .models import (
    MODULE_DEPENDENCIES,
    PROFILE_MODULES,
    PROFILE_RANK,
    SETTINGS_ONLY_MODULES,
    SKILL_PROFILE_REQUIREMENTS,
    FilePlan,
    Installation,
    InstalledFile,
    InstallMode,
    InstallModule,
    InstallPlan,
    InstallProfile,
    InstallScope,
    SettingsPlan,
    now_iso,
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
from .tracking import TrackingStore, compute_checksum

logger = logging.getLogger(__name__)


def get_forge_source_root() -> Path:
    """Get the forge repo source root.

    This assumes running from a repo checkout. Future work may use
    importlib.resources for pip-installed packages.

    Returns:
        Path to the repo root (parent of src/).
    """
    # Navigate from this file to repo root:
    # src/forge/install/installer.py -> ../../../..
    return Path(__file__).parent.parent.parent.parent


def get_extensions_root() -> Path:
    """Get the extensions source directory (src/).

    Returns:
        Path to src/ directory containing extension modules.
    """
    return get_forge_source_root() / "src"


_EXCLUDED_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
_EXCLUDED_EXTENSIONS = {".pyc", ".pyo"}


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

    Used by `forge init` to auto-detect scope. Walks up from start directory
    looking for a .claude/ directory. If found, returns LOCAL scope at that
    project. If reaching home directory (~), returns USER scope.

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

    Used by `forge uninstall`, `forge update`, etc. to auto-detect scope.
    Walks up from start directory, checking LOCAL then PROJECT at each level,
    then USER at home.

    Detection is based on file evidence (.settings.*.json.forge.* files)
    which works across multiple projects, not just tracking store state.

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

        if current == home:
            user_settings = home / ".claude" / "settings.json"
            user_backups = find_backup_files(user_settings)
            user_added = find_added_files(user_settings)
            if user_backups or user_added:
                return (InstallScope.USER, None)
            # Fallback to tracking store for USER (no project_path for user scope)
            if tracking.get_installation(InstallScope.USER.value, None):
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
        *,
        _modules_override: set[InstallModule] | None = None,
    ) -> InstallPlan:
        """Compute installation plan without making changes.

        Args:
            profile: Installation profile.
            mode: Installation mode.
            with_modules: Modules to add.
            without_modules: Modules to remove.
            force: If True, override conflicts.
            _modules_override: Internal. If provided, use exactly these modules
                instead of resolving from profile. Used by update() to ensure
                only tracked modules are touched.

        Returns:
            InstallPlan describing what would be done.
        """
        if _modules_override is not None:
            modules = _modules_override
        else:
            modules = resolve_modules(profile, with_modules, without_modules)

        # Sort modules for deterministic output
        sorted_modules = sorted(m.value for m in modules)

        plan = InstallPlan(
            scope=self._scope.value,
            mode=mode.value,
            profile=profile.value,
            modules=sorted_modules,
        )

        source_root = get_extensions_root()
        target_root = get_target_root(self._scope, self._project_root)
        existing = self._tracking.get_installation(self._scope.value, self._project_path_str)

        # Only install git-tracked files (avoids __pycache__, .pyc, editor temps, etc.)
        git_tracked = _get_git_tracked_files(get_forge_source_root())

        # Precompute installed skill names from manifest (skill-level, not file-level)
        # so that update keeps the entire skill coherent when new files are added
        installed_skills: set[str] = set()
        if existing:
            skills_prefix = str(target_root / "skills") + "/"
            for f in existing.files:
                if f.target_path.startswith(skills_prefix):
                    suffix = f.target_path[len(skills_prefix) :]
                    if "/" in suffix:
                        installed_skills.add(suffix.split("/", 1)[0])

        for module in sorted(modules, key=lambda m: m.value):
            if module in SETTINGS_ONLY_MODULES:
                continue

            source_dir = source_root / get_module_source_dir(module)
            if not source_dir.is_dir():
                # Source not yet in allowlist - silently skip
                continue

            target_dir = target_root / get_module_source_dir(module)

            # Find installable source files (sorted for determinism)
            # _is_installable excludes __pycache__/.pyc unconditionally (works in Docker
            # where .git/ is absent and _get_git_tracked_files returns None).
            source_files = sorted(
                f
                for f in source_dir.rglob("*")
                if f.is_file() and _is_installable(f) and (git_tracked is None or f in git_tracked)
            )

            for source_file in source_files:
                rel_path = source_file.relative_to(source_dir)
                target_file = target_dir / rel_path

                # Per-skill profile gating: skip skills that require a higher profile,
                # unless the skill is already installed (update keeps entire skill coherent)
                if module == InstallModule.SKILLS and rel_path.parts:
                    skill_name = rel_path.parts[0]
                    required = SKILL_PROFILE_REQUIREMENTS.get(skill_name)
                    if required and PROFILE_RANK[profile] < PROFILE_RANK[required]:
                        if skill_name not in installed_skills:
                            continue

                file_plan = self._plan_file(source_file, target_file, mode, existing, force)
                plan.files.append(file_plan)
                if file_plan.action == "conflict":
                    plan.has_conflicts = True
                    plan.conflicts.append(f"File: {file_plan.target_path} - {file_plan.reason}")

        # Sort files for deterministic output
        plan.files.sort(key=lambda f: f.target_path)

        settings_plans = self._plan_settings(modules, force)
        plan.settings.extend(settings_plans)
        for sp in settings_plans:
            if sp.action == "conflict":
                plan.has_conflicts = True
                plan.conflicts.append(f"Setting: {sp.key_path} - {sp.reason}")

        # Sort settings for determinism
        plan.settings.sort(key=lambda s: (s.key_path, str(s.value)))

        return plan

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

        # Env vars (dict merge - Forge overrides)
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
        *,
        _modules_override: set[InstallModule] | None = None,
    ) -> InstallPlan:
        """Install extensions.

        Args:
            profile: Installation profile.
            mode: Installation mode.
            with_modules: Modules to add.
            without_modules: Modules to remove.
            force: If True, override conflicts.
            _modules_override: Internal. If provided, use exactly these modules.

        Returns:
            The executed plan.
        """
        plan = self.plan(
            profile,
            mode,
            with_modules,
            without_modules,
            force,
            _modules_override=_modules_override,
        )

        if plan.has_conflicts and not force:
            return plan  # Don't execute if conflicts

        settings_path = get_settings_path(self._scope, self._project_root)
        backup_path = backup_settings(settings_path)

        installed_files: list[InstalledFile] = []
        for file_plan in plan.files:
            if file_plan.action in ("install", "update"):
                installed_file = self._execute_file(file_plan, mode)
                installed_files.append(installed_file)

        if _modules_override is not None:
            modules = _modules_override
        else:
            modules = resolve_modules(profile, with_modules, without_modules)
        settings = read_settings(settings_path)
        forge_settings = self._load_forge_settings()
        entries = merge(
            settings,
            forge_settings,
            force=force,
            include_statusline=InstallModule.STATUSLINE in modules,
        )
        write_settings(settings_path, settings)

        # Save what we added for smart uninstall
        added_structure = entries_to_added_structure(entries)
        save_added_settings(settings_path, added_structure)

        # Merge newly installed files with existing tracked files (for idempotent re-runs)
        now = now_iso()
        existing = self._tracking.get_installation(self._scope.value, self._project_path_str)

        # All targets the current source scan knows about (installed, skipped, or conflicted)
        planned_targets = {f.target_path for f in plan.files}

        # Remove stale tracked files whose source no longer exists (e.g., after renames).
        # A file is stale if it was tracked in the previous installation but isn't in the
        # current plan's target set — meaning no source file maps to that target anymore.
        # Only auto-delete if ownership is verified (symlink target or checksum matches);
        # otherwise drop from manifest silently — the user may have repurposed the path.
        base_dir = get_target_root(self._scope, self._project_root)
        dirs_to_clean: set[Path] = set()
        if existing:
            for existing_file in existing.files:
                if existing_file.target_path not in planned_targets:
                    target = Path(existing_file.target_path)
                    try:
                        validate_path_within_boundary(target, base_dir, "remove stale file")
                    except PathBoundaryViolationError:
                        continue
                    if not self._is_forge_owned(target, existing_file):
                        logger.debug("Stale target not Forge-owned, dropping from manifest: %s", target)
                        continue
                    try:
                        target.unlink(missing_ok=True)
                        logger.debug("Removed stale tracked file: %s", target)
                    except OSError:
                        logger.debug("Could not remove stale target: %s", target)
                        continue
                    # Collect parent dirs for empty-directory cleanup
                    parent = target.parent
                    while parent != base_dir and parent.is_relative_to(base_dir):
                        dirs_to_clean.add(parent)
                        parent = parent.parent

        # Clean up empty directories left by stale file removal (deepest first)
        for dir_path in sorted(dirs_to_clean, key=lambda p: len(p.parts), reverse=True):
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

        entry_ids = {(e.key_path, e.stable_id) for e in entries}
        final_entries = list(entries)
        if existing:
            for existing_entry in existing.settings_entries:
                if (existing_entry.key_path, existing_entry.stable_id) not in entry_ids:
                    final_entries.append(existing_entry)

        installation = Installation(
            scope=self._scope.value,
            mode=mode.value,
            profile=profile.value,
            modules_enabled=[m.value for m in sorted(modules, key=lambda m: m.value)],
            files=final_files,
            settings_entries=final_entries,
            settings_backup_path=str(backup_path) if backup_path else None,
            installed_at=existing.installed_at if existing else now,
            updated_at=now,
        )
        self._tracking.set_installation(self._scope.value, installation, self._project_path_str)

        return plan

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

        return InstalledFile(
            target_path=str(target),
            source_path=str(source),
            checksum=compute_checksum(source),
            mode=mode.value,
            installed_at=now_iso(),
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

        # Use exact modules from existing installation
        existing_modules = {InstallModule(m) for m in existing.modules_enabled}

        return self.init(
            profile=InstallProfile(existing.profile),
            mode=InstallMode(existing.mode),
            force=force,
            _modules_override=existing_modules,
        )

    def uninstall(self) -> None:
        """Remove Forge installation.

        Raises:
            NotInstalledError: If no existing installation.
        """
        existing = self._tracking.get_installation(self._scope.value, self._project_path_str)
        if existing is None:
            raise NotInstalledError(self._scope.value)

        dirs_to_clean: set[Path] = set()
        base_dir = get_target_root(self._scope, self._project_root)

        for file_record in existing.files:
            target = Path(file_record.target_path)
            # Security: validate path is within expected boundary
            validate_path_within_boundary(target, base_dir, "delete file")
            if target.exists() or target.is_symlink():
                target.unlink()
            parent = target.parent
            while parent != base_dir and parent.is_relative_to(base_dir):
                dirs_to_clean.add(parent)
                parent = parent.parent

        # Clean up empty directories (deepest first)
        for dir_path in sorted(dirs_to_clean, key=lambda p: len(p.parts), reverse=True):
            try:
                dir_path.rmdir()
            except OSError:
                pass  # Directory not empty or doesn't exist

        settings_path = get_settings_path(self._scope, self._project_root)
        backup_files = find_backup_files(settings_path)
        added_files = find_added_files(settings_path)

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
                    # Security: validate settings path is within expected boundary
                    validate_path_within_boundary(settings_path, base_dir, "delete settings")
                    settings_path.unlink()
            else:
                write_settings(settings_path, result)
        else:
            # Fallback to old unmerge if no .forge-added file
            unmerge(current, existing.settings_entries)
            write_settings(settings_path, current)

        # Clean up .forge.added files only (keep .forge.backup files for history)
        for added_file in added_files:
            # Security: validate added file path is within expected boundary
            validate_path_within_boundary(added_file, base_dir, "delete added file")
            added_file.unlink()

        self._tracking.remove_installation(self._scope.value, self._project_path_str)

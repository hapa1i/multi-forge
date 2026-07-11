"""Migration from project/local legacy hooks to the user dispatcher."""

from __future__ import annotations

import json
import shlex
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from forge.core.state import now_iso
from forge.session.claude.paths import get_claude_home

from .codex_hooks import (
    CodexMergePlan,
    CodexRemovePlan,
    apply_codex_merge,
    backup_codex_config,
    get_builtin_codex_entries,
    get_codex_config_path,
    plan_codex_merge,
    plan_codex_remove,
    read_codex_registration,
    remove_codex_block,
)
from .exceptions import ForgeInstallError
from .hook_dispatcher import diagnose_hook_dispatcher, install_hook_dispatcher
from .hooks import (
    entry_is_forge_hook,
    find_forge_hook_cleanup_registrations,
    forge_hook_handler,
    has_forge_hook_double_fire,
    is_legacy_forge_hook_command,
)
from .models import (
    Installation,
    InstalledSettingsEntry,
    InstallMode,
    InstallModule,
    InstallProfile,
    InstallScope,
)
from .preset import get_builtin_preset
from .project_registry import ProjectRegistryStore, project_paths_match
from .settings_merge import (
    backup_settings,
    cleanup_empty_settings,
    entries_to_added_structure,
    find_added_files,
    get_added_path,
    get_settings_path,
    merge,
    write_settings,
)
from .tracking import TrackingStore


class HookMigrationError(ForgeInstallError):
    """Raised when migration cannot safely plan or apply a change."""


@dataclass(frozen=True)
class LegacyHookShape:
    """One released direct-hook wrapper shape, excluding command spelling."""

    event: str
    matcher: str | None
    handler: str
    timeout: int | None


# Frozen migration history. Do not derive this from the current preset: append a
# released generation deliberately if Forge ever ships another direct-hook shape.
KNOWN_LEGACY_HOOK_SHAPES: tuple[LegacyHookShape, ...] = (
    LegacyHookShape("SessionStart", None, "session-start", None),
    LegacyHookShape("PreToolUse", "Read", "read-hygiene", 5),
    LegacyHookShape("PreToolUse", "ExitPlanMode", "exit-plan-mode", None),
    LegacyHookShape("PreToolUse", "Write", "policy-check", 60),
    LegacyHookShape("PreToolUse", "Edit", "policy-check", 60),
    LegacyHookShape("PostToolUse", "Write", "plan-write", None),
    LegacyHookShape("Stop", None, "stop", None),
    LegacyHookShape("StopFailure", None, "stop-failure", None),
    LegacyHookShape("UserPromptSubmit", None, "user-prompt-submit", None),
    LegacyHookShape("PreCompact", None, "pre-compact", 10),
    LegacyHookShape("PostCompact", None, "post-compact", 5),
    LegacyHookShape("WorktreeCreate", None, "worktree-create", 30),
    LegacyHookShape("SubagentStop", None, "subagent-stop", 10),
    LegacyHookShape("TeammateIdle", None, "teammate-idle", 60),
    LegacyHookShape("TaskCompleted", None, "task-completed", 60),
    LegacyHookShape("SessionEnd", None, "session-end", 5),
)
_KNOWN_LEGACY_SIGNATURES = {
    (shape.event, shape.matcher, shape.handler, shape.timeout) for shape in KNOWN_LEGACY_HOOK_SHAPES
}


@dataclass(frozen=True)
class HookRemoval:
    """One full Claude hook wrapper eligible for removal."""

    event: str
    handler: str
    matcher: str | None
    source: str
    entry: dict[str, Any]


@dataclass(frozen=True)
class SettingsCleanupPlan:
    """Strict plan for one Claude settings file."""

    scope: str
    path: Path
    original: dict[str, Any]
    result: dict[str, Any]
    removals: tuple[HookRemoval, ...] = ()
    unresolved: tuple[str, ...] = ()
    added_path: Path | None = None

    @property
    def changed(self) -> bool:
        return self.original != self.result


@dataclass(frozen=True)
class MigrationCandidate:
    """One tracked project/local installation that may need cleanup."""

    root: str | None
    scopes: tuple[str, ...]
    stale: bool
    reason: str | None = None

    @property
    def cleanup_command(self) -> str | None:
        if self.root is None or self.stale:
            return None
        return f"forge extension cleanup-project --root {shlex.quote(self.root)}"


@dataclass(frozen=True)
class UserRuntimePlan:
    """User-scope runtime-hook transition planned without writes."""

    settings: SettingsCleanupPlan
    legacy_settings: SettingsCleanupPlan
    runtime_entries: tuple[InstalledSettingsEntry, ...]
    codex: CodexMergePlan | None
    needs_codex: bool
    dispatcher_current: bool
    tracking_change: bool
    blockers: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        codex_change = self.codex is not None and self.codex.action in {
            "install",
            "update",
        }
        return (
            self.settings.changed
            or self.legacy_settings.changed
            or codex_change
            or not self.dispatcher_current
            or self.tracking_change
        )


@dataclass(frozen=True)
class ProjectHookMigrationPlan:
    """Complete preview for one explicitly selected Forge root."""

    root: Path
    settings: tuple[SettingsCleanupPlan, ...]
    codex: CodexRemovePlan
    tracked_installations: tuple[tuple[str, Installation], ...]
    user: UserRuntimePlan
    enrolled: bool
    blockers: tuple[str, ...] = ()

    @property
    def hook_removal_count(self) -> int:
        return sum(len(item.removals) for item in self.settings)

    @property
    def root_changes(self) -> bool:
        tracked_cleanup = any(
            InstallModule.HOOKS.value in installation.modules_enabled
            or any(entry.key_path.startswith("hooks.") for entry in installation.settings_entries)
            or installation.codex_config_path
            or InstallModule.CODEX_HOOKS.value in installation.modules_enabled
            for _scope, installation in self.tracked_installations
        )
        return any(item.changed for item in self.settings) or self.codex.action == "remove" or tracked_cleanup

    @property
    def has_actions(self) -> bool:
        return self.root_changes or self.user.changed or not self.enrolled


@dataclass(frozen=True)
class ProjectHookMigrationResult:
    """Applied migration outcome for CLI rendering."""

    root: Path
    removed_hooks: int
    changed_paths: tuple[Path, ...]
    backup_paths: tuple[Path, ...]
    enrolled: bool
    enrollment_created: bool


@dataclass(frozen=True)
class UserLegacyCleanupResult:
    """Best-effort legacy user-file cleanup used by plain enable/sync."""

    changed_paths: tuple[Path, ...]
    backup_paths: tuple[Path, ...]
    unresolved: tuple[str, ...]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _direct_legacy_handler(command: Any) -> str | None:
    if not isinstance(command, str):
        return None
    try:
        tokens = shlex.split(command.strip())
    except ValueError:
        return None
    if len(tokens) != 3 or Path(tokens[0]).name != "forge" or tokens[1] != "hook":
        return None
    return tokens[2]


def known_legacy_hook_shape(event: str, entry: Any) -> LegacyHookShape | None:
    """Return the frozen released shape matched by *entry*, if any."""

    if not isinstance(entry, dict):
        return None
    matcher = entry.get("matcher")
    expected_entry_keys = {"hooks"} | ({"matcher"} if matcher is not None else set())
    if set(entry) != expected_entry_keys or (matcher is not None and not isinstance(matcher, str)):
        return None
    hooks = entry.get("hooks")
    if not isinstance(hooks, list) or len(hooks) != 1 or not isinstance(hooks[0], dict):
        return None
    command_entry = hooks[0]
    timeout = command_entry.get("timeout")
    expected_command_keys = {"type", "command"} | ({"timeout"} if timeout is not None else set())
    if set(command_entry) != expected_command_keys or command_entry.get("type") != "command":
        return None
    if timeout is not None and (not isinstance(timeout, int) or isinstance(timeout, bool)):
        return None
    handler = _direct_legacy_handler(command_entry.get("command"))
    if handler is None:
        return None
    signature = (event, matcher, handler, timeout)
    if signature not in _KNOWN_LEGACY_SIGNATURES:
        return None
    return LegacyHookShape(event=event, matcher=matcher, handler=handler, timeout=timeout)


def remove_known_legacy_hook_entries(
    settings: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    """Remove exact frozen legacy wrappers from an in-memory settings object."""

    result = deepcopy(settings)
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        return result, 0
    removed = 0
    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        kept = []
        for entry in entries:
            if known_legacy_hook_shape(str(event), entry) is not None:
                removed += 1
            else:
                kept.append(entry)
        hooks[event] = kept
    return cleanup_empty_settings(result), removed


def _read_settings_strict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise HookMigrationError(f"cannot read settings at '{path}': {e}") from e
    if not isinstance(data, dict):
        raise HookMigrationError(f"settings at '{path}' must contain a JSON object")
    hooks = data.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        raise HookMigrationError(f"settings key 'hooks' at '{path}' must be an object")
    if isinstance(hooks, dict):
        for event, entries in hooks.items():
            if not isinstance(event, str) or not isinstance(entries, list):
                raise HookMigrationError(f"settings hook event '{event}' at '{path}' must be an array")
    return data


def _entry_commands(entry: Any) -> tuple[str, ...]:
    if not isinstance(entry, dict):
        return ()
    commands: list[str] = []
    command = entry.get("command")
    if isinstance(command, str):
        commands.append(command)
    hooks = entry.get("hooks")
    if isinstance(hooks, list):
        for hook in hooks:
            if isinstance(hook, dict) and isinstance(hook.get("command"), str):
                commands.append(hook["command"])
    return tuple(commands)


def _plan_settings_cleanup(
    path: Path,
    scope: str,
    tracked_entries: tuple[InstalledSettingsEntry, ...] = (),
    *,
    reconcile_tracking: bool = False,
) -> SettingsCleanupPlan:
    original = _read_settings_strict(path)
    result = deepcopy(original)
    added_path = None
    if reconcile_tracking:
        added_files = find_added_files(path)
        if added_files:
            added_path = added_files[0]
            _read_settings_strict(added_path)
        else:
            added_path = get_added_path(path)
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        return SettingsCleanupPlan(
            scope=scope,
            path=path,
            original=original,
            result=result,
            added_path=added_path,
        )

    tracked_by_event: dict[str, set[str]] = {}
    for tracked in tracked_entries:
        if not tracked.key_path.startswith("hooks.") or not isinstance(tracked.value, dict):
            continue
        event = tracked.key_path.split(".", 1)[1]
        tracked_by_event.setdefault(event, set()).add(_canonical_json(tracked.value))

    removals: list[HookRemoval] = []
    unresolved: list[str] = []
    for event, entries in list(hooks.items()):
        kept: list[Any] = []
        tracked_values = tracked_by_event.get(event, set())
        for index, entry in enumerate(entries):
            canonical = _canonical_json(entry) if isinstance(entry, dict) else None
            if canonical is not None and canonical in tracked_values:
                commands = _entry_commands(entry)
                if (
                    scope == "user"
                    and commands
                    and all(not is_legacy_forge_hook_command(command) for command in commands)
                ):
                    kept.append(entry)
                    continue
                handler = next(
                    (_direct_legacy_handler(command) for command in commands if _direct_legacy_handler(command)),
                    None,
                )
                removals.append(
                    HookRemoval(
                        event=event,
                        handler=handler or "tracked",
                        matcher=(entry.get("matcher") if isinstance(entry.get("matcher"), str) else None),
                        source="tracked",
                        entry=deepcopy(entry),
                    )
                )
                continue

            shape = known_legacy_hook_shape(event, entry)
            if shape is not None:
                removals.append(
                    HookRemoval(
                        event=event,
                        handler=shape.handler,
                        matcher=shape.matcher,
                        source="fallback",
                        entry=deepcopy(entry),
                    )
                )
                continue

            if entry_is_forge_hook(entry):
                commands = _entry_commands(entry)
                user_dispatcher_only = (
                    scope == "user"
                    and commands
                    and all(not is_legacy_forge_hook_command(command) for command in commands)
                )
                if not user_dispatcher_only:
                    unresolved.append(
                        f"{path}: hooks.{event}[{index}] is Forge-looking but not a known removable shape"
                    )
            kept.append(entry)
        hooks[event] = kept

    result = cleanup_empty_settings(result)
    return SettingsCleanupPlan(
        scope=scope,
        path=path,
        original=original,
        result=result,
        removals=tuple(removals),
        unresolved=tuple(unresolved),
        added_path=added_path,
    )


def list_hook_migration_candidates(
    tracking: TrackingStore | None = None,
) -> tuple[MigrationCandidate, ...]:
    """List tracked roots needing cleanup without reading or enrolling them."""

    store = tracking or TrackingStore()
    grouped: dict[str | None, dict[str, Any]] = {}
    for scope, project_path, installation in store.list_installations():
        if scope not in {InstallScope.LOCAL.value, InstallScope.PROJECT.value}:
            continue
        has_legacy_tracking = (
            InstallModule.HOOKS.value in installation.modules_enabled
            or InstallModule.CODEX_HOOKS.value in installation.modules_enabled
            or bool(installation.codex_config_path)
            or any(entry.key_path.startswith("hooks.") for entry in installation.settings_entries)
        )
        if not has_legacy_tracking:
            continue
        key = str(Path(project_path).expanduser().resolve(strict=False)) if project_path else None
        item = grouped.setdefault(key, {"scopes": set(), "reason": None})
        item["scopes"].add(scope)
        if project_path is None:
            item["reason"] = "tracking row has no recoverable project path"

    candidates: list[MigrationCandidate] = []
    for root, item in grouped.items():
        missing = root is None or not Path(root).is_dir()
        not_forge = root is not None and not missing and not (Path(root) / ".forge").is_dir()
        stale = missing or not_forge
        reason = item["reason"]
        if reason is None and missing:
            reason = "tracked root no longer exists"
        if reason is None and not_forge:
            reason = "tracked path is no longer a Forge project"
        candidates.append(
            MigrationCandidate(
                root=root,
                scopes=tuple(sorted(item["scopes"])),
                stale=stale,
                reason=reason,
            )
        )
    return tuple(sorted(candidates, key=lambda candidate: candidate.root or ""))


def _settings_contains_entry(settings: dict[str, Any], key_path: str, value: Any) -> bool:
    if not key_path.startswith("hooks."):
        return False
    event = key_path.split(".", 1)[1]
    hooks = settings.get("hooks")
    entries = hooks.get(event) if isinstance(hooks, dict) else None
    return isinstance(entries, list) and any(_canonical_json(entry) == _canonical_json(value) for entry in entries)


def plan_user_legacy_hook_files(
    tracked_entries: tuple[InstalledSettingsEntry, ...] = (),
    *,
    reconcile_tracking: bool = False,
) -> tuple[SettingsCleanupPlan, SettingsCleanupPlan]:
    """Strictly plan both user settings targets before either is changed."""

    current = _plan_settings_cleanup(
        get_settings_path(InstallScope.USER),
        InstallScope.USER.value,
        tracked_entries,
        reconcile_tracking=reconcile_tracking,
    )
    legacy = _plan_settings_cleanup(
        get_claude_home() / "settings.local.json",
        InstallScope.USER.value,
    )
    return current, legacy


def _logical_hook_registrations(
    plan: SettingsCleanupPlan,
) -> list[tuple[tuple[str, str | None, str], Path]]:
    hooks = plan.result.get("hooks")
    if not isinstance(hooks, dict):
        return []
    registrations: list[tuple[tuple[str, str | None, str], Path]] = []
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            outer_matcher = entry.get("matcher") if isinstance(entry.get("matcher"), str) else None
            command = entry.get("command")
            if isinstance(command, str) and (handler := forge_hook_handler(command)) is not None:
                registrations.append(((str(event), outer_matcher, handler), plan.path))
            inner = entry.get("hooks")
            if not isinstance(inner, list):
                continue
            for hook in inner:
                if not isinstance(hook, dict) or not isinstance(hook.get("command"), str):
                    continue
                handler = forge_hook_handler(hook["command"])
                if handler is None:
                    continue
                matcher = hook.get("matcher") if isinstance(hook.get("matcher"), str) else outer_matcher
                registrations.append(((str(event), matcher, handler), plan.path))
    return registrations


def _duplicate_user_hook_issues(plans: tuple[SettingsCleanupPlan, ...]) -> tuple[str, ...]:
    seen: dict[tuple[str, str | None, str], Path] = {}
    issues: list[str] = []
    for key, path in (registration for plan in plans for registration in _logical_hook_registrations(plan)):
        first = seen.get(key)
        if first is None:
            seen[key] = path
            continue
        event, matcher, handler = key
        trigger = f"{event}/{matcher or '*'} -> {handler}"
        issues.append(f"user hook trigger {trigger} is registered more than once in '{first}' and '{path}'")
    return tuple(issues)


def _runtime_hook_entries() -> tuple[InstalledSettingsEntry, ...]:
    scratch: dict[str, Any] = {}
    entries = merge(
        scratch,
        get_builtin_preset(),
        include_hooks=True,
        include_permissions=False,
        include_env=False,
        include_statusline=False,
    )
    return tuple(entries)


def _planned_user_tracking_entries(
    existing: Installation | None,
    settings: dict[str, Any],
    runtime_entries: tuple[InstalledSettingsEntry, ...],
) -> list[InstalledSettingsEntry]:
    existing_entries = list(existing.settings_entries) if existing is not None else []
    preserved = [
        entry
        for entry in existing_entries
        if not entry.key_path.startswith("hooks.")
        or (
            _settings_contains_entry(settings, entry.key_path, entry.value)
            and not any(is_legacy_forge_hook_command(command) for command in _entry_commands(entry.value))
        )
    ]
    return _dedupe_tracking_entries([*preserved, *runtime_entries])


def plan_user_runtime_transition(needs_codex: bool, tracking: TrackingStore | None = None) -> UserRuntimePlan:
    """Plan the narrow user runtime-hook transition without touching other modules."""

    store = tracking or TrackingStore()
    existing = store.get_installation(InstallScope.USER.value)
    current, legacy = plan_user_legacy_hook_files(
        tuple(existing.settings_entries) if existing is not None else (),
        reconcile_tracking=True,
    )

    merged = deepcopy(current.result)
    merge(
        merged,
        get_builtin_preset(),
        include_hooks=True,
        include_permissions=False,
        include_env=False,
        include_statusline=False,
    )
    current = replace(current, result=cleanup_empty_settings(merged))
    runtime_entries = _runtime_hook_entries()

    codex_plan = None
    if needs_codex:
        codex_plan = plan_codex_merge(get_codex_config_path(InstallScope.USER), get_builtin_codex_entries())

    required_modules = {InstallModule.HOOKS.value}
    if needs_codex:
        required_modules.add(InstallModule.CODEX_HOOKS.value)
    existing_modules = set(existing.modules_enabled) if existing is not None else set()
    planned_entries = _planned_user_tracking_entries(existing, current.result, runtime_entries)
    tracking_change = (
        existing is None
        or not required_modules.issubset(existing_modules)
        or planned_entries != existing.settings_entries
    )

    blockers = [*current.unresolved, *legacy.unresolved]
    blockers.extend(_duplicate_user_hook_issues((current, legacy)))
    if codex_plan is not None and codex_plan.action == "conflict":
        blockers.append(f"{codex_plan.config_path}: {codex_plan.reason}")

    dispatcher_current = diagnose_hook_dispatcher().status == "current"
    return UserRuntimePlan(
        settings=current,
        legacy_settings=legacy,
        runtime_entries=runtime_entries,
        codex=codex_plan,
        needs_codex=needs_codex,
        dispatcher_current=dispatcher_current,
        tracking_change=tracking_change,
        blockers=tuple(blockers),
    )


def _tracked_installations_for_root(
    root: Path,
    tracking: TrackingStore,
) -> tuple[tuple[str, Installation], ...]:
    matches: list[tuple[str, Installation]] = []
    for scope, project_path, installation in tracking.list_installations():
        if scope not in {InstallScope.LOCAL.value, InstallScope.PROJECT.value} or project_path is None:
            continue
        if project_paths_match(project_path, root):
            matches.append((scope, installation))
    return tuple(sorted(matches, key=lambda item: item[0]))


def plan_project_hook_migration(
    root: Path,
    *,
    tracking: TrackingStore | None = None,
    registry: ProjectRegistryStore | None = None,
) -> ProjectHookMigrationPlan:
    """Build a strict, side-effect-free migration plan for *root*."""

    resolved_root = root.expanduser().resolve()
    store = tracking or TrackingStore()
    registry_store = registry or ProjectRegistryStore()
    tracked = _tracked_installations_for_root(resolved_root, store)
    tracked_by_scope = {scope: installation for scope, installation in tracked}

    settings_plans: list[SettingsCleanupPlan] = []
    blockers: list[str] = []
    for install_scope in (InstallScope.LOCAL, InstallScope.PROJECT):
        installation = tracked_by_scope.get(install_scope.value)
        tracked_entries = tuple(installation.settings_entries) if installation is not None else ()
        reconcile_tracking = installation is not None and (
            InstallModule.HOOKS.value in installation.modules_enabled
            or any(entry.key_path.startswith("hooks.") for entry in installation.settings_entries)
        )
        settings_plan = _plan_settings_cleanup(
            get_settings_path(install_scope, resolved_root),
            install_scope.value,
            tracked_entries,
            reconcile_tracking=reconcile_tracking,
        )
        settings_plans.append(settings_plan)
        blockers.extend(settings_plan.unresolved)

    codex_path = get_codex_config_path(InstallScope.PROJECT, resolved_root)
    for scope, installation in tracked:
        if installation.codex_config_path and Path(installation.codex_config_path).resolve() != codex_path.resolve():
            blockers.append(
                f"tracked {scope} Codex path '{installation.codex_config_path}' does not match '{codex_path}'"
            )
    codex_plan = plan_codex_remove(codex_path, get_builtin_codex_entries())
    if codex_plan.action == "conflict":
        blockers.append(f"{codex_path}: {codex_plan.reason}")

    needs_codex = codex_plan.action == "remove" or any(
        installation.codex_config_path or InstallModule.CODEX_HOOKS.value in installation.modules_enabled
        for _scope, installation in tracked
    )
    user_plan = plan_user_runtime_transition(needs_codex, store)
    blockers.extend(user_plan.blockers)

    registry_data = registry_store.read_strict()
    enrolled = any(project_paths_match(entry.canonical_path, resolved_root) for entry in registry_data.projects)
    return ProjectHookMigrationPlan(
        root=resolved_root,
        settings=tuple(settings_plans),
        codex=codex_plan,
        tracked_installations=tracked,
        user=user_plan,
        enrolled=enrolled,
        blockers=tuple(blockers),
    )


def _dedupe_tracking_entries(
    entries: list[InstalledSettingsEntry],
) -> list[InstalledSettingsEntry]:
    seen: set[tuple[str, str]] = set()
    result: list[InstalledSettingsEntry] = []
    for entry in entries:
        key = (entry.key_path, entry.stable_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return result


def _apply_user_runtime_transition(
    plan: UserRuntimePlan,
    tracking: TrackingStore,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    if plan.blockers:
        raise HookMigrationError("user runtime transition is blocked: " + "; ".join(plan.blockers))

    changed_paths: list[Path] = []
    backup_paths: list[Path] = []
    if not plan.dispatcher_current:
        dispatcher = install_hook_dispatcher()
        if dispatcher is not None:
            changed_paths.extend(
                [
                    Path(dispatcher.dispatcher_path),
                    Path(dispatcher.metadata_path),
                ]
            )

    settings_backups: dict[Path, Path] = {}
    for settings_plan in (plan.settings, plan.legacy_settings):
        if not settings_plan.changed:
            continue
        if backup := backup_settings(settings_plan.path):
            backup_paths.append(backup)
            settings_backups[settings_plan.path] = backup
        write_settings(settings_plan.path, settings_plan.result)
        changed_paths.append(settings_plan.path)

    codex_path = get_codex_config_path(InstallScope.USER)
    if plan.codex is not None and plan.codex.action in {"install", "update"}:
        backup = apply_codex_merge(codex_path, get_builtin_codex_entries())
        if backup is not None:
            backup_paths.append(backup)
        changed_paths.append(codex_path)

    existing = tracking.get_installation(InstallScope.USER.value)
    final_entries = _planned_user_tracking_entries(existing, plan.settings.result, plan.runtime_entries)

    modules = set(existing.modules_enabled) if existing is not None else set()
    modules.add(InstallModule.HOOKS.value)
    if plan.needs_codex:
        modules.add(InstallModule.CODEX_HOOKS.value)

    codex_status = read_codex_registration(codex_path, get_builtin_codex_entries())
    codex_config_path: str | None
    codex_commands: list[str]
    if plan.needs_codex and codex_status.block_present:
        codex_config_path = str(codex_path)
        codex_commands = list(codex_status.commands_registered)
    elif existing is not None and not plan.needs_codex:
        codex_config_path = existing.codex_config_path
        codex_commands = list(existing.codex_commands)
    else:
        codex_config_path = None
        codex_commands = []

    now = now_iso()
    installation = Installation(
        scope=InstallScope.USER.value,
        mode=existing.mode if existing is not None else InstallMode.COPY.value,
        profile=(existing.profile if existing is not None else InstallProfile.STANDARD.value),
        modules_enabled=sorted(modules),
        files=list(existing.files) if existing is not None else [],
        settings_entries=final_entries,
        settings_backup_path=(
            str(settings_backups[plan.settings.path])
            if plan.settings.path in settings_backups
            else (existing.settings_backup_path if existing is not None else None)
        ),
        codex_config_path=codex_config_path,
        codex_commands=codex_commands,
        installed_at=existing.installed_at if existing is not None else now,
        updated_at=now,
    )
    if plan.settings.added_path is None:
        raise HookMigrationError("user runtime plan is missing its tracking payload path")
    write_settings(plan.settings.added_path, entries_to_added_structure(final_entries))
    changed_paths.append(plan.settings.added_path)
    tracking.set_installation(InstallScope.USER.value, installation)
    changed_paths.append(tracking.path)
    return tuple(changed_paths), tuple(backup_paths)


def _rewrite_project_tracking(
    plan: ProjectHookMigrationPlan,
    tracking: TrackingStore,
    settings_backups: dict[str, Path],
) -> tuple[Path, ...]:
    now = now_iso()
    clear_codex = plan.codex.action in {"remove", "skip"}
    changed_paths: list[Path] = []
    settings_by_scope = {settings.scope: settings for settings in plan.settings}
    for scope, installation in plan.tracked_installations:
        has_hook_tracking = InstallModule.HOOKS.value in installation.modules_enabled or any(
            entry.key_path.startswith("hooks.") for entry in installation.settings_entries
        )
        has_codex_tracking = bool(installation.codex_config_path) or (
            InstallModule.CODEX_HOOKS.value in installation.modules_enabled
        )
        if not has_hook_tracking and not (clear_codex and has_codex_tracking):
            continue
        entries = [entry for entry in installation.settings_entries if not entry.key_path.startswith("hooks.")]
        modules = [module for module in installation.modules_enabled if module != InstallModule.HOOKS.value]
        codex_config_path = installation.codex_config_path
        codex_commands = list(installation.codex_commands)
        if clear_codex:
            modules = [module for module in modules if module != InstallModule.CODEX_HOOKS.value]
            codex_config_path = None
            codex_commands = []
        updated = replace(
            installation,
            modules_enabled=modules,
            settings_entries=entries,
            settings_backup_path=str(settings_backups.get(scope, installation.settings_backup_path or "")) or None,
            codex_config_path=codex_config_path,
            codex_commands=codex_commands,
            updated_at=now,
        )
        if has_hook_tracking:
            settings_plan = settings_by_scope[scope]
            if settings_plan.added_path is None:
                raise HookMigrationError(f"{scope} cleanup plan is missing its tracking payload path")
            added_payload = entries_to_added_structure(entries)
            write_settings(settings_plan.added_path, added_payload)
            changed_paths.append(settings_plan.added_path)
        tracking.set_installation(scope, updated, installation.project_path or str(plan.root))
        changed_paths.append(tracking.path)
    return tuple(dict.fromkeys(changed_paths))


def apply_project_hook_migration(
    root: Path,
    *,
    tracking: TrackingStore | None = None,
    registry: ProjectRegistryStore | None = None,
) -> ProjectHookMigrationResult:
    """Re-plan and apply one explicit root migration in remove-first order."""

    store = tracking or TrackingStore()
    registry_store = registry or ProjectRegistryStore()
    plan = plan_project_hook_migration(root, tracking=store, registry=registry_store)
    if plan.blockers:
        raise HookMigrationError("migration is blocked: " + "; ".join(plan.blockers))

    changed_paths: list[Path] = []
    backups: list[Path] = []
    settings_backups: dict[str, Path] = {}
    transition_started = False
    try:
        # Establish every selected-root backup before the first destructive
        # write so a backup failure cannot partially clean the root.
        for settings_plan in plan.settings:
            if not settings_plan.changed:
                continue
            if backup := backup_settings(settings_plan.path):
                backups.append(backup)
                settings_backups[settings_plan.scope] = backup

        codex_path = Path(plan.codex.config_path)
        if plan.codex.action == "remove":
            if backup := backup_codex_config(codex_path):
                backups.append(backup)

        for settings_plan in plan.settings:
            if not settings_plan.changed:
                continue
            write_settings(settings_plan.path, settings_plan.result)
            changed_paths.append(settings_plan.path)
            transition_started = True

        if plan.codex.action == "remove":
            result = remove_codex_block(codex_path, get_builtin_codex_entries())
            if not result.removed or result.leftover_commands:
                raise HookMigrationError(
                    f"Codex block at '{codex_path}' changed during migration; retry after inspection"
                )
            changed_paths.append(codex_path)
            transition_started = True

        if plan.root_changes:
            transition_started = True
        changed_paths.extend(_rewrite_project_tracking(plan, store, settings_backups))
        remaining_root = [
            registration
            for registration in find_forge_hook_cleanup_registrations(plan.root)
            if registration.scope in {InstallScope.LOCAL.value, InstallScope.PROJECT.value}
        ]
        if remaining_root:
            paths = ", ".join(sorted({str(registration.settings_path) for registration in remaining_root}))
            raise HookMigrationError(f"post-clean root scan still found legacy registrations in: {paths}")
        if plan.user.changed:
            transition_started = True
            user_paths, user_backups = _apply_user_runtime_transition(plan.user, store)
            changed_paths.extend(user_paths)
            backups.extend(user_backups)

        remaining = find_forge_hook_cleanup_registrations(plan.root)
        if remaining:
            paths = ", ".join(sorted({str(registration.settings_path) for registration in remaining}))
            raise HookMigrationError(f"pre-enrollment scan still found legacy registrations in: {paths}")
        if has_forge_hook_double_fire(plan.root):
            raise HookMigrationError("pre-enrollment scan found duplicate user hook triggers")

        enrollment = registry_store.enroll(plan.root, "backfill")
        if enrollment.created:
            changed_paths.append(registry_store.path)
        remaining = find_forge_hook_cleanup_registrations(plan.root)
        if remaining:
            paths = ", ".join(sorted({str(registration.settings_path) for registration in remaining}))
            raise HookMigrationError(f"post-clean scan still found legacy registrations in: {paths}")
        if has_forge_hook_double_fire(plan.root):
            raise HookMigrationError("post-clean scan found duplicate hook triggers")
    except Exception as e:
        if transition_started:
            command = f"forge extension cleanup-project --root {shlex.quote(str(plan.root))} --yes"
            raise HookMigrationError(
                "migration writes started but the user transition or final enrollment failed; "
                f"hooks may be temporarily off. Backups were retained. Retry with: {command}. Cause: {e}"
            ) from e
        if isinstance(e, HookMigrationError):
            raise
        raise HookMigrationError(f"migration failed before hook/config changes were applied: {e}") from e
    return ProjectHookMigrationResult(
        root=plan.root,
        removed_hooks=plan.hook_removal_count,
        changed_paths=tuple(dict.fromkeys(changed_paths)),
        backup_paths=tuple(dict.fromkeys(backups)),
        enrolled=True,
        enrollment_created=enrollment.created,
    )


def cleanup_user_legacy_hook_files() -> UserLegacyCleanupResult:
    """Remove exact released direct-hook siblings after plain user enable/sync."""

    changed: list[Path] = []
    backups: list[Path] = []
    plans = plan_user_legacy_hook_files()
    unresolved = [issue for plan in plans for issue in plan.unresolved]
    unresolved.extend(_duplicate_user_hook_issues(plans))
    for plan in plans:
        if not plan.changed:
            continue
        try:
            if backup := backup_settings(plan.path):
                backups.append(backup)
            write_settings(plan.path, plan.result)
        except OSError as e:
            raise HookMigrationError(
                f"could not clean legacy user hooks at '{plan.path}': {e}. "
                "Retry the user-scope enable/sync after fixing the file."
            ) from e
        changed.append(plan.path)
    return UserLegacyCleanupResult(
        changed_paths=tuple(changed),
        backup_paths=tuple(backups),
        unresolved=tuple(unresolved),
    )

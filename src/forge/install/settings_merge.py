"""Settings merge logic for Claude Code settings.json.

Handles merging Forge settings into user's Claude Code settings with:
- hooks.*: append + dedupe by command path
- permissions.allow/deny: union unique entries
- statusLine: scalar (conflict unless --force)

Also handles unmerge (removing only Forge-added entries) for uninstall.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from forge.core.state import atomic_write_text
from forge.session.claude.paths import get_claude_home

from .exceptions import SettingsConflictError
from .models import InstalledSettingsEntry, InstallScope


def _get_timestamp() -> str:
    """Get current timestamp for file naming (YYYYMMDD-HHMMSS format)."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def get_settings_path(scope: InstallScope, project_root: Path | None = None) -> Path:
    """Get settings file path for a scope.

    Per design.md:
    - USER: ~/.claude/settings.json
    - PROJECT: .claude/settings.json
    - LOCAL: .claude/settings.local.json

    Args:
        scope: The installation scope.
        project_root: Project root directory (required for PROJECT/LOCAL).

    Returns:
        Path to the settings file.

    Raises:
        ValueError: If project_root is required but not provided.
    """
    if scope == InstallScope.USER:
        return get_claude_home() / "settings.json"
    elif scope == InstallScope.PROJECT:
        if project_root is None:
            raise ValueError("project_root required for PROJECT scope")
        return project_root / ".claude" / "settings.json"
    elif scope == InstallScope.LOCAL:
        if project_root is None:
            raise ValueError("project_root required for LOCAL scope")
        return project_root / ".claude" / "settings.local.json"
    raise ValueError(f"unknown scope: {scope}")


def read_settings(path: Path) -> dict[str, Any]:
    """Read settings file.

    Args:
        path: Path to settings file.

    Returns:
        Settings dict, or empty dict if file doesn't exist.
    """
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_settings(path: Path, settings: dict[str, Any]) -> None:
    """Write settings file atomically.

    Args:
        path: Path to settings file.
        settings: Settings dict to write.
    """
    json_str = json.dumps(settings, indent=2) + "\n"
    atomic_write_text(path, json_str)


def _get_forge_file_base(settings_path: Path) -> str:
    """Get base name for forge backup/added files.

    Converts:
    - settings.json -> .settings.json.forge
    - settings.local.json -> .settings.local.json.forge
    """
    return f".{settings_path.name}.forge"


def get_backup_path(settings_path: Path, timestamp: str | None = None) -> Path:
    """Get path for forge backup file (hidden, timestamped).

    Pattern: .settings.json.forge.backup.{timestamp}
    """
    ts = timestamp or _get_timestamp()
    base = _get_forge_file_base(settings_path)
    return settings_path.parent / f"{base}.backup.{ts}"


def get_added_path(settings_path: Path, timestamp: str | None = None) -> Path:
    """Get path for forge added file (hidden, timestamped).

    Pattern: .settings.json.forge.added.{timestamp}
    """
    ts = timestamp or _get_timestamp()
    base = _get_forge_file_base(settings_path)
    return settings_path.parent / f"{base}.added.{ts}"


def find_backup_files(settings_path: Path) -> list[Path]:
    """Find all forge backup files for a settings file (newest first)."""
    base = _get_forge_file_base(settings_path)
    pattern = f"{base}.backup.*"
    return sorted(settings_path.parent.glob(pattern), reverse=True)


def find_added_files(settings_path: Path) -> list[Path]:
    """Find all forge added files for a settings file (newest first)."""
    base = _get_forge_file_base(settings_path)
    pattern = f"{base}.added.*"
    return sorted(settings_path.parent.glob(pattern), reverse=True)


def backup_settings(path: Path) -> Path | None:
    """Create backup of settings file (hidden, timestamped).

    Args:
        path: Path to settings file.

    Returns:
        Path to backup file, or None if settings file doesn't exist.
    """
    if not path.is_file():
        return None
    backup_path = get_backup_path(path)
    shutil.copy2(path, backup_path)
    return backup_path


def restore_settings_backup(path: Path) -> bool:
    """Restore settings from most recent backup.

    Args:
        path: Path to settings file.

    Returns:
        True if restored, False if no backup exists.
    """
    backups = find_backup_files(path)
    if not backups:
        return False
    shutil.copy2(backups[0], path)  # Most recent
    return True


def save_added_settings(settings_path: Path, added: dict[str, Any]) -> Path:
    """Save the added settings structure.

    Args:
        settings_path: Path to main settings file.
        added: The settings structure containing what Forge added.

    Returns:
        Path to the added file.
    """
    added_path = get_added_path(settings_path)
    write_settings(added_path, added)
    return added_path


def load_added_settings(settings_path: Path) -> dict[str, Any]:
    """Load the most recent added settings structure.

    Args:
        settings_path: Path to main settings file.

    Returns:
        Added settings dict, or empty dict if no added file exists.
    """
    added_files = find_added_files(settings_path)
    if not added_files:
        return {}
    return read_settings(added_files[0])  # Most recent


def entries_to_added_structure(entries: list[InstalledSettingsEntry]) -> dict[str, Any]:
    """Convert tracking entries list to a settings-like structure for .forge-added.

    Args:
        entries: List of InstalledSettingsEntry from merge.

    Returns:
        Settings dict structure containing exactly what was added.
    """
    added: dict[str, Any] = {}

    for entry in entries:
        if entry.key_path.startswith("hooks."):
            hook_type = entry.key_path.split(".", 1)[1]
            hooks = added.setdefault("hooks", {})
            hook_list = hooks.setdefault(hook_type, [])
            hook_list.append(entry.value)
        elif entry.key_path.startswith("permissions."):
            perm_type = entry.key_path.split(".", 1)[1]
            perms = added.setdefault("permissions", {})
            perm_list = perms.setdefault(perm_type, [])
            perm_list.append(entry.value)
        elif entry.key_path.startswith("env."):
            env_key = entry.key_path.split(".", 1)[1]
            env = added.setdefault("env", {})
            env[env_key] = entry.value
        elif entry.merge_type == "scalar":
            # Top-level scalar like statusLine
            added[entry.key_path] = entry.value

    return added


def _deep_equals(a: Any, b: Any) -> bool:
    """Deep equality check for settings values."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_deep_equals(a[k], b[k]) for k in a)
    if isinstance(a, list):
        if len(a) != len(b):
            return False
        return all(_deep_equals(x, y) for x, y in zip(a, b))
    return a == b


def _is_empty_value(value: Any) -> bool:
    """Check if a value is empty (for cleanup purposes)."""
    if value is None:
        return True
    if isinstance(value, (list, dict, str)):
        return len(value) == 0
    return False


def smart_unmerge(
    current: dict[str, Any],
    backup: dict[str, Any],
    added: dict[str, Any],
) -> dict[str, Any]:
    """Smart unmerge: remove what we added, preserve user changes.

    For each thing in `added`:
    - Hooks: remove by command-path identity (same as merge dedupe logic)
    - Permissions: remove by value equality
    - Scalars: if current == added, restore backup value (or delete if not in backup)
    - If user modified our value, leave their modification

    Note: Does NOT restore backup entries that user deleted. If user removed
    something while Forge was installed, we respect that deletion.

    Args:
        current: Current settings dict.
        backup: Settings before Forge install (empty dict if didn't exist).
        added: What Forge added (from .forge-added).

    Returns:
        New settings dict with Forge additions removed but user changes preserved.
    """
    import copy

    result = copy.deepcopy(current)

    # Process hooks - use full-entry equality (matches merge dedupe logic)
    if "hooks" in added:
        result_hooks = result.get("hooks")
        # Defensive: skip if hooks is not a dict (corrupted settings)
        if not isinstance(result_hooks, dict):
            result_hooks = {}

        for hook_type, added_entries in added["hooks"].items():
            if hook_type not in result_hooks:
                continue

            current_list = result_hooks.get(hook_type)
            # Defensive: skip if not a list
            if not isinstance(current_list, list):
                continue

            added_canonical: set[str] = set()
            for added_entry in added_entries:
                if isinstance(added_entry, dict):
                    added_canonical.add(_canonical_json(added_entry))

            new_list = []
            for item in current_list:
                if not isinstance(item, dict):
                    new_list.append(item)
                    continue

                if _canonical_json(item) not in added_canonical:
                    new_list.append(item)

            result_hooks[hook_type] = new_list

    if "permissions" in added:
        result_perms = result.get("permissions")
        # Defensive: skip if permissions is not a dict
        if not isinstance(result_perms, dict):
            result_perms = {}

        for perm_type, added_entries in added["permissions"].items():
            if perm_type not in result_perms:
                continue

            current_list = result_perms.get(perm_type)
            # Defensive: skip if not a list
            if not isinstance(current_list, list):
                continue

            new_list = [item for item in current_list if item not in added_entries]

            result_perms[perm_type] = new_list

    if "env" in added:
        result_env = result.get("env")
        # Defensive: skip if env is not a dict
        if isinstance(result_env, dict):
            backup_env = backup.get("env", {})
            for env_key, added_value in added["env"].items():
                if env_key not in result_env:
                    continue

                current_value = result_env[env_key]
                backup_value = backup_env.get(env_key)

                if current_value == added_value:
                    # User hasn't modified our value - restore or delete
                    if backup_value is not None:
                        result_env[env_key] = backup_value
                    else:
                        del result_env[env_key]
                # else: user modified, leave their value

    for key, added_value in added.items():
        if key in ("hooks", "permissions", "env"):
            continue  # Already handled

        if key in result:
            current_value = result[key]
            backup_value = backup.get(key)

            if _deep_equals(current_value, added_value):
                # User hasn't modified our value - restore or delete
                if backup_value is not None:
                    result[key] = backup_value
                else:
                    del result[key]
            # else: user modified, leave their value

    return result


def cleanup_empty_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Remove empty arrays and objects from settings.

    Args:
        settings: Settings dict to clean.

    Returns:
        Cleaned settings dict.
    """
    import copy

    result = copy.deepcopy(settings)

    if "hooks" in result:
        result["hooks"] = {k: v for k, v in result["hooks"].items() if v}
        if not result["hooks"]:
            del result["hooks"]

    if "permissions" in result:
        result["permissions"] = {k: v for k, v in result["permissions"].items() if v}
        if not result["permissions"]:
            del result["permissions"]

    if "env" in result:
        result["env"] = {k: v for k, v in result["env"].items() if v}
        if not result["env"]:
            del result["env"]

    return result


def settings_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Check if two settings dicts are equivalent.

    Handles the case where one has empty arrays/objects and the other doesn't.
    """
    cleaned_a = cleanup_empty_settings(a)
    cleaned_b = cleanup_empty_settings(b)
    return _deep_equals(cleaned_a, cleaned_b)


# --- Pre-check functions (for planning phase) ---


def hooks_already_present(
    current_settings: dict[str, Any],
    hook_type: str,
    entries: list[dict[str, Any]],
) -> bool:
    """Check if all hook entries are already present in current settings.

    Args:
        current_settings: Current settings dict.
        hook_type: Hook type (e.g., "PreToolUse", "PostToolUse").
        entries: Hook entries to check.

    Returns:
        True if ALL entries are already present (nothing would be added).
    """
    existing = current_settings.get("hooks", {}).get(hook_type, [])

    existing_canonical: set[str] = {_canonical_json(e) for e in existing}

    for entry in entries:
        if _canonical_json(entry) not in existing_canonical:
            return False

    return True


def permissions_already_present(
    current_settings: dict[str, Any],
    perm_type: str,
    entries: list[str],
) -> bool:
    """Check if all permission entries are already present in current settings.

    Args:
        current_settings: Current settings dict.
        perm_type: Permission type ("allow" or "deny").
        entries: Permission entries to check.

    Returns:
        True if ALL entries are already present (nothing would be added).
    """
    existing = set(current_settings.get("permissions", {}).get(perm_type, []))
    return all(entry in existing for entry in entries)


def scalar_already_set(
    current_settings: dict[str, Any],
    key: str,
    value: Any,
) -> bool:
    """Check if a scalar value is already set to the expected value.

    Args:
        current_settings: Current settings dict.
        key: Setting key (e.g., "statusLine").
        value: Expected value.

    Returns:
        True if the key is already set to exactly this value.
    """
    return current_settings.get(key) == value


# --- Merge operations ---


def _extract_command_paths(entry: dict[str, Any]) -> set[str]:
    """Extract command paths from a hook entry for deduplication.

    System boundary: reads Claude Code settings.json which may contain
    either format depending on when the user last ran forge extension sync.
    - Current: {"hooks": [{"type": "command", "command": "..."}]}
    - Pre-sync: {"type": "command", "command": "..."} at entry level
    """
    commands = set()
    # Pre-sync format: command at entry level
    if cmd := entry.get("command"):
        commands.add(cmd)
    # Current format: nested hooks array
    for hook in entry.get("hooks", []):
        if cmd := hook.get("command"):
            commands.add(cmd)
    return commands


def _canonical_json(entry: dict[str, Any]) -> str:
    """Serialize a hook entry to a canonical JSON string for equality comparison."""
    import json

    return json.dumps(entry, sort_keys=True, separators=(",", ":"))


def merge_hooks(
    settings: dict[str, Any],
    hook_type: str,
    entries: list[dict[str, Any]],
) -> list[InstalledSettingsEntry]:
    """Merge hook entries: append + dedupe by full JSON entry equality.

    Two entries are duplicates only if they are structurally identical
    (same command, matcher, and all other fields). This ensures hooks
    with the same command but different matchers are preserved (e.g.,
    policy-check for Write vs Edit).

    Args:
        settings: Current settings dict (modified in place).
        hook_type: Hook type (e.g., "PreToolUse", "PostToolUse").
        entries: Hook entries to add.

    Returns:
        List of InstalledSettingsEntry for tracking.
    """
    hooks = settings.setdefault("hooks", {})
    existing = hooks.setdefault(hook_type, [])

    existing_canonical: set[str] = {_canonical_json(e) for e in existing if isinstance(e, dict)}

    added: list[InstalledSettingsEntry] = []
    for entry in entries:
        canonical = _canonical_json(entry)

        if canonical not in existing_canonical:
            existing.append(entry)
            existing_canonical.add(canonical)
            added.append(
                InstalledSettingsEntry(
                    key_path=f"hooks.{hook_type}",
                    value=entry,
                    merge_type="append",
                    stable_id=canonical,
                )
            )

    return added


def merge_permissions(
    settings: dict[str, Any],
    permission_type: str,
    entries: list[str],
) -> list[InstalledSettingsEntry]:
    """Merge permission entries: union unique.

    Args:
        settings: Current settings dict (modified in place).
        permission_type: Permission type ("allow" or "deny").
        entries: Permission entries to add.

    Returns:
        List of InstalledSettingsEntry for tracking.
    """
    permissions = settings.setdefault("permissions", {})
    existing = permissions.setdefault(permission_type, [])
    existing_set = set(existing)

    added: list[InstalledSettingsEntry] = []
    for entry in entries:
        if entry not in existing_set:
            existing.append(entry)
            existing_set.add(entry)
            added.append(
                InstalledSettingsEntry(
                    key_path=f"permissions.{permission_type}",
                    value=entry,
                    merge_type="union",
                    stable_id=entry,  # Entry value is the stable_id
                )
            )

    return added


def merge_env(
    settings: dict[str, Any],
    forge_env: dict[str, str],
) -> list[InstalledSettingsEntry]:
    """Merge env vars: Forge values override on conflicts.

    Args:
        settings: Current settings dict (modified in place).
        forge_env: Environment variables to set.

    Returns:
        List of InstalledSettingsEntry for tracking.
    """
    current_env = settings.setdefault("env", {})

    added: list[InstalledSettingsEntry] = []
    for key, value in sorted(forge_env.items()):
        current_env[key] = value
        added.append(
            InstalledSettingsEntry(
                key_path=f"env.{key}",
                value=value,
                merge_type="env",
                stable_id=key,
            )
        )

    return added


def check_scalar_conflict(
    settings: dict[str, Any],
    key: str,
    forge_value: Any,
) -> bool:
    """Check if scalar key has conflicting value.

    Args:
        settings: Current settings dict.
        key: Settings key to check.
        forge_value: Value Forge wants to set.

    Returns:
        True if conflict exists, False otherwise.
    """
    current = settings.get(key)
    if current is None:
        return False
    return current != forge_value


def set_scalar(
    settings: dict[str, Any],
    key: str,
    value: Any,
    force: bool = False,
) -> InstalledSettingsEntry | None:
    """Set a scalar value.

    Args:
        settings: Current settings dict (modified in place).
        key: Settings key to set.
        value: Value to set.
        force: If True, override existing value.

    Returns:
        InstalledSettingsEntry if value was set, None if no change needed.

    Raises:
        SettingsConflictError: If conflict and not force.
    """
    current = settings.get(key)
    if current is not None and current != value and not force:
        raise SettingsConflictError(key, current, value)

    if current == value:
        return None  # No change needed

    settings[key] = value
    return InstalledSettingsEntry(
        key_path=key,
        value=value,
        merge_type="scalar",
        stable_id=key,
    )


# --- Full merge/unmerge ---


def merge(
    settings: dict[str, Any],
    forge_settings: dict[str, Any],
    *,
    force: bool = False,
    include_statusline: bool = False,
    include_hooks: bool = True,
    include_permissions: bool = True,
) -> list[InstalledSettingsEntry]:
    """Full settings merge.

    Args:
        settings: Current settings dict (modified in place).
        forge_settings: Forge settings template to merge.
        force: If True, override scalar conflicts.
        include_statusline: If True, include statusLine setting.
        include_hooks: If True, merge hook entries.
        include_permissions: If True, merge permission entries.

    Returns:
        List of InstalledSettingsEntry for all changes made.

    Raises:
        SettingsConflictError: If scalar conflict and not force.
    """
    entries: list[InstalledSettingsEntry] = []

    if include_hooks:
        forge_hooks = forge_settings.get("hooks", {})
        for hook_type, hook_entries in sorted(forge_hooks.items()):
            entries.extend(merge_hooks(settings, hook_type, hook_entries))

    if include_permissions:
        forge_perms = forge_settings.get("permissions", {})
        if allow := forge_perms.get("allow"):
            entries.extend(merge_permissions(settings, "allow", allow))
        if deny := forge_perms.get("deny"):
            entries.extend(merge_permissions(settings, "deny", deny))

    # Merge statusLine (only if opted in)
    if include_statusline and "statusLine" in forge_settings:
        entry = set_scalar(
            settings,
            "statusLine",
            forge_settings["statusLine"],
            force=force,
        )
        if entry:
            entries.append(entry)

    if forge_env := forge_settings.get("env"):
        entries.extend(merge_env(settings, forge_env))

    return entries


def unmerge(
    settings: dict[str, Any],
    tracking_entries: list[InstalledSettingsEntry],
) -> None:
    """Remove Forge-added entries from settings.

    Uses stable_id for value-based matching (not index-based).

    Args:
        settings: Current settings dict (modified in place).
        tracking_entries: List of entries to remove.
    """
    # Group by key_path for efficient processing
    by_key: dict[str, list[InstalledSettingsEntry]] = {}
    for entry in tracking_entries:
        by_key.setdefault(entry.key_path, []).append(entry)

    hooks = settings.get("hooks", {})
    for key_path, entries in by_key.items():
        if key_path.startswith("hooks."):
            hook_type = key_path.split(".", 1)[1]
            if hook_type not in hooks:
                continue

            canonical_to_remove: set[str] = set()
            for e in entries:
                if e.value and isinstance(e.value, dict):
                    canonical_to_remove.add(_canonical_json(e.value))

            hooks[hook_type] = [
                h for h in hooks[hook_type] if not isinstance(h, dict) or _canonical_json(h) not in canonical_to_remove
            ]

    permissions = settings.get("permissions", {})
    for key_path, entries in by_key.items():
        if key_path.startswith("permissions."):
            perm_type = key_path.split(".", 1)[1]
            if perm_type not in permissions:
                continue

            values_to_remove = {e.stable_id for e in entries}
            permissions[perm_type] = [p for p in permissions[perm_type] if p not in values_to_remove]

    env = settings.get("env", {})
    for key_path, entries in by_key.items():
        if key_path.startswith("env."):
            env_key = key_path.split(".", 1)[1]
            if env_key in env:
                del env[env_key]
    if "env" in settings and not settings["env"]:
        del settings["env"]

    for key_path, entries in by_key.items():
        if entries and entries[0].merge_type == "scalar":
            if key_path in settings:
                del settings[key_path]


# --- Template path resolution ---


def resolve_template_paths(
    settings: dict[str, Any],
    target_root: Path,
) -> dict[str, Any]:
    """Replace {{PLACEHOLDER}} with actual paths.

    Used to resolve template placeholders in settings.template.json to
    actual target paths based on installation scope.

    Note: statusLine now uses `forge status-line` command directly (no path substitution).
    This function is kept for any future path placeholders.

    Args:
        settings: Settings dict with placeholders.
        target_root: Target .claude directory (e.g., ~/.claude or .claude).

    Returns:
        New settings dict with placeholders resolved.
    """
    import copy

    result = copy.deepcopy(settings)

    placeholders: dict[str, str] = {
        # No path placeholders currently needed - hooks and status-line
        # are now `forge <command>` invocations, not installed scripts.
    }

    def replace_placeholders(obj: Any) -> Any:
        if isinstance(obj, str):
            for placeholder, value in placeholders.items():
                obj = obj.replace(placeholder, value)
            return obj
        elif isinstance(obj, dict):
            return {k: replace_placeholders(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [replace_placeholders(item) for item in obj]
        return obj

    return replace_placeholders(result)

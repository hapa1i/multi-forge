"""Hook installation detection.

Checks whether Forge hooks are installed in Claude Code settings,
used by CLI commands to warn when features depend on hooks that aren't present.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ForgeHookRegistration:
    """One Forge hook command registered in a Claude Code settings file."""

    scope: str
    settings_path: Path
    event: str
    handler: str
    command: str
    matcher: str | None = None


def _find_claude_dir(start: Path) -> Path | None:
    """Walk up from start to find the nearest .claude/ directory.

    Returns the directory containing .claude/, or None if not found
    before reaching the filesystem root or the user's home directory. The
    home-directory stop prevents ~/.claude from being misclassified as a
    project scope for ordinary repos under $HOME.
    """
    current = start.resolve()
    try:
        home = Path.home().resolve()
    except RuntimeError:
        home = None
    for _ in range(50):  # safety bound
        if home is not None and current == home:
            return None
        if (current / ".claude").is_dir():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None


def _scoped_settings_paths(worktree_path: Path) -> list[tuple[str, Path]]:
    """Return named settings files to scan in priority order.

    Walks up from worktree_path to find the nearest .claude/ directory,
    so detection works correctly from subdirectories.
    """
    from forge.session.claude.paths import get_claude_home

    project_root = _find_claude_dir(worktree_path)
    paths: list[tuple[str, Path]] = []
    if project_root is not None:
        paths.extend(
            [
                ("local", project_root / ".claude" / "settings.local.json"),
                ("project", project_root / ".claude" / "settings.json"),
            ]
        )
    paths.extend(
        [
            ("user", get_claude_home() / "settings.local.json"),
            ("user", get_claude_home() / "settings.json"),
        ]
    )
    return _dedupe_scoped_settings_paths(paths)


def _dedupe_scoped_settings_paths(paths: list[tuple[str, Path]]) -> list[tuple[str, Path]]:
    """Return paths once by resolved identity, preferring later scope labels.

    When running from ``$HOME``, ``~/.claude/settings.json`` can otherwise be
    discovered once as project settings and once as user settings. Keeping the
    later user label preserves the real Claude scope.
    """

    order: list[Path] = []
    by_identity: dict[Path, tuple[str, Path]] = {}
    for scope, path in paths:
        identity = _settings_path_identity(path)
        if identity not in by_identity:
            order.append(identity)
        by_identity[identity] = (scope, path)
    return [by_identity[identity] for identity in order]


def _settings_path_identity(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _settings_paths(worktree_path: Path) -> list[Path]:
    """Return settings files to scan in priority order (local > project > user)."""

    return [path for _scope, path in _scoped_settings_paths(worktree_path)]


def is_forge_hook_command(command: str, handler: str | None = None) -> bool:
    """Return True when *command* invokes a Forge hook.

    The match is command-token based: legacy bare ``forge hook ...`` commands
    and dispatcher ``forge-hook ...`` commands match, while contains-only strings
    like ``echo forge hook stop`` do not.
    """
    found = forge_hook_handler(command)
    if found is None:
        return False
    return handler is None or found == handler


def forge_hook_handler(command: str) -> str | None:
    """Return the Forge hook handler invoked by *command*, if any.

    Both pre-T5 ``forge hook <handler>`` commands and T5 dispatcher
    ``forge-hook <handler>`` commands map to the same logical handler. Callers
    that need additive migration behavior should key on this value instead of
    raw command bytes.
    """
    try:
        tokens = shlex.split(command.strip())
    except ValueError:
        return None
    if not tokens:
        return None

    command_name = Path(tokens[0]).name
    if command_name == "forge-hook":
        if len(tokens) < 2:
            return None
        return tokens[1]

    if len(tokens) >= 2 and command_name == "forge" and tokens[1] == "hook":
        if len(tokens) < 3:
            return None
        return tokens[2]

    return None


def entry_is_forge_hook(entry: Any, handler: str | None = None, *, require_command_type: bool = False) -> bool:
    """Check whether a Claude Code hook entry invokes a Forge hook.

    System boundary: reads Claude Code settings.json which may contain
    either format depending on when the user last ran forge extension sync.
    - Current: {"hooks": [{"type": "command", "command": "..."}]}
    - Pre-sync: {"type": "command", "command": "..."}
    """
    if not isinstance(entry, dict):
        return False

    # Pre-sync format: command at entry top level
    if _entry_command_matches(entry, handler, require_command_type=require_command_type):
        return True

    # Current format: nested hooks array
    hooks = entry.get("hooks")
    if isinstance(hooks, list):
        for hook in hooks:
            if isinstance(hook, dict) and _entry_command_matches(
                hook, handler, require_command_type=require_command_type
            ):
                return True
    return False


def _entry_command_matches(entry: dict[str, Any], handler: str | None, *, require_command_type: bool) -> bool:
    return bool(_entry_command_registration(entry, handler, require_command_type=require_command_type))


def _entry_command_registration(
    entry: dict[str, Any],
    handler: str | None,
    *,
    require_command_type: bool,
) -> tuple[str, str] | None:
    if require_command_type and entry.get("type") != "command":
        return None

    command = entry.get("command")
    if not isinstance(command, str):
        return None
    found = forge_hook_handler(command)
    if found is None or (handler is not None and found != handler):
        return None
    return found, command


def _entry_forge_hook_registrations(
    entry: Any,
    handler: str | None = None,
    *,
    require_command_type: bool = False,
) -> list[tuple[str, str, str | None]]:
    if not isinstance(entry, dict):
        return []

    matcher = _entry_matcher(entry)
    registrations: list[tuple[str, str, str | None]] = []
    if found := _entry_command_registration(entry, handler, require_command_type=require_command_type):
        found_handler, command = found
        registrations.append((found_handler, command, matcher))

    hooks = entry.get("hooks")
    if isinstance(hooks, list):
        for hook in hooks:
            if isinstance(hook, dict) and (
                found := _entry_command_registration(hook, handler, require_command_type=require_command_type)
            ):
                found_handler, command = found
                hook_matcher = _entry_matcher(hook)
                registrations.append((found_handler, command, matcher if hook_matcher is None else hook_matcher))
    return registrations


def _entry_matcher(entry: dict[str, Any]) -> str | None:
    matcher = entry.get("matcher")
    if isinstance(matcher, str):
        return matcher
    return None


def _settings_path_has_forge_hook(
    settings_path: Path,
    hook_type: str | None = None,
    handler: str | None = None,
) -> bool:
    return bool(_settings_path_forge_hook_registrations("unknown", settings_path, hook_type, handler))


def _settings_path_forge_hook_registrations(
    scope: str,
    settings_path: Path,
    hook_type: str | None = None,
    handler: str | None = None,
) -> list[ForgeHookRegistration]:
    try:
        data = json.loads(settings_path.read_text())
        if not isinstance(data, dict):
            return []
        hooks = data.get("hooks")
        if not isinstance(hooks, dict):
            return []
        events: list[tuple[str, Any]]
        if hook_type is None:
            events = [(str(event), value) for event, value in hooks.items()]
        else:
            events = [(hook_type, hooks.get(hook_type))]
        registrations: list[ForgeHookRegistration] = []
        for event, hook_entries in events:
            if not hook_entries or not isinstance(hook_entries, list):
                continue
            for entry in hook_entries:
                for found_handler, command, matcher in _entry_forge_hook_registrations(entry, handler):
                    registrations.append(
                        ForgeHookRegistration(
                            scope=scope,
                            settings_path=settings_path,
                            event=event,
                            handler=found_handler,
                            command=command,
                            matcher=matcher,
                        )
                    )
        return registrations
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        OSError,
        TypeError,
        AttributeError,
    ):
        return []


def has_forge_hook(worktree_path: Path, hook_type: str, handler: str | None = None) -> bool:
    """Check if a specific Forge hook type is installed in any settings scope.

    Scans local, project, and user settings files for a hook entry whose
    command invokes ``forge hook``. Leave *handler* unset to match any Forge
    hook; pass ``"policy-check"`` to require that handler.

    Args:
        worktree_path: Project/worktree root to resolve local/project settings.
        hook_type: Claude Code hook event name (e.g., "SessionStart", "PreToolUse", "Stop").
        handler: Forge hook handler name to require, or None for any handler.
    """
    return any(
        _settings_path_has_forge_hook(settings_path, hook_type, handler)
        for settings_path in _settings_paths(worktree_path)
    )


def has_forge_hooks(worktree_path: Path) -> bool:
    """Check if any Forge hooks are installed.

    Uses SessionStart as the sentinel — it's included in all Forge
    installations and is the minimum viable hook for session tracking.
    """
    return has_forge_hook(worktree_path, "SessionStart")


def find_forge_hook_scopes(
    worktree_path: Path,
    hook_type: str | None = None,
    handler: str | None = None,
) -> set[str]:
    """Return settings scopes that currently register Forge hooks.

    The scope labels are ``local``, ``project``, and ``user``. User
    ``settings.local.json`` is intentionally folded into ``user`` because it is a
    legacy migration shape, not a separate runtime tier.
    """

    scopes: set[str] = set()
    for registration in find_forge_hook_registrations(worktree_path, hook_type, handler):
        scopes.add(registration.scope)
    return scopes


def find_forge_hook_registrations(
    worktree_path: Path,
    hook_type: str | None = None,
    handler: str | None = None,
) -> list[ForgeHookRegistration]:
    """Return concrete Forge hook registrations across local/project/user settings."""

    registrations: list[ForgeHookRegistration] = []
    for scope, settings_path in _scoped_settings_paths(worktree_path):
        registrations.extend(_settings_path_forge_hook_registrations(scope, settings_path, hook_type, handler))
    return registrations


def has_forge_hook_double_fire(
    worktree_path: Path,
    hook_type: str | None = None,
    handler: str | None = None,
) -> bool:
    """Return True when one Forge hook trigger has duplicate registrations.

    The trigger identity includes Claude event, matcher, and Forge handler.
    Distinct matchers under one event, such as policy checks for Write and Edit,
    are expected and do not double-fire for a single Claude hook dispatch.
    """

    seen: set[tuple[str, str | None, str]] = set()
    for registration in find_forge_hook_registrations(worktree_path, hook_type, handler):
        key = (registration.event, registration.matcher, registration.handler)
        if key in seen:
            return True
        seen.add(key)
    return False

"""Hook installation detection.

Checks whether Forge hooks are installed in Claude Code settings,
used by CLI commands to warn when features depend on hooks that aren't present.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any


def _find_claude_dir(start: Path) -> Path | None:
    """Walk up from start to find the nearest .claude/ directory.

    Returns the directory containing .claude/, or None if not found
    before reaching the filesystem root.
    """
    current = start.resolve()
    for _ in range(50):  # safety bound
        if (current / ".claude").is_dir():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None


def _settings_paths(worktree_path: Path) -> list[Path]:
    """Return settings files to scan in priority order (local > project > user).

    Walks up from worktree_path to find the nearest .claude/ directory,
    so detection works correctly from subdirectories.
    """
    from forge.session.claude.paths import get_claude_home

    project_root = _find_claude_dir(worktree_path) or worktree_path
    return [
        project_root / ".claude" / "settings.local.json",
        project_root / ".claude" / "settings.json",
        get_claude_home() / "settings.local.json",
        get_claude_home() / "settings.json",
    ]


def is_forge_hook_command(command: str, handler: str | None = None) -> bool:
    """Return True when *command* invokes ``forge hook``.

    The match is command-token based: bare ``forge hook ...`` and absolute-path
    ``/path/to/forge hook ...`` commands match, while contains-only strings like
    ``echo forge hook stop`` do not.
    """
    try:
        tokens = shlex.split(command.strip())
    except ValueError:
        return False

    if len(tokens) < 2:
        return False
    if Path(tokens[0]).name != "forge" or tokens[1] != "hook":
        return False
    if handler is not None:
        return len(tokens) >= 3 and tokens[2] == handler
    return True


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
    if require_command_type and entry.get("type") != "command":
        return False

    command = entry.get("command")
    return isinstance(command, str) and is_forge_hook_command(command, handler)


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
    for settings_path in _settings_paths(worktree_path):
        try:
            data = json.loads(settings_path.read_text())
            if not isinstance(data, dict):
                continue
            hooks = data.get("hooks")
            if not isinstance(hooks, dict):
                continue
            hook_entries = hooks.get(hook_type)
            if not hook_entries or not isinstance(hook_entries, list):
                continue
            for entry in hook_entries:
                if not isinstance(entry, dict):
                    continue
                if entry_is_forge_hook(entry, handler):
                    return True
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, AttributeError):
            continue
    return False


def has_forge_hooks(worktree_path: Path) -> bool:
    """Check if any Forge hooks are installed.

    Uses SessionStart as the sentinel — it's included in all Forge
    installations and is the minimum viable hook for session tracking.
    """
    return has_forge_hook(worktree_path, "SessionStart")

"""Hook installation detection.

Checks whether Forge hooks are installed in Claude Code settings,
used by CLI commands to warn when features depend on hooks that aren't present.
"""

from __future__ import annotations

import json
from pathlib import Path


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


def _entry_has_command(entry: dict, needle: str) -> bool:
    """Check if a hook entry contains a command matching the needle.

    System boundary: reads Claude Code settings.json which may contain
    either format depending on when the user last ran forge extension sync.
    - Current: {"hooks": [{"type": "command", "command": "..."}]}
    - Pre-sync: {"type": "command", "command": "..."}
    """
    # Pre-sync format: command at entry top level
    cmd = entry.get("command")
    if isinstance(cmd, str) and needle in cmd:
        return True
    # Current format: nested hooks array
    for hook in entry.get("hooks", []):
        if not isinstance(hook, dict):
            continue
        cmd = hook.get("command", "")
        if isinstance(cmd, str) and needle in cmd:
            return True
    return False


def has_forge_hook(worktree_path: Path, hook_type: str, command_needle: str = "forge hook") -> bool:
    """Check if a specific Forge hook type is installed in any settings scope.

    Scans local, project, and user settings files for a hook entry whose
    command contains *command_needle*. The default needle ``"forge hook"``
    matches any Forge hook; pass a more specific string like
    ``"forge hook policy-check"`` to require a particular handler.

    Args:
        worktree_path: Project/worktree root to resolve local/project settings.
        hook_type: Claude Code hook event name (e.g., "SessionStart", "PreToolUse", "Stop").
        command_needle: Substring to look for in the command string.
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
                if _entry_has_command(entry, command_needle):
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

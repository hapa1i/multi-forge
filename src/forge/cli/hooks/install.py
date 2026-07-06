"""Hook enable/disable for Claude Code settings."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import click

from forge.cli.output import err_console, print_error_with_tip, print_tip
from forge.install.hooks import entry_is_forge_hook
from forge.install.preset import get_builtin_preset
from forge.session.claude.paths import get_claude_home

SETTINGS_FILENAME = "settings.local.json"

# Single source of truth: derive from the canonical preset
FORGE_HOOK_CONFIG: dict[str, Any] = {"hooks": get_builtin_preset()["hooks"]}


def _find_hooks_target(scope: str | None) -> tuple[Path, str]:
    """Find target settings file for hooks based on scope.

    Args:
        scope: "user", "local", or None (auto-detect)

    Returns:
        Tuple of (settings_file_path, display_location)

    Raises:
        click.ClickException if no valid target found
    """
    if scope == "user":
        settings_dir = get_claude_home()
        return settings_dir / SETTINGS_FILENAME, "~/.claude"

    if scope == "local":
        settings_dir = Path.cwd() / ".claude"
        return settings_dir / SETTINGS_FILENAME, ".claude"

    current = Path.cwd().resolve()
    home = Path.home().resolve()

    while True:
        claude_dir = current / ".claude"
        if claude_dir.is_dir():
            if current == home:
                return claude_dir / SETTINGS_FILENAME, "~/.claude"
            # Use relpath to safely compute display path (works when .claude is above cwd)
            display_path = os.path.relpath(claude_dir, Path.cwd())
            return claude_dir / SETTINGS_FILENAME, display_path

        if current == home:
            # At home without finding .claude = use user scope
            return (get_claude_home() / SETTINGS_FILENAME), "~/.claude"

        parent = current.parent
        if parent == current:
            raise click.ClickException(
                "No .claude directory found. " "Run from a Claude Code project, or use --user for global install."
            )
        current = parent


@click.command(name="enable")
@click.option(
    "--user",
    "-U",
    "scope",
    flag_value="user",
    help="Enable for ~/.claude/settings.local.json",
)
@click.option(
    "--local",
    "-L",
    "scope",
    flag_value="local",
    help="Enable for .claude/settings.local.json (current directory)",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Overwrite existing hook configuration",
)
def enable(scope: str | None, force: bool) -> None:
    """Enable Forge hooks in Claude Code settings.

    Adds all Forge hook configurations to settings.local.json.

    \b
    Scope Detection (when no --user/--local specified):
        Walks up from current directory looking for a .claude/ directory.
        - If found: enables in that project's .claude/settings.local.json
        - If reached ~: enables in ~/.claude/settings.local.json
    """
    from forge.install.version import check_minimum_version

    version_check = check_minimum_version()
    if not version_check.ok:
        print_error_with_tip(
            version_check.reason,
            "Run 'claude update' to upgrade.",
            console=err_console,
        )
        raise SystemExit(1)

    settings_file, location = _find_hooks_target(scope)
    if scope is None:
        click.echo(f"Auto-detected: {location}")

    settings: dict[str, Any] = {}
    if settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            click.echo(f"Error: Invalid JSON in {settings_file}: {e}", err=True)
            raise SystemExit(1)

    existing_hooks = settings.get("hooks", {})
    if any(key in existing_hooks for key in FORGE_HOOK_CONFIG["hooks"].keys()) and not force:
        click.echo(f"Forge hooks already configured in {settings_file}")
        print_tip("Use --force to overwrite", blank_before=False)
        raise SystemExit(1)

    if "hooks" not in settings:
        settings["hooks"] = {}

    for key, value in FORGE_HOOK_CONFIG["hooks"].items():
        settings["hooks"][key] = value

    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    click.echo(f"Enabled Forge hooks in {location}/{SETTINGS_FILENAME}")


def _is_forge_hook_entry(entry: Any) -> bool:
    """Check if a hook entry is a Forge hook.

    Matches entries where:
    - type == "command" AND command invokes "forge hook"
    - OR nested hooks contain such an entry
    """
    return entry_is_forge_hook(entry, require_command_type=True)


@click.command(name="disable")
@click.option(
    "--user",
    "-U",
    "scope",
    flag_value="user",
    help="Disable from ~/.claude/settings.local.json",
)
@click.option(
    "--local",
    "-L",
    "scope",
    flag_value="local",
    help="Disable from .claude/settings.local.json (current directory)",
)
def disable(scope: str | None) -> None:
    """Disable Forge hooks in Claude Code settings.

    Removes all Forge hook configuration entries from settings.local.json.

    \b
    Scope Detection (when no --user/--local specified):
        Walks up from current directory looking for a .claude/ directory.
        - If found: disables in that project's .claude/settings.local.json
        - If reached ~: disables in ~/.claude/settings.local.json
    """
    settings_file, location = _find_hooks_target(scope)
    if scope is None:
        click.echo(f"Auto-detected: {location}")

    if not settings_file.exists():
        click.echo(f"No settings file found at {settings_file}")
        return

    try:
        settings = json.loads(settings_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        click.echo(f"Error: Invalid JSON in {settings_file}: {e}", err=True)
        raise SystemExit(1)

    hooks_config = settings.get("hooks", {})
    if not hooks_config:
        click.echo("No hooks configured")
        return

    removed_any = False
    for hook_name in list(hooks_config.keys()):
        existing = hooks_config.get(hook_name, [])
        if not isinstance(existing, list):
            continue

        remaining = [e for e in existing if not _is_forge_hook_entry(e)]
        if len(remaining) != len(existing):
            removed_any = True

        if remaining:
            settings["hooks"][hook_name] = remaining
        else:
            del settings["hooks"][hook_name]

    if not removed_any:
        click.echo("No Forge hooks found to disable")
        return

    if not settings.get("hooks"):
        settings.pop("hooks", None)

    settings_file.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    click.echo(f"Disabled Forge hooks in {location}/{SETTINGS_FILENAME}")

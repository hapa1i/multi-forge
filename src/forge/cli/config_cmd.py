"""CLI commands for Forge runtime configuration.

Manages ~/.forge/config.yaml — global runtime preferences that affect
CLI and session behavior (not proxy routing).

Patterns:
- show: matches forge proxy show (syntax-highlighted YAML)
- set: matches forge proxy set (type coercion, atomic write)
- edit: matches forge proxy edit ($EDITOR + validation)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import fields
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.syntax import Syntax

from forge.core.paths import display_path
from forge.runtime_config import (
    RuntimeConfig,
    ensure_config,
    get_config_path,
    load_runtime_config,
    reset_runtime_config,
    write_runtime_config,
)


@click.group(invoke_without_command=True, subcommand_metavar="[COMMAND] [ARGS]...")
@click.pass_context
def config(ctx: click.Context) -> None:
    """Manage Forge global configuration.

    \b
    Configuration file: ~/.forge/config.yaml
    Auto-created with documented defaults by `forge config show`.

    \b
    Examples:
        forge config show                 # Show effective config
        forge config set proxy_mode=sidecar
        forge config edit                 # Open in $EDITOR
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@config.command("show")
@click.option("--raw", is_flag=True, help="Output raw YAML without syntax highlighting")
def show_cmd(raw: bool = False) -> None:
    """Show effective runtime configuration.

    Displays current values (from file + defaults + env var overrides).
    """
    console = Console(width=200)
    config_path = ensure_config()

    rc = load_runtime_config()
    env_sources: dict[str, str] = getattr(rc, "_env_sources", {})

    import yaml

    effective: dict[str, Any] = {}
    for f in fields(RuntimeConfig):
        effective[f.name] = getattr(rc, f.name)

    content = yaml.dump(effective, default_flow_style=False, sort_keys=False)

    if raw:
        console.print(content, end="")
    else:
        console.print("[bold]Forge Runtime Config[/bold]")
        console.print(f"[bold]Path:[/bold] {display_path(config_path)}")
        if env_sources:
            overrides = ", ".join(f"{v}={k}" for k, v in env_sources.items())
            console.print(f"[bold]Env overrides:[/bold] {overrides}")
        console.print()
        syntax = Syntax(content, "yaml", theme="monokai")
        console.print(syntax)


@config.command("set")
@click.argument("key_value")
def set_cmd(key_value: str) -> None:
    """Set a configuration value.

    \b
    Examples:
        forge config set proxy_mode=sidecar
        forge config set status_timeout=0.5
        forge config set context_limit=1000000
    """
    console = Console(width=200)

    if "=" not in key_value:
        console.print(f"[red]Error:[/red] Expected format: key=value (got: {key_value})")
        sys.exit(1)

    key, value = key_value.split("=", 1)

    known_fields = {f.name: f for f in fields(RuntimeConfig)}
    if key not in known_fields:
        console.print(f"[red]Error:[/red] Unknown config key: '{key}'")
        console.print(f"\n[dim]Available keys: {', '.join(sorted(known_fields))}[/dim]")
        sys.exit(1)

    coerced_value: Any = _coerce_value(key, value, known_fields[key])
    if coerced_value is _COERCE_ERROR:
        console.print(f"[red]Error:[/red] Invalid value for '{key}': {value}")
        sys.exit(1)

    config_path = get_config_path()
    if config_path.is_file():
        from ruamel.yaml import YAML

        ruamel = YAML()
        ruamel.preserve_quotes = True
        with open(config_path) as f:
            data = ruamel.load(f) or {}
    else:
        data = {}

    data[key] = coerced_value

    try:
        RuntimeConfig(**{k: v for k, v in dict(data).items() if k in known_fields})
    except (ValueError, TypeError) as e:
        console.print(f"[red]Error:[/red] Invalid configuration: {e}")
        sys.exit(1)

    write_runtime_config(data)
    console.print(f"[green]Set[/green] {key}={coerced_value}")


@config.command("edit")
def edit_cmd() -> None:
    """Open runtime configuration in $EDITOR.

    Creates the file with defaults if it doesn't exist.
    Validates changes before applying.
    """
    console = Console(width=200)

    config_path = ensure_config()
    editor = os.environ.get("EDITOR", "vim")

    if not shutil.which(editor):
        console.print(f"[red]Error:[/red] Editor '{editor}' not found. Set $EDITOR to an available editor.")
        sys.exit(1)

    # Copy to temp file for safe editing
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        tmp.write(config_path.read_text())
        tmp_path = Path(tmp.name)

    success = False
    try:
        result = subprocess.run([editor, str(tmp_path)])
        if result.returncode != 0:
            console.print(f"[red]Error:[/red] Editor exited with code {result.returncode}")
            console.print(f"Your changes are saved at: {display_path(tmp_path)}")
            sys.exit(1)

        # Validate edited YAML (use ruamel for consistency with write path)
        from ruamel.yaml import YAML

        ruamel = YAML()
        try:
            with open(tmp_path) as f:
                edited_data = ruamel.load(f)
        except Exception as e:
            console.print(f"[red]Error:[/red] Invalid YAML: {e}")
            console.print(f"Your changes are saved at: {display_path(tmp_path)}")
            sys.exit(1)

        if edited_data is None:
            edited_data = {}

        if not isinstance(edited_data, dict):
            console.print("[red]Error:[/red] Config must be a YAML mapping")
            console.print(f"Your changes are saved at: {display_path(tmp_path)}")
            sys.exit(1)

        known_fields = {f.name for f in fields(RuntimeConfig)}
        try:
            RuntimeConfig(**{k: v for k, v in dict(edited_data).items() if k in known_fields})
        except (ValueError, TypeError) as e:
            console.print(f"[red]Error:[/red] Invalid configuration: {e}")
            console.print(f"Your changes are saved at: {display_path(tmp_path)}")
            sys.exit(1)

        write_runtime_config(dict(edited_data))
        success = True
        console.print("[green]Updated[/green] runtime configuration")

    finally:
        if success and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


@config.command("reset")
@click.argument("key", required=False)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.option("--force", "-f", is_flag=True, hidden=True, help="Deprecated alias for --yes")
def reset_cmd(key: str | None = None, yes: bool = False, force: bool = False) -> None:
    """Reset configuration to defaults.

    With KEY: removes that key (reverts to built-in default).
    Without KEY: deletes the entire config file.
    """
    yes = yes or force
    console = Console(width=200)
    config_path = get_config_path()

    if not config_path.is_file():
        console.print("[dim]No config file to reset (already using defaults).[/dim]")
        return

    if key is None:
        if not yes:
            if not click.confirm("Reset all configuration to defaults?"):
                console.print("[dim]Cancelled.[/dim]")
                return
        config_path.unlink()
        reset_runtime_config()
        console.print("[green]Reset[/green] all configuration to defaults")
        console.print(f"[dim]Removed {display_path(config_path)}[/dim]")
        return

    known_fields = {f.name for f in fields(RuntimeConfig)}
    if key not in known_fields:
        console.print(f"[red]Error:[/red] Unknown config key: '{key}'")
        console.print(f"\n[dim]Available keys: {', '.join(sorted(known_fields))}[/dim]")
        sys.exit(1)

    from ruamel.yaml import YAML

    ruamel = YAML()
    ruamel.preserve_quotes = True
    with open(config_path) as f:
        data = ruamel.load(f) or {}

    if key not in data:
        console.print(f"[dim]Key '{key}' not in config (already using default).[/dim]")
        return

    del data[key]

    if data:
        write_runtime_config(dict(data))
    else:
        config_path.unlink()
        reset_runtime_config()

    default_val = getattr(RuntimeConfig(), key)
    console.print(f"[green]Reset[/green] {key} (default: {default_val})")


# --- Helpers ---

_COERCE_ERROR = object()


def _coerce_value(key: str, value: str, field_info: Any) -> Any:
    """Coerce string CLI value to the field's expected Python type."""
    field_type = field_info.type

    # Compare actual types (not string representations)
    # With `from __future__ import annotations`, field.type is a string,
    # so we need to resolve it
    if field_type is int or field_type == "int":
        try:
            return int(value)
        except ValueError:
            return _COERCE_ERROR

    if field_type is float or field_type == "float":
        try:
            return float(value)
        except ValueError:
            return _COERCE_ERROR

    if field_type is bool or field_type == "bool":
        if value.lower() in ("true", "1", "yes", "on"):
            return True
        if value.lower() in ("false", "0", "no", "off"):
            return False
        return _COERCE_ERROR

    # String fields: pass through
    return value

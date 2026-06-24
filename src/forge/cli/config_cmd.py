"""CLI commands for Forge runtime configuration.

Manages ~/.forge/config.yaml — global runtime preferences that affect
CLI and session behavior (not proxy routing).

`forge config` is an editable-config object: it implements the core verb
vocabulary {show, edit, reset} plus the optional `set`, per the
"Editable config objects share a verb vocabulary" rule in
docs/developer/cli_style_guidelines.md. It is not modeled on `forge proxy`,
which is a partial-lifecycle exception with no `reset`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import MutableMapping
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.syntax import Syntax

from forge.cli.output import print_error
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
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def show_cmd(raw: bool = False, as_json: bool = False) -> None:
    """Show effective runtime configuration.

    Displays current values (from file + defaults + env var overrides).
    """
    console = Console(width=200)
    config_path = ensure_config()

    rc = load_runtime_config()
    env_sources: dict[str, str] = getattr(rc, "_env_sources", {})

    effective: dict[str, Any] = {}
    for f in fields(RuntimeConfig):
        val = getattr(rc, f.name)
        # Nested config (e.g. statusline) must render as a plain mapping — yaml
        # can't dump a dataclass instance.
        if is_dataclass(val) and not isinstance(val, type):
            val = asdict(val)
        effective[f.name] = val

    if as_json:
        import json

        click.echo(
            json.dumps(
                {"path": str(config_path), "env_sources": env_sources, "config": effective},
                indent=2,
                default=str,
            )
        )
        return

    import yaml

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
        print_error(f"Expected format: key=value (got: {key_value})", console=console)
        sys.exit(1)

    key, value = key_value.split("=", 1)

    # Nested section keys (e.g. statusline.cost_mode) take the dotted path.
    if "." in key:
        _set_nested_key(key, value, console)
        return

    known_fields = {f.name: f for f in fields(RuntimeConfig)}
    if key not in known_fields:
        print_error(f"Unknown config key: '{key}'", console=console)
        console.print(f"\n[dim]Available keys: {', '.join(sorted(known_fields))}[/dim]")
        sys.exit(1)

    coerced_value: Any = _coerce_value(value, known_fields[key])
    if coerced_value is _COERCE_ERROR:
        print_error(f"Invalid value for '{key}': {value}", console=console)
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
        print_error(f"Invalid configuration: {e}", console=console)
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
        print_error(f"Editor '{editor}' not found. Set $EDITOR to an available editor.", console=console)
        sys.exit(1)

    # Copy to temp file for safe editing
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        tmp.write(config_path.read_text())
        tmp_path = Path(tmp.name)

    success = False
    try:
        result = subprocess.run([editor, str(tmp_path)])
        if result.returncode != 0:
            print_error(f"Editor exited with code {result.returncode}", console=console)
            console.print(f"Your changes are saved at: {display_path(tmp_path)}")
            sys.exit(1)

        # Validate edited YAML (use ruamel for consistency with write path)
        from ruamel.yaml import YAML

        ruamel = YAML()
        try:
            with open(tmp_path) as f:
                edited_data = ruamel.load(f)
        except Exception as e:
            print_error(f"Invalid YAML: {e}", console=console)
            console.print(f"Your changes are saved at: {display_path(tmp_path)}")
            sys.exit(1)

        if edited_data is None:
            edited_data = {}

        if not isinstance(edited_data, dict):
            print_error("Config must be a YAML mapping", console=console)
            console.print(f"Your changes are saved at: {display_path(tmp_path)}")
            sys.exit(1)

        known_fields = {f.name for f in fields(RuntimeConfig)}
        try:
            RuntimeConfig(**{k: v for k, v in dict(edited_data).items() if k in known_fields})
        except (ValueError, TypeError) as e:
            print_error(f"Invalid configuration: {e}", console=console)
            console.print(f"Your changes are saved at: {display_path(tmp_path)}")
            sys.exit(1)

        # RuntimeConfig construction silently DROPS unknown nested subkeys (loader forward-compat,
        # see _coerce_*_config), so a typo like provider_trace.inject_provider_usre would pass the
        # validation above and then persist while the toggle stays off. The edit path is a write
        # surface, so reject unknown nested subkeys here -- parity with `forge config set` (fail-closed).
        for section_name, section_cls in _nested_sections().items():
            section_block = edited_data.get(section_name)
            if not isinstance(section_block, dict):
                continue
            known_sub = {f.name for f in fields(section_cls)}
            unknown_sub = [k for k in section_block if k not in known_sub]
            if unknown_sub:
                print_error(f"Unknown {section_name} key(s): {', '.join(map(str, unknown_sub))}", console=console)
                console.print(f"[dim]Available: {', '.join(sorted(known_sub))}[/dim]")
                console.print(f"Your changes are saved at: {display_path(tmp_path)}")
                sys.exit(1)

        # Segment names aren't validated by StatusLineConfig (the renderer and
        # the set/edit CLI own that), so the edit path must enforce the allowlist
        # too — otherwise statusline.segments: [path, bogus] would be accepted.
        sl_section = edited_data.get("statusline")
        if isinstance(sl_section, dict) and isinstance(sl_section.get("segments"), list):
            unknown_segs = _unknown_segments(sl_section["segments"])
            if unknown_segs:
                from forge.cli.statusline.names import SEGMENT_NAMES

                print_error(f"Unknown statusline segment(s): {', '.join(map(str, unknown_segs))}", console=console)
                console.print(f"[dim]Valid segments: {', '.join(SEGMENT_NAMES)}[/dim]")
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
def reset_cmd(key: str | None = None, yes: bool = False) -> None:
    """Reset configuration to defaults.

    With KEY: removes that key (reverts to built-in default).
    Without KEY: deletes the entire config file.
    """
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
        print_error(f"Unknown config key: '{key}'", console=console)
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
    _persist_or_clear(data, config_path)

    default_val = getattr(RuntimeConfig(), key)
    console.print(f"[green]Reset[/green] {key} (default: {default_val})")


# --- Helpers ---


def _persist_or_clear(data: MutableMapping[str, Any], config_path: Path) -> None:
    """Write ``data`` back, or remove the config file when nothing remains."""
    if data:
        write_runtime_config(dict(data))
    else:
        config_path.unlink()
        reset_runtime_config()


_COERCE_ERROR = object()


def _coerce_value(value: str, field_info: Any) -> Any:
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


def _unknown_segments(segments: list[Any]) -> list[Any]:
    """Return segment names not in the allowlist (the set/edit strict gate).

    Segment names are intentionally NOT validated by ``StatusLineConfig`` (the
    renderer drops unknown names on load); the write paths reject them instead.
    """
    from forge.cli.statusline.names import SEGMENT_NAMES

    return [s for s in segments if s not in SEGMENT_NAMES]


def _nested_sections() -> dict[str, type]:
    """Map nested config section name -> its dataclass (the dotted-key registry).

    Add a section here to make ``forge config set <section>.<subkey>`` work.
    """
    from forge.runtime_config import RuntimeProviderTraceConfig, StatusLineConfig

    return {
        "statusline": StatusLineConfig,
        "provider_trace": RuntimeProviderTraceConfig,
    }


def _set_nested_key(key: str, value: str, console: Console) -> None:
    """Set a dotted nested config key (e.g. ``statusline.cost_mode``,
    ``provider_trace.inject_provider_user``).

    Strict (fail-closed): unknown section/subkey, invalid values, and unknown
    statusline segment names all error and exit non-zero, naming valid options.
    """
    from forge.cli.statusline.names import SEGMENT_NAMES

    sections = _nested_sections()
    section, _, subkey = key.partition(".")
    section_cls = sections.get(section)
    if section_cls is None:
        print_error(f"Unknown config section: '{section}'", console=console)
        console.print(f"\n[dim]Nested sections: {', '.join(sorted(sections))}[/dim]")
        sys.exit(1)

    sec_fields = {f.name: f for f in fields(section_cls)}
    if subkey not in sec_fields:
        print_error(f"Unknown {section} key: '{subkey}'", console=console)
        console.print(f"\n[dim]Available: {', '.join(sorted(sec_fields))}[/dim]")
        sys.exit(1)

    coerced_sub: Any
    # statusline.segments is the one list field needing allowlist validation.
    if section == "statusline" and subkey == "segments":
        coerced_sub = [s.strip() for s in value.split(",") if s.strip()]
        unknown = _unknown_segments(coerced_sub)
        if unknown:
            print_error(f"Unknown segment(s): {', '.join(unknown)}", console=console)
            console.print(f"\n[dim]Valid segments: {', '.join(SEGMENT_NAMES)}[/dim]")
            sys.exit(1)
    else:
        coerced_sub = _coerce_value(value, sec_fields[subkey])
        if coerced_sub is _COERCE_ERROR:
            print_error(f"Invalid value for '{section}.{subkey}': {value}", console=console)
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

    section_data = data.get(section)
    if not isinstance(section_data, dict):
        section_data = {}
    section_data[subkey] = coerced_sub
    data[section] = section_data

    # Validate via construction — the nested dataclass __post_init__ rejects bad
    # values (fail-closed); statusline segment names were already checked above.
    known_fields = {f.name for f in fields(RuntimeConfig)}
    try:
        RuntimeConfig(**{k: v for k, v in dict(data).items() if k in known_fields})
    except (ValueError, TypeError) as e:
        print_error(f"Invalid configuration: {e}", console=console)
        sys.exit(1)

    write_runtime_config(data)
    console.print(f"[green]Set[/green] {key}={coerced_sub}")

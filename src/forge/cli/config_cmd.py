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

from forge.cli.editor import resolve_editor_argv
from forge.cli.output import err_console, print_error, print_tip
from forge.core.paths import display_path
from forge.runtime_config import (
    RuntimeConfig,
    ensure_config,
    get_config_path,
    load_runtime_config,
    render_runtime_config_yaml,
    reset_runtime_config,
    write_runtime_config,
)


@click.group(no_args_is_help=True, subcommand_metavar="[COMMAND] [ARGS]...")
def config() -> None:
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


@config.command("show")
@click.option("--raw", is_flag=True, help="Output raw YAML without syntax highlighting")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def show_cmd(raw: bool = False, as_json: bool = False) -> None:
    """Show effective runtime configuration.

    Displays current values (from file + defaults + env var overrides).
    With --json, emits {path, env_sources, config, downstream_retention}.
    """
    console = Console(width=200)
    config_path = ensure_config()

    rc = load_runtime_config()
    env_sources: dict[str, str] = getattr(rc, "_env_sources", {})
    from forge.core.telemetry.downstream_retention import resolve_downstream_retention

    retention = resolve_downstream_retention(runtime_config_path=config_path)

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
                {
                    "path": str(config_path),
                    "env_sources": env_sources,
                    "config": effective,
                    "downstream_retention": retention.to_dict(),
                },
                indent=2,
                default=str,
            )
        )
        return

    content = render_runtime_config_yaml(effective)

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
        _print_downstream_retention_status(console, retention)


@config.command("set")
@click.argument("key_value")
def set_cmd(key_value: str) -> None:
    """Set a configuration value.

    \b
    Examples:
        forge config set proxy_mode=sidecar
        forge config set status_timeout=0.5
        forge config set context_limit=1000000
        forge config set skills.invocation.review=model
        forge config set statusline.cost_mode=actual
        forge config set provider_trace.inject_provider_user=true
        forge config set telemetry.downstream.retention_days=30
    """
    console = Console(width=200)

    if "=" not in key_value:
        print_error(f"Expected format: key=value (got: {key_value})")
        sys.exit(1)

    key, value = key_value.split("=", 1)

    # Nested section keys (e.g. statusline.cost_mode) take the dotted path.
    if "." in key:
        _set_nested_key(key, value, console)
        return

    known_fields = {f.name: f for f in fields(RuntimeConfig)}
    if key not in known_fields:
        print_error(f"Unknown config key: '{key}'")
        err_console.print(f"\n[dim]Available keys: {', '.join(sorted(known_fields))}[/dim]")
        sys.exit(1)

    coerced_value: Any = _coerce_value(value, known_fields[key])
    if coerced_value is _COERCE_ERROR:
        print_error(f"Invalid value for '{key}': {value}")
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
        print_error(f"Invalid configuration: {e}")
        sys.exit(1)

    write_runtime_config(data)
    console.print(f"[green]Set[/green] {key}={coerced_value}")


@config.command("migrate-retention")
@click.option("--yes", "apply_changes", is_flag=True, help="Apply the previewed migration")
@click.option("--json", "as_json", is_flag=True, help="Output one JSON result")
def migrate_retention_cmd(apply_changes: bool = False, as_json: bool = False) -> None:
    """Move proxy-local downstream retention keys to the global owner.

    Preview is the default. With --yes, Forge writes the global policy before
    removing matching legacy keys from user-owned proxy files, so a partial
    failure remains coherent and the same command can be rerun safely.
    """
    import json

    from forge.core.telemetry.downstream_retention import (
        DownstreamRetentionMigrationError,
        apply_downstream_retention_migration,
        plan_downstream_retention_migration,
    )

    console = Console(width=200)
    plan = plan_downstream_retention_migration()
    payload: dict[str, Any] = {"applied": False, "plan": plan.to_dict(), "result": None}

    if plan.blocked:
        if as_json:
            payload["error"] = "Retention migration is blocked by conflicting or unreadable configuration"
            click.echo(json.dumps(payload, indent=2), err=True)
        else:
            _print_downstream_retention_status(err_console, plan.resolution)
            if plan.resolution.pruning_enabled:
                print_error("Retention migration is blocked; the effective global policy remains active.")
            else:
                print_error("Retention migration is blocked; automatic pruning remains disabled.")
            if plan.resolution.errors:
                recovery = "Repair each named configuration input, then rerun this command:"
                commands = []
                if any(error.scope == "global" for error in plan.resolution.errors):
                    commands.append("forge config edit")
                commands.extend(
                    f"forge proxy edit {proxy_id}"
                    for proxy_id in sorted(
                        {
                            error.proxy_id
                            for error in plan.resolution.errors
                            if error.scope == "proxy" and error.proxy_id is not None
                        }
                    )
                )
                commands.append("forge config migrate-retention --yes")
            else:
                recovery = "Choose the global policy explicitly, then rerun this command:"
                commands = [
                    "forge config set telemetry.downstream.retention_days=<days>",
                    "forge config set telemetry.downstream.max_total_mb=<mb>",
                    "forge config migrate-retention --yes",
                ]
            print_tip(
                recovery,
                commands=commands,
                console=err_console,
            )
        sys.exit(1)

    if not apply_changes:
        if as_json:
            click.echo(json.dumps(payload, indent=2))
        else:
            console.print("[bold]Downstream retention migration preview[/bold]")
            _print_downstream_retention_status(console, plan.resolution)
            if not plan.has_changes:
                console.print("[dim]No legacy retention keys require migration.[/dim]")
            else:
                if plan.write_global_policy:
                    console.print(f"[cyan]Write[/cyan] global policy to {display_path(plan.runtime_config_path)}")
                for target in plan.targets:
                    keys = ", ".join(item.key for item in target.keys)
                    console.print(f"[cyan]Update[/cyan] {target.proxy_id}: remove {keys}")
                print_tip(
                    "Review the plan, then apply it.",
                    commands=["forge config migrate-retention --yes"],
                    console=console,
                )
        return

    try:
        result = apply_downstream_retention_migration()
    except (DownstreamRetentionMigrationError, OSError) as exc:
        if as_json:
            payload["error"] = str(exc)
            click.echo(json.dumps(payload, indent=2), err=True)
        else:
            print_error(f"Retention migration failed: {exc}")
            print_tip(
                "Fix the named file and rerun 'forge config migrate-retention --yes'.",
                console=err_console,
            )
        sys.exit(1)

    payload["applied"] = True
    payload["result"] = {
        "wrote_global_policy": result.wrote_global_policy,
        "migrated_proxy_ids": list(result.migrated_proxy_ids),
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2))
    else:
        console.print("[green]Downstream retention migration complete[/green]")
        if result.wrote_global_policy:
            console.print(f"  Global policy: {display_path(get_config_path())}")
        if result.migrated_proxy_ids:
            console.print(f"  Updated proxies: {', '.join(result.migrated_proxy_ids)}")
        else:
            console.print("  No proxy files required changes")
        print_tip(
            "Restart running proxies so they use the global retention policy.",
            blank_before=False,
            console=console,
        )


@config.command("edit")
def edit_cmd() -> None:
    """Open runtime configuration in $EDITOR.

    Creates the file with defaults if it doesn't exist.
    Validates changes before applying.
    """
    console = Console(width=200)

    config_path = ensure_config()
    original_skill_invocation = dict(load_runtime_config(config_path).skills.invocation)
    editor_argv = resolve_editor_argv()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        tmp.write(config_path.read_text())
        tmp_path = Path(tmp.name)

    success = False
    try:
        result = subprocess.run([*editor_argv, str(tmp_path)])
        if result.returncode != 0:
            print_error(f"Editor exited with code {result.returncode}")
            err_console.print(f"Your changes are saved at: {display_path(tmp_path)}")
            sys.exit(1)

        # Validate edited YAML (use ruamel for consistency with write path)
        from ruamel.yaml import YAML

        ruamel = YAML()
        try:
            with open(tmp_path) as f:
                edited_data = ruamel.load(f)
        except Exception as e:
            print_error(f"Invalid YAML: {e}")
            err_console.print(f"Your changes are saved at: {display_path(tmp_path)}")
            sys.exit(1)

        if edited_data is None:
            edited_data = {}

        if not isinstance(edited_data, dict):
            print_error("Config must be a YAML mapping")
            err_console.print(f"Your changes are saved at: {display_path(tmp_path)}")
            sys.exit(1)

        known_fields = {f.name for f in fields(RuntimeConfig)}
        try:
            validated_config = RuntimeConfig(**{k: v for k, v in dict(edited_data).items() if k in known_fields})
        except (ValueError, TypeError) as e:
            print_error(f"Invalid configuration: {e}")
            err_console.print(f"Your changes are saved at: {display_path(tmp_path)}")
            sys.exit(1)

        # RuntimeConfig construction silently DROPS unknown nested subkeys (loader forward-compat,
        # see _coerce_*_config), so a typo like provider_trace.inject_provider_usre would pass the
        # validation above and then persist while the toggle stays off. The edit path is a write
        # surface, so reject unknown nested subkeys here -- parity with `forge config set` (fail-closed).
        for section_path, section_cls in _nested_sections().items():
            section_name = ".".join(section_path)
            section_block = _mapping_at_path(edited_data, section_path)
            if not isinstance(section_block, dict):
                continue
            known_sub = {f.name for f in fields(section_cls)}
            unknown_sub = [k for k in section_block if k not in known_sub]
            if unknown_sub:
                print_error(
                    f"Unknown {section_name} key(s): {', '.join(map(str, unknown_sub))}",
                )
                err_console.print(f"[dim]Available: {', '.join(sorted(known_sub))}[/dim]")
                err_console.print(f"Your changes are saved at: {display_path(tmp_path)}")
                sys.exit(1)

        # Segment names aren't validated by StatusLineConfig (the renderer and
        # the set/edit CLI own that), so the edit path must enforce the allowlist
        # too — otherwise statusline.segments: [path, bogus] would be accepted.
        sl_section = edited_data.get("statusline")
        if isinstance(sl_section, dict) and isinstance(sl_section.get("segments"), list):
            unknown_segs = _unknown_segments(sl_section["segments"])
            if unknown_segs:
                from forge.cli.statusline.names import SEGMENT_NAMES

                print_error(
                    f"Unknown statusline segment(s): {', '.join(map(str, unknown_segs))}",
                )
                err_console.print(f"[dim]Valid segments: {', '.join(SEGMENT_NAMES)}[/dim]")
                err_console.print(f"Your changes are saved at: {display_path(tmp_path)}")
                sys.exit(1)

        skills_section = edited_data.get("skills")
        if isinstance(skills_section, dict) and isinstance(skills_section.get("invocation"), dict):
            try:
                known_skills = _forge_skill_names()
            except (OSError, ValueError) as e:
                print_error(f"Unable to discover Forge skills: {e}")
                err_console.print(f"Your changes are saved at: {display_path(tmp_path)}")
                sys.exit(1)
            unknown_skills = [name for name in skills_section["invocation"] if name not in known_skills]
            if unknown_skills:
                print_error(f"Unknown Forge skill(s): {', '.join(unknown_skills)}")
                err_console.print(f"[dim]Available: {', '.join(known_skills)}[/dim]")
                err_console.print(f"Your changes are saved at: {display_path(tmp_path)}")
                sys.exit(1)

        write_runtime_config(dict(edited_data))
        success = True
        console.print("[green]Updated[/green] runtime configuration")
        if validated_config.skills.invocation != original_skill_invocation:
            _print_skill_invocation_sync_tip(console)

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

    original_skill_invocation = dict(load_runtime_config(config_path).skills.invocation)

    if key is None:
        if not yes:
            if not click.confirm("Reset all configuration to defaults?"):
                console.print("[dim]Cancelled.[/dim]")
                return
        config_path.unlink()
        reset_runtime_config()
        console.print("[green]Reset[/green] all configuration to defaults")
        console.print(f"[dim]Removed {display_path(config_path)}[/dim]")
        if original_skill_invocation:
            _print_skill_invocation_sync_tip(console)
        return

    known_fields = {f.name for f in fields(RuntimeConfig)}
    if key not in known_fields:
        print_error(f"Unknown config key: '{key}'")
        err_console.print(f"\n[dim]Available keys: {', '.join(sorted(known_fields))}[/dim]")
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
    updated_skill_invocation = dict(load_runtime_config(config_path).skills.invocation)
    if updated_skill_invocation != original_skill_invocation:
        _print_skill_invocation_sync_tip(console)


# --- Helpers ---


def _persist_or_clear(data: MutableMapping[str, Any], config_path: Path) -> None:
    """Write ``data`` back, or remove the config file when nothing remains."""
    if data:
        write_runtime_config(dict(data))
    else:
        config_path.unlink()
        reset_runtime_config()


def _print_skill_invocation_sync_tip(console: Console) -> None:
    """Tell users when installed runtime packages need recompilation."""
    print_tip(
        "Run 'forge extension sync' to apply the new invocation mode to installed packages.",
        blank_before=False,
        console=console,
    )


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


def _forge_skill_names() -> tuple[str, ...]:
    """Return bundled Forge skill names without parsing source contents."""

    from forge.install.installer import get_extensions_root
    from forge.install.skill_compiler import discover_skill_source_names

    return discover_skill_source_names(get_extensions_root() / "skills")


def _nested_sections() -> dict[tuple[str, ...], type]:
    """Map nested config paths to their dataclasses (the dotted-key registry).

    Add a path here to make ``forge config set <section>.<subkey>`` work.
    """
    from forge.runtime_config import (
        RuntimeDownstreamRetentionConfig,
        RuntimeProviderTraceConfig,
        RuntimeSkillsConfig,
        RuntimeTelemetryConfig,
        StatusLineConfig,
    )

    return {
        ("skills",): RuntimeSkillsConfig,
        ("statusline",): StatusLineConfig,
        ("provider_trace",): RuntimeProviderTraceConfig,
        ("telemetry",): RuntimeTelemetryConfig,
        ("telemetry", "downstream"): RuntimeDownstreamRetentionConfig,
    }


def _mapping_at_path(data: MutableMapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for part in path:
        if not isinstance(current, MutableMapping):
            return None
        current = current.get(part)
    return current


def _set_nested_key(key: str, value: str, console: Console) -> None:
    """Set a dotted nested config key (e.g. ``statusline.cost_mode``,
    ``provider_trace.inject_provider_user``).

    Strict (fail-closed): unknown section/subkey, invalid values, and unknown
    statusline segment names all error and exit non-zero, naming valid options.
    """
    from forge.cli.statusline.names import SEGMENT_NAMES

    sections = _nested_sections()
    parts = tuple(key.split("."))
    if parts[:2] == ("skills", "invocation"):
        _set_skill_invocation(parts, value, console)
        return
    section_path, subkey = parts[:-1], parts[-1]
    section_name = ".".join(section_path)
    section_cls = sections.get(section_path)
    if section_cls is None:
        print_error(f"Unknown config section: '{section_name}'")
        names = sorted(".".join(path) for path in sections)
        err_console.print(f"\n[dim]Nested sections: {', '.join(names)}[/dim]")
        sys.exit(1)

    sec_fields = {f.name: f for f in fields(section_cls)}
    if subkey not in sec_fields:
        print_error(f"Unknown {section_name} key: '{subkey}'")
        err_console.print(f"\n[dim]Available: {', '.join(sorted(sec_fields))}[/dim]")
        sys.exit(1)

    coerced_sub: Any
    # statusline.segments is the one list field needing allowlist validation.
    if section_path == ("statusline",) and subkey == "segments":
        coerced_sub = [s.strip() for s in value.split(",") if s.strip()]
        unknown = _unknown_segments(coerced_sub)
        if unknown:
            print_error(f"Unknown segment(s): {', '.join(unknown)}")
            err_console.print(f"\n[dim]Valid segments: {', '.join(SEGMENT_NAMES)}[/dim]")
            sys.exit(1)
    else:
        coerced_sub = _coerce_value(value, sec_fields[subkey])
        if coerced_sub is _COERCE_ERROR:
            print_error(f"Invalid value for '{section_name}.{subkey}': {value}")
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

    current = data
    for part in section_path:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[subkey] = coerced_sub

    # Validate via construction — the nested dataclass __post_init__ rejects bad
    # values (fail-closed); statusline segment names were already checked above.
    known_fields = {f.name for f in fields(RuntimeConfig)}
    try:
        RuntimeConfig(**{k: v for k, v in dict(data).items() if k in known_fields})
    except (ValueError, TypeError) as e:
        print_error(f"Invalid configuration: {e}")
        sys.exit(1)

    write_runtime_config(data)
    console.print(f"[green]Set[/green] {key}={coerced_sub}")


def _set_skill_invocation(parts: tuple[str, ...], value: str, console: Console) -> None:
    """Set ``skills.invocation.<skill>`` while preserving sibling overrides."""

    if len(parts) != 3 or not parts[2]:
        print_error("Expected format: skills.invocation.<skill>=explicit|model")
        sys.exit(1)

    skill_name = parts[2]
    try:
        known_skills = _forge_skill_names()
    except (OSError, ValueError) as e:
        print_error(f"Unable to discover Forge skills: {e}")
        sys.exit(1)
    if skill_name not in known_skills:
        print_error(f"Unknown Forge skill: '{skill_name}'")
        err_console.print(f"\n[dim]Available: {', '.join(known_skills)}[/dim]")
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

    skills = data.get("skills")
    if not isinstance(skills, dict):
        skills = {}
        data["skills"] = skills
    invocation = skills.get("invocation")
    if not isinstance(invocation, dict):
        invocation = {}
        skills["invocation"] = invocation
    invocation[skill_name] = value

    known_fields = {f.name for f in fields(RuntimeConfig)}
    try:
        RuntimeConfig(**{k: v for k, v in dict(data).items() if k in known_fields})
    except (ValueError, TypeError) as e:
        print_error(f"Invalid configuration: {e}")
        sys.exit(1)

    write_runtime_config(data)
    console.print(f"[green]Set[/green] skills.invocation.{skill_name}={value}")
    _print_skill_invocation_sync_tip(console)


def _print_downstream_retention_status(console: Console, resolution: Any) -> None:
    """Render the effective global owner and any compatibility/degraded facts."""
    console.print("\n[bold]Downstream retention[/bold]")
    console.print(f"[bold]Owner:[/bold] telemetry.downstream in {display_path(get_config_path())}")
    configured = resolution.configured
    if configured is None:
        console.print("[bold]Configured:[/bold] not set")
    else:
        days = configured.retention_days if configured.retention_days is not None else "default"
        size = configured.max_total_mb if configured.max_total_mb is not None else "default"
        console.print(f"[bold]Configured:[/bold] retention_days={days}, max_total_mb={size}")
    if resolution.effective is None:
        console.print("[bold]Effective:[/bold] [yellow]disabled (configuration requires recovery)[/yellow]")
    else:
        console.print(
            f"[bold]Effective:[/bold] retention_days={resolution.effective.retention_days}, "
            f"max_total_mb={resolution.effective.max_total_mb} ([cyan]{resolution.source}[/cyan])"
        )
    if resolution.deprecated_keys:
        console.print(f"[yellow]Deprecated proxy keys:[/yellow] {len(resolution.deprecated_keys)}")
        for item in resolution.deprecated_keys:
            console.print(f"  {item.proxy_id}: {item.key} -> {item.replacement}")
    for conflict in resolution.conflicts:
        values = "; ".join(f"{item.value} ({', '.join(item.proxy_ids)})" for item in conflict.values)
        console.print(f"[yellow]Conflict {conflict.field}:[/yellow] {values}")
    for error in resolution.errors:
        label = f"{error.proxy_id}: " if error.proxy_id else ""
        console.print(f"[yellow]Invalid input:[/yellow] {label}{error.detail} ({display_path(error.path)})")

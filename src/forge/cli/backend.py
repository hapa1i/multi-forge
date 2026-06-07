"""Backend management CLI commands.

Provides commands to manage backend services (LiteLLM, etc.) that proxies depend on:
- forge backend list: List all backends
- forge backend create: Create backend config
- forge backend start: Start a backend instance
- forge backend stop: Stop a backend instance
- forge backend delete: Delete backend config or instance
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from forge.backend import BackendManager
from forge.backend.adapters import get_adapter
from forge.backend.creation import create_backend_config, get_backend_config_path
from forge.backend.registry import BackendRegistryStore, is_pid_alive
from forge.cli.output import print_error_with_tip, print_tip
from forge.core.paths import display_path, get_forge_home


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def backend() -> None:
    """Manage backends (LiteLLM, etc.).

    \b
    Examples:
        forge backend list                     # List backends
        forge backend create litellm           # Create backend config
        forge backend start litellm -p 4000    # Start an instance
    """


@backend.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def list_cmd(as_json: bool) -> None:
    """List all backends."""
    console = Console(width=200)
    store = BackendRegistryStore()

    backends = store.read().backends

    if as_json:
        import json

        data = []
        for backend_id, b in backends.items():
            data.append(
                {
                    "backend_id": b.backend_id,
                    "adapter_type": b.adapter_type,
                    "port": b.port,
                    "pid": b.pid,
                    "status": b.status,
                }
            )
        click.echo(json.dumps(data, indent=2, default=str))
        return

    if not backends:
        console.print("No backends found.")
        print_tip("Run 'forge backend create litellm'.", console=console)
        return

    table = Table(title="Forge Backends")
    table.add_column("BACKEND ID", style="cyan")
    table.add_column("ADAPTER")
    table.add_column("PORT", justify="right")
    table.add_column("PID", justify="right")
    table.add_column("STATUS")

    for backend_id, backend in backends.items():
        table.add_row(
            backend_id,
            backend.adapter_type,
            str(backend.port),
            str(backend.pid) if backend.pid else "-",
            backend.status,
        )

    console.print(table)


@backend.command("show")
@click.argument("backend_id")
@click.option("--raw", is_flag=True, help="Output raw config without syntax highlighting")
def show_cmd(backend_id: str, raw: bool) -> None:
    """Show backend details and configuration.

    \b
    Examples:
        forge backend show litellm-4000
    """
    console = Console(width=200)
    store = BackendRegistryStore()

    # Parse adapter type from backend_id (e.g., "litellm-4000" -> "litellm")
    parts = backend_id.rsplit("-", 1)
    adapter_type = parts[0] if len(parts) == 2 else backend_id

    try:
        registry = store.read()
        instance = registry.backends.get(backend_id)
        if instance:
            alive = instance.pid is not None and is_pid_alive(instance.pid)
            status_color = "green" if alive else "yellow"
            console.print(f"[bold]Backend:[/bold] [cyan]{backend_id}[/cyan]")
            console.print(f"[bold]Adapter:[/bold] {instance.adapter_type}")
            console.print(f"[bold]Port:[/bold] {instance.port}")
            console.print(f"[bold]PID:[/bold] {instance.pid or '-'}")
            console.print(
                f"[bold]Status:[/bold] [{status_color}]{'healthy' if alive else 'not running'}[/{status_color}]"
            )
            if instance.created_at:
                console.print(f"[bold]Started:[/bold] {instance.created_at}")
        else:
            console.print(f"[bold]Backend:[/bold] [cyan]{backend_id}[/cyan] [dim](not in registry)[/dim]")
    except Exception:
        console.print(f"[bold]Backend:[/bold] [cyan]{backend_id}[/cyan]")

    log_file = get_forge_home() / "logs" / "backend" / f"{backend_id}.log"
    if log_file.exists():
        console.print(f"[bold]Log:[/bold] {display_path(log_file)}")
    else:
        log_file = (
            get_forge_home() / "logs" / "backend" / f"{adapter_type}-{parts[1] if len(parts) == 2 else '4000'}.log"
        )
        if log_file.exists():
            console.print(f"[bold]Log:[/bold] {display_path(log_file)}")

    config_path = get_backend_config_path(adapter_type)
    if config_path.exists():
        content = config_path.read_text()
        console.print(f"[bold]Config:[/bold] {display_path(config_path)}\n")
        if raw:
            console.print(content)
        else:
            from rich.syntax import Syntax

            syntax = Syntax(content, "yaml", theme="monokai", line_numbers=True)
            console.print(syntax)
    else:
        console.print(f"\n[dim]No config found for adapter '{adapter_type}'.[/dim]")
        print_tip(f"Run 'forge backend create {adapter_type}'.", blank_before=False, console=console)


@backend.command("create")
@click.argument("adapter", type=click.Choice(["litellm"]))
@click.option(
    "--config",
    "-c",
    type=Path,
    help="Source config file (defaults to installed template)",
)
def create_cmd(adapter: str, config: Path | None) -> None:
    """Create a backend config (copy to installed location).

    Config is shared by all instances of this adapter type.
    """
    console = Console(width=200)

    config_path = get_backend_config_path(adapter)
    if config_path.exists():
        print_error_with_tip(
            f"Backend config already exists: {display_path(config_path)}",
            "Start an instance with:",
            commands=[f"forge backend start {adapter} --port 4000"],
            console=console,
        )
        sys.exit(1)

    try:
        config_path = create_backend_config(
            adapter_type=adapter,
            source_config=config,
        )
        console.print(f"[green]Created[/green] backend config for '{adapter}'")
        console.print(f"  Config: {display_path(config_path)}")
        console.print("\n[dim]Start an instance with:[/dim]")
        console.print(f"  forge backend start {adapter} --port 4000")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@backend.command("start")
@click.argument("adapter", type=click.Choice(["litellm"]))
@click.option("--port", "-p", type=int, required=True, help="Port number")
def start_cmd(adapter: str, port: int) -> None:
    """Start a backend instance."""
    console = Console(width=200)

    config_path = get_backend_config_path(adapter)
    if not config_path.exists():
        print_error_with_tip(
            f"Backend config not found for '{adapter}'",
            "Create it first:",
            commands=[f"forge backend create {adapter}"],
            console=console,
        )
        sys.exit(1)

    backend_id = f"{adapter}-{port}"
    store = BackendRegistryStore()
    manager = BackendManager(store)
    manager.register_adapter(adapter, get_adapter(adapter))

    try:
        result = manager.ensure_backend(backend_id, adapter, port)
        if result.source == "start":
            console.print(f"[green]Started[/green] backend '{backend_id}' on port {port} (pid {result.instance.pid})")
        else:
            console.print(f"Backend '{backend_id}' already running on port {port}")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@backend.command("stop")
@click.argument("adapter", type=click.Choice(["litellm"]))
@click.option("--port", "-p", type=int, required=True, help="Port number")
def stop_cmd(adapter: str, port: int) -> None:
    """Stop a backend instance."""
    console = Console(width=200)
    backend_id = f"{adapter}-{port}"

    store = BackendRegistryStore()
    manager = BackendManager(store)
    manager.register_adapter(adapter, get_adapter(adapter))

    try:
        manager.stop_backend(backend_id)
        console.print(f"[green]Stopped[/green] backend '{backend_id}'")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@backend.command("delete")
@click.argument("adapter", type=click.Choice(["litellm"]))
@click.option(
    "--port",
    "-p",
    type=int,
    help="Delete specific instance (if not specified, deletes config)",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def delete_cmd(adapter: str, port: int | None, yes: bool) -> None:
    """Delete a backend instance or config.

    Without --port: Deletes the backend config (stops all instances first).
    With --port: Stops and unregisters specific instance (keeps config).
    """
    import shutil

    console = Console(width=200)

    if port is not None:
        backend_id = f"{adapter}-{port}"
        if not yes and not click.confirm(f"Stop backend instance '{backend_id}'?"):
            console.print("Cancelled.")
            return

        try:
            stop_cmd.callback(adapter, port)  # type: ignore[misc]  # click.Command.callback is Optional[Callable]; always set here
            console.print(f"[green]Stopped[/green] backend instance '{backend_id}'")
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
    else:
        backend_dir = get_forge_home() / "backends" / adapter
        if not backend_dir.exists():
            print_error_with_tip(
                f"Backend config not found for '{adapter}'",
                "Create it first:",
                commands=[f"forge backend create {adapter}"],
                console=console,
            )
            sys.exit(1)

        if not yes and not click.confirm(f"Delete backend config for '{adapter}' (stops all instances)?"):
            console.print("Cancelled.")
            return

        store = BackendRegistryStore()
        registry = store.read()
        stopped = []
        for backend_id in list(registry.backends.keys()):
            if backend_id.startswith(f"{adapter}-"):
                try:
                    # Use rsplit to handle adapter names with hyphens (e.g., "some-adapter-4000")
                    port_str = backend_id.rsplit("-", 1)[1]
                    stop_cmd.callback(adapter, int(port_str))  # type: ignore[misc]  # click.Command.callback is Optional[Callable]; always set here
                    stopped.append(backend_id)
                except Exception:
                    pass

        if stopped:
            console.print(f"Stopped instances: {', '.join(stopped)}")

        shutil.rmtree(backend_dir)
        console.print(f"[green]Deleted[/green] backend config for '{adapter}'")

"""Backend management CLI commands.

Provides commands to manage backend services (LiteLLM, etc.) that proxies depend on:
- forge model backend list: List all backends
- forge model backend create: Create backend config
- forge model backend start: Start a managed local process
- forge model backend stop: Stop a managed local process
- forge model backend delete: Delete backend config
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, NoReturn

import click
import yaml
from rich.console import Console
from rich.table import Table

from forge.backend import (
    BackendInstanceAmbiguousError,
    BackendInstanceNotFoundError,
    BackendManager,
    ModelSource,
    ModelSourceNotFoundError,
    resolve_backend_instance,
)
from forge.backend.adapters import get_adapter
from forge.backend.creation import create_backend_config, get_backend_config_path
from forge.backend.registry import (
    BackendRegistryStore,
    ManagedBackendProcess,
    is_pid_alive,
)
from forge.backend.remote.base import RemoteAdapterError
from forge.backend.sources import (
    get_model_source,
    list_model_sources,
    resolve_model_source_id,
)
from forge.cli.output import err_console, print_error, print_error_with_tip, print_tip
from forge.core.auth.template_secrets import resolve_env_or_credential_with_source
from forge.core.credential_registry import EnvVar
from forge.core.ops import (
    ExecutionContext,
    ForgeOpError,
    reconcile_generation,
    render_reconcile_lines,
)
from forge.core.paths import display_path, get_forge_home

_SUPPORTED_ADAPTERS = frozenset({"litellm"})
_ENV_REF_RE = re.compile(r"^os\.environ/([A-Z][A-Z0-9_]*)$")
_BACKEND_COMMAND = "forge model backend"


@dataclass(frozen=True)
class _ProbeResult:
    status: str
    detail: str
    http_status: int | None = None


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def backend() -> None:
    """Manage model backends, local configs, and managed local processes.

    \b
    Identifiers:
        Backend: openrouter (configured inference target shown by list)
        Managed process: litellm-4000 (local process shown by list)
        Adapter: litellm (local config type)

    \b
    Examples:
        forge model backend list
        forge model backend show openrouter
        forge model backend test-auth openrouter
        forge model backend start litellm -p 4000
        forge model backend stop litellm-4000
    """


def _source_for_identifier(identifier: str) -> ModelSource | None:
    try:
        return get_model_source(resolve_model_source_id(identifier))
    except ModelSourceNotFoundError:
        return None


def _source_for_backend_identifier(identifier: str) -> ModelSource | None:
    try:
        return resolve_backend_instance(identifier).source
    except BackendInstanceNotFoundError:
        return None


def _iter_config_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(_iter_config_strings(item))
        return strings
    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(_iter_config_strings(item))
        return strings
    return []


def _backend_config_env_vars(adapter: str) -> frozenset[str]:
    """Return env vars referenced by an installed backend adapter config."""

    config_path = get_backend_config_path(adapter)
    if not config_path.exists():
        return frozenset()
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return frozenset()

    env_vars: set[str] = set()
    for text in _iter_config_strings(data):
        match = _ENV_REF_RE.match(text.strip())
        if match:
            env_vars.add(match.group(1))
    return frozenset(env_vars)


def _local_source_matches_backend_config(source: ModelSource) -> bool:
    if source.local_lifecycle is None:
        return False
    config_env_vars = _backend_config_env_vars(source.local_lifecycle.adapter)
    return bool(set(source.required_env_vars) & set(config_env_vars))


def _managed_process_for_source(
    source: ModelSource,
    managed_processes: dict[str, ManagedBackendProcess],
) -> ManagedBackendProcess | None:
    if source.local_lifecycle is None:
        return None
    process_id = f"{source.local_lifecycle.adapter}-{source.local_lifecycle.default_port}"
    process = managed_processes.get(process_id)
    if process is None:
        return None
    if not _local_source_matches_backend_config(source):
        return None
    return process


def _process_source_map(
    managed_processes: dict[str, ManagedBackendProcess],
) -> dict[str, list[str]]:
    """Map each running process id to the local source ids it backs.

    Local LiteLLM sources share one adapter+port, so a single process can back
    several sources at once (the default config serves Gemini and OpenAI models
    from one litellm-4000 process). The list/show views use this to mark a managed
    process as shared instead of implying separate local processes.
    """
    mapping: dict[str, list[str]] = {}
    for source in list_model_sources():
        process = _managed_process_for_source(source, managed_processes)
        if process is not None:
            mapping.setdefault(process.process_id, []).append(source.id)
    return mapping


def _shared_sibling_sources(
    source: ModelSource,
    process: ManagedBackendProcess | None,
    process_sources: dict[str, list[str]],
) -> tuple[str, ...]:
    """Return other source ids that share `process` with `source`."""

    if process is None:
        return ()
    return tuple(sid for sid in process_sources.get(process.process_id, ()) if sid != source.id)


def _managed_process_record(
    process: ManagedBackendProcess | None,
    *,
    shared_with: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    if process is None:
        return None
    return {
        "process_id": process.process_id,
        "adapter_type": process.adapter_type,
        "port": process.port,
        "pid": process.pid,
        "status": process.status,
        "created_at": process.created_at,
        "alive": process.pid is not None and is_pid_alive(process.pid),
        # Other local sources backed by the same adapter+port process; non-empty
        # when one local LiteLLM process serves multiple sources (e.g. Gemini + OpenAI).
        "shared_with": list(shared_with),
    }


def _process_cell(process: dict[str, Any] | None) -> str:
    """Render the PROCESS column, flagging a process shared across sources."""

    if not process:
        return "-"
    label = str(process["process_id"])
    if process.get("shared_with"):
        label += " (shared)"
    return label


def _resolve_env_var(ev: EnvVar) -> dict[str, Any]:
    value, provenance = resolve_env_or_credential_with_source(ev.name)
    configured = bool(value) or (not ev.required and ev.default_value is not None)
    return {
        "name": ev.name,
        "required": ev.required,
        "secret": ev.secret,
        "connection_value": ev.connection_value,
        "configured": configured,
        "provenance": provenance,
    }


def _auth_record(source: ModelSource) -> dict[str, Any]:
    # A runtime_native source has no Forge credential -- auth is owned by its
    # runtime (e.g. chatgpt via codex login). Report that explicitly instead of
    # letting the empty credential loop fall through to a misleading "configured".
    if source.endpoint.kind == "runtime_native":
        return {
            "status": "runtime_native",
            "credentials": [],
            "missing_required_env_vars": [],
        }

    credentials: list[dict[str, Any]] = []
    missing_required: list[str] = []
    configured_required = 0
    required_count = 0

    for credential_id, credential in zip(source.credential_ids, source.credentials, strict=True):
        env_vars = [_resolve_env_var(ev) for ev in credential.env_vars]
        credential_missing = [ev["name"] for ev in env_vars if ev["required"] and not ev["configured"]]
        credentials.append(
            {
                "credential_id": credential_id,
                "env_vars": env_vars,
                "configured": not credential_missing,
            }
        )
        missing_required.extend(credential_missing)
        configured_required += sum(1 for ev in env_vars if ev["required"] and ev["configured"])
        required_count += sum(1 for ev in env_vars if ev["required"])

    if not missing_required:
        status = "configured"
    elif configured_required and configured_required < required_count:
        status = "partial"
    else:
        status = "missing"

    return {
        "status": status,
        "credentials": credentials,
        "missing_required_env_vars": missing_required,
    }


def _endpoint_record(source: ModelSource, process: ManagedBackendProcess | None = None) -> dict[str, Any]:
    endpoint = source.endpoint
    if endpoint.kind == "local_backend":
        lifecycle = source.local_lifecycle
        return {
            "kind": endpoint.kind,
            "adapter": lifecycle.adapter if lifecycle else None,
            "default_port": lifecycle.default_port if lifecycle else None,
            "url": (f"http://localhost:{process.port if process else lifecycle.default_port}" if lifecycle else None),
        }
    if endpoint.kind == "connection_value":
        _, provenance = resolve_env_or_credential_with_source(endpoint.value or "")
        return {
            "kind": endpoint.kind,
            "env_var": endpoint.value,
            "default_url": endpoint.default_url,
            "provenance": provenance,
        }
    return {
        "kind": endpoint.kind,
        "url": endpoint.value,
    }


def _endpoint_display(source: ModelSource, process: ManagedBackendProcess | None = None) -> str:
    endpoint = _endpoint_record(source, process)
    if endpoint["kind"] == "local_backend":
        return str(endpoint.get("url") or "-")
    if endpoint["kind"] == "connection_value":
        env_var = str(endpoint["env_var"])
        default_url = endpoint.get("default_url")
        if default_url:
            return f"{env_var} (default {default_url})"
        return env_var
    return str(endpoint.get("url") or "-")


def _auth_display(auth: dict[str, Any]) -> str:
    if auth["status"] == "configured":
        pieces: list[str] = []
        for credential in auth["credentials"]:
            provenances = {
                env_var["provenance"]
                for env_var in credential["env_vars"]
                if env_var["required"] and env_var["configured"]
            }
            if not provenances:
                provenance = "none"
            else:
                provenance = "+".join(sorted(provenances))
            pieces.append(f"{credential['credential_id']}:{provenance}")
        return ", ".join(pieces)
    missing = ", ".join(auth["missing_required_env_vars"])
    return f"{auth['status']} ({missing})" if missing else str(auth["status"])


def _source_health(source: ModelSource, process: ManagedBackendProcess | None, auth: dict[str, Any]) -> str:
    if source.endpoint.kind == "runtime_native":
        return "runtime-owned"
    if source.kind == "remote":
        return "missing" if auth["status"] != "configured" else "unprobed"
    if process is None:
        return "stopped"
    if process.pid is not None and not is_pid_alive(process.pid):
        return "stopped"
    return process.status


def _source_record(
    source: ModelSource,
    managed_processes: dict[str, ManagedBackendProcess],
    process_sources: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    process = _managed_process_for_source(source, managed_processes)
    shared_with = _shared_sibling_sources(source, process, process_sources or {})
    auth = _auth_record(source)
    return {
        "backend_instance_id": source.id,
        "kind": source.kind,
        "provider": source.provider,
        "endpoint": _endpoint_record(source, process),
        "required_credentials": list(source.credential_ids),
        "credentials": auth["credentials"],
        "auth_status": auth["status"],
        "missing_required_env_vars": auth["missing_required_env_vars"],
        "health": _source_health(source, process, auth),
        "has_lifecycle": source.has_lifecycle,
        "managed_process": _managed_process_record(process, shared_with=shared_with),
    }


def _unmatched_managed_processes(
    records: list[dict[str, Any]],
    managed_processes: dict[str, ManagedBackendProcess],
) -> list[ManagedBackendProcess]:
    matched_process_ids = {
        process["process_id"] for record in records if (process := record["managed_process"]) is not None
    }
    return [
        process for process_id, process in sorted(managed_processes.items()) if process_id not in matched_process_ids
    ]


def _load_managed_processes() -> dict[str, ManagedBackendProcess]:
    store = BackendRegistryStore()
    return {instance.process_id: instance for instance in store.list_processes()}


def _resolve_lifecycle_operand(operand: str, port: int | None) -> tuple[str, int]:
    source = _source_for_identifier(operand)
    if source is not None:
        if source.local_lifecycle is None:
            raise click.ClickException(
                f"Backend '{source.id}' is {source.kind} and has no local lifecycle to start or stop."
            )
        lifecycle = source.local_lifecycle
        return lifecycle.adapter, port or lifecycle.default_port

    if operand in _SUPPORTED_ADAPTERS:
        if port is None:
            raise click.ClickException(f"--port is required when using adapter '{operand}'.")
        return operand, port

    raise click.ClickException(
        f"Unknown backend or adapter '{operand}'. Use '{_BACKEND_COMMAND} list' to see backends."
    )


def _process_id_tip() -> str:
    return "Find the managed process id with:"


def _process_id_tip_commands() -> tuple[str, ...]:
    return (f"{_BACKEND_COMMAND} list",)


def _process_stop_target_error(
    operand: str,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    source = _source_for_identifier(operand)
    if source is not None:
        if source.local_lifecycle is None:
            return (
                f"Backend '{source.id}' is {source.kind} and has no local lifecycle to start or stop.",
                (),
                (),
            )
        return (
            f"Backend '{source.id}' is not a managed process id.",
            (_process_id_tip(),),
            _process_id_tip_commands(),
        )

    if operand in _SUPPORTED_ADAPTERS:
        return (
            f"Backend adapter '{operand}' is not a managed process id.",
            (_process_id_tip(),),
            _process_id_tip_commands(),
        )

    return (
        f"Unknown managed process '{operand}'.",
        ("Run 'forge model backend list' to see managed process ids.",),
        (),
    )


def _print_error_with_optional_tip(
    message: str,
    tip_lines: tuple[str, ...],
    commands: tuple[str, ...],
) -> None:
    if tip_lines or commands:
        print_error_with_tip(message, *tip_lines, commands=commands or None)
        return
    print_error(message)


def _resolve_local_adapter_operand(operand: str) -> str:
    if operand in _SUPPORTED_ADAPTERS:
        return operand

    source = _source_for_identifier(operand)
    if source is not None:
        if source.kind == "remote":
            raise click.ClickException(
                f"Backend '{source.id}' is built in and remote; it has no local config to create or delete."
            )
        adapter = source.local_lifecycle.adapter if source.local_lifecycle else "litellm"
        raise click.ClickException(
            f"Backend '{source.id}' is built in; manage its local adapter config with "
            f"'{_BACKEND_COMMAND} create {adapter}' or '{_BACKEND_COMMAND} delete {adapter}'."
        )

    valid_adapters = ", ".join(sorted(_SUPPORTED_ADAPTERS))
    raise click.ClickException(
        f"Unknown backend or adapter '{operand}'. Valid adapters: {valid_adapters}. "
        f"Use '{_BACKEND_COMMAND} list' to see backends."
    )


def _exit_click_error(error: click.ClickException) -> NoReturn:
    print_error(error.message)
    sys.exit(1)


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _resolved_endpoint_url(source: ModelSource, process: ManagedBackendProcess | None = None) -> str | None:
    endpoint = source.endpoint
    if endpoint.kind == "literal_url":
        return endpoint.value
    if endpoint.kind == "connection_value" and endpoint.value:
        value, _ = resolve_env_or_credential_with_source(endpoint.value)
        return value or endpoint.default_url
    if endpoint.kind == "local_backend":
        lifecycle = source.local_lifecycle
        if lifecycle is None:
            return None
        return f"http://localhost:{process.port if process else lifecycle.default_port}"
    return None


def _runtime_native_probe_detail(source: ModelSource) -> str:
    """Verification hint for a runtime-native source (auth owned by its runtime, not Forge)."""
    if "codex" in source.reachable_via:
        return "runtime-native auth; verify with 'forge runtime preflight codex'"
    if "claude_code" in source.reachable_via:
        return "runtime-native auth; verify the Claude subscription login via 'claude'"
    return "runtime-native auth; verify via the owning runtime's login"


def _probe_model_source(
    source: ModelSource,
    *,
    process: ManagedBackendProcess | None,
    timeout_s: float,
) -> _ProbeResult:
    if source.endpoint.kind == "runtime_native":
        return _ProbeResult(
            status="skipped",
            detail=_runtime_native_probe_detail(source),
        )

    import httpx

    base_url = _resolved_endpoint_url(source, process)
    if not base_url:
        return _ProbeResult(status="failed", detail="endpoint is not configured")

    if source.provider == "litellm_local":
        if process is None:
            return _ProbeResult(status="skipped", detail="local backend is not running")
        try:
            with httpx.Client(timeout=httpx.Timeout(timeout_s)) as client:
                response = client.get(_join_url(base_url, "/health/liveliness"))
            if response.status_code == 200:
                return _ProbeResult(
                    status="passed",
                    detail="local backend liveliness check passed",
                    http_status=200,
                )
            return _ProbeResult(
                status="failed",
                detail=f"local backend liveliness check returned HTTP {response.status_code}",
                http_status=response.status_code,
            )
        except (httpx.RequestError, httpx.TimeoutException) as e:
            return _ProbeResult(status="failed", detail=str(e))

    headers: dict[str, str] = {}
    path = "/models"
    if source.provider == "anthropic":
        api_key, _ = resolve_env_or_credential_with_source("ANTHROPIC_API_KEY")
        headers = {"x-api-key": api_key or "", "anthropic-version": "2023-06-01"}
        path = "/v1/models"
    elif source.provider == "openrouter":
        api_key, _ = resolve_env_or_credential_with_source("OPENROUTER_API_KEY")
        headers = {"Authorization": f"Bearer {api_key or ''}"}
    elif source.provider == "litellm_remote":
        api_key, _ = resolve_env_or_credential_with_source("LITELLM_API_KEY")
        headers = {"Authorization": f"Bearer {api_key or ''}"}

    try:
        with httpx.Client(timeout=httpx.Timeout(timeout_s)) as client:
            response = client.get(_join_url(base_url, path), headers=headers)
        if 200 <= response.status_code < 300:
            return _ProbeResult(
                status="passed",
                detail="authenticated endpoint probe passed",
                http_status=response.status_code,
            )
        if response.status_code in {401, 403}:
            return _ProbeResult(
                status="failed",
                detail="endpoint rejected the configured credential",
                http_status=response.status_code,
            )
        return _ProbeResult(
            status="failed",
            detail=f"endpoint probe returned HTTP {response.status_code}",
            http_status=response.status_code,
        )
    except (httpx.RequestError, httpx.TimeoutException) as e:
        return _ProbeResult(status="failed", detail=str(e))


def _show_source(source: ModelSource, raw: bool, console: Console) -> None:
    managed_processes = _load_managed_processes()
    process = _managed_process_for_source(source, managed_processes)
    shared_with = _shared_sibling_sources(source, process, _process_source_map(managed_processes))
    auth = _auth_record(source)

    console.print(f"[bold]Backend:[/bold] [cyan]{source.id}[/cyan]")
    console.print(f"[bold]Kind:[/bold] {source.kind}")
    console.print(f"[bold]Provider:[/bold] {source.provider}")
    console.print(f"[bold]Endpoint:[/bold] {_endpoint_display(source, process)}")
    console.print(f"[bold]Credentials:[/bold] {_auth_display(auth)}")
    console.print(f"[bold]Health:[/bold] {_source_health(source, process, auth)}")

    if source.template_names:
        console.print(f"[bold]Templates:[/bold] {', '.join(source.template_names)}")

    if source.local_lifecycle:
        lifecycle = source.local_lifecycle
        console.print(f"[bold]Lifecycle:[/bold] {lifecycle.adapter} on default port {lifecycle.default_port}")
        if process:
            console.print(f"[bold]Managed process:[/bold] {process.process_id}")
            console.print(f"[bold]Process PID:[/bold] {process.pid or '-'}")
            console.print(f"[bold]Process status:[/bold] {process.status}")
            if shared_with:
                console.print(f"[bold]Shared with:[/bold] {', '.join(shared_with)}")
        else:
            console.print("[bold]Managed process:[/bold] -")

        config_path = get_backend_config_path(lifecycle.adapter)
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
            console.print(f"\n[dim]No config found for adapter '{lifecycle.adapter}'.[/dim]")
            print_tip(
                f"Run '{_BACKEND_COMMAND} create {lifecycle.adapter}'.",
                blank_before=False,
                console=console,
            )
    else:
        console.print("[bold]Lifecycle:[/bold] none")


@backend.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def list_cmd(as_json: bool) -> None:
    """List model backends and managed local processes."""
    console = Console(width=200)
    managed_processes = _load_managed_processes()
    process_sources = _process_source_map(managed_processes)
    records = [_source_record(source, managed_processes, process_sources) for source in list_model_sources()]

    if as_json:
        click.echo(json.dumps(records, indent=2, default=str))
        return

    table = Table(title="Forge Model Backends")
    table.add_column("BACKEND", style="cyan")
    table.add_column("KIND")
    table.add_column("PROVIDER")
    table.add_column("ENDPOINT")
    table.add_column("AUTH")
    table.add_column("HEALTH")
    table.add_column("PROCESS")

    for record in records:
        process = record["managed_process"]
        table.add_row(
            record["backend_instance_id"],
            record["kind"],
            record["provider"],
            _endpoint_display(
                get_model_source(record["backend_instance_id"]),
                managed_processes.get(process["process_id"]) if process else None,
            ),
            _auth_display(
                {
                    "status": record["auth_status"],
                    "credentials": record["credentials"],
                    "missing_required_env_vars": record["missing_required_env_vars"],
                }
            ),
            record["health"],
            _process_cell(process),
        )

    console.print(table)

    unmatched_processes = _unmatched_managed_processes(records, managed_processes)
    if unmatched_processes:
        runtime_table = Table(title="Unmatched Managed Processes")
        runtime_table.add_column("PROCESS", style="cyan")
        runtime_table.add_column("ADAPTER")
        runtime_table.add_column("PORT", justify="right")
        runtime_table.add_column("PID", justify="right")
        runtime_table.add_column("STATUS")

        for instance in unmatched_processes:
            runtime_table.add_row(
                instance.process_id,
                instance.adapter_type,
                str(instance.port),
                str(instance.pid or "-"),
                instance.status,
            )

        console.print()
        console.print(runtime_table)


@backend.command("show")
@click.argument("identifier", metavar="BACKEND_OR_PROCESS")
@click.option("--raw", is_flag=True, help="Output raw config without syntax highlighting")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def show_cmd(identifier: str, raw: bool, as_json: bool) -> None:
    """Show backend or managed process details and configuration.

    \b
    Examples:
        forge model backend show openrouter
        forge model backend show litellm-4000
    """
    console = Console(width=200)
    try:
        source = _source_for_backend_identifier(identifier)
    except BackendInstanceAmbiguousError as exc:
        print_error(str(exc), console=err_console)
        sys.exit(1)
    if source is not None:
        if as_json:
            managed_processes = _load_managed_processes()
            process_sources = _process_source_map(managed_processes)
            click.echo(
                json.dumps(
                    _source_record(source, managed_processes, process_sources),
                    indent=2,
                    default=str,
                )
            )
            return
        _show_source(source, raw, console)
        return

    store = BackendRegistryStore()
    process_id = identifier

    # Parse adapter type from process_id (e.g., "litellm-4000" -> "litellm")
    parts = process_id.rsplit("-", 1)
    adapter_type = parts[0] if len(parts) == 2 else process_id

    if as_json:
        json_process = None
        try:
            json_process = store.read().processes.get(process_id)
        except Exception:
            json_process = None
        json_config_path = get_backend_config_path(adapter_type)
        click.echo(
            json.dumps(
                {
                    "managed_process_id": process_id,
                    "found": json_process is not None,
                    "adapter_type": adapter_type,
                    "managed_process": _managed_process_record(json_process),
                    "config_path": (str(json_config_path) if json_config_path.exists() else None),
                },
                indent=2,
                default=str,
            )
        )
        return

    try:
        registry = store.read()
        process = registry.processes.get(process_id)
        if process:
            alive = process.pid is not None and is_pid_alive(process.pid)
            status_color = "green" if alive else "yellow"
            console.print(f"[bold]Managed process:[/bold] [cyan]{process_id}[/cyan]")
            console.print(f"[bold]Adapter:[/bold] {process.adapter_type}")
            console.print(f"[bold]Port:[/bold] {process.port}")
            console.print(f"[bold]PID:[/bold] {process.pid or '-'}")
            console.print(
                f"[bold]Status:[/bold] [{status_color}]{'healthy' if alive else 'not running'}[/{status_color}]"
            )
            if process.created_at:
                console.print(f"[bold]Started:[/bold] {process.created_at}")
        else:
            console.print(f"[bold]Managed process:[/bold] [cyan]{process_id}[/cyan] [dim](not in registry)[/dim]")
    except Exception:
        console.print(f"[bold]Managed process:[/bold] [cyan]{process_id}[/cyan]")

    log_file = get_forge_home() / "logs" / "backend" / f"{process_id}.log"
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
        print_tip(
            f"Run '{_BACKEND_COMMAND} create {adapter_type}'.",
            blank_before=False,
            console=console,
        )


@backend.command("test-auth")
@click.argument("backend_identifier", metavar="BACKEND")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option(
    "--timeout",
    type=float,
    default=5.0,
    show_default=True,
    help="Probe timeout in seconds",
)
def test_auth_cmd(backend_identifier: str, as_json: bool, timeout: float) -> None:
    """Test a backend's credential configuration and reachable auth endpoint.

    \b
    Examples:
        forge model backend test-auth openrouter
    """
    console = Console(width=200)
    try:
        source = _source_for_backend_identifier(backend_identifier)
    except BackendInstanceAmbiguousError as exc:
        print_error(str(exc), console=err_console)
        sys.exit(1)
    if source is None:
        print_error(
            f"Unknown backend '{backend_identifier}'. Use '{_BACKEND_COMMAND} list' to see backends.",
            console=err_console,
        )
        sys.exit(1)

    managed_processes = _load_managed_processes()
    process = _managed_process_for_source(source, managed_processes)
    auth = _auth_record(source)
    probe: _ProbeResult
    if auth["status"] == "runtime_native":
        probe = _ProbeResult(
            status="skipped",
            detail=_runtime_native_probe_detail(source),
        )
    elif auth["status"] != "configured":
        missing = ", ".join(auth["missing_required_env_vars"])
        probe = _ProbeResult(status="skipped", detail=f"missing required credential values: {missing}")
    elif not source.capabilities.auth_probe:
        probe = _ProbeResult(status="skipped", detail="source does not declare an auth probe capability")
    else:
        probe = _probe_model_source(source, process=process, timeout_s=timeout)

    payload = {
        "backend_instance_id": source.id,
        "kind": source.kind,
        "provider": source.provider,
        "auth_status": auth["status"],
        "missing_required_env_vars": auth["missing_required_env_vars"],
        "credentials": auth["credentials"],
        "probe": {
            "status": probe.status,
            "detail": probe.detail,
            "http_status": probe.http_status,
        },
    }

    if as_json:
        click.echo(json.dumps(payload, indent=2, default=str))
    else:
        console.print(f"[bold]Backend:[/bold] [cyan]{source.id}[/cyan]")
        console.print(f"[bold]Auth:[/bold] {_auth_display(auth)}")
        console.print(f"[bold]Probe:[/bold] {probe.status} - {probe.detail}")

    if auth["status"] not in ("configured", "runtime_native") or probe.status == "failed":
        sys.exit(1)


@backend.command("create")
@click.argument("adapter")
@click.option(
    "--config",
    "-c",
    type=Path,
    help="Adapter config file (defaults to installed template)",
)
def create_cmd(adapter: str, config: Path | None) -> None:
    """Create a backend config (copy to installed location).

    Config is shared by all instances of this adapter type.
    """
    console = Console(width=200)
    try:
        adapter = _resolve_local_adapter_operand(adapter)
    except click.ClickException as e:
        _exit_click_error(e)

    config_path = get_backend_config_path(adapter)
    if config_path.exists():
        print_error_with_tip(
            f"Backend config already exists: {display_path(config_path)}",
            "Start an instance with:",
            commands=[f"{_BACKEND_COMMAND} start {adapter} --port 4000"],
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
        console.print(f"  {_BACKEND_COMMAND} start {adapter} --port 4000")
    except Exception as e:
        print_error(str(e))
        sys.exit(1)


@backend.command("start")
@click.argument("source_or_adapter", metavar="BACKEND_OR_ADAPTER")
@click.option(
    "--port",
    "-p",
    type=int,
    required=False,
    help="Port number (required for adapter names like litellm; backend names use their default port unless overridden)",
)
def start_cmd(source_or_adapter: str, port: int | None) -> None:
    """Start a managed local process from a backend or adapter config.

    \b
    Examples:
        forge model backend start litellm-openai-local
        forge model backend start litellm --port 4000
    """
    console = Console(width=200)
    try:
        adapter, resolved_port = _resolve_lifecycle_operand(source_or_adapter, port)
    except click.ClickException as e:
        _exit_click_error(e)

    config_path = get_backend_config_path(adapter)
    if not config_path.exists():
        print_error_with_tip(
            f"Backend config not found for '{adapter}'",
            "Create it first:",
            commands=[f"{_BACKEND_COMMAND} create {adapter}"],
        )
        sys.exit(1)

    process_id = f"{adapter}-{resolved_port}"
    store = BackendRegistryStore()
    manager = BackendManager(store)
    manager.register_adapter(adapter, get_adapter(adapter))

    try:
        result = manager.ensure_backend(process_id, adapter, resolved_port)
        if result.source == "start":
            console.print(
                f"[green]Started[/green] managed process '{process_id}' on port {resolved_port} "
                f"(pid {result.process.pid})"
            )
        else:
            console.print(f"Managed process '{process_id}' already running on port {resolved_port}")
    except Exception as e:
        print_error(str(e))
        sys.exit(1)


def _stop_managed_process(process: ManagedBackendProcess) -> None:
    """Stop a single registered managed process. Raises on failure; the caller owns output."""
    store = BackendRegistryStore()
    manager = BackendManager(store)
    manager.register_adapter(process.adapter_type, get_adapter(process.adapter_type))
    manager.stop_backend(process.process_id)


@backend.command("stop")
@click.argument("process_ids", nargs=-1, metavar="PROCESS_ID...")
@click.option(
    "--all",
    "-a",
    "stop_all",
    is_flag=True,
    help="Stop all registered managed local processes",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
def stop_cmd(process_ids: tuple[str, ...], stop_all: bool, yes: bool) -> None:
    """Stop managed local backend process(es).

    Managed process ids are shown in `forge model backend list` (for example, litellm-4000).

    \b
    Examples:
        forge model backend stop litellm-4000
        forge model backend stop litellm-4000 litellm-4001
        forge model backend stop --all
        forge model backend stop --all --yes
    """
    console = Console(width=200)
    if stop_all and process_ids:
        print_error("Cannot combine --all with explicit managed process IDs")
        sys.exit(1)
    if not stop_all and not process_ids:
        print_error_with_tip(
            "Provide managed process ID(s) or use --all.",
            "Run 'forge model backend list' to see managed process ids.",
        )
        sys.exit(1)

    store = BackendRegistryStore()
    registry = store.read()
    if stop_all:
        if not registry.processes:
            console.print("[dim]No managed processes to stop.[/dim]")
            return
        targets = list(registry.processes.keys())
        console.print(f"About to stop [bold]all {len(targets)} managed process(es)[/bold]:")
        for target in targets:
            console.print(f"  - {target}")
        console.print()
        if not yes and not click.confirm("Are you sure you want to stop all managed processes?"):
            console.print("Cancelled.")
            return
    else:
        targets = list(dict.fromkeys(process_ids))

    stopped = 0
    failed = 0
    for target in targets:
        process = registry.processes.get(target)
        if process is None:
            message, tip_lines, commands = _process_stop_target_error(target)
            _print_error_with_optional_tip(message, tip_lines, commands)
            failed += 1
            if len(targets) == 1:
                sys.exit(1)
            continue

        was_pidless = process.pid is None
        try:
            _stop_managed_process(process)
        except Exception as e:
            print_error(f"{target}: {e}")
            failed += 1
            if len(targets) == 1:
                sys.exit(1)
            continue

        stopped += 1
        if was_pidless:
            console.print(f"[yellow]Unregistered[/yellow] pidless managed process '{target}'; no process was killed")
        else:
            console.print(f"[green]Stopped[/green] managed process '{target}'")

    if len(targets) > 1:
        summary = f"{stopped} stopped"
        if failed:
            summary += f", {failed} failed"
        console.print(summary)
    if failed:
        sys.exit(1)


@backend.command("delete")
@click.argument("adapter")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def delete_cmd(adapter: str, yes: bool) -> None:
    """Delete a local backend adapter config.

    Stops matching managed processes first, but the command's object is the
    adapter config. Use 'stop' for managed processes.
    """
    import shutil

    console = Console(width=200)
    store = BackendRegistryStore()
    registry = store.read()
    if adapter in registry.processes:
        print_error_with_tip(
            f"'{adapter}' is a managed process id, not an adapter config.",
            f"Use '{_BACKEND_COMMAND} stop {adapter}' to stop a managed process.",
        )
        sys.exit(1)

    try:
        adapter = _resolve_local_adapter_operand(adapter)
    except click.ClickException as e:
        _exit_click_error(e)

    backend_dir = get_forge_home() / "backends" / adapter
    if not backend_dir.exists():
        print_error_with_tip(
            f"Backend config not found for '{adapter}'",
            "Create it first:",
            commands=[f"{_BACKEND_COMMAND} create {adapter}"],
        )
        sys.exit(1)

    if not yes and not click.confirm(f"Delete backend config for '{adapter}' (stops matching managed processes)?"):
        console.print("Cancelled.")
        return

    stopped = []
    registry = store.read()
    for process in list(registry.processes.values()):
        if process.adapter_type == adapter:
            try:
                _stop_managed_process(process)
                stopped.append(process.process_id)
            except Exception:
                pass

    if stopped:
        console.print(f"Stopped managed processes: {', '.join(stopped)}")

    shutil.rmtree(backend_dir)
    console.print(f"[green]Deleted[/green] backend config for '{adapter}'")


@backend.command("reconcile")
@click.argument("backend_identifier", metavar="BACKEND")
@click.option(
    "--request-id",
    "request_id",
    default=None,
    help="Local request id to join to a remote record (scoped to <backend>; run 'forge model backend list' for backends).",
)
@click.option(
    "--remote-id",
    "remote_id",
    default=None,
    help="The backend's own record id (e.g. an OpenRouter gen-... id); remote-only.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option(
    "--timeout",
    type=float,
    default=5.0,
    show_default=True,
    help="Remote lookup timeout (seconds).",
)
def reconcile_cmd(
    backend_identifier: str,
    request_id: str | None,
    remote_id: str | None,
    as_json: bool,
    timeout: float,
) -> None:
    """Reconcile local telemetry against a backend's remote account-side record.

    Provide exactly one of --request-id (local-anchored: local trace -> remote record) or
    --remote-id (remote-only: the backend's own record id, no local side).

    \b
    Examples:
        forge model backend reconcile openrouter --request-id req_abc...
        forge model backend reconcile openrouter --remote-id gen-...
    """
    if request_id and remote_id:
        print_error(
            "Use only one of --request-id or --remote-id, not both.",
            console=err_console,
        )
        sys.exit(1)
    if not request_id and not remote_id:
        print_error_with_tip(
            "Provide a local request id or a remote record id to reconcile.",
            "Use --request-id <id> for a local request, or use --remote-id <id> for the backend's own record id.",
            console=err_console,
        )
        sys.exit(1)

    try:
        result = reconcile_generation(
            ctx=ExecutionContext.from_cwd(),
            backend_instance_id=backend_identifier,
            request_id=request_id,
            remote_id=remote_id,
            timeout_s=timeout,
        )
    except ForgeOpError as e:
        print_error_with_tip(
            str(e),
            f"Run '{_BACKEND_COMMAND} list' to see backends.",
            console=err_console,
        )
        sys.exit(1)
    except RemoteAdapterError as e:
        # Adapter bug / config fault (e.g. no base URL) -- a clean CLI error, not a traceback.
        print_error(f"Remote adapter error: {e}", console=err_console)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(asdict(result), indent=2, default=str))
        return

    for line in render_reconcile_lines(result):
        click.echo(line)

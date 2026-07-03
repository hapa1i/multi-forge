"""Backend management CLI commands.

Provides commands to manage backend services (LiteLLM, etc.) that proxies depend on:
- forge model backend list: List all backends
- forge model backend create: Create backend config
- forge model backend start: Start a backend instance
- forge model backend stop: Stop a backend instance
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

from forge.backend import BackendManager, ModelSource, ModelSourceNotFoundError
from forge.backend.adapters import get_adapter
from forge.backend.creation import create_backend_config, get_backend_config_path
from forge.backend.registry import BackendInstance, BackendRegistryStore, is_pid_alive
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
    """Manage model backends, local configs, and backend instances.

    \b
    Identifiers:
        Backend: openrouter (configured inference target shown by list)
        Backend instance: litellm-4000 (managed local process shown by list)
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


def _runtime_instance_for_source(
    source: ModelSource,
    runtime_instances: dict[str, BackendInstance],
) -> BackendInstance | None:
    if source.local_lifecycle is None:
        return None
    instance_id = f"{source.local_lifecycle.adapter}-{source.local_lifecycle.default_port}"
    instance = runtime_instances.get(instance_id)
    if instance is None:
        return None
    if not _local_source_matches_backend_config(source):
        return None
    return instance


def _instance_source_map(
    runtime_instances: dict[str, BackendInstance],
) -> dict[str, list[str]]:
    """Map each running instance backend_id to the local source ids it backs.

    Local LiteLLM sources share one adapter+port, so a single process can back
    several sources at once (the default config serves Gemini and OpenAI models
    from one litellm-4000 process). The list/show views use this to mark a runtime
    instance as shared instead of implying separate backends.
    """
    mapping: dict[str, list[str]] = {}
    for source in list_model_sources():
        instance = _runtime_instance_for_source(source, runtime_instances)
        if instance is not None:
            mapping.setdefault(instance.backend_id, []).append(source.id)
    return mapping


def _shared_sibling_sources(
    source: ModelSource,
    instance: BackendInstance | None,
    instance_sources: dict[str, list[str]],
) -> tuple[str, ...]:
    """Return other source ids that share `instance` with `source`."""

    if instance is None:
        return ()
    return tuple(sid for sid in instance_sources.get(instance.backend_id, ()) if sid != source.id)


def _runtime_instance_record(
    instance: BackendInstance | None,
    *,
    shared_with: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    if instance is None:
        return None
    return {
        "backend_id": instance.backend_id,
        "adapter_type": instance.adapter_type,
        "port": instance.port,
        "pid": instance.pid,
        "status": instance.status,
        "created_at": instance.created_at,
        # Other local sources backed by the same adapter+port process; non-empty
        # when one local LiteLLM instance serves multiple sources (e.g. Gemini + OpenAI).
        "shared_with": list(shared_with),
    }


def _runtime_cell(runtime: dict[str, Any] | None) -> str:
    """Render the INSTANCE column, flagging an instance shared across sources."""

    if not runtime:
        return "-"
    label = str(runtime["backend_id"])
    if runtime.get("shared_with"):
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


def _endpoint_record(source: ModelSource, instance: BackendInstance | None = None) -> dict[str, Any]:
    endpoint = source.endpoint
    if endpoint.kind == "local_backend":
        lifecycle = source.local_lifecycle
        return {
            "kind": endpoint.kind,
            "adapter": lifecycle.adapter if lifecycle else None,
            "default_port": lifecycle.default_port if lifecycle else None,
            "url": (f"http://localhost:{instance.port if instance else lifecycle.default_port}" if lifecycle else None),
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


def _endpoint_display(source: ModelSource, instance: BackendInstance | None = None) -> str:
    endpoint = _endpoint_record(source, instance)
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


def _source_health(source: ModelSource, instance: BackendInstance | None, auth: dict[str, Any]) -> str:
    if source.endpoint.kind == "runtime_native":
        return "runtime-owned"
    if source.kind == "remote":
        return "missing" if auth["status"] != "configured" else "unprobed"
    if instance is None:
        return "stopped"
    if instance.pid is not None and not is_pid_alive(instance.pid):
        return "stopped"
    return instance.status


def _source_record(
    source: ModelSource,
    runtime_instances: dict[str, BackendInstance],
    instance_sources: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    instance = _runtime_instance_for_source(source, runtime_instances)
    shared_with = _shared_sibling_sources(source, instance, instance_sources or {})
    auth = _auth_record(source)
    # Source-row JSON keeps both names: backend_id is the telemetry catalog key,
    # while source_id is the row alias. Runtime-instance JSON uses source_id=None.
    return {
        "backend_id": source.id,
        "source_id": source.id,
        "kind": source.kind,
        "provider": source.provider,
        "endpoint": _endpoint_record(source, instance),
        "required_credentials": list(source.credential_ids),
        "credentials": auth["credentials"],
        "auth_status": auth["status"],
        "missing_required_env_vars": auth["missing_required_env_vars"],
        "health": _source_health(source, instance, auth),
        "has_lifecycle": source.has_lifecycle,
        "runtime_instance": _runtime_instance_record(instance, shared_with=shared_with),
    }


def _unmatched_runtime_instances(
    records: list[dict[str, Any]],
    runtime_instances: dict[str, BackendInstance],
) -> list[BackendInstance]:
    matched_backend_ids = {
        runtime["backend_id"] for record in records if (runtime := record["runtime_instance"]) is not None
    }
    return [
        instance for backend_id, instance in sorted(runtime_instances.items()) if backend_id not in matched_backend_ids
    ]


def _load_runtime_instances() -> dict[str, BackendInstance]:
    store = BackendRegistryStore()
    return {instance.backend_id: instance for instance in store.list_backends()}


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


def _runtime_id_tip() -> str:
    return "Find the backend instance id with:"


def _runtime_id_tip_commands() -> tuple[str, ...]:
    return (f"{_BACKEND_COMMAND} list",)


def _runtime_stop_target_error(
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
            f"Backend '{source.id}' is not a backend instance id.",
            (_runtime_id_tip(),),
            _runtime_id_tip_commands(),
        )

    if operand in _SUPPORTED_ADAPTERS:
        return (
            f"Backend adapter '{operand}' is not a backend instance id.",
            (_runtime_id_tip(),),
            _runtime_id_tip_commands(),
        )

    return (
        f"Unknown backend instance '{operand}'.",
        ("Run 'forge model backend list' to see backend instance ids.",),
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


def _resolved_endpoint_url(source: ModelSource, instance: BackendInstance | None = None) -> str | None:
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
        return f"http://localhost:{instance.port if instance else lifecycle.default_port}"
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
    instance: BackendInstance | None,
    timeout_s: float,
) -> _ProbeResult:
    if source.endpoint.kind == "runtime_native":
        return _ProbeResult(
            status="skipped",
            detail=_runtime_native_probe_detail(source),
        )

    import httpx

    base_url = _resolved_endpoint_url(source, instance)
    if not base_url:
        return _ProbeResult(status="failed", detail="endpoint is not configured")

    if source.provider == "litellm_local":
        if instance is None:
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
    runtime_instances = _load_runtime_instances()
    instance = _runtime_instance_for_source(source, runtime_instances)
    shared_with = _shared_sibling_sources(source, instance, _instance_source_map(runtime_instances))
    auth = _auth_record(source)

    console.print(f"[bold]Backend:[/bold] [cyan]{source.id}[/cyan]")
    console.print(f"[bold]Kind:[/bold] {source.kind}")
    console.print(f"[bold]Provider:[/bold] {source.provider}")
    console.print(f"[bold]Endpoint:[/bold] {_endpoint_display(source, instance)}")
    console.print(f"[bold]Credentials:[/bold] {_auth_display(auth)}")
    console.print(f"[bold]Health:[/bold] {_source_health(source, instance, auth)}")

    if source.template_names:
        console.print(f"[bold]Templates:[/bold] {', '.join(source.template_names)}")

    if source.local_lifecycle:
        lifecycle = source.local_lifecycle
        console.print(f"[bold]Lifecycle:[/bold] {lifecycle.adapter} on default port {lifecycle.default_port}")
        if instance:
            console.print(f"[bold]Backend instance:[/bold] {instance.backend_id}")
            console.print(f"[bold]Instance PID:[/bold] {instance.pid or '-'}")
            console.print(f"[bold]Instance status:[/bold] {instance.status}")
            if shared_with:
                console.print(f"[bold]Shared with:[/bold] {', '.join(shared_with)}")
        else:
            console.print("[bold]Backend instance:[/bold] -")

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
    """List model backends and local backend instances."""
    console = Console(width=200)
    runtime_instances = _load_runtime_instances()
    instance_sources = _instance_source_map(runtime_instances)
    records = [_source_record(source, runtime_instances, instance_sources) for source in list_model_sources()]

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
    table.add_column("INSTANCE")

    for record in records:
        runtime = record["runtime_instance"]
        table.add_row(
            record["source_id"],
            record["kind"],
            record["provider"],
            _endpoint_display(
                get_model_source(record["source_id"]),
                runtime_instances.get(runtime["backend_id"]) if runtime else None,
            ),
            _auth_display(
                {
                    "status": record["auth_status"],
                    "credentials": record["credentials"],
                    "missing_required_env_vars": record["missing_required_env_vars"],
                }
            ),
            record["health"],
            _runtime_cell(runtime),
        )

    console.print(table)

    unmatched_runtimes = _unmatched_runtime_instances(records, runtime_instances)
    if unmatched_runtimes:
        runtime_table = Table(title="Unmatched Backend Instances")
        runtime_table.add_column("INSTANCE", style="cyan")
        runtime_table.add_column("ADAPTER")
        runtime_table.add_column("PORT", justify="right")
        runtime_table.add_column("PID", justify="right")
        runtime_table.add_column("STATUS")

        for instance in unmatched_runtimes:
            runtime_table.add_row(
                instance.backend_id,
                instance.adapter_type,
                str(instance.port),
                str(instance.pid or "-"),
                instance.status,
            )

        console.print()
        console.print(runtime_table)


@backend.command("show")
@click.argument("backend_id", metavar="BACKEND_OR_INSTANCE")
@click.option("--raw", is_flag=True, help="Output raw config without syntax highlighting")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def show_cmd(backend_id: str, raw: bool, as_json: bool) -> None:
    """Show backend or backend instance details and configuration.

    \b
    Examples:
        forge model backend show openrouter
        forge model backend show litellm-4000
    """
    console = Console(width=200)
    source = _source_for_identifier(backend_id)
    if source is not None:
        if as_json:
            runtime_instances = _load_runtime_instances()
            instance_sources = _instance_source_map(runtime_instances)
            click.echo(
                json.dumps(
                    _source_record(source, runtime_instances, instance_sources),
                    indent=2,
                    default=str,
                )
            )
            return
        _show_source(source, raw, console)
        return

    store = BackendRegistryStore()

    # Parse adapter type from backend_id (e.g., "litellm-4000" -> "litellm")
    parts = backend_id.rsplit("-", 1)
    adapter_type = parts[0] if len(parts) == 2 else backend_id

    if as_json:
        json_instance = None
        try:
            json_instance = store.read().backends.get(backend_id)
        except Exception:
            json_instance = None
        json_config_path = get_backend_config_path(adapter_type)
        runtime_record: dict[str, Any] | None = None
        if json_instance is not None:
            alive = json_instance.pid is not None and is_pid_alive(json_instance.pid)
            runtime_record = {
                "backend_id": backend_id,
                "adapter_type": json_instance.adapter_type,
                "port": json_instance.port,
                "pid": json_instance.pid,
                "status": json_instance.status,
                "alive": alive,
                "created_at": json_instance.created_at,
            }
        click.echo(
            json.dumps(
                {
                    "backend_id": backend_id,
                    "source_id": None,
                    "found": json_instance is not None,
                    "adapter_type": adapter_type,
                    "runtime_instance": runtime_record,
                    "config_path": (str(json_config_path) if json_config_path.exists() else None),
                },
                indent=2,
                default=str,
            )
        )
        return

    try:
        registry = store.read()
        instance = registry.backends.get(backend_id)
        if instance:
            alive = instance.pid is not None and is_pid_alive(instance.pid)
            status_color = "green" if alive else "yellow"
            console.print(f"[bold]Backend instance:[/bold] [cyan]{backend_id}[/cyan]")
            console.print(f"[bold]Adapter:[/bold] {instance.adapter_type}")
            console.print(f"[bold]Port:[/bold] {instance.port}")
            console.print(f"[bold]PID:[/bold] {instance.pid or '-'}")
            console.print(
                f"[bold]Status:[/bold] [{status_color}]{'healthy' if alive else 'not running'}[/{status_color}]"
            )
            if instance.created_at:
                console.print(f"[bold]Started:[/bold] {instance.created_at}")
        else:
            console.print(f"[bold]Backend instance:[/bold] [cyan]{backend_id}[/cyan] [dim](not in registry)[/dim]")
    except Exception:
        console.print(f"[bold]Backend instance:[/bold] [cyan]{backend_id}[/cyan]")

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
        print_tip(
            f"Run '{_BACKEND_COMMAND} create {adapter_type}'.",
            blank_before=False,
            console=console,
        )


@backend.command("test-auth")
@click.argument("source_id", metavar="BACKEND")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option(
    "--timeout",
    type=float,
    default=5.0,
    show_default=True,
    help="Probe timeout in seconds",
)
def test_auth_cmd(source_id: str, as_json: bool, timeout: float) -> None:
    """Test a backend's credential configuration and reachable auth endpoint.

    \b
    Examples:
        forge model backend test-auth openrouter
    """
    console = Console(width=200)
    source = _source_for_identifier(source_id)
    if source is None:
        print_error(
            f"Unknown backend '{source_id}'. Use '{_BACKEND_COMMAND} list' to see backends.",
            console=err_console,
        )
        sys.exit(1)

    runtime_instances = _load_runtime_instances()
    instance = _runtime_instance_for_source(source, runtime_instances)
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
        probe = _probe_model_source(source, instance=instance, timeout_s=timeout)

    # Source-row JSON keeps both names: backend_id is the telemetry catalog key,
    # while source_id is the row alias. Runtime-instance JSON uses source_id=None.
    payload = {
        "backend_id": source.id,
        "source_id": source.id,
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
    """Start a local backend instance from a backend or adapter config.

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

    backend_id = f"{adapter}-{resolved_port}"
    store = BackendRegistryStore()
    manager = BackendManager(store)
    manager.register_adapter(adapter, get_adapter(adapter))

    try:
        result = manager.ensure_backend(backend_id, adapter, resolved_port)
        if result.source == "start":
            console.print(
                f"[green]Started[/green] backend '{backend_id}' on port {resolved_port} (pid {result.instance.pid})"
            )
        else:
            console.print(f"Backend '{backend_id}' already running on port {resolved_port}")
    except Exception as e:
        print_error(str(e))
        sys.exit(1)


def _stop_runtime_instance(instance: BackendInstance) -> None:
    """Stop a single registered backend instance. Raises on failure; the caller owns output."""
    store = BackendRegistryStore()
    manager = BackendManager(store)
    manager.register_adapter(instance.adapter_type, get_adapter(instance.adapter_type))
    manager.stop_backend(instance.backend_id)


@backend.command("stop")
@click.argument("runtime_ids", nargs=-1, metavar="BACKEND_INSTANCE...")
@click.option(
    "--all",
    "-a",
    "stop_all",
    is_flag=True,
    help="Stop all registered local backend instances",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
def stop_cmd(runtime_ids: tuple[str, ...], stop_all: bool, yes: bool) -> None:
    """Stop live local backend instance(s).

    Backend instance ids are shown in `forge model backend list` (for example, litellm-4000).

    \b
    Examples:
        forge model backend stop litellm-4000
        forge model backend stop litellm-4000 litellm-4001
        forge model backend stop --all
        forge model backend stop --all --yes
    """
    console = Console(width=200)
    if stop_all and runtime_ids:
        print_error("Cannot combine --all with explicit backend instance IDs")
        sys.exit(1)
    if not stop_all and not runtime_ids:
        print_error_with_tip(
            "Provide backend instance ID(s) or use --all.",
            "Run 'forge model backend list' to see backend instance ids.",
        )
        sys.exit(1)

    store = BackendRegistryStore()
    registry = store.read()
    if stop_all:
        if not registry.backends:
            console.print("[dim]No backend instances to stop.[/dim]")
            return
        targets = list(registry.backends.keys())
        console.print(f"About to stop [bold]all {len(targets)} backend instance(s)[/bold]:")
        for target in targets:
            console.print(f"  - {target}")
        console.print()
        if not yes and not click.confirm("Are you sure you want to stop all backend instances?"):
            console.print("Cancelled.")
            return
    else:
        targets = list(dict.fromkeys(runtime_ids))

    stopped = 0
    failed = 0
    for target in targets:
        instance = registry.backends.get(target)
        if instance is None:
            message, tip_lines, commands = _runtime_stop_target_error(target)
            _print_error_with_optional_tip(message, tip_lines, commands)
            failed += 1
            if len(targets) == 1:
                sys.exit(1)
            continue

        was_pidless = instance.pid is None
        try:
            _stop_runtime_instance(instance)
        except Exception as e:
            print_error(f"{target}: {e}")
            failed += 1
            if len(targets) == 1:
                sys.exit(1)
            continue

        stopped += 1
        if was_pidless:
            console.print(f"[yellow]Unregistered[/yellow] pidless instance '{target}'; no process was killed")
        else:
            console.print(f"[green]Stopped[/green] backend '{target}'")

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

    Stops matching backend instances first, but the command's object is the
    adapter config. Use 'stop' for backend instances.
    """
    import shutil

    console = Console(width=200)
    store = BackendRegistryStore()
    registry = store.read()
    if adapter in registry.backends:
        print_error_with_tip(
            f"'{adapter}' is a backend instance id, not an adapter config.",
            f"Use '{_BACKEND_COMMAND} stop {adapter}' to stop a backend instance.",
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

    if not yes and not click.confirm(f"Delete backend config for '{adapter}' (stops matching backend instances)?"):
        console.print("Cancelled.")
        return

    stopped = []
    registry = store.read()
    for instance in list(registry.backends.values()):
        if instance.adapter_type == adapter:
            try:
                _stop_runtime_instance(instance)
                stopped.append(instance.backend_id)
            except Exception:
                pass

    if stopped:
        console.print(f"Stopped instances: {', '.join(stopped)}")

    shutil.rmtree(backend_dir)
    console.print(f"[green]Deleted[/green] backend config for '{adapter}'")


@backend.command("reconcile")
@click.argument("source_id", metavar="BACKEND")
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
    source_id: str,
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
            source_id=source_id,
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

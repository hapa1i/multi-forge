"""Backend management CLI commands.

Provides commands to manage backend services (LiteLLM, etc.) that proxies depend on:
- forge model backend list: List all backends
- forge model backend create: Create backend config
- forge model backend start: Start a backend instance
- forge model backend stop: Stop a backend instance
- forge model backend delete: Delete backend config or instance
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
    """Manage backends (LiteLLM, etc.).

    \b
    Examples:
        forge model backend list                     # List backends
        forge model backend create litellm           # Create backend config
        forge model backend start litellm -p 4000    # Start an instance
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


def _instance_source_map(runtime_instances: dict[str, BackendInstance]) -> dict[str, list[str]]:
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
    """Render the RUNTIME column, flagging an instance shared across sources."""

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
        return {"status": "runtime_native", "credentials": [], "missing_required_env_vars": []}

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
            "url": f"http://localhost:{instance.port if instance else lifecycle.default_port}" if lifecycle else None,
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
                f"Backend source '{source.id}' is {source.kind} and has no local lifecycle to start or stop."
            )
        lifecycle = source.local_lifecycle
        return lifecycle.adapter, port or lifecycle.default_port

    if operand in _SUPPORTED_ADAPTERS:
        if port is None:
            raise click.ClickException(f"--port is required when using adapter '{operand}'.")
        return operand, port

    raise click.ClickException(
        f"Unknown backend source or adapter '{operand}'. Use '{_BACKEND_COMMAND} list' to see source ids."
    )


def _resolve_local_adapter_operand(operand: str) -> str:
    if operand in _SUPPORTED_ADAPTERS:
        return operand

    source = _source_for_identifier(operand)
    if source is not None:
        if source.kind == "remote":
            raise click.ClickException(
                f"Backend source '{source.id}' is built in and remote; it has no local config to create or delete."
            )
        adapter = source.local_lifecycle.adapter if source.local_lifecycle else "litellm"
        raise click.ClickException(
            f"Backend source '{source.id}' is built in; manage its local adapter config with "
            f"'{_BACKEND_COMMAND} create {adapter}' or '{_BACKEND_COMMAND} delete {adapter}'."
        )

    valid_adapters = ", ".join(sorted(_SUPPORTED_ADAPTERS))
    raise click.ClickException(
        f"Unknown backend adapter or source '{operand}'. Valid adapters: {valid_adapters}. "
        f"Use '{_BACKEND_COMMAND} list' to see source ids."
    )


def _exit_click_error(error: click.ClickException, console: Console) -> NoReturn:
    print_error(error.message, console=console)
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


def _probe_model_source(
    source: ModelSource,
    *,
    instance: BackendInstance | None,
    timeout_s: float,
) -> _ProbeResult:
    if source.endpoint.kind == "runtime_native":
        return _ProbeResult(
            status="skipped",
            detail="runtime-native auth; verify with 'forge runtime preflight codex'",
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

    console.print(f"[bold]Backend source:[/bold] [cyan]{source.id}[/cyan]")
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
            console.print(f"[bold]Runtime instance:[/bold] {instance.backend_id}")
            console.print(f"[bold]Runtime PID:[/bold] {instance.pid or '-'}")
            console.print(f"[bold]Runtime status:[/bold] {instance.status}")
            if shared_with:
                console.print(f"[bold]Shared with:[/bold] {', '.join(shared_with)}")
        else:
            console.print("[bold]Runtime instance:[/bold] -")

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
    """List built-in backend sources and local runtime state."""
    console = Console(width=200)
    runtime_instances = _load_runtime_instances()
    instance_sources = _instance_source_map(runtime_instances)
    records = [_source_record(source, runtime_instances, instance_sources) for source in list_model_sources()]

    if as_json:
        click.echo(json.dumps(records, indent=2, default=str))
        return

    table = Table(title="Forge Backend Sources")
    table.add_column("SOURCE ID", style="cyan")
    table.add_column("KIND")
    table.add_column("PROVIDER")
    table.add_column("ENDPOINT")
    table.add_column("AUTH")
    table.add_column("HEALTH")
    table.add_column("RUNTIME")

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
        runtime_table = Table(title="Unmatched Runtime Instances")
        runtime_table.add_column("RUNTIME", style="cyan")
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
@click.argument("backend_id")
@click.option("--raw", is_flag=True, help="Output raw config without syntax highlighting")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def show_cmd(backend_id: str, raw: bool, as_json: bool) -> None:
    """Show backend details and configuration.

    \b
    Examples:
        forge model backend show litellm-4000
    """
    console = Console(width=200)
    source = _source_for_identifier(backend_id)
    if source is not None:
        if as_json:
            runtime_instances = _load_runtime_instances()
            instance_sources = _instance_source_map(runtime_instances)
            click.echo(json.dumps(_source_record(source, runtime_instances, instance_sources), indent=2, default=str))
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
                    "config_path": str(json_config_path) if json_config_path.exists() else None,
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
        print_tip(
            f"Run '{_BACKEND_COMMAND} create {adapter_type}'.",
            blank_before=False,
            console=console,
        )


@backend.command("test-auth")
@click.argument("source_id")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option(
    "--timeout",
    type=float,
    default=5.0,
    show_default=True,
    help="Probe timeout in seconds",
)
def test_auth_cmd(source_id: str, as_json: bool, timeout: float) -> None:
    """Test a backend source's credential configuration and reachable auth endpoint."""
    console = Console(width=200)
    source = _source_for_identifier(source_id)
    if source is None:
        print_error(
            f"Unknown backend source '{source_id}'. Use '{_BACKEND_COMMAND} list' to see source ids.",
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
            detail="runtime-native auth; verify with 'forge runtime preflight codex'",
        )
    elif auth["status"] != "configured":
        missing = ", ".join(auth["missing_required_env_vars"])
        probe = _ProbeResult(status="skipped", detail=f"missing required credential values: {missing}")
    elif not source.capabilities.auth_probe:
        probe = _ProbeResult(status="skipped", detail="source does not declare an auth probe capability")
    else:
        probe = _probe_model_source(source, instance=instance, timeout_s=timeout)

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
        console.print(f"[bold]Backend source:[/bold] [cyan]{source.id}[/cyan]")
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
    help="Source config file (defaults to installed template)",
)
def create_cmd(adapter: str, config: Path | None) -> None:
    """Create a backend config (copy to installed location).

    Config is shared by all instances of this adapter type.
    """
    console = Console(width=200)
    try:
        adapter = _resolve_local_adapter_operand(adapter)
    except click.ClickException as e:
        _exit_click_error(e, console)

    config_path = get_backend_config_path(adapter)
    if config_path.exists():
        print_error_with_tip(
            f"Backend config already exists: {display_path(config_path)}",
            "Start an instance with:",
            commands=[f"{_BACKEND_COMMAND} start {adapter} --port 4000"],
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
        console.print(f"  {_BACKEND_COMMAND} start {adapter} --port 4000")
    except Exception as e:
        print_error(str(e), console=console)
        sys.exit(1)


@backend.command("start")
@click.argument("source_or_adapter")
@click.option("--port", "-p", type=int, required=False, help="Port number")
def start_cmd(source_or_adapter: str, port: int | None) -> None:
    """Start a local backend instance by source id or adapter."""
    console = Console(width=200)
    try:
        adapter, resolved_port = _resolve_lifecycle_operand(source_or_adapter, port)
    except click.ClickException as e:
        _exit_click_error(e, console)

    config_path = get_backend_config_path(adapter)
    if not config_path.exists():
        print_error_with_tip(
            f"Backend config not found for '{adapter}'",
            "Create it first:",
            commands=[f"{_BACKEND_COMMAND} create {adapter}"],
            console=console,
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
        print_error(str(e), console=console)
        sys.exit(1)


@backend.command("stop")
@click.argument("source_or_adapter")
@click.option("--port", "-p", type=int, required=False, help="Port number")
def stop_cmd(source_or_adapter: str, port: int | None) -> None:
    """Stop a local backend instance by source id or adapter."""
    console = Console(width=200)
    try:
        adapter, resolved_port = _resolve_lifecycle_operand(source_or_adapter, port)
    except click.ClickException as e:
        _exit_click_error(e, console)

    backend_id = f"{adapter}-{resolved_port}"

    store = BackendRegistryStore()
    manager = BackendManager(store)
    manager.register_adapter(adapter, get_adapter(adapter))

    try:
        manager.stop_backend(backend_id)
        console.print(f"[green]Stopped[/green] backend '{backend_id}'")
    except Exception as e:
        print_error(str(e), console=console)
        sys.exit(1)


@backend.command("delete")
@click.argument("adapter")
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
    try:
        adapter = _resolve_local_adapter_operand(adapter)
    except click.ClickException as e:
        _exit_click_error(e, console)

    if port is not None:
        backend_id = f"{adapter}-{port}"
        if not yes and not click.confirm(f"Stop backend instance '{backend_id}'?"):
            console.print("Cancelled.")
            return

        try:
            stop_cmd.callback(adapter, port)  # type: ignore[misc]  # click.Command.callback is Optional[Callable]; always set here
            console.print(f"[green]Stopped[/green] backend instance '{backend_id}'")
        except Exception as e:
            print_error(str(e), console=console)
            sys.exit(1)
    else:
        backend_dir = get_forge_home() / "backends" / adapter
        if not backend_dir.exists():
            print_error_with_tip(
                f"Backend config not found for '{adapter}'",
                "Create it first:",
                commands=[f"{_BACKEND_COMMAND} create {adapter}"],
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


@backend.command("reconcile")
@click.argument("source_id")
@click.option(
    "--request-id",
    "request_id",
    default=None,
    help="Local request id to join to a remote record (scoped to <source-id>).",
)
@click.option(
    "--remote-id",
    "remote_id",
    default=None,
    help="The backend's own record id (e.g. an OpenRouter gen-... id); remote-only.",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--timeout", type=float, default=5.0, show_default=True, help="Remote lookup timeout (seconds).")
def reconcile_cmd(source_id: str, request_id: str | None, remote_id: str | None, as_json: bool, timeout: float) -> None:
    """Reconcile local telemetry against a backend's remote account-side record.

    Provide exactly one of --request-id (local-anchored: local trace -> remote record) or
    --remote-id (remote-only: the backend's own record id, no local side).
    """
    if request_id and remote_id:
        print_error("Use only one of --request-id or --remote-id, not both.", console=err_console)
        sys.exit(1)
    if not request_id and not remote_id:
        print_error_with_tip(
            "Provide a local request id or a remote record id to reconcile.",
            "Use --request-id <id> (local) or --remote-id <id> (the backend's own record id).",
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
        print_error_with_tip(str(e), f"Run '{_BACKEND_COMMAND} list' to see source ids.", console=err_console)
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

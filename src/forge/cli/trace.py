"""CLI command group: forge telemetry trace.

Read-only surface over provider lifecycle/correlation fields in the downstream telemetry
plane (``~/.forge/telemetry/downstream/``): ``list`` recent traces, ``show`` one record,
``explain`` a local-only provenance narrative. Metadata-only; no secrets, no
prompt/completion text, and no remote lookups. Backed by the UI-agnostic ops in
``forge.core.ops.provider_trace`` so the table and ``--json`` cannot drift.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import click
from rich.console import Console
from rich.table import Table

from forge.cli.output import print_error_with_tip
from forge.core.ops import (
    ForgeOpError,
    explain_provider_trace,
    list_provider_traces,
    render_explanation_lines,
    show_provider_trace,
)
from forge.core.ops.context import ExecutionContext

console = Console(width=200)


def _period_bounds(period: str) -> tuple[datetime | None, datetime | None]:
    """Compute UTC start/end for a named period using the local timezone.

    ``all`` returns ``(None, None)`` so the op reads every retained shard.
    """
    now_local = datetime.now().astimezone()
    now_utc = datetime.now(timezone.utc)
    if period == "today":
        start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        return start, now_utc
    if period == "week":
        midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start = (midnight - timedelta(days=midnight.weekday())).astimezone(timezone.utc)
        return start, now_utc
    if period == "month":
        start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        return start, now_utc
    return None, None


def _short_time(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.rstrip("Z") + "+00:00").astimezone().strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        return ts or "-"


def _status_cell(final_usage_seen: bool, client_disconnected: bool, local_usage_status: str) -> str:
    if final_usage_seen:
        lifecycle = "ok"
    elif client_disconnected:
        lifecycle = "[yellow]disconnect[/yellow]"
    else:
        lifecycle = "no-usage"
    return f"{lifecycle} / {local_usage_status}"


@click.group("trace", context_settings={"help_option_names": ["-h", "--help"]})
def trace() -> None:
    """Local provider-trace records (metadata only; no secrets, no remote lookups)."""


@trace.command("list")
@click.option("--session", default=None, help="Filter by session name (session-label match; see note)")
@click.option("--root-run-id", "root_run_id", default=None, help="Filter by exact forge_root_run_id (precise)")
@click.option(
    "--period",
    type=click.Choice(["today", "week", "month", "all"]),
    default="today",
    help="Time window (default: today)",
)
@click.option("--limit", type=int, default=50, help="Max records to show (default: 50)")
@click.option("--json", "as_json", is_flag=True, help="Output records as a JSON array")
def trace_list(session: str | None, root_run_id: str | None, period: str, limit: int, as_json: bool) -> None:
    """List recent provider traces.

    \b
    Examples:
        forge telemetry trace list                          # today, all sessions
        forge telemetry trace list --session my-session     # by session label
        forge telemetry trace list --root-run-id run_abc... # exact run tree
        forge telemetry trace list --period week --json

    Note: --session matches the hashed session *label* only (two same-named sessions in
    one FORGE_HOME share it); use --root-run-id when exactness matters.
    """
    start, end = _period_bounds(period)
    try:
        result = list_provider_traces(
            ctx=ExecutionContext.from_cwd(),
            session=session,
            root_run_id=root_run_id,
            period_start=start,
            period_end=end,
            limit=limit,
        )
    except ForgeOpError as e:
        print_error_with_tip(str(e), "Provider traces live in '~/.forge/telemetry/downstream/'.", console=console)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps([asdict(r) for r in result.traces], indent=2, default=str))
        return

    if not result.traces:
        scope = f" (session {session})" if session else (f" (root {root_run_id})" if root_run_id else "")
        console.print(f"[dim]No provider traces for {period}{scope}.[/dim]")
        return

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Time", style="dim")
    table.add_column("Request", style="cyan")
    table.add_column("Proxy")
    table.add_column("Model")
    table.add_column("Session", style="dim")
    table.add_column("Role", style="dim")
    table.add_column("Status")
    for r in result.traces:
        table.add_row(
            _short_time(r.ts),
            r.request_id,
            r.proxy_id,
            r.mapped_model,
            r.provider_session_id or "-",
            r.provider_command or "-",
            _status_cell(r.final_usage_seen, r.client_disconnected, r.local_usage_status),
        )
    console.print(table)


@trace.command("show")
@click.argument("request_id")
@click.option("--json", "as_json", is_flag=True, help="Output the record as JSON")
def trace_show(request_id: str, as_json: bool) -> None:
    """Show the full provider-trace record for a request id."""
    try:
        result = show_provider_trace(ctx=ExecutionContext.from_cwd(), request_id=request_id)
    except ForgeOpError as e:
        print_error_with_tip(str(e), "Run 'forge telemetry trace list' to see recent request ids.", console=console)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(asdict(result.record), indent=2, default=str))
        return

    rec = result.record
    console.print(f"[bold]Provider trace:[/bold] {rec.request_id}")
    for label, value in (
        ("Time", rec.ts),
        ("Proxy", rec.proxy_id),
        ("Provider", rec.provider),
        ("Model", rec.mapped_model),
        ("Upstream", rec.selected_provider),
        ("Mode", rec.request_mode),
        ("Generation id", rec.provider_generation_id),
        ("Provider response id", rec.provider_response_id),
        ("Provider request id", rec.provider_request_id),
        ("Session", rec.provider_session_id),
        ("Role", rec.provider_command),
        ("Run id", rec.forge_run_id),
        ("Root run id", rec.forge_root_run_id),
        ("Stream started", rec.stream_started),
        ("First chunk seen", rec.first_chunk_seen),
        ("Final usage seen", rec.final_usage_seen),
        ("Client disconnected", rec.client_disconnected),
        ("Local usage status", rec.local_usage_status),
        ("Reported cost (micros)", rec.reported_cost_micros),
        ("Latency (ms)", rec.latency_ms),
    ):
        if value is not None:
            console.print(f"  {label}: {value}")


@trace.command("explain")
@click.argument("request_id")
@click.option("--json", "as_json", is_flag=True, help="Output the structured explanation as JSON")
def trace_explain(request_id: str, as_json: bool) -> None:
    """Explain what happened to a request, from local records only (no remote lookup)."""
    try:
        explanation = explain_provider_trace(ctx=ExecutionContext.from_cwd(), request_id=request_id)
    except ForgeOpError as e:
        print_error_with_tip(str(e), "Run 'forge telemetry trace list' to see recent request ids.", console=console)
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(asdict(explanation), indent=2, default=str))
        return

    for line in render_explanation_lines(explanation):
        console.print(line)

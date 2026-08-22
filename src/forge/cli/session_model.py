"""``forge session model`` route-provenance read surfaces."""

from __future__ import annotations

import json
import sys

import click
from rich.table import Table

from forge.cli.output import err_console, print_error
from forge.cli.session import console
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import ForgeOpError
from forge.core.ops.session_model import (
    MODEL_REPORT_LIMITATIONS,
    get_session_model_history_report,
    get_session_model_report,
)
from forge.session.exceptions import ForgeSessionError


@click.group("model")
def session_model() -> None:
    """Inspect the model route committed for a managed session."""


@session_model.command("show")
@click.argument("session_name", required=False)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def show_cmd(session_name: str | None, as_json: bool) -> None:
    """Show route intent, committed evidence, and current proxy facts."""
    try:
        report = get_session_model_report(ctx=ExecutionContext.from_cwd(), session_name=session_name)
    except (ForgeOpError, ForgeSessionError, ValueError) as exc:
        print_error(str(exc), console=err_console)
        sys.exit(1)
    payload = report.to_dict()
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return

    commit = payload["route_commit"]
    live = payload["live_proxy"]
    table = Table(show_header=False, box=None)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Session", payload["session"])
    table.add_row("Runtime", payload["runtime"])
    table.add_row("Active", "yes" if payload["active"] else "no")
    table.add_row("Intent", payload["route_intent"]["kind"])
    table.add_row(
        "Committed route",
        commit["kind"] if commit and commit["kind"] else "unavailable",
    )
    table.add_row("Route evidence", commit["evidence_source"] if commit else "none")
    table.add_row("History", payload["history_status"] or "no claim")
    table.add_row("Live proxy", live["evidence_source"])
    table.add_row("Default tier", live["default_tier"] or "-")
    table.add_row("Launch marking entries", str(len(payload["marking"]["launch_entries"])))
    table.add_row("Live marking entries", str(len(payload["marking"]["live_proxy_entries"])))
    console.print(table)
    console.print("\n[bold]Limitations[/bold]")
    for limitation in payload["limitations"]:
        console.print(f"- {limitation}")


@session_model.command("history")
@click.argument("session_name", required=False)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def history_cmd(session_name: str | None, as_json: bool) -> None:
    """Show validated route events in append order."""
    try:
        report = get_session_model_history_report(ctx=ExecutionContext.from_cwd(), session_name=session_name)
    except (ForgeOpError, ForgeSessionError, ValueError) as exc:
        print_error(str(exc), console=err_console)
        sys.exit(1)
    payload = report.to_dict()
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return

    if payload["events"]:
        for index, event in enumerate(payload["events"], start=1):
            if index > 1:
                console.print()
            console.print(f"[bold]Event {index}[/bold]")
            table = Table(show_header=False, box=None)
            table.add_column("Field", style="bold")
            table.add_column("Value")
            table.add_row("Timestamp", event["timestamp"])
            table.add_row("Event ID", event["event_id"])
            table.add_row("Event", event["event_type"])
            table.add_row("Run", event["run_id"] or "-")
            table.add_row("Route", event["payload"]["route"]["kind"])
            table.add_row("Models", _model_slot_summary(event["payload"]["marking_snapshots"]))
            table.add_row("Outcome", event["outcome"])
            console.print(table)
    else:
        console.print("No routing events.")
    console.print(f"History support: {payload['history_status'] or 'no claim'}")
    console.print("\n[bold]Limitations[/bold]")
    for limitation in MODEL_REPORT_LIMITATIONS:
        console.print(f"- {limitation}")


def _model_slot_summary(snapshots: object) -> str:
    if not isinstance(snapshots, list):
        return "-"
    parts: list[str] = []
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        slot = snapshot.get("slot")
        tier = snapshot.get("tier")
        request = snapshot.get("request_model")
        route = snapshot.get("route_model")
        if slot == "direct" and isinstance(route, str):
            parts.append(f"direct={route}")
        elif slot == "tier_default" and isinstance(tier, str) and isinstance(route, str):
            parts.append(f"{tier}={route}")
        elif (
            slot == "model_alternative"
            and isinstance(tier, str)
            and isinstance(request, str)
            and isinstance(route, str)
        ):
            parts.append(f"{tier}:{request}->{route}")
    return "; ".join(parts) or "-"

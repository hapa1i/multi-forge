"""``forge session model`` route-provenance read surfaces."""

from __future__ import annotations

import json
import sys
from typing import Any

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

    table = Table(show_header=False, box=None)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    for field, value in session_model_summary_rows(payload):
        table.add_row(field, value)
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


def session_model_summary_rows(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Return the fixed-size human summary shared by terminal and direct reads."""
    commit = payload["route_commit"]
    live = payload["live_proxy"]
    return [
        ("Session", payload["session"]),
        ("Runtime", payload["runtime"]),
        ("Active", "yes" if payload["active"] else "no"),
        ("Intent", payload["route_intent"]["kind"]),
        ("Committed route", commit["kind"] if commit and commit["kind"] else "unavailable"),
        ("Route evidence", commit["evidence_source"] if commit else "none"),
        ("History", payload["history_status"] or "no claim"),
        ("Live proxy", live["evidence_source"]),
        ("Default tier", live["default_tier"] or "-"),
        ("Launch marking entries", str(len(payload["marking"]["launch_entries"]))),
        ("Live marking entries", str(len(payload["marking"]["live_proxy_entries"]))),
    ]


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

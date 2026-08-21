"""``forge session authority`` control and posture surfaces."""

from __future__ import annotations

import json
import sys

import click
from rich.table import Table

from forge.cli.output import err_console, print_error
from forge.cli.session import console
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import ForgeOpError
from forge.core.ops.session_authority import (
    clear_session_authority,
    get_session_authority_report,
    set_session_authority,
)
from forge.session.exceptions import ForgeSessionError


@click.group("authority")
def session_authority() -> None:
    """Assign and inspect artifact authority for a managed session."""


@session_authority.command("set")
@click.argument("session_name")
@click.option("--role", type=click.Choice(["advisory", "producer"]), required=True)
@click.option("--tier", type=click.Choice(["named_tools", "shell_closed"]), default=None)
def set_cmd(session_name: str, role: str, tier: str | None) -> None:
    """Assign advisory or positive producer authority to an inactive session."""
    try:
        result = set_session_authority(
            ctx=ExecutionContext.from_cwd(),
            session_name=session_name,
            role=role,
            tier=tier,
        )
    except (ForgeOpError, ForgeSessionError) as exc:
        print_error(str(exc), console=err_console)
        sys.exit(1)
    tier_text = f" ({result.tier})" if result.tier is not None else ""
    console.print(f"Authority for [cyan]{result.session}[/cyan]: {result.role}{tier_text}.")


@session_authority.command("clear")
@click.argument("session_name")
def clear_cmd(session_name: str) -> None:
    """Remove the complete authority designation from an inactive session."""
    try:
        result = clear_session_authority(ctx=ExecutionContext.from_cwd(), session_name=session_name)
    except (ForgeOpError, ForgeSessionError) as exc:
        print_error(str(exc), console=err_console)
        sys.exit(1)
    console.print(f"Authority for [cyan]{result.session}[/cyan] cleared; the session is unmarked.")


@session_authority.command("show")
@click.argument("session_name", required=False)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def show_cmd(session_name: str | None, as_json: bool) -> None:
    """Show configured intent, local history support, and live launch support."""
    try:
        report = get_session_authority_report(
            ctx=ExecutionContext.from_cwd(),
            session_name=session_name,
        )
    except (ForgeOpError, ForgeSessionError) as exc:
        print_error(str(exc), console=err_console)
        sys.exit(1)
    payload = report.to_dict()
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return

    table = Table(show_header=False, box=None)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Session", report.session)
    table.add_row("Role", report.role or "unmarked")
    table.add_row("Tier", report.tier or "-")
    table.add_row("Runtime", report.runtime)
    table.add_row("Active", "yes" if report.active else "no")
    table.add_row("Launch support", report.launch_support or "not applicable")
    table.add_row("Configuration history", report.configuration_history or "no claim")
    denial_count = report.observed_denials["count"]
    denial_window = ""
    if denial_count:
        denial_window = f" (first {report.observed_denials['first_at']}, " f"last {report.observed_denials['last_at']})"
    table.add_row("Observed denials", f"{denial_count}{denial_window}")
    table.add_row("Covered tools", ", ".join(report.covered_tools) or "-")
    table.add_row("Read-only tools", ", ".join(report.read_only_tools) or "-")
    table.add_row("Control tools", ", ".join(report.control_tools) or "-")
    console.print(table)
    console.print("\n[bold]Limitations[/bold]")
    for limitation in report.limitations:
        console.print(f"- {limitation}")

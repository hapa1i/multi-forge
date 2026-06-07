"""``forge activity`` — per-session Forge *automation* activity (supervisor, memory
writer, workflow verbs) + policy decisions. NOT your full interactive Claude usage.

Reads the two already-captured planes (usage ledger + ``confirmed.policy.decisions``)
via :func:`forge.core.ops.usage_summary.build_session_activity_summary` and renders a
table. Cost is reported-or-estimated (best-effort attribution) — ``forge proxy costs show``
stays the authoritative spend view.
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
from forge.core.ops.session_context import (
    SessionContextError,
    resolve_session_identifier,
)
from forge.core.ops.usage_summary import (
    SessionActivitySummary,
    build_session_activity_summary,
)

console = Console()


@click.command("activity")
@click.argument("session", required=False)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--days", "-d", type=int, default=30, help="Look back this many days (default: 30)")
@click.option("--all", "all_time", is_flag=True, help="Report all time (ignore --days)")
def activity_cmd(session: str | None, as_json: bool, days: int, all_time: bool) -> None:
    """Show Forge's automation activity for a session: supervisor checks, cost, tokens.

    This is what Forge did *on top of* your session — the supervisor, memory writer,
    and workflow verbs (panel/debate/...) — plus policy decisions. It is **not** your
    full interactive Claude usage. Reads the usage ledger and the session's
    policy-decision log. Cost is reported-or-estimated (best-effort attribution);
    'forge proxy costs show' is the authoritative spend view.

    \b
    Examples:
        forge activity                  # current session ($FORGE_SESSION)
        forge activity planner          # a named session (or Claude UUID)
        forge activity --all --json     # full history, JSON
    """
    try:
        session_name, forge_root = resolve_session_identifier(session)
    except SessionContextError as e:
        if as_json:
            click.echo(json.dumps({"error": str(e)}))
        else:
            print_error_with_tip(
                str(e),
                "Run 'forge session list' to see sessions.",
                console=console,
            )
        sys.exit(1)

    since = None if all_time else datetime.now(timezone.utc) - timedelta(days=days)
    summary = build_session_activity_summary(session_name, forge_root, since=since)

    if as_json:
        console.print_json(data=asdict(summary))
        return
    _render(summary, days=None if all_time else days)


def _render(summary: SessionActivitySummary, *, days: int | None) -> None:
    scope = "all time" if days is None else f"last {days}d"
    if summary.is_empty:
        console.print(f"[dim]No Forge activity for session '{summary.session}' ({scope}).[/dim]")
        return

    console.print(f"\n[bold]Forge activity — {summary.session}[/bold] [dim]({scope})[/dim]")
    console.print(
        "[dim]Forge automation (supervisor, memory writer, workflow verbs) — "
        "not your full interactive session.[/dim]"
    )

    if summary.commands:
        # The Workers column only earns its width when a fan-out (panel/debate/...) ran;
        # supervisor/memory-writer have no workers, so most sessions skip it.
        show_workers = any(c.workers for c in summary.commands)
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("Command", style="cyan")
        table.add_column("Calls", justify="right")
        if show_workers:
            table.add_column("Workers", justify="right", style="dim")
        table.add_column("Errors", justify="right")
        table.add_column("Tokens in/out", justify="right", style="dim")
        table.add_column("Cost", justify="right", style="dim")
        for c in summary.commands:
            errors = f"[red]{c.errors}[/red]" if c.errors else "0"
            tokens = f"{c.input_tokens}/{c.output_tokens}" if (c.input_tokens or c.output_tokens) else "-"
            cost = f"~{_fmt_usd(c.cost_micro_usd)}" if c.cost_micro_usd is not None else "-"
            row = [c.command, str(c.calls)]
            if show_workers:
                row.append(str(c.workers) if c.workers else "-")
            row += [errors, tokens, cost]
            table.add_row(*row)
        console.print(table)

    pol = summary.policy
    if pol and pol.has_content:
        console.print(
            f"\n[bold]Supervisor[/bold]: {pol.supervisor_allow} allow · "
            f"{pol.supervisor_warn} warn · {pol.supervisor_deny} block"
        )
        for warning in pol.recent_warnings:
            console.print(f"  [yellow]•[/yellow] {warning}")

    if summary.subagents:
        console.print(f"\n[bold]Subagents[/bold]: {summary.subagents}")

    total_cost = f"~{_fmt_usd(summary.total_cost_micro_usd)}" if summary.total_cost_micro_usd is not None else "n/a"
    console.print(
        f"\n[dim]Total:[/dim] {summary.total_events} events · "
        f"{summary.total_input_tokens}/{summary.total_output_tokens} tok · {total_cost}"
    )

    for note in _footnotes(summary):
        console.print(f"[dim]{note}[/dim]")


def _footnotes(summary: SessionActivitySummary) -> list[str]:
    notes: list[str] = []
    if summary.cost_partial:
        notes.append("cost is best-effort and partial (some calls report no cost)")
    if summary.policy is not None and summary.policy.log_capped:
        notes.append("policy decision log is at capacity — older decisions may not be shown")
    if summary.session_tagging_partial:
        notes.append("some calls (e.g. the action tagger) are not session-attributed")
    notes.append("cost is reported-or-estimated, best-effort; 'forge proxy costs show' is the authoritative spend view")
    return notes


def _fmt_usd(micros: int | None) -> str:
    if micros is None:
        return "-"
    dollars = micros / 1_000_000
    if dollars and abs(dollars) < 0.01:
        return f"${dollars:.4f}"
    return f"${dollars:.2f}"

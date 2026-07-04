"""``forge telemetry activity`` — per-session Forge automation outcomes plus model-call evidence.

Reads upstream outcomes, downstream attempts, transitional usage events, and the capped
manifest policy fallback via :func:`forge.core.ops.usage_summary.build_session_activity_summary`.
Cost is reported-or-estimated (best-effort attribution) — ``forge telemetry costs show`` stays the
authoritative spend view.
"""

from __future__ import annotations

import json
import sys
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
    activity_summary_to_json,
    build_session_activity_summary,
    format_failing_open,
)

console = Console()
_SESSION_LIST_TIP = "Run 'forge session list' to see sessions."
_PERIOD_CHOICES = ("today", "week", "month", "all")


@click.command("activity")
@click.argument("session", required=False)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option(
    "--period",
    type=click.Choice(_PERIOD_CHOICES),
    default="today",
    show_default=True,
    help="Time window",
)
def activity_cmd(session: str | None, as_json: bool, period: str) -> None:
    """Show Forge automation outcomes and model-call evidence for a session.

    This is what Forge did *on top of* your session — the supervisor, memory writer,
    workflow verbs (panel/debate/...), transfer curation, and action tagging — plus
    the model-call evidence Forge can attribute to those operations. It is **not** your
    full interactive Claude usage. Cost is reported-or-estimated (best-effort attribution);
    'forge telemetry costs show' is the authoritative spend view.

    \b
    Examples:
        forge telemetry activity                  # current session ($FORGE_SESSION)
        forge telemetry activity planner          # a named session (or Claude UUID)
        forge telemetry activity --period week    # this week
        forge telemetry activity --period all --json
    """
    try:
        session_name, forge_root = resolve_session_identifier(session)
    except SessionContextError as e:
        if as_json:
            click.echo(
                json.dumps({"error": str(e), "tip": _SESSION_LIST_TIP}), err=True
            )
        else:
            print_error_with_tip(
                str(e),
                _SESSION_LIST_TIP,
            )
        sys.exit(1)

    since = _period_start(period)
    summary = build_session_activity_summary(session_name, forge_root, since=since)

    if as_json:
        console.print_json(data=activity_summary_to_json(summary))
        return
    _render(summary, period=period)


def _period_start(period: str) -> datetime | None:
    """Return the UTC lower bound for a named local-calendar period."""
    now_local = datetime.now()
    if period == "today":
        return now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(
            timezone.utc
        )
    if period == "week":
        local_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        return (local_midnight - timedelta(days=local_midnight.weekday())).astimezone(
            timezone.utc
        )
    if period == "month":
        return now_local.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).astimezone(timezone.utc)
    return None


def _render(summary: SessionActivitySummary, *, period: str) -> None:
    scope = {
        "today": "today",
        "week": "this week",
        "month": "this month",
        "all": "all time",
    }[period]
    if summary.is_empty:
        console.print(
            f"[dim]No Forge activity for session '{summary.session}' ({scope}).[/dim]"
        )
        if note := _legacy_schema_note(summary.downstream.skipped_legacy_schema):
            console.print(f"[dim]{note}[/dim]")
        return

    console.print(
        f"\n[bold]Forge activity — {summary.session}[/bold] [dim]({scope})[/dim]"
    )
    console.print(
        "[dim]Forge automation (supervisor, memory writer, workflow verbs) — "
        "not your full interactive session.[/dim]"
    )

    pol = summary.policy
    # Fail-open breakdown is ledger-derived (the supervisor CommandUsage), so the
    # Supervisor line must render even when there is no decision log (pol is None) --
    # the acceptance case is a session whose every supervisor run timed out.
    sup_cmd = next((c for c in summary.commands if c.command == "supervisor"), None)
    failing = format_failing_open(sup_cmd)

    console.print("\n[bold]Operation outcomes[/bold]")

    rendered_operation_content = False
    if pol and (pol.plan_check_allow or pol.plan_check_needs_review):
        console.print(
            f"Plan check (tier-1): {pol.plan_check_allow} allow · "
            f"{pol.plan_check_needs_review} needs review"
        )
        rendered_operation_content = True

    sup_has_pol = bool(
        pol
        and (
            pol.supervisor_allow
            or pol.supervisor_warn
            or pol.supervisor_deny
            or pol.total_warnings
        )
    )
    if sup_has_pol or failing:
        bits: list[str] = []
        if sup_has_pol and pol is not None:
            bits.append(
                f"{pol.supervisor_allow} allow · {pol.supervisor_warn} warn · {pol.supervisor_deny} block"
            )
        if failing:
            bits.append(f"[red]{failing}[/red]")
        console.print("Supervisor: " + " · ".join(bits))
        rendered_operation_content = True

    for warning in pol.recent_warnings if pol else ():
        console.print(f"  [yellow]•[/yellow] {warning}")

    if summary.upstream.operations:
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("Command", style="cyan")
        table.add_column("Operation", style="dim")
        table.add_column("Status")
        table.add_column("Count", justify="right")
        table.add_column("Join", style="dim")
        table.add_column("Reason", style="dim")
        for operation_row in summary.upstream.operations:
            status = (
                f"[red]{operation_row.status}[/red]"
                if operation_row.status in {"error", "timeout", "deny"}
                else operation_row.status
            )
            table.add_row(
                operation_row.command,
                operation_row.operation or operation_row.policy_id or "-",
                status,
                str(operation_row.count),
                operation_row.join_state.replace("_", "-"),
                operation_row.reason_code or "-",
            )
        console.print(table)
        rendered_operation_content = True
    if not rendered_operation_content:
        console.print("[dim]No upstream outcomes recorded for this window.[/dim]")

    if summary.downstream.rows:
        console.print("\n[bold]Model calls[/bold]")
        show_workers = any(row.workers for row in summary.downstream.rows)
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
        table.add_column("Command", style="cyan")
        table.add_column("Calls", justify="right")
        if show_workers:
            table.add_column("Workers", justify="right", style="dim")
        table.add_column("Attempts", justify="right")
        table.add_column("Errors", justify="right")
        table.add_column("Join", style="dim")
        table.add_column("Runtime/Billing", style="dim")
        table.add_column("Tokens in/out", justify="right", style="dim")
        table.add_column("Cost", justify="right", style="dim")
        for model_row in summary.downstream.rows:
            tokens = (
                f"{model_row.input_tokens}/{model_row.output_tokens}"
                if (model_row.input_tokens or model_row.output_tokens)
                else "-"
            )
            if model_row.cost_micro_usd is None:
                cost = "-"
            else:
                cost = f"{'~' if model_row.cost_estimated else ''}{_fmt_usd(model_row.cost_micro_usd)}"
            # T5/WS3: the lane the row's usage events ran on. "-" for a downstream-only row
            # (no usage-event source); "mixed" when the command's events disagree.
            if not model_row.runtime and not model_row.billing_mode:
                lane = "-"
            else:
                lane = f"{model_row.runtime or '?'}/{model_row.billing_mode or '?'}"
            values = [model_row.command, str(model_row.calls)]
            if show_workers:
                values.append(str(model_row.workers) if model_row.workers else "-")
            errors = f"[red]{model_row.errors}[/red]" if model_row.errors else "0"
            values += [
                str(model_row.attempts),
                errors,
                model_row.join_state.replace("_", "-"),
                lane,
                tokens,
                cost,
            ]
            table.add_row(*values)
        console.print(table)

    sh = summary.shadow
    if sh is not None and sh.has_content:
        line = f"\n[bold]Shadow (audit)[/bold]: {sh.checked} checked"
        if sh.checked:
            line += f" · {sh.agree} agree · [yellow]{sh.disagree} disagree[/yellow] · {sh.inconclusive} inconclusive"
            if sh.error:
                line += f" · [red]{sh.error} error[/red]"
        if sh.pending:
            line += f" · {sh.pending} pending"
        console.print(line)

    if summary.subagents:
        console.print(f"\n[bold]Subagents[/bold]: {summary.subagents}")

    if summary.total_cost_micro_usd is None:
        total_cost = "n/a"
    else:
        total_cost = f"{'~' if summary.cost_estimated else ''}{_fmt_usd(summary.total_cost_micro_usd)}"
    console.print(
        f"\n[dim]Total:[/dim] {summary.total_events} events · "
        f"{summary.total_input_tokens}/{summary.total_output_tokens} tok · {total_cost}"
    )

    for note in _footnotes(summary):
        console.print(f"[dim]{note}[/dim]")


def _footnotes(summary: SessionActivitySummary) -> list[str]:
    notes: list[str] = []
    if note := _legacy_schema_note(summary.downstream.skipped_legacy_schema):
        notes.append(note)
    if summary.cost_partial:
        notes.append("cost is best-effort and partial (some calls report no cost)")
    if summary.upstream.log_capped:
        notes.append(
            "policy decision log is at capacity — older decisions may not be shown"
        )
    if summary.session_tagging_partial:
        notes.append("some calls (e.g. the action tagger) are not session-attributed")
    # "no snapshot estimates" covers both exact sources: the 4g cost-plane root-join
    # and runtime-reported (runtime_native) self-reports. A cost-less summary keeps
    # the generic caveat -- there is no figure to call exact.
    exact = summary.total_cost_micro_usd is not None and not summary.cost_estimated
    evidence = (
        "reported (no snapshot estimates mixed in)"
        if exact
        else "reported-or-estimated"
    )
    notes.append(
        f"cost is {evidence}, best-effort; 'forge telemetry costs show' is the authoritative spend view"
    )
    return notes


def _legacy_schema_note(skipped: int) -> str | None:
    if not skipped:
        return None
    plural = "" if skipped == 1 else "s"
    return f"skipped {skipped} downstream telemetry record{plural} from an older Forge schema in this window"


def _fmt_usd(micros: int | None) -> str:
    if micros is None:
        return "-"
    dollars = micros / 1_000_000
    if dollars and abs(dollars) < 0.01:
        return f"${dollars:.4f}"
    return f"${dollars:.2f}"

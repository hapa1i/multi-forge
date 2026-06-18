"""CLI command group: forge proxy audit (Phase 2 audit proxy).

Reads the redacted downstream audit records written by the proxy in inspect/override
mode (``~/.forge/telemetry/downstream/``). Metadata-only by default; the records are
already redacted, so no secrets or message text are ever printed.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import click
from rich.console import Console
from rich.table import Table

console = Console(stderr=True, width=200)


def _period_bounds(period: str) -> tuple[datetime, datetime]:
    """Compute UTC start/end for a named period using the local timezone."""
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
    return datetime.min.replace(tzinfo=timezone.utc), now_utc


def _short_hash(value: str | None) -> str:
    return value.removeprefix("sha256:")[:10] if value else "-"


def _short_time(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.rstrip("Z") + "+00:00").astimezone().strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        return ts or "-"


@click.group("audit", context_settings={"help_option_names": ["-h", "--help"]})
def audit_cmd() -> None:
    """Inspect proxy audit records (metadata by default; secrets never printed)."""


@audit_cmd.command("show")
@click.argument("proxy_id", required=False, default=None)
@click.option(
    "--period",
    type=click.Choice(["today", "week", "month", "all"]),
    default="today",
    help="Time period to show (default: today)",
)
@click.option("--limit", type=int, default=20, help="Max records to show (default: 20)")
@click.option("--json", "as_json", is_flag=True, help="Output raw records as JSON")
def audit_show_cmd(proxy_id: str | None, period: str, limit: int, as_json: bool) -> None:
    """Show recent audit metadata (system-prompt/tool hashes, drift, mode).

    \b
    Examples:
        forge proxy audit show                 # today, all proxies
        forge proxy audit show audit-test      # filter to one proxy
        forge proxy audit show --period week --json
    """
    from forge.proxy.audit_logger import read_audit_logs

    if period == "all":
        records = read_audit_logs(proxy_id=proxy_id)
    else:
        start, end = _period_bounds(period)
        records = read_audit_logs(start, end, proxy_id=proxy_id)

    records = records[-limit:]

    if as_json:
        click.echo(json.dumps(records, indent=2))
        return

    if not records:
        scope = f" ({proxy_id})" if proxy_id else ""
        console.print(f"[dim]No audit data for {period}{scope}.[/dim]")
        return

    scope = f" ({proxy_id})" if proxy_id else ""
    console.print(f"\n[bold]Audit ({period}{scope}):[/bold]")

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Time", style="dim")
    table.add_column("Proxy", style="cyan")
    table.add_column("Type")
    table.add_column("Mode")
    table.add_column("System", style="dim")
    table.add_column("Tools", style="dim")
    table.add_column("Detail", style="dim")

    has_full_body = False
    for record in records:
        rtype = record.get("record_type", "request")
        if rtype == "drift":
            detail = (
                f"{record.get('dimension')}: "
                f"{_short_hash(record.get('previous_hash'))} -> {_short_hash(record.get('current_hash'))}"
            )
            table.add_row(
                _short_time(record.get("ts", "")),
                record.get("proxy_id", "-"),
                "[yellow]drift[/yellow]",
                "-",
                "-",
                "-",
                detail,
            )
            continue

        if record.get("full_body"):
            has_full_body = True
        counts = record.get("counts", {})
        detail = f"{counts.get('num_messages', '?')} msgs, {counts.get('num_tools', '?')} tools"
        if record.get("full_body"):
            # Honest about scope: streaming/translated records capture the request
            # only; non-streaming passthrough also captures the redacted response.
            detail += " [req+resp]" if record.get("response_body") is not None else " [req-body]"
        table.add_row(
            _short_time(record.get("ts", "")),
            record.get("proxy_id", "-"),
            rtype,
            record.get("mode", "-"),
            _short_hash(record.get("system_prompt_hash")),
            _short_hash(record.get("tool_surface_hash")),
            detail,
        )

    console.print(table)
    console.print()

    if has_full_body:
        from forge.cli.output import print_tip
        from forge.core.paths import display_path, get_forge_home

        print_tip(
            "Full-body audit is enabled; downstream telemetry contains redacted request/response structure at "
            f"{display_path(get_forge_home() / 'telemetry' / 'downstream')}.",
            console=console,
        )


def _mutation_rows(record: dict) -> list[tuple[str, str]]:
    """Render an override mutation record into (what, change) display rows."""
    sys_before = _short_hash(record.get("system_prompt_hash_before"))
    sys_after = _short_hash(record.get("system_prompt_hash_after"))
    rows: list[tuple[str, str]] = []
    for mutation in record.get("mutations", []):
        action = mutation.get("action")
        target = mutation.get("target", "-")
        if action == "augment":
            extra = ", cache-inval" if mutation.get("cache_invalidation_expected") else ""
            rows.append(
                (f"{target} augment", f"{sys_before} -> {sys_after}  (+{mutation.get('augment_len')} chars{extra})")
            )
        elif action == "reasoning_pin":
            rows.append(
                (
                    "thinking pin",
                    f"{mutation.get('budget_before')} -> {mutation.get('budget_after')} tok (floor={mutation.get('effort_floor')})",
                )
            )
        elif action == "strip":
            rows.append(
                (f"{target} strip", f"{sys_before} -> {sys_after}  (stripped {mutation.get('stripped_count')})")
            )
        elif action in ("warn", "block"):
            rows.append((f"{target} {action}", f"matched {_short_hash(mutation.get('pattern_hash'))}"))
        else:
            rows.append((f"{target} {action}", "-"))
    return rows or [("-", "-")]


@audit_cmd.command("diff")
@click.argument("proxy_id", required=False, default=None)
@click.option(
    "--period",
    type=click.Choice(["today", "week", "month", "all"]),
    default="week",
    help="Time period to show (default: week)",
)
@click.option("--limit", type=int, default=30, help="Max changes to show (default: 30)")
@click.option("--json", "as_json", is_flag=True, help="Output raw records as JSON")
def audit_diff_cmd(proxy_id: str | None, period: str, limit: int, as_json: bool) -> None:
    """Show what changed on the wire over time: drift + override mutations.

    Folds system-prompt/tool-surface drift (tagged drift) and override before/after
    mutations (tagged mutation) into one timeline -- "what changed, and who changed it."
    Hashes/lengths only; never plaintext.

    \b
    Examples:
        forge proxy audit diff                 # this week, all proxies
        forge proxy audit diff audit-test      # one proxy
        forge proxy audit diff --period all --json
    """
    from forge.proxy.audit_logger import read_audit_logs

    if period == "all":
        records = read_audit_logs(proxy_id=proxy_id)
    else:
        start, end = _period_bounds(period)
        records = read_audit_logs(start, end, proxy_id=proxy_id)
    changes = [r for r in records if r.get("record_type") in ("drift", "mutation")][-limit:]

    if as_json:
        click.echo(json.dumps(changes, indent=2))
        return

    if not changes:
        scope = f" ({proxy_id})" if proxy_id else ""
        console.print(f"[dim]No wire changes for {period}{scope}.[/dim]")
        return

    scope = f" ({proxy_id})" if proxy_id else ""
    console.print(f"\n[bold]Wire changes ({period}{scope}):[/bold]")

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Time", style="dim")
    table.add_column("Proxy", style="cyan")
    table.add_column("Kind")
    table.add_column("What")
    table.add_column("Change", style="dim")

    for record in changes:
        ts = _short_time(record.get("ts", ""))
        pid = record.get("proxy_id", "-")
        if record.get("record_type") == "drift":
            table.add_row(
                ts,
                pid,
                "[yellow]drift[/yellow]",
                record.get("dimension", "-"),
                f"{_short_hash(record.get('previous_hash'))} -> {_short_hash(record.get('current_hash'))}",
            )
        else:  # mutation
            kind = "[red]blocked[/red]" if record.get("blocked") else "[magenta]mutation[/magenta]"
            for what, change in _mutation_rows(record):
                table.add_row(ts, pid, kind, what, change)

    console.print(table)
    console.print()

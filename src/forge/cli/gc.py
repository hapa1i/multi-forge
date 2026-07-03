"""CLI command: forge clean — garbage collection for orphaned Forge state."""

from __future__ import annotations

import json
import sys

import click
from rich.console import Console

from forge.cli.output import err_console, print_error, print_tip
from forge.core.ops.context import ExecutionContext
from forge.core.ops.gc import CleanError, CleanReport, collect_clean_report, run_clean


@click.command("clean")
@click.option(
    "--scope",
    type=click.Choice(["workspace", "project", "all"]),
    default="workspace",
    help="Scope: workspace (default), project, or all",
)
@click.option("--yes", "-y", is_flag=True, help="Actually delete (default is dry-run)")
@click.option("--verbose", "-v", is_flag=True, help="Show individual items")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def clean_cmd(scope: str, yes: bool, verbose: bool, as_json: bool) -> None:
    """Remove orphaned Forge state (sessions, transfer files, stale entries).

    By default, shows what would be cleaned (dry-run). Pass --yes to actually delete.

    Examples:

    \b
        forge clean                       # Dry-run (scope: workspace)
        forge clean --yes                 # Actually clean
        forge clean --scope all --yes     # Clean globally
        forge clean --scope project       # Current Forge project only
        forge clean --verbose             # Show individual items
    """
    console = Console(width=200)

    try:
        ctx = ExecutionContext.from_cwd()
    except Exception as e:
        print_error(f"{e}", console=err_console)
        sys.exit(1)

    try:
        report = collect_clean_report(ctx=ctx, scope=scope)
    except CleanError as e:
        print_error(f"{e}", console=err_console)
        sys.exit(1)

    if as_json and yes:
        _run_and_report_json(ctx, scope, report)
    elif as_json:
        _print_json(report)
    elif yes:
        _run_and_report(ctx, scope, report, console)
    else:
        _print_report(report, verbose, console)


def _print_report(report: CleanReport, verbose: bool, console: Console) -> None:
    """Print dry-run report."""
    console.print(f"\nForge Clean Report (scope: {report.scope})\n")

    for cat in report.categories:
        label = _category_label(cat.category)
        count_style = "cyan" if cat.count > 0 else "dim"
        console.print(f"  {label:<32} [{count_style}]{cat.count}[/{count_style}]")

        if verbose and cat.items:
            for item in cat.items:
                console.print(f"    [dim]{item}[/dim]")

    console.print()
    if report.is_clean:
        console.print("[green]Nothing to clean.[/green]")
    else:
        console.print(f"Total: [cyan]{report.total_count}[/cyan] objects to clean\n")
        print_tip(
            "Use --yes to clean, or --verbose for details.",
            blank_before=False,
            console=console,
        )


def _run_and_report(ctx: ExecutionContext, scope: str, report: CleanReport, console: Console) -> None:
    """Run cleanup and report results."""
    if report.is_clean:
        console.print("[green]Nothing to clean.[/green]")
        return

    try:
        result = run_clean(ctx=ctx, scope=scope)
    except CleanError as e:
        print_error(f"{e}")
        sys.exit(1)

    if result.deleted_count == 0 and not result.failed:
        console.print("[green]Nothing to clean.[/green]")
        return

    console.print(f"\nCleaned [cyan]{result.deleted_count}[/cyan] objects:")
    for cat, count in sorted(result.categories_cleaned.items()):
        label = _category_label(cat)
        console.print(f"  {label:<32} {count}")

    if result.failed:
        console.print(f"\n[yellow]{len(result.failed)} failures:[/yellow]")
        for item, error in result.failed:
            console.print(f"  [red]{item}[/red]: {error}")


def _run_and_report_json(ctx: ExecutionContext, scope: str, report: CleanReport) -> None:
    """Run cleanup and output JSON result."""
    from forge.core.ops.gc import CleanResult

    if report.is_clean:
        clean_result = CleanResult()
    else:
        try:
            clean_result = run_clean(ctx=ctx, scope=scope)
        except CleanError as e:
            click.echo(json.dumps({"error": str(e)}), err=True)
            sys.exit(1)

    data = {
        "scope": report.scope,
        "dry_run": False,
        "total": report.total_count,
        "deleted": clean_result.deleted_count,
        "failed": [{"item": item, "error": err} for item, err in clean_result.failed],
        "categories_cleaned": clean_result.categories_cleaned,
    }
    click.echo(json.dumps(data, indent=2))


def _print_json(report: CleanReport) -> None:
    """Print dry-run JSON report."""
    data = {
        "scope": report.scope,
        "dry_run": True,
        "total": report.total_count,
        "categories": [
            {
                "category": cat.category,
                "description": cat.description,
                "count": cat.count,
                "items": cat.items,
            }
            for cat in report.categories
        ],
    }
    click.echo(json.dumps(data, indent=2))


def _category_label(category: str) -> str:
    """Human-readable label for a category."""
    labels = {
        "session_dirs": "Orphan session dirs:",
        "transfer_files": "Orphan transfer files:",
        "active_entries": "Stale active entries:",
        "work_queue": "Stale work queue:",
        "proxies": "Stale proxy entries:",
        "search_docs": "Orphan search docs:",
        "dead_installations": "Dead installations:",
        "corrupt_state": "Corrupt state files:",
    }
    return labels.get(category, f"{category}:")

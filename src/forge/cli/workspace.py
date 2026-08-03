"""CLI read surface for Git-derived workspaces."""

from __future__ import annotations

import json
import sys

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from forge.cli.output import err_console, print_error
from forge.core.ops import ForgeOpError, list_workspace_worktrees
from forge.core.ops.context import ExecutionContext
from forge.core.ops.workspace import WorkspaceWorktreeSummary

console = Console(width=200)


@click.group(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
def workspace() -> None:
    """Inspect the Git worktree family containing the current path."""


@workspace.command("worktrees")
@click.option("--json", "as_json", is_flag=True, help="Output the workspace as JSON")
def worktrees(as_json: bool) -> None:
    """List registered worktrees with Forge session occupancy."""

    try:
        result = list_workspace_worktrees(ctx=ExecutionContext.from_cwd())
    except ForgeOpError as exc:
        print_error(str(exc), console=err_console)
        sys.exit(1)

    if as_json:
        payload = {
            "primary_root": str(result.primary_root),
            "common_dir": str(result.common_dir) if result.common_dir is not None else None,
            "worktrees": [_worktree_json(row) for row in result.worktrees],
        }
        click.echo(json.dumps(payload, indent=2))
        return

    console.print(f"[bold]Workspace:[/bold] {escape(str(result.primary_root))}")
    console.print()
    table = Table(title="Worktrees", show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Branch")
    table.add_column("Path")
    table.add_column("Availability")
    table.add_column("Sessions", justify="right")
    for summary in result.worktrees:
        row = summary.worktree
        table.add_row(
            _branch_label(summary),
            escape(str(row.checkout_root)),
            _availability_label(summary),
            _session_label(summary.sessions, summary.active),
        )
    console.print(table)


def _worktree_json(summary: WorkspaceWorktreeSummary) -> dict[str, object]:
    row = summary.worktree
    return {
        "checkout_root": str(row.checkout_root),
        "branch": row.branch,
        "head": row.head,
        "is_primary": row.is_primary,
        "is_bare": row.is_bare,
        "is_prunable": row.is_prunable,
        "is_locked": row.is_locked,
        "is_detached": row.is_detached,
        "path_exists": row.path_exists,
        "sessions": summary.sessions,
        "active": summary.active,
    }


def _branch_label(summary: WorkspaceWorktreeSummary) -> str:
    row = summary.worktree
    if row.is_bare:
        return "(bare)"
    if row.branch is not None:
        return escape(row.branch)
    if row.is_detached:
        return "(detached)"
    return "(directory)"


def _availability_label(summary: WorkspaceWorktreeSummary) -> str:
    row = summary.worktree
    if not row.path_exists:
        if row.is_locked:
            return "[yellow]missing (locked)[/yellow]"
        if row.is_prunable:
            return "[yellow]missing (prunable)[/yellow]"
        return "[yellow]missing[/yellow]"
    if row.is_locked:
        return "locked"
    if row.is_prunable:
        return "prunable"
    return "available"


def _session_label(sessions: int, active: int) -> str:
    label = f"{sessions} {'session' if sessions == 1 else 'sessions'}"
    if active:
        label += f", {active} active"
    return label

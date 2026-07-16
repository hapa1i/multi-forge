"""``forge session memory report`` -- inspect memory writer reports.

The memory writer (``session/memory_writer.py``) runs as a detached process
launched by a later pending-work drain, so its stdout vanishes to ``DEVNULL``.
To make the writer's proposed or applied changes visible, ``run_memory_writer`` persists each run's
output to ``<forge_root>/.forge/artifacts/<session>/handoff/review-<timestamp>.md``.
This module surfaces that file via ``forge session memory report`` (a flat leaf;
the former ``forge memory report show`` group was collapsed in the CLI cleanup).

Note: this is the memory writer's report surface, not the resume-context
(transfer) file. See ``forge.session.transfer`` for the resume-context generator.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click
from rich.syntax import Syntax

from forge.cli.output import err_console, print_error, print_error_with_tip, print_tip
from forge.cli.session import console, handle_session_error
from forge.core.ops.context import _cwd_forge_root
from forge.core.state.exceptions import StateCorruptedError, StateUnreadableError
from forge.session import ForgeSessionError, SessionManager
from forge.session.memory_writer import memory_report_dir

# The former ``report`` group held a single ``show`` leaf; the CLI cleanup
# flattened it to one ``forge session memory report`` command (see session_memory.py).


def _resolve_session_forge_root(session_name: str | None) -> tuple[str, Path]:
    """Resolve (session_name, forge_root) using current cwd if no name given.

    Resolution rules:
    - If session_name is provided, look it up by name (with current forge_root
      as scope hint to disambiguate cross-project name reuse).
    - If session_name is None, derive from the current Forge project: use the
      single active session, or error if zero/multiple.
    """
    manager = SessionManager()
    current_root = _cwd_forge_root()

    if session_name is None:
        env_name = os.environ.get("FORGE_SESSION")
        if env_name:
            env_root = os.environ.get("FORGE_FORGE_ROOT") or (str(current_root) if current_root else None)
            try:
                env_entry = manager.index_store.get_session(env_name, forge_root=env_root)
            except (StateCorruptedError, StateUnreadableError):
                raise  # corrupt index -> top-level reset handler, not "not in a project"
            except ForgeSessionError:
                pass
            else:
                return env_name, Path(env_entry.forge_root or env_entry.worktree_path)

        if current_root is None:
            print_error_with_tip(
                "Not inside a Forge project, and no session name given.",
                "Run from a directory with .forge/ or pass an explicit session name.",
                console=err_console,
            )
            sys.exit(1)
        sessions = manager.list_sessions(
            include_incognito=True,
            forge_root_filter=str(current_root),
        )
        if len(sessions) == 0:
            print_error(f"No sessions found under {current_root}.", console=err_console)
            sys.exit(1)
        if len(sessions) > 1:
            print_error(
                "Multiple sessions in this Forge project; " "specify which one explicitly.", console=err_console
            )
            for name, _entry in sessions:
                err_console.print(f"  - {name}")
            sys.exit(1)
        return sessions[0][0], Path(sessions[0][1].forge_root or sessions[0][1].worktree_path)

    try:
        resolved_entry = manager.index_store.get_session(
            session_name,
            forge_root=str(current_root) if current_root else None,
        )
    except ForgeSessionError as e:
        handle_session_error(e, console=err_console)
        raise  # for mypy; handle_session_error sys.exits

    return session_name, Path(resolved_entry.forge_root or resolved_entry.worktree_path)


def _list_reports(forge_root: Path, session_name: str) -> list[Path]:
    """Return review-*.md files sorted oldest -> newest."""
    target = memory_report_dir(forge_root, session_name)
    if not target.is_dir():
        return []
    return sorted(
        (p for p in target.iterdir() if p.is_file() and p.name.startswith("review-") and p.suffix == ".md"),
        key=lambda p: p.name,
    )


def _emit_report_json(session_name: str, report_dir: Path, reports: list[Path], *, show_all: bool) -> None:
    """Emit the report surface as JSON for scripting.

    ``--all`` lists every report (name + path); otherwise the payload carries the
    latest report's name, path, and full markdown content (``None`` when no
    reports exist).
    """
    if show_all:
        payload: dict[str, object] = {
            "session": session_name,
            "report_dir": str(report_dir),
            "reports": [{"name": p.name, "path": str(p)} for p in reports],
        }
    else:
        latest = reports[-1] if reports else None
        payload = {
            "session": session_name,
            "report_dir": str(report_dir),
            "report": (
                {"name": latest.name, "path": str(latest), "content": latest.read_text(encoding="utf-8")}
                if latest is not None
                else None
            ),
        }
    click.echo(json.dumps(payload, indent=2))


@click.command("report")
@click.argument("session_name", required=False)
@click.option("--latest", "show_latest", is_flag=True, default=False, help="Show the most recent report (default).")
@click.option("--all", "show_all", is_flag=True, default=False, help="List all reports with timestamps.")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    default=False,
    help="Emit JSON (latest report path + content, or the report list under --all).",
)
def report_cmd(session_name: str | None, show_latest: bool, show_all: bool, as_json: bool) -> None:
    """Show a memory writer report for a session.

    With no flags, prints the most recent report. ``--all`` lists every
    report (paths + timestamps). ``--json`` emits the same data for scripting.

    \b
    Examples:
        forge session memory report                 # Latest report for current session
        forge session memory report my-session      # Latest report for named session
        forge session memory report --all           # List all reports
        forge session memory report --json          # Latest report as JSON
    """
    if show_latest and show_all:
        print_error("--latest and --all are mutually exclusive.", console=err_console)
        sys.exit(1)

    resolved_name, forge_root = _resolve_session_forge_root(session_name)
    reports = _list_reports(forge_root, resolved_name)
    report_dir = memory_report_dir(forge_root, resolved_name)

    if as_json:
        _emit_report_json(resolved_name, report_dir, reports, show_all=show_all)
        return

    if not reports:
        console.print(f"[dim]No memory reports found for session [cyan]{resolved_name}[/cyan].[/dim]")
        print_tip(f"The memory writer writes reports to {report_dir}.", console=console)
        return

    if show_all:
        console.print(f"[bold]Memory reports for [cyan]{resolved_name}[/cyan][/bold]")
        for path in reports:
            console.print(f"  {path.name}  [dim]{path}[/dim]")
        return

    # Default: show latest
    latest = reports[-1]
    console.print(f"[bold]Memory report:[/bold] [dim]{latest}[/dim]")
    console.print()
    content = latest.read_text(encoding="utf-8")
    syntax = Syntax(content, "markdown", theme="monokai", word_wrap=True)
    console.print(syntax)

"""``forge session memory`` -- session-scoped memory activation and reports.

Activation is a property of a session, not a project doc: enable/disable whether
the memory writer runs at Stop, inspect activation across sessions, and read the
writer's reports. Project-doc passports (``track``/``list``/``passport``/
``shadows``) live under the top-level ``forge memory`` group.
"""

from __future__ import annotations

import logging
import os
import sys

import click

from forge.cli.memory_report import report_cmd
from forge.cli.output import err_console, print_error
from forge.cli.session import console
from forge.core.effort import CLAUDE_EFFORT_LEVELS, validate_claude_effort
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import (
    ForgeOpError,
    resolve_session,
    set_session_override,
)
from forge.session.exceptions import ForgeSessionError

logger = logging.getLogger(__name__)


@click.group("memory")
def session_memory() -> None:
    """Manage memory auto-update for a session.

    Activation is session-scoped. Project-doc passports live under 'forge memory'.

    \b
    Examples:
        forge session memory enable --session planner    # run the memory writer at Stop
        forge session memory status --scope workspace    # activation across sessions
        forge session memory report                      # latest writer report
    """


# ---------------------------------------------------------------------------
# enable
# ---------------------------------------------------------------------------


@session_memory.command("enable")
@click.option("--session", "-s", "session_name", default=None, help="Target session (default: ambient $FORGE_SESSION).")
@click.option("--review-only", is_flag=True, default=False, help="Enable in review-only mode (no edits).")
@click.option(
    "--effort",
    "effort",
    type=click.Choice(list(CLAUDE_EFFORT_LEVELS)),
    default=None,
    help="Memory-writer reasoning effort (claude --effort: low/medium/high/xhigh/max). Updates effort even if already enabled.",
)
def enable_cmd(session_name: str | None, review_only: bool, effort: str | None) -> None:
    """Enable memory auto-update for a session.

    Sets ``memory.auto_update.enabled`` on the session manifest. ``--effort``
    sets ``memory.auto_update.effort`` and applies even when memory is already
    enabled in the same mode. Resolves ``$FORGE_SESSION`` when ``--session`` is omitted.
    """
    target_mode = "review-only" if review_only else "augment"
    resolved_name = session_name or os.environ.get("FORGE_SESSION")
    if not resolved_name:
        print_error(
            "Memory activation is session-scoped. "
            "Use --session <name> or run inside a Forge session ($FORGE_SESSION).",
            console=err_console,
        )
        sys.exit(1)
    _set_memory_activation(resolved_name, enabled=True, mode=target_mode, effort=effort)


# ---------------------------------------------------------------------------
# disable
# ---------------------------------------------------------------------------


@session_memory.command("disable")
@click.option("--session", "-s", "session_name", default=None, help="Target session (default: ambient $FORGE_SESSION).")
def disable_cmd(session_name: str | None) -> None:
    """Disable memory auto-update for a session.

    Sets ``memory.auto_update.enabled=false`` on the session manifest.
    Resolves ``$FORGE_SESSION`` when ``--session`` is omitted.
    """
    resolved_name = session_name or os.environ.get("FORGE_SESSION")
    if not resolved_name:
        print_error(
            "Memory activation is session-scoped. "
            "Use --session <name> or run inside a Forge session ($FORGE_SESSION).",
            console=err_console,
        )
        sys.exit(1)
    _set_memory_activation(resolved_name, enabled=False)


def _set_memory_activation(
    session_name: str, *, enabled: bool, mode: str | None = None, effort: str | None = None
) -> None:
    """Write memory activation state to a session manifest override."""
    import json

    # Defense-in-depth: callers pass click.Choice-constrained values, but the
    # function is also reachable from other code paths.
    validate_claude_effort(effort)

    try:
        ctx = ExecutionContext.from_cwd()
        resolved = resolve_session(ctx=ctx, session_name=session_name)
    except ForgeOpError as e:
        print_error(str(e), console=err_console)
        sys.exit(1)

    from forge.session.effective import compute_effective_intent

    state = resolved.state
    effective = compute_effective_intent(state)
    display_name = session_name or state.name

    auto_update = effective.memory.auto_update if effective.memory else None
    current_enabled = auto_update is not None and auto_update.enabled
    current_mode = auto_update.mode if auto_update else None
    current_effort = auto_update.effort if auto_update else None

    # Short-circuit only when nothing is pending. An effort-only change must
    # still persist even when memory is already enabled in the same mode.
    if enabled and current_enabled:
        mode_pending = mode is not None and mode != current_mode
        effort_pending = effort is not None and effort != current_effort
        if not mode_pending and not effort_pending:
            console.print(
                f"[dim]Memory auto-update already enabled for session {display_name} (mode: {current_mode}).[/dim]"
            )
            return
    elif not enabled and not current_enabled:
        console.print(f"[dim]Memory auto-update already disabled for session {display_name}.[/dim]")
        return

    try:
        set_session_override(
            ctx=ctx,
            session_name=session_name,
            key="memory.auto_update.enabled",
            value_str=json.dumps(enabled),
        )
        if mode and enabled:
            set_session_override(
                ctx=ctx,
                session_name=session_name,
                key="memory.auto_update.mode",
                value_str=json.dumps(mode),
            )
        if effort and enabled:
            set_session_override(
                ctx=ctx,
                session_name=session_name,
                key="memory.auto_update.effort",
                value_str=json.dumps(effort),
            )
    except ForgeOpError as e:
        print_error(str(e), console=err_console)
        sys.exit(1)

    if enabled:
        effort_note = f", effort: {effort}" if effort else ""
        console.print(f"Memory auto-update enabled for session {display_name} (mode: {mode}{effort_note}).")
    else:
        console.print(f"Memory auto-update disabled for session {display_name}.")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@session_memory.command("status")
@click.option(
    "--scope",
    type=click.Choice(["project", "workspace", "all"]),
    default="project",
    show_default=True,
    help="Scope for discovery.",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON.")
def status_cmd(scope: str, as_json: bool) -> None:
    """Show memory activation status across sessions."""
    import json

    from forge.core.ops.session import list_sessions
    from forge.session.effective import compute_effective_intent
    from forge.session.manager import SessionManager

    try:
        ctx = ExecutionContext.from_cwd()
        result = list_sessions(ctx=ctx, include_incognito=False, scope=scope)
    except ForgeOpError as e:
        print_error(str(e), console=err_console)
        sys.exit(1)

    manager = SessionManager()
    entries: list[dict[str, object]] = []

    for item in result.sessions:
        entry = item.entry
        fr = entry.forge_root or entry.worktree_path
        if not fr:
            continue

        try:
            manifest = manager.get_session(item.name, forge_root=fr)
            effective = compute_effective_intent(manifest)
        except (ForgeSessionError, ForgeOpError, OSError):
            logger.debug("Failed to read manifest for session %r in %s", item.name, fr, exc_info=True)
            continue

        auto = effective.memory.auto_update if effective.memory else None
        entries.append(
            {
                "session": item.name,
                "forge_root": fr,
                "enabled": bool(auto and auto.enabled),
                "mode": auto.mode if auto else None,
                "min_turns": auto.min_turns if auto else None,
            }
        )

    if as_json:
        click.echo(json.dumps({"sessions": entries}, indent=2))
        return

    if not entries:
        console.print(f"[dim]No sessions found (scope: {scope}).[/dim]")
        return

    from rich.table import Table

    table = Table(show_header=True, header_style="bold")
    table.add_column("Session", style="cyan")
    table.add_column("Memory")
    table.add_column("Mode")
    table.add_column("Min Turns")

    for row_data in sorted(entries, key=lambda x: str(x["session"])):
        enabled = row_data["enabled"]
        table.add_row(
            str(row_data["session"]),
            "[green]on[/green]" if enabled else "[dim]off[/dim]",
            str(row_data["mode"] or "—"),
            str(row_data["min_turns"] or "—"),
        )
    console.print(table)


# ---------------------------------------------------------------------------
# report (flattened from the former `forge memory report show`)
# ---------------------------------------------------------------------------

session_memory.add_command(report_cmd)

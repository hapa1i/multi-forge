"""``forge session transfer`` -- inspect and reshape resume/fork transfer context.

Pairs with ``forge memory`` (project-doc curation) as the two halves of session
continuity: ``forge memory`` curates project docs; ``forge session transfer``
assembles the resume/fork context that moves a session forward. Every verb takes
a parent session argument -- transfer is session-derived, which is why it lives
under ``forge session``.

\b
Layout (see prev_sessions.py):
    generated.md            parent AI cache  (regenerate rewrites this)
    children/<child>.md     pure AI snapshot (frozen; never edited)
    children/<child>.notes.md  user-notes overlay (edit this; merged at launch)
"""

from __future__ import annotations

import json

import click

from forge.cli.editor import open_in_editor
from forge.cli.output import print_error_with_tip, print_tip
from forge.cli.session import console
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import ForgeOpError
from forge.core.ops.transfer import (
    diff_transfer,
    regenerate_transfer,
    resolve_notes_target,
    resolve_single_child,
    show_transfer,
)
from forge.core.paths import display_path
from forge.session.transfer import TRANSFER_TARGET_RUNTIMES, ResumeStrategy

_STRATEGY_CHOICES = [s.value for s in ResumeStrategy]


@click.group("transfer")
def transfer() -> None:
    """Inspect and reshape session transfer context.

    Pairs with 'forge memory' (the two halves of session continuity): memory
    curates project docs; transfer assembles the per-parent resume/fork context.

    \b
    Examples:
        forge session transfer show planner                # show the parent AI cache
        forge session transfer show planner --child exec   # show a child's composed transfer view
        forge session transfer edit planner --child exec   # edit that child's user notes
        forge session transfer regenerate planner          # rebuild the cache (same strategy)
        forge session transfer diff planner --child exec   # cache-vs-snapshot drift
    """


@transfer.command("show")
@click.argument("parent")
@click.option(
    "--child",
    default=None,
    help="Show a child's composed transfer view (snapshot + notes; approximates launch).",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON (frontmatter + sections + content).")
def show_cmd(parent: str, child: str | None, as_json: bool) -> None:
    """Show the parent cache, or a child's composed transfer view with --child."""
    ctx = ExecutionContext.from_cwd()
    try:
        view = show_transfer(ctx=ctx, parent=parent, child=child)
    except ForgeOpError as e:
        print_error_with_tip(
            str(e),
            f"Run 'forge session resume {parent} --fresh' to create transfer context.",
            console=console,
        )
        raise SystemExit(1) from e

    if as_json:
        click.echo(
            json.dumps(
                {
                    "parent": view.parent,
                    "child": view.child,
                    "path": str(view.path),
                    "frontmatter": view.frontmatter,
                    "sections": view.sections,
                    "has_notes": view.has_notes,
                    "warning": view.warning,
                    "content": view.content,
                },
                indent=2,
            )
        )
        return

    if view.warning:
        console.print(f"[yellow]Warning:[/yellow] {view.warning}")
    # click.echo (not console.print) so markdown brackets aren't read as Rich markup.
    click.echo(view.content)
    if view.child is not None and not view.has_notes:
        print_tip(
            f"No user notes yet. Run 'forge session transfer edit {parent} --child {view.child}' to add some.",
            console=console,
        )


@transfer.command("regenerate")
@click.argument("parent")
@click.option(
    "--strategy",
    type=click.Choice(_STRATEGY_CHOICES),
    default=None,
    help="Override strategy (default: the cache's current strategy).",
)
@click.option("--depth", type=int, default=None, help="Override lineage depth (default: the cache's current depth).")
@click.option(
    "--target-runtime",
    type=click.Choice(list(TRANSFER_TARGET_RUNTIMES)),
    default=None,
    help="Which runtime will consume this context (default: the cache's current target runtime).",
)
def regenerate_cmd(parent: str, strategy: str | None, depth: int | None, target_runtime: str | None) -> None:
    """Rebuild the parent cache (generated.md). Never touches children or notes."""
    ctx = ExecutionContext.from_cwd()
    try:
        result = regenerate_transfer(
            ctx=ctx, parent=parent, strategy=strategy, depth=depth, target_runtime=target_runtime
        )
    except ForgeOpError as e:
        print_error_with_tip(
            str(e),
            f"Run 'forge session resume {parent} --fresh' to create transfer context.",
            console=console,
        )
        raise SystemExit(1) from e

    console.print(
        f"Regenerated [green]{display_path(result.path)}[/green] "
        f"[dim](strategy={result.strategy}, depth={result.depth}, runtime={result.target_runtime})[/dim]"
    )
    for warning in result.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")
    console.print("[dim]Child snapshots and notes are unchanged.[/dim]")


@transfer.command("edit")
@click.argument("parent")
@click.option("--child", default=None, help="Child to edit notes for (inferred when the parent has exactly one).")
def edit_cmd(parent: str, child: str | None) -> None:
    """Edit a child's user-notes overlay in $EDITOR (created if absent)."""
    ctx = ExecutionContext.from_cwd()
    try:
        resolved_child = resolve_single_child(ctx=ctx, parent=parent, child=child)
        notes_path = resolve_notes_target(ctx=ctx, parent=parent, child=resolved_child)
    except ForgeOpError as e:
        print_error_with_tip(
            str(e),
            f"Run 'forge session transfer show {parent}' to list available transfer context.",
            console=console,
        )
        raise SystemExit(1) from e

    open_in_editor(
        notes_path,
        console=console,
        abort_tip=f"Your notes at {display_path(notes_path)} are preserved.",
    )
    console.print(f"Saved notes for [cyan]{parent}[/cyan] → [green]{resolved_child}[/green].")
    print_tip(
        "Notes are merged into the child's launch context on the next resume/relaunch.",
        console=console,
    )


@transfer.command("diff")
@click.argument("parent")
@click.option("--child", default=None, help="Child to diff (inferred when the parent has exactly one).")
def diff_cmd(parent: str, child: str | None) -> None:
    """Show how the parent cache has drifted from a child's frozen snapshot."""
    ctx = ExecutionContext.from_cwd()
    try:
        resolved_child = resolve_single_child(ctx=ctx, parent=parent, child=child)
        diff_text = diff_transfer(ctx=ctx, parent=parent, child=resolved_child)
    except ForgeOpError as e:
        print_error_with_tip(
            str(e),
            f"Run 'forge session transfer show {parent}' to list available transfer context.",
            console=console,
        )
        raise SystemExit(1) from e

    if not diff_text:
        console.print(f"[dim]No drift: child '{resolved_child}' snapshot matches the current cache.[/dim]")
        return
    click.echo(diff_text)

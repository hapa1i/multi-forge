"""Session delete and purge previews share the session-domain cleanup planner."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import cast

import click
from rich.markup import escape
from rich.progress import track

from forge.cli.output import (
    console,
    err_console,
    print_error,
    print_error_with_tip,
    print_tip,
)
from forge.cli.session import session as _session_untyped
from forge.core.ops.context import _cwd_forge_root
from forge.core.state import FileLockTimeoutError
from forge.install.project_compat import ProjectCompatibilityError
from forge.session import ForgeSessionError, IndexStore, SessionManager
from forge.session.cleanup_dependencies import session_entries
from forge.session.deletion import (
    SessionDeletionPlan,
    apply_session_deletion,
    plan_session_deletion,
)
from forge.session.exceptions import SessionCleanupRetryError, SessionNotFoundError
from forge.session.purge_native import NativePurgePlan

session = cast(click.Group, _session_untyped)  # type: ignore[has-type]  # circular registration


@session.command()
@click.argument("names", nargs=-1)
@click.option(
    "--all",
    "-a",
    "delete_all",
    is_flag=True,
    help="Delete all sessions in this Forge project",
)
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt")
@click.option("--verbose", "-v", is_flag=True, help="Show the full per-session inventory and results with --all")
@click.option("--force", "-f", is_flag=True, help="Bypass dirty-worktree protection")
@click.option("--keep-worktree", "-K", is_flag=True, help="Preserve worktree directory")
@click.option(
    "--delete-branch",
    "-d",
    is_flag=True,
    help="Also delete the owned worktree's git branch",
)
@click.option(
    "--forge-root",
    type=click.Path(path_type=Path),
    help="Absolute owning Forge root, including a removed root",
)
def delete(
    names: tuple[str, ...],
    delete_all: bool,
    yes: bool,
    verbose: bool,
    force: bool,
    keep_worktree: bool,
    delete_branch: bool,
    forge_root: Path | None,
) -> None:
    """Remove Forge session data and keep native conversations.

    Removes the owned worktree by default; use --keep-worktree to preserve it.
    Active sessions and existing dependent sessions refuse even with --force.
    """
    _run_cleanup(
        names,
        all_sessions=delete_all,
        yes=yes,
        force=force,
        keep_worktree=keep_worktree,
        delete_branch=delete_branch,
        purge=False,
        as_json=False,
        explicit_root=forge_root,
        compact=delete_all and not verbose,
    )


@session.command()
@click.argument("names", nargs=-1)
@click.option(
    "--all",
    "-a",
    "purge_all",
    is_flag=True,
    help="Select all sessions in this Forge project",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Remove the previewed Forge and native conversation files",
)
@click.option("--json", "as_json", is_flag=True, help="Output the read-only preview as JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show the full per-session inventory and results with --all")
@click.option("--force", "-f", is_flag=True, help="Bypass dirty-worktree protection only")
@click.option("--keep-worktree", "-K", is_flag=True, help="Preserve worktree directory")
@click.option(
    "--delete-branch",
    "-d",
    is_flag=True,
    help="Also delete the owned worktree's git branch",
)
@click.option(
    "--forge-root",
    type=click.Path(path_type=Path),
    help="Absolute owning Forge root, including a removed root",
)
def purge(
    names: tuple[str, ...],
    purge_all: bool,
    yes: bool,
    as_json: bool,
    verbose: bool,
    force: bool,
    keep_worktree: bool,
    delete_branch: bool,
    forge_root: Path | None,
) -> None:
    """Preview removal of Forge data and identified native conversation files.

    Pass --yes to apply. Includes adopted conversations created outside Forge.
    Activity, identity and dependency refusals cannot be overridden by --force.
    """
    _run_cleanup(
        names,
        all_sessions=purge_all,
        yes=yes,
        force=force,
        keep_worktree=keep_worktree,
        delete_branch=delete_branch,
        purge=True,
        as_json=as_json,
        explicit_root=forge_root,
        compact=purge_all and not verbose,
    )


def _plan_notes(plan: SessionDeletionPlan) -> Iterator[str]:
    yield from plan.notes
    if plan.branch:
        yield f"Remove branch: {plan.branch}"


def _print_inventory_line(line: str) -> None:
    # Preserve copyable paths when Rich renders to a narrow terminal or a pipe.
    console.print(line, markup=False, soft_wrap=True)


def _print_refusal(name: str, reason: str) -> None:
    console.print(f"Refused {name}: {reason}", style="yellow", markup=False, soft_wrap=True)


def _print_native_inventory(plans: Sequence[NativePurgePlan]) -> None:
    for runtime, title in (("claude", "Claude store"), ("codex", "Codex store")):
        files = [file for plan in plans for file in plan.files if file.runtime == runtime]
        if not files:
            continue
        console.print(f"  {title}:")
        for file in files:
            label = "created outside Forge; " if file.created_outside_forge else ""
            label += file.provenance
            if file.fingerprint is None:
                label += "; already absent"
            _print_inventory_line(f"    {file.path} ({label})")
    exclusions = dict.fromkeys(exclusion for plan in plans for exclusion in plan.outside_scope)
    if exclusions:
        console.print("  Outside removal scope:")
        for exclusion in exclusions:
            _print_inventory_line(f"    {exclusion}")


def print_deletion_plan(plan: SessionDeletionPlan) -> None:
    """Render exact absolute inventory paths and all admission refusals on stdout."""
    console.print(
        f"[bold]{plan.mode.capitalize()} {escape(plan.name)}[/bold] ({escape(plan.forge_root)})", soft_wrap=True
    )
    console.print("  Forge project:")
    _print_inventory_line(
        f"    {Path(plan.forge_root) / '.forge' / 'sessions' / plan.name} (entire session metadata directory)"
    )
    for file in plan.content.files:
        _print_inventory_line(f"    {file.path} ({file.category})")
    for directory in plan.content.directories:
        _print_inventory_line(f"    {directory.path} (directory after its inventoried files)")
    for path in plan.content.search_keys:
        _print_inventory_line(f"    Search document: {path}")
    if plan.native:
        _print_native_inventory([plan.native])
    for note in _plan_notes(plan):
        _print_inventory_line(f"  {note}")
    for exclusion in plan.content.exclusions:
        _print_inventory_line(f"  Outside removal scope: {exclusion}")
    for reason in plan.refusals:
        console.print(f"  Refused: {reason}", style="yellow", markup=False, soft_wrap=True)


def _print_bulk_preview(root: str, mode: str, admitted: list[SessionDeletionPlan]) -> None:
    console.print(f"[bold]Forge project[/bold] {escape(root)}", soft_wrap=True)
    if not admitted:
        return
    files: set[str] = set()
    external_files: dict[str, str] = {}
    for plan in admitted:
        project_state = Path(plan.forge_root) / ".forge"
        for file in plan.content.files:
            files.add(file.path)
            if not Path(file.path).is_relative_to(project_state):
                external_files[file.path] = file.category
    names = ", ".join(plan.name for plan in admitted)
    search_records = {key for plan in admitted for key in plan.content.search_keys}
    console.print(f"Sessions to {mode} ({len(admitted)}): {escape(names)}")
    console.print(
        f"Remove session metadata and Forge content ({len(files)} files, {len(search_records)} search records)."
    )
    for note in dict.fromkeys(note for plan in admitted for note in _plan_notes(plan)):
        _print_inventory_line(f"  {note}")
    for path, category in external_files.items():
        _print_inventory_line(f"  Remove {category}: {path}")
    _print_native_inventory([plan.native for plan in admitted if plan.native is not None])


def _target_root(name: str, root: str | None, manager: SessionManager) -> str | None:
    if root is None:
        return None
    from forge.core.ops.resolution import resolve_session_repo_wide

    try:
        return resolve_session_repo_wide(name, root, manager=manager, repair_stale=False).forge_root
    except SessionNotFoundError:
        # The planner owns missing/orphan diagnosis without repairing the index.
        return root


def _run_cleanup(
    names: tuple[str, ...],
    *,
    all_sessions: bool,
    yes: bool,
    force: bool,
    keep_worktree: bool,
    delete_branch: bool,
    purge: bool,
    as_json: bool,
    explicit_root: Path | None,
    compact: bool,
) -> None:
    mode = "purge" if purge else "delete"
    if all_sessions and names:
        raise click.UsageError("Cannot combine --all with explicit session names")
    if not all_sessions and not names:
        raise click.UsageError("Provide session name(s) or use --all")
    if yes and as_json:
        raise click.UsageError("--json is a read-only preview; omit --yes")
    if keep_worktree and delete_branch:
        raise click.UsageError("--delete-branch cannot be combined with --keep-worktree")
    if explicit_root is not None and all_sessions:
        raise click.UsageError("--forge-root cannot be combined with --all")
    if explicit_root is not None and not explicit_root.is_absolute():
        raise click.UsageError("--forge-root must be an absolute path")
    root = str(explicit_root.resolve()) if explicit_root is not None else _cwd_forge_root()
    if all_sessions and root is None:
        raise click.UsageError("--all requires being inside a Forge project (directory with .forge/)")
    manager = SessionManager()
    index: IndexStore = manager.index_store
    plans: list[SessionDeletionPlan] = []
    refused: list[dict[str, str | None]] = []
    try:
        targets = (
            [
                (name, entry.root)
                for name, entry in session_entries(index)
                if root is not None and Path(entry.root).resolve() == Path(root).resolve()
            ]
            if all_sessions
            else [(name, root) for name in dict.fromkeys(names)]
        )
    except (ForgeSessionError, OSError, ValueError) as exc:
        print_error(str(exc))
        raise SystemExit(1) from exc
    # Freeze every admission before applying anything, including dependencies
    # between selected sessions; processing order cannot enlarge this batch.
    for name, selected_root in targets:
        try:
            actual_root = (
                selected_root
                if all_sessions or explicit_root is not None
                else _target_root(name, selected_root, manager)
            )
            plans.append(
                plan_session_deletion(
                    index,
                    name,
                    forge_root=actual_root,
                    purge=purge,
                    delete_worktree=not keep_worktree,
                    delete_branch=delete_branch,
                    force=force,
                )
            )
        except (
            FileLockTimeoutError,
            ForgeSessionError,
            ProjectCompatibilityError,
            OSError,
            ValueError,
        ) as exc:
            refused.append({"name": name, "forge_root": selected_root, "reason": str(exc)})
    admitted = [plan for plan in plans if not plan.refusals]
    failed = len(targets) - len(admitted)
    if as_json:
        click.echo(
            json.dumps(
                {
                    "schema_version": 1,
                    "mode": mode,
                    "targets": [plan.preview_dict() for plan in plans],
                    "refused": refused,
                },
                indent=2,
            )
        )
    else:
        if compact and targets and root is not None:
            _print_bulk_preview(root, mode, admitted)
            for plan in plans:
                for reason in plan.refusals:
                    _print_refusal(plan.name, reason)
            if not yes:
                print_tip(
                    "Use --verbose for individual paths and per-session exclusions.",
                    blank_before=False,
                    console=console,
                )
        else:
            for plan in plans:
                print_deletion_plan(plan)
        for refusal in refused:
            _print_refusal(str(refusal["name"]), str(refusal["reason"]))
        if not targets:
            console.print(f"[dim]No sessions to {mode}.[/dim]")
    if purge and not yes:
        if admitted and not as_json:
            print_tip("Use --yes to apply this purge selection.", console=console)
    elif admitted:
        if not yes and not click.confirm(f"Delete Forge data for {len(admitted)} session(s)?", err=True):
            err_console.print("[dim]Cancelled[/dim]")
            raise SystemExit(1 if failed else 0)
        past_tense = "Purged" if purge else "Deleted"
        to_apply = (
            track(
                admitted,
                description="Purging sessions" if purge else "Deleting sessions",
                console=err_console,
                transient=True,
            )
            if compact and err_console.is_terminal
            else admitted
        )
        for plan in to_apply:
            try:
                apply_session_deletion(index, plan)
            except (ForgeSessionError, OSError, ValueError) as exc:
                if isinstance(exc, SessionCleanupRetryError):
                    print_error_with_tip(escape(f"{plan.name}: {exc.reason}"), exc.hint, commands=[exc.command])
                else:
                    print_error(escape(f"{plan.name}: {exc}"))
                failed += 1
            else:
                if not compact:
                    console.print(f"{past_tense} session [green]{escape(plan.name)}[/green]")
        if compact:
            completed = len(targets) - failed
            console.print(f"{past_tense} {completed} {'session' if completed == 1 else 'sessions'}.")
    if failed:
        print_error(f"{failed} session(s) refused or failed {mode}.")
        raise SystemExit(1)

"""Session delete and purge previews share the session-domain cleanup planner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import click
from rich.markup import escape

from forge.cli.output import console, err_console, print_error, print_tip
from forge.cli.session import session as _session_untyped
from forge.core.ops.context import _cwd_forge_root
from forge.install.project_compat import ProjectCompatibilityError
from forge.session import ForgeSessionError, IndexStore, SessionManager
from forge.session.cleanup_dependencies import session_entries
from forge.session.deletion import (
    SessionDeletionPlan,
    apply_session_deletion,
    plan_session_deletion,
)
from forge.session.exceptions import SessionNotFoundError

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
    )


def print_deletion_plan(plan: SessionDeletionPlan) -> None:
    """Render exact absolute inventory paths and all admission refusals on stdout."""
    console.print(f"[bold]{plan.mode.capitalize()} {escape(plan.name)}[/bold] ({escape(plan.forge_root)})")
    console.print("  Forge project:")
    console.print(
        f"    {escape(str(Path(plan.forge_root) / '.forge' / 'sessions' / plan.name))}"
        " (entire session metadata directory)"
    )
    for file in plan.content.files:
        console.print(f"    {escape(file.path)} ({escape(file.category)})")
    for directory in plan.content.directories:
        console.print(f"    {escape(directory.path)} (directory after its inventoried files)")
    for path in plan.content.search_keys:
        console.print(f"    Search document: {escape(path)}")
    if plan.native:
        for runtime, title in (("claude", "Claude store"), ("codex", "Codex store")):
            files = [file for file in plan.native.files if file.runtime == runtime]
            if not files:
                continue
            console.print(f"  {title}:")
            for native_file in files:
                label = "created outside Forge; " if native_file.created_outside_forge else ""
                label += native_file.provenance
                if native_file.fingerprint is None:
                    label += "; already absent"
                console.print(f"    {escape(native_file.path)} ({label})")
        console.print("  Outside removal scope:")
        for exclusion in plan.native.outside_scope:
            console.print(f"    {escape(exclusion)}")
    for note in plan.notes:
        console.print(f"  {escape(note)}")
    for exclusion in plan.content.exclusions:
        console.print(f"  Outside removal scope: {escape(exclusion)}")
    for reason in plan.refusals:
        console.print(f"  [yellow]Refused: {escape(reason)}[/yellow]")


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
            ForgeSessionError,
            ProjectCompatibilityError,
            OSError,
            ValueError,
        ) as exc:
            refused.append({"name": name, "forge_root": selected_root, "reason": str(exc)})
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
        for plan in plans:
            print_deletion_plan(plan)
        for refusal in refused:
            console.print(f"[yellow]Refused {escape(str(refusal['name']))}: {escape(str(refusal['reason']))}[/yellow]")
        if not targets:
            console.print(f"[dim]No sessions to {mode}.[/dim]")
    failed = len(refused) + sum(bool(plan.refusals) for plan in plans)
    admitted = [plan for plan in plans if not plan.refusals]
    if purge and not yes:
        if admitted and not as_json:
            print_tip("Use --yes to apply this purge selection.", console=console)
    elif admitted:
        if not yes and not click.confirm(f"Delete Forge data for {len(admitted)} session(s)?", err=True):
            err_console.print("[dim]Cancelled[/dim]")
            raise SystemExit(1 if failed else 0)
        for plan in admitted:
            try:
                apply_session_deletion(index, plan)
            except (ForgeSessionError, OSError, ValueError) as exc:
                print_error(f"{plan.name}: {exc}")
                failed += 1
            else:
                console.print(f"{'Purged' if purge else 'Deleted'} session [green]{escape(plan.name)}[/green]")
    if failed:
        print_error(f"{failed} session(s) refused or failed {mode}.")
        raise SystemExit(1)

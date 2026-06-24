"""``forge memory`` -- top-level memory doc management.

Two primitives: passports select docs (project-scoped, git-tracked),
session activation decides whether the memory writer runs.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

import click

from forge.cli.output import print_error, print_tip
from forge.cli.session import console
from forge.core.effort import CLAUDE_EFFORT_LEVELS
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import (
    ForgeOpError,
    resolve_session,
)
from forge.session.exceptions import (
    ForgeSessionError,
    PassportError,
)
from forge.session.passport import (
    VALID_STRATEGY_NAMES,
    Passport,
    derive_shadow_path,
    read_passport,
    remove_passport,
    resolve_passport_source,
    resolve_with_overrides,
    synthesize_passport,
    write_passport,
)
from forge.session.project_memory import (
    DEFAULT_SCAN_ROOTS,
    check_shadow_path_collision_in_roots,
    is_under_scan_roots,
)
from forge.session.shadow_curation import ShadowEntry
from forge.session.validation import is_safe_designated_doc_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _auto_create_shadow(shadow_path: str, forge_root: Path) -> bool:
    """Create a shadow file under ``.forge/memory/`` if it doesn't exist.

    Returns True if the file was created. Returns False for paths outside
    ``.forge/memory/`` (caller must validate those exist separately).
    Raises ClickException on unsafe paths.
    """
    from forge.session.memory_inheritance import create_shadow_file

    try:
        return create_shadow_file(shadow_path, forge_root)
    except ValueError as e:
        raise click.ClickException(f"Invalid shadow path: {e}") from e


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------


@click.group("memory")
def memory() -> None:
    """Manage project memory docs (passports and doc curation).

    Pairs with 'forge session transfer': memory curates project docs; transfer
    assembles the per-session resume/fork context. Session-scoped activation
    (enable/disable/status/report) lives under 'forge session memory'.

    \b
    Examples:
        forge memory track docs/changelog.md --strategy changelog    # author a passport (sessionless)
        forge memory list                                            # show passported docs
        forge memory passport show docs/changelog.md                 # inspect a passport
        forge memory shadows review --for docs/impl_notes.md         # curate shadow proposals
    """


# ---------------------------------------------------------------------------
# track
# ---------------------------------------------------------------------------


@memory.command("track")
@click.argument("path")
@click.option(
    "--strategy",
    "strategy",
    type=str,
    default=None,
    help="Augmentation strategy.",
)
@click.option("--intent", default=None, help="Doc intent description for passport synthesis.")
@click.option("--writers", default=None, help="Writer spec (default: all-sessions).")
@click.option("--propose", is_flag=True, default=False, help="Author a shadow-only passport (proposal mode).")
@click.option("--shadow-path", "shadow_override", default=None, help="Explicit shadow file path (use with --propose).")
def track_cmd(
    path: str,
    strategy: str | None,
    intent: str | None,
    writers: str | None,
    propose: bool,
    shadow_override: str | None,
) -> None:
    """Author a project-memory passport on a doc (project-lifetime, sessionless).

    Writes ``forge_memory`` frontmatter so every session in this checkout treats
    the doc as memory. Runnable from a bare terminal: it does not resolve or
    require a session. Re-running with --strategy/--writers updates the passport;
    with no flags on an already-passported doc it is a no-op.

    Use --propose to author a shadow-only passport: the memory writer writes
    suggestions to a shadow file instead of editing the doc directly.

    For one-off updates without a passport, instruct the agent directly.

    \b
    Strategies (--strategy):
      changelog      Add accomplishments not already recorded
      checklist      Mark completed tasks [x], add newly discovered tasks
      generic        Add any new information missing from the file
      project-state  Update current focus, decisions, and handoff notes
    """
    # Strategy validation: unknown strategy names get the list of valid options.
    if strategy is not None and strategy not in VALID_STRATEGY_NAMES:
        raise click.ClickException(
            f"Unknown strategy '{strategy}'. " f"Valid strategies: {', '.join(sorted(VALID_STRATEGY_NAMES))}"
        )

    # Early flag-combination validation
    if shadow_override and not propose:
        raise click.ClickException("--shadow-path requires --propose.")

    ctx = ExecutionContext.from_cwd()
    if ctx.forge_root is None:
        raise click.ClickException("Not inside a Forge project. Run `forge extension enable` first.")
    forge_root = ctx.forge_root

    resolved_base = forge_root.resolve()
    reason = is_safe_designated_doc_path(path, forge_root, resolved_base)
    if reason:
        raise click.ClickException(f"Invalid path: {reason}")

    abs_path = (forge_root / path).resolve()
    if not abs_path.is_file():
        raise click.ClickException(f"File does not exist: {path}")

    # Read existing passport on the official doc
    try:
        passport = read_passport(abs_path)
    except PassportError as e:
        raise click.ClickException(f"Malformed passport in {path}: {e}") from e

    # Scan roots power the out-of-root warning and the collision check. A
    # corrupt config must not block authoring (system-boundary warn+degrade).
    roots = _resolve_scan_roots()

    if propose:
        _track_propose(
            path=path,
            abs_path=abs_path,
            passport=passport,
            strategy=strategy,
            intent=intent,
            writers=writers,
            shadow_override=shadow_override,
            forge_root=forge_root,
            roots=roots,
        )
        return

    # Shadow-only passport without --propose: honor the passport's shadow_path.
    if passport and passport.update.mode == "shadow-only":
        _track_existing_shadow_only(
            path=path,
            abs_path=abs_path,
            passport=passport,
            strategy=strategy,
            writers=writers,
            forge_root=forge_root,
            roots=roots,
        )
        return

    # --- Direct passport authoring ---
    has_flags = strategy is not None or writers is not None

    if passport is None and strategy is None:
        raise click.ClickException(
            f"This doc has no passport. Provide a strategy:\n"
            f"  forge memory track {path} --strategy <strategy>\n\n"
            f"Valid strategies: {', '.join(sorted(VALID_STRATEGY_NAMES))}"
        )

    if passport is None:
        try:
            new_pp = synthesize_passport(
                strategy=strategy,  # type: ignore[arg-type]  # checked above
                intent=intent,
                writers=writers or "all-sessions",
            )
            write_passport(abs_path, new_pp)
        except PassportError as e:
            raise click.ClickException(str(e)) from e
        console.print(f"Passport created for [cyan]{path}[/cyan] (strategy: {strategy}).")
        _warn_if_out_of_root(path, forge_root, roots)
        return

    # Existing direct passport.
    if not has_flags:
        console.print(f"Passport already present in [cyan]{path}[/cyan] (strategy: {passport.update.strategy}).")
        _warn_if_out_of_root(path, forge_root, roots)
        return

    try:
        resolved_pp, warnings = resolve_with_overrides(passport, strategy=strategy, writers=writers)
    except PassportError as e:
        raise click.ClickException(str(e)) from e
    if warnings:
        write_passport(abs_path, resolved_pp)
        for w in warnings:
            console.print(f"[yellow]Warning:[/yellow] {w}")
        console.print(f"Passport updated in [cyan]{path}[/cyan]. Future sessions will use the new values.")
    else:
        console.print(f"Passport already present in [cyan]{path}[/cyan] (strategy: {passport.update.strategy}).")
    _warn_if_out_of_root(path, forge_root, roots)


def _resolve_scan_roots() -> tuple[str, ...]:
    """Return the effective scan roots (hardcoded defaults)."""
    return DEFAULT_SCAN_ROOTS


def _warn_if_out_of_root(path: str, forge_root: Path, roots: tuple[str, ...]) -> None:
    """Warn when a passported doc lies outside the scan roots."""
    if is_under_scan_roots(path, forge_root, roots):
        return
    console.print(
        f"[yellow]Warning:[/yellow] {path} is outside the default scan roots ({', '.join(roots)}). "
        "The passport is written, but Stop-time memory will not process it."
    )


def _track_existing_shadow_only(
    *,
    path: str,
    abs_path: Path,
    passport: Passport,
    strategy: str | None,
    writers: str | None,
    forge_root: Path,
    roots: tuple[str, ...],
) -> None:
    """Honor an existing shadow-only passport (no --propose).

    Ensures the declared shadow file exists and applies any flag overrides.
    Passport-only and sessionless: no manifest write, no auto-enable.
    """
    shadow_path = passport.update.shadow_path
    if not shadow_path:
        raise click.ClickException(
            f"Passport in {path} has mode 'shadow-only' but no shadow_path. "
            "Fix the passport or re-run with --propose."
        )

    has_flags = strategy is not None or writers is not None
    updated = False
    if has_flags:
        try:
            resolved_pp, pp_warnings = resolve_with_overrides(passport, strategy=strategy, writers=writers)
        except PassportError as exc:
            raise click.ClickException(str(exc)) from exc
        if pp_warnings:
            write_passport(abs_path, resolved_pp)
            updated = True
            for w in pp_warnings:
                console.print(f"[yellow]Warning:[/yellow] {w}")

    created = _auto_create_shadow(shadow_path, forge_root)
    shadow_abs = (forge_root / shadow_path).resolve()
    if not shadow_abs.is_file():
        raise click.ClickException(f"Shadow file does not exist: {shadow_path}")
    if created:
        console.print(f"Shadow file created: {shadow_path}.")
    if updated:
        console.print(f"Passport updated in [cyan]{path}[/cyan] (shadow-only proposals at {shadow_path}).")
    else:
        console.print(f"Passport already present in [cyan]{path}[/cyan] (shadow-only proposals at {shadow_path}).")
    _warn_if_out_of_root(path, forge_root, roots)


def _track_propose(
    *,
    path: str,
    abs_path: Path,
    passport: Passport | None,
    strategy: str | None,
    intent: str | None,
    writers: str | None,
    shadow_override: str | None,
    forge_root: Path,
    roots: tuple[str, ...],
) -> None:
    """Author a shadow-only passport and materialize its shadow file.

    Passport-only and sessionless: never resolves a session.
    """
    new_passport_strategy = strategy or "generic"
    shadow_path = shadow_override or derive_shadow_path(path)

    # Validate shadow path
    resolved_base = forge_root.resolve()
    reason = is_safe_designated_doc_path(shadow_path, forge_root, resolved_base)
    if reason:
        raise click.ClickException(f"Invalid shadow path: {reason}")

    # Self-shadow: compare resolved paths, not raw strings
    resolved_shadow = (forge_root / shadow_path).resolve()
    resolved_official = (forge_root / path).resolve()
    if resolved_shadow == resolved_official:
        raise click.ClickException("Shadow path cannot be the same as the official doc.")

    collision = check_shadow_path_collision_in_roots(shadow_path, path, forge_root, roots)
    if collision:
        raise click.ClickException(collision)

    # Auto-create shadow file if Forge-owned
    created = _auto_create_shadow(shadow_path, forge_root)
    shadow_abs = (forge_root / shadow_path).resolve()
    if not shadow_abs.is_file():
        raise click.ClickException(f"Shadow file does not exist: {shadow_path}")

    # Passport handling: synthesize or update.
    # For existing passports, pass strategy only when the user explicitly provided --strategy
    # so the passport's own strategy is preserved by default.
    if isinstance(passport, Passport) and passport.update.mode == "shadow-only":
        # Already shadow-only -- apply overrides if any
        try:
            resolved_pp, pp_warnings = resolve_with_overrides(
                passport,
                strategy=strategy,
                shadow_path=shadow_path if shadow_path != passport.update.shadow_path else None,
                writers=writers,
            )
        except PassportError as e:
            raise click.ClickException(str(e)) from e
        if pp_warnings:
            write_passport(abs_path, resolved_pp)
            for w in pp_warnings:
                console.print(f"[yellow]Warning:[/yellow] {w}")
            console.print(f"Passport updated in [cyan]{path}[/cyan]. Future sessions will use the new values.")
        else:
            console.print(f"Passport already present in [cyan]{path}[/cyan] (shadow-only proposals at {shadow_path}).")
    elif isinstance(passport, Passport):
        # Convert existing direct passport to shadow-only
        try:
            resolved_pp, pp_warnings = resolve_with_overrides(
                passport,
                strategy=strategy,
                update_mode="shadow-only",
                shadow_path=shadow_path,
                writers=writers,
            )
        except PassportError as e:
            raise click.ClickException(str(e)) from e
        write_passport(abs_path, resolved_pp)
        for w in pp_warnings:
            console.print(f"[yellow]Warning:[/yellow] {w}")
        console.print(f"Passport in [cyan]{path}[/cyan] converted to shadow-only proposals at {shadow_path}.")
    else:
        # No passport -- synthesize with default strategy
        try:
            new_pp = synthesize_passport(
                strategy=new_passport_strategy,
                intent=intent,
                update_mode="shadow-only",
                shadow_path=shadow_path,
                writers=writers or "all-sessions",
            )
            write_passport(abs_path, new_pp)
        except PassportError as e:
            raise click.ClickException(str(e)) from e
        console.print(
            f"Shadow-only passport written for [cyan]{path}[/cyan] "
            f"(strategy: {new_passport_strategy}, proposals at {shadow_path})."
        )

    if created:
        console.print(f"Shadow file created: {shadow_path}.")
    _warn_if_out_of_root(path, forge_root, roots)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@memory.command("list")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON.")
def list_cmd(as_json: bool) -> None:
    """List passported memory docs under scan roots."""
    import json

    from forge.session.project_memory import scan_all_passported_docs

    ctx = ExecutionContext.from_cwd()
    if ctx.forge_root is None:
        print_error("Not inside a Forge project.", console=console)
        sys.exit(1)
    forge_root = ctx.forge_root

    docs = scan_all_passported_docs(forge_root, DEFAULT_SCAN_ROOTS)

    enriched: list[dict[str, object]] = []
    for doc in docs:
        passport_path = forge_root / resolve_passport_source(doc)
        pp_strategy = doc.strategy
        pp_mode = "direct"
        pp_writers = "all-sessions"
        try:
            pp = read_passport(passport_path)
            if pp is not None:
                pp_strategy = pp.update.strategy
                pp_mode = pp.update.mode
                pp_writers = pp.update.writers
        except (FileNotFoundError, PassportError):
            pass
        enriched.append(
            {
                "path": doc.path,
                "shadows": doc.shadows,
                "strategy": pp_strategy,
                "mode": pp_mode,
                "writers": pp_writers,
            }
        )

    if as_json:
        click.echo(json.dumps(enriched, indent=2))
        return

    if not enriched:
        console.print("[dim]No passported memory docs found under scan roots.[/dim]")
        print_tip("Run 'forge memory track <path> --strategy <strategy>'.", blank_before=False, console=console)
        return

    from rich.table import Table

    has_shadows = any(e["shadows"] for e in enriched)

    table = Table(show_header=True, header_style="bold")
    table.add_column("Path", style="cyan")
    if has_shadows:
        table.add_column("Official", style="dim")
    table.add_column("Strategy")
    table.add_column("Mode")
    table.add_column("Writers")
    for entry in enriched:
        row = [str(entry["path"])]
        if has_shadows:
            row.append(str(entry["shadows"] or ""))
        row.extend(
            [
                str(entry["strategy"]),
                str(entry["mode"]),
                str(entry["writers"]),
            ]
        )
        table.add_row(*row)
    console.print(table)


# ---------------------------------------------------------------------------
# shadows subgroup
# ---------------------------------------------------------------------------


@memory.group("shadows")
def shadows_group() -> None:
    """Inspect accumulated shadow proposals."""


def _collect_shadow_entries(
    scope: str,
    session_filter: str | None,
) -> tuple[list[ShadowEntry], set[str]]:
    """Thin wrapper around session-layer ``collect_shadow_entries``."""
    from forge.session.shadow_curation import collect_shadow_entries

    ctx = ExecutionContext.from_cwd()
    return collect_shadow_entries(ctx=ctx, scope=scope, session_filter=session_filter)


@shadows_group.command("list")
@click.option(
    "--scope",
    type=click.Choice(["project", "workspace", "all"]),
    default="project",
    show_default=True,
    help="Scope for discovery.",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON.")
def shadows_list_cmd(scope: str, as_json: bool) -> None:
    """List shadow proposals discovered from passports."""
    try:
        entries, scanned_roots = _collect_shadow_entries(scope, None)
    except ForgeOpError as e:
        print_error(f"{e}", console=console)
        sys.exit(1)

    # Deduplicate by (forge_root, official, shadow_path)
    grouped: dict[tuple[str, str, str], list[str]] = {}
    strategy_map: dict[tuple[str, str, str], str] = {}
    for entry in entries:
        key = (entry.forge_root, entry.official, entry.shadow_path)
        grouped.setdefault(key, []).append(entry.session)
        strategy_map[key] = entry.strategy

    if as_json:
        rows = [
            {
                "official": k[1],
                "shadow_path": k[2],
                "strategy": strategy_map[k],
                "sessions": sorted(set(sessions)),
                "forge_root": k[0],
            }
            for k, sessions in sorted(grouped.items())
        ]
        click.echo(json.dumps(rows, indent=2))
        return

    if not grouped:
        console.print(f"[dim]No shadow proposals found (scope: {scope}).[/dim]")
        return

    from rich.table import Table

    multi_root = len(scanned_roots) > 1

    table = Table(show_header=True, header_style="bold")
    table.add_column("Official Target", style="cyan")
    table.add_column("Shadow Path")
    table.add_column("Sessions")
    table.add_column("Strategy")
    if multi_root:
        table.add_column("Forge Root", style="dim")

    for key, sessions in sorted(grouped.items()):
        row = [key[1], key[2], ", ".join(sorted(set(sessions))), strategy_map[key]]
        if multi_root:
            row.append(key[0])
        table.add_row(*row)

    console.print(table)


@shadows_group.command("show")
@click.option("--for", "for_doc", required=True, help="Official doc to show shadow content for.")
@click.option(
    "--scope",
    type=click.Choice(["project", "workspace", "all"]),
    default="project",
    show_default=True,
    help="Scope for discovery.",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON.")
def shadows_show_cmd(for_doc: str, scope: str, as_json: bool) -> None:
    """Show shadow proposal content for an official doc."""
    try:
        entries, scanned_roots = _collect_shadow_entries(scope, None)
    except ForgeOpError as e:
        print_error(f"{e}", console=console)
        sys.exit(1)

    matches = [entry for entry in entries if entry.official == for_doc]

    if as_json:
        # Multi-row: one entry per (forge_root, shadow_path). Unsafe/absent files
        # report readable=false + reason with content=null rather than dropping out.
        seen_rows: dict[tuple[str, str], list[str]] = {}
        for entry in matches:
            seen_rows.setdefault((entry.forge_root, entry.shadow_path), []).append(entry.session)

        shadows: list[dict[str, Any]] = []
        for (fr, shadow_path), sessions in sorted(seen_rows.items()):
            entry_root = Path(fr)
            shadow_err = is_safe_designated_doc_path(shadow_path, entry_root, entry_root.resolve())
            content: str | None = None
            readable = False
            reason: str | None = None
            if shadow_err:
                reason = shadow_err
            else:
                abs_path = entry_root / shadow_path
                if not abs_path.is_file():
                    reason = "shadow file does not exist yet"
                else:
                    content = abs_path.read_text(encoding="utf-8").strip()
                    readable = True
            shadows.append(
                {
                    "shadow_path": shadow_path,
                    "forge_root": fr,
                    "sessions": sorted(set(sessions)),
                    "content": content,
                    "readable": readable,
                    "reason": reason,
                }
            )
        click.echo(json.dumps({"official": for_doc, "scope": scope, "shadows": shadows}, indent=2))
        return

    if not matches:
        console.print(f"[dim]No shadow proposals found for {for_doc} (scope: {scope}).[/dim]")
        return

    # Deduplicate by (forge_root, shadow_path)
    seen: dict[tuple[str, str], list[str]] = {}
    for entry in matches:
        key = (entry.forge_root, entry.shadow_path)
        seen.setdefault(key, []).append(entry.session)

    multi_root = len(scanned_roots) > 1

    skipped: list[str] = []
    for (fr, shadow_path), sessions in sorted(seen.items()):
        entry_root = Path(fr)
        shadow_err = is_safe_designated_doc_path(shadow_path, entry_root, entry_root.resolve())
        if shadow_err:
            skipped.append(f"{shadow_path}: {shadow_err}")
            continue

        header_parts = [f"[bold]{shadow_path}[/bold]"]
        header_parts.append(f"sessions: {', '.join(sorted(set(sessions)))}")
        if multi_root:
            header_parts.append(f"root: {fr}")
        console.print(" | ".join(header_parts))
        console.print()

        abs_path = entry_root / shadow_path
        if not abs_path.is_file():
            console.print("[dim](shadow file does not exist yet)[/dim]")
        else:
            content = abs_path.read_text(encoding="utf-8").strip()
            if content:
                console.print(content)
            else:
                console.print("[dim](empty)[/dim]")
        console.print()

    for warning in skipped:
        console.print(f"[yellow]Warning:[/yellow] Skipping unsafe shadow path {warning}")

    if skipped and len(skipped) == len(seen):
        console.print(f"[dim]No readable shadow proposals found for {for_doc} (scope: {scope}).[/dim]")


@shadows_group.command("review")
@click.option("--for", "for_doc", required=True, help="Official doc to review.")
@click.option("--curate", is_flag=True, default=False, help="Run LLM curation.")
@click.option("--show-latest", is_flag=True, default=False, help="Show latest curation report.")
@click.option("--session", "-s", "session_name", default=None, help="Session name.")
@click.option(
    "--scope",
    type=click.Choice(["project", "workspace", "all"]),
    default="project",
    show_default=True,
    help="Scope for shadow discovery.",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON.")
@click.option(
    "--effort",
    "effort",
    type=click.Choice(list(CLAUDE_EFFORT_LEVELS)),
    default=None,
    help="Curation reasoning effort (claude --effort: low/medium/high/xhigh/max). Used with --curate.",
)
def shadows_review_cmd(
    for_doc: str,
    curate: bool,
    show_latest: bool,
    session_name: str | None,
    scope: str,
    as_json: bool,
    effort: str | None,
) -> None:
    """Review shadow proposals for an official doc."""
    if curate and show_latest:
        raise click.ClickException("--curate and --show-latest are mutually exclusive.")
    if effort and not curate:
        raise click.ClickException("--effort applies only to --curate.")

    if show_latest:
        _review_show_latest(for_doc, session_name, scope, as_json)
        return

    if curate:
        _review_curate(for_doc, session_name, scope, as_json, effort=effort)
        return

    # Bare review: show raw content + hint
    ctx = click.get_current_context()
    ctx.invoke(shadows_show_cmd, for_doc=for_doc, scope=scope)
    print_tip("Use --curate to run LLM synthesis, --show-latest to view the last report.", console=console)


def _review_show_latest(
    for_doc: str,
    session_name: str | None,
    scope: str,
    as_json: bool,
) -> None:
    """Handle ``--show-latest``: session-scoped report retrieval."""
    from forge.session.shadow_curation import curation_report_dir, report_glob_pattern

    if scope != "project":
        raise click.ClickException("Reports are session-scoped; --scope is not applicable with --show-latest.")

    ctx = ExecutionContext.from_cwd()
    try:
        resolved = resolve_session(ctx=ctx, session_name=session_name)
    except (ForgeSessionError, ForgeOpError) as e:
        raise click.ClickException(f"Could not resolve session: {e}. Set FORGE_SESSION or pass --session.")

    state = resolved.state
    forge_root_str = state.forge_root or (state.worktree.path if state.worktree else None)
    if not forge_root_str:
        raise click.ClickException("Could not resolve forge_root for session.")
    forge_root = Path(forge_root_str)

    report_dir = curation_report_dir(forge_root, resolved.store.session_name)
    pattern = report_glob_pattern(for_doc)
    reports = sorted(report_dir.glob(pattern)) if report_dir.is_dir() else []

    if not reports:
        if as_json:
            click.echo(json.dumps({"success": False, "reason": "no_reports", "official": for_doc}, indent=2))
        else:
            console.print(f"[dim]No curation reports found for {for_doc}.[/dim]")
            print_tip("Use --curate to generate one.", blank_before=False, console=console)
        return

    latest = reports[-1]
    content = latest.read_text(encoding="utf-8")

    if as_json:
        click.echo(
            json.dumps(
                {
                    "success": True,
                    "official": for_doc,
                    "report_path": str(latest),
                    "content": content,
                },
                indent=2,
            )
        )
    else:
        console.print(content)


def _review_curate(
    for_doc: str,
    session_name: str | None,
    scope: str,
    as_json: bool,
    effort: str | None = None,
) -> None:
    """Handle ``--curate``: run LLM curation."""
    import os

    from forge.session.memory_writer import resolve_writer_base_url
    from forge.session.shadow_curation import (
        collect_shadow_entries,
        run_shadow_curation,
    )

    if scope == "all":
        raise click.ClickException("Cross-project curation deferred; use --scope project or --scope workspace.")

    ctx = ExecutionContext.from_cwd()
    try:
        resolved = resolve_session(ctx=ctx, session_name=session_name)
    except (ForgeSessionError, ForgeOpError) as e:
        raise click.ClickException(f"Curation requires an active session: {e}. Set FORGE_SESSION or pass --session.")

    state = resolved.state
    forge_root_str = state.forge_root or (state.worktree.path if state.worktree else None)
    if not forge_root_str:
        raise click.ClickException("Could not resolve forge_root for session.")
    forge_root = Path(forge_root_str)

    from forge.session.effective import compute_effective_intent

    effective = compute_effective_intent(state)

    # Validate official doc path before reading
    resolved_root = forge_root.resolve()
    safety_err = is_safe_designated_doc_path(for_doc, forge_root, resolved_root)
    if safety_err:
        raise click.ClickException(f"Unsafe official doc path: {safety_err}")

    # Anchor shadow discovery to the resolved session's forge_root so
    # --session cross-project doesn't mix CWD shadows with another root's official doc.
    session_ctx = ExecutionContext.from_cwd(cwd=forge_root)
    try:
        entries, _roots = collect_shadow_entries(ctx=session_ctx, scope=scope, session_filter=None)
    except ForgeOpError as e:
        raise click.ClickException(str(e))

    matches = [entry for entry in entries if entry.official == for_doc]
    if not matches:
        if as_json:
            click.echo(
                json.dumps(
                    {"success": True, "official": for_doc, "shadow_count": 0, "report_path": None, "scope": scope},
                    indent=2,
                )
            )
        else:
            console.print(f"[dim]No shadow proposals found for {for_doc} (scope: {scope}).[/dim]")
        return

    # Read official doc from the resolved session's forge_root
    official_abs = forge_root / for_doc
    if not official_abs.is_file():
        raise click.ClickException(f"Official doc not found: {official_abs}")
    official_content = official_abs.read_text(encoding="utf-8")

    # Populate shadow content and deduplicate, with path safety checks
    seen: dict[tuple[str, str], ShadowEntry] = {}
    for entry in matches:
        entry_root = Path(entry.forge_root)
        shadow_err = is_safe_designated_doc_path(entry.shadow_path, entry_root, entry_root.resolve())
        if shadow_err:
            logger.warning("Skipping unsafe shadow path: %s", shadow_err)
            continue
        key = (entry.forge_root, entry.shadow_path)
        if key in seen:
            existing = seen[key]
            existing_sessions = existing.session.split(", ")
            if entry.session not in existing_sessions:
                seen[key] = ShadowEntry(
                    official=entry.official,
                    shadow_path=entry.shadow_path,
                    strategy=entry.strategy,
                    session=f"{existing.session}, {entry.session}",
                    forge_root=entry.forge_root,
                    content=existing.content,
                )
            continue
        abs_path = entry_root / entry.shadow_path
        content = ""
        if abs_path.is_file():
            content = abs_path.read_text(encoding="utf-8")
        seen[key] = ShadowEntry(
            official=entry.official,
            shadow_path=entry.shadow_path,
            strategy=entry.strategy,
            session=entry.session,
            forge_root=entry.forge_root,
            content=content,
        )

    shadow_entries = list(seen.values())

    # Resolve proxy routing
    config = effective.memory.auto_update if effective.memory and effective.memory.auto_update else None
    confirmed_proxy_url = None
    if state.confirmed.started_with_proxy:
        confirmed_proxy_url = state.confirmed.started_with_proxy.base_url

    direct = config.direct if config else False
    base_url = resolve_writer_base_url(
        proxy_id=config.proxy if config else None,
        confirmed_proxy_base_url=confirmed_proxy_url,
        env_base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        direct=direct,
        subprocess_proxy=effective.subprocess_proxy,
    )

    if not as_json:
        console.print(f"[dim]Curating {len(shadow_entries)} shadow source(s) for {for_doc}...[/dim]")

    # --effort overrides; otherwise inherit the memory writer's configured effort
    # (curation already inherits proxy/direct routing from the same config).
    effective_effort = effort or (config.effort if config else None)

    result = run_shadow_curation(
        session_name=resolved.store.session_name,
        forge_root=forge_root,
        official_path=for_doc,
        official_content=official_content,
        shadow_entries=shadow_entries,
        base_url=base_url,
        direct=direct,
        scope=scope,
        reasoning_effort=effective_effort,
    )

    if as_json:
        click.echo(
            json.dumps(
                {
                    "success": result.success,
                    "official": for_doc,
                    "report_path": str(result.report_path) if result.report_path else None,
                    "shadow_count": len(shadow_entries),
                    "scope": scope,
                },
                indent=2,
            )
        )
        if not result.success:
            sys.exit(1)
    elif result.success:
        console.print(result.stdout)
        if result.report_path:
            console.print(f"\n[dim]Report saved: {result.report_path}[/dim]")
    else:
        console.print("[red]Curation failed.[/red]")
        if result.stdout:
            console.print(result.stdout)
        sys.exit(1)


# ---------------------------------------------------------------------------
# passport subgroup
# ---------------------------------------------------------------------------


@memory.group("passport")
def passport_group() -> None:
    """Inspect and remove memory-doc passports."""


@passport_group.command("show")
@click.argument("path")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON.")
def passport_show_cmd(path: str, as_json: bool) -> None:
    """Show the passport embedded in a memory doc."""
    from dataclasses import asdict

    try:
        ctx = ExecutionContext.from_cwd()
    except ForgeOpError as e:
        raise click.ClickException(str(e)) from e

    if ctx.forge_root is None:
        raise click.ClickException("Not inside a Forge project. Run `forge extension enable` first.")

    resolved_base = ctx.forge_root.resolve()
    reason = is_safe_designated_doc_path(path, ctx.forge_root, resolved_base)
    if reason:
        raise click.ClickException(f"Invalid path: {reason}")

    abs_path = (ctx.forge_root / path).resolve()

    if not abs_path.is_file():
        raise click.ClickException(f"File not found: {path}")

    try:
        passport = read_passport(abs_path)
    except PassportError as e:
        raise click.ClickException(f"Malformed passport in {path}: {e}") from e

    if passport is None:
        if as_json:
            click.echo(
                json.dumps(
                    {
                        "success": False,
                        "reason": "no_passport",
                        "path": path,
                        "tip": f"forge memory track {path} --strategy <strategy>",
                    },
                    indent=2,
                )
            )
            return
        console.print(f"[dim]No passport found in {path}.[/dim]")
        print_tip(f"Run 'forge memory track {path} --strategy <strategy>' to add one.", console=console)
        return

    if as_json:
        raw = asdict(passport)
        update = raw.get("update", {})
        raw["update"] = {k: v for k, v in update.items() if v is not None}
        click.echo(json.dumps(raw, indent=2))
        return

    from rich.table import Table

    table = Table(show_header=True, header_style="bold")
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    table.add_row("version", str(passport.version))
    table.add_row("intent", passport.intent)
    table.add_row("captures", ", ".join(passport.captures) if passport.captures else "(none)")
    table.add_row("excludes", ", ".join(passport.excludes) if passport.excludes else "(none)")
    table.add_row("strategy", passport.update.strategy)
    table.add_row("mode", passport.update.mode)
    table.add_row("writers", passport.update.writers)
    if passport.update.compact_when:
        table.add_row("compact_when", passport.update.compact_when)
    if passport.update.shadow_path:
        table.add_row("shadow_path", passport.update.shadow_path)
    if passport.update.approval:
        table.add_row("approval", passport.update.approval)
    if passport.update.instruction:
        table.add_row("instruction", passport.update.instruction)

    console.print(table)


@passport_group.command("remove")
@click.argument("path")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON.")
def passport_remove_cmd(path: str, as_json: bool) -> None:
    """Remove the project-memory passport from a doc."""
    try:
        ctx = ExecutionContext.from_cwd()
    except ForgeOpError as e:
        raise click.ClickException(str(e)) from e

    if ctx.forge_root is None:
        raise click.ClickException("Not inside a Forge project. Run `forge extension enable` first.")

    resolved_base = ctx.forge_root.resolve()
    reason = is_safe_designated_doc_path(path, ctx.forge_root, resolved_base)
    if reason:
        raise click.ClickException(f"Invalid path: {reason}")

    abs_path = (ctx.forge_root / path).resolve()
    if not abs_path.is_file():
        raise click.ClickException(f"File not found: {path}")

    try:
        removed = remove_passport(abs_path)
    except PassportError as e:
        raise click.ClickException(f"Malformed frontmatter in {path}: {e}") from e

    if as_json:
        payload: dict[str, object] = {"success": removed, "removed": removed, "path": path}
        if not removed:
            payload["reason"] = "no_passport"
        click.echo(json.dumps(payload, indent=2))
        return

    if removed:
        console.print(f"Passport removed from [cyan]{path}[/cyan].")
        console.print("[dim]This doc is no longer project-discovered unless added as a session extra.[/dim]")
    else:
        console.print(f"[dim]No passport found in {path}.[/dim]")

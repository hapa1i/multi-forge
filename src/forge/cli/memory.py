"""``forge memory`` -- top-level memory doc management.

Replaces ``forge session memory`` (Phase 2 of the memory enhancement proposal).
Each command manages doc participation in session manifests and passport
frontmatter. The handoff agent re-reads passports at stop time for the
authoritative contract (Phase 1 design: passport-authoritative).
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import click

from forge.cli.session import console
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import ForgeOpError, resolve_session, set_session_override
from forge.session.exceptions import ForgeSessionError, PassportError
from forge.session.handoff_agent import is_safe_designated_doc_path
from forge.session.models import DesignatedDoc
from forge.session.passport import (
    VALID_STRATEGY_NAMES,
    read_passport,
    resolve_passport_source,
    resolve_with_overrides,
    synthesize_passport,
    write_passport,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _current_docs(*, ctx: ExecutionContext, session_name: str | None) -> tuple[list[DesignatedDoc], Path]:
    """Return (effective designated_docs, forge_root) for the resolved session."""
    resolved = resolve_session(ctx=ctx, session_name=session_name)
    state = resolved.state
    from forge.session.effective import compute_effective_intent

    effective = compute_effective_intent(state)
    docs = list(effective.memory.designated_docs) if effective.memory else []
    forge_root_str = state.forge_root or (state.worktree.path if state.worktree else None)
    if forge_root_str is None:
        raise ForgeOpError("Could not resolve forge_root for session.")
    return docs, Path(forge_root_str)


def _write_docs(*, ctx: ExecutionContext, session_name: str | None, docs: list[DesignatedDoc]) -> None:
    """Persist docs as an override on ``memory.designated_docs``."""
    payload = [{"path": d.path, "strategy": d.strategy, "shadows": d.shadows} for d in docs]
    set_session_override(
        ctx=ctx,
        session_name=session_name,
        key="memory.designated_docs",
        value_str=json.dumps(payload),
    )


def _check_legacy_docs(docs: list[DesignatedDoc], forge_root: Path) -> list[str]:
    """Return warning lines if docs lack passports or have malformed ones.

    Separates missing from malformed for actionable guidance.
    Uses ``resolve_passport_source(doc)`` so shadow entries check the official doc.
    """
    if not docs:
        return []
    missing = 0
    malformed = 0
    for doc in docs:
        passport_path = forge_root / resolve_passport_source(doc)
        try:
            if read_passport(passport_path) is None:
                missing += 1
        except FileNotFoundError:
            missing += 1
        except PassportError:
            malformed += 1
    warnings: list[str] = []
    if missing:
        warnings.append(
            f"{missing} of {len(docs)} tracked doc(s) have no passport "
            "(manifest-fallback behavior). Re-track to attach passports: "
            "forge memory track <path> --as <strategy> --session <name>"
        )
    if malformed:
        warnings.append(
            f"{malformed} of {len(docs)} tracked doc(s) have malformed passports. "
            "Fix the YAML frontmatter in the affected files."
        )
    return warnings


def _auto_enable_memory(*, ctx: ExecutionContext, session_name: str | None, effective_memory: object) -> bool:
    """Enable memory auto-update if not yet enabled. Returns True if enabled."""
    from forge.session.models import MemoryIntent

    needs_enable = True
    if isinstance(effective_memory, MemoryIntent) and effective_memory.auto_update:
        needs_enable = not effective_memory.auto_update.enabled

    if not needs_enable:
        return False

    set_session_override(
        ctx=ctx,
        session_name=session_name,
        key="memory.auto_update.enabled",
        value_str="true",
    )
    set_session_override(
        ctx=ctx,
        session_name=session_name,
        key="memory.auto_update.mode",
        value_str='"augment"',
    )
    return True


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------


@click.group("memory")
def memory() -> None:
    """Manage project memory docs and handoff agent tracking.

    \b
    Examples:
        forge memory enable --session planner
        forge memory track docs/changelog.md --as changelog --session planner
        forge memory list --session planner
        forge memory status --scope repo
    """


# ---------------------------------------------------------------------------
# enable
# ---------------------------------------------------------------------------


@memory.command("enable")
@click.option("--session", "-s", "session_name", default=None, help="Target session (default: active session).")
@click.option("--review-only", is_flag=True, default=False, help="Enable in review-only mode (no edits).")
def enable_cmd(session_name: str | None, review_only: bool) -> None:
    """Enable memory auto-update for the handoff agent.

    Idempotent. Sets mode=augment by default, or mode=review-only
    with --review-only. Shows tracked docs after enabling.
    """
    try:
        ctx = ExecutionContext.from_cwd()
        resolved = resolve_session(ctx=ctx, session_name=session_name)
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    from forge.session.effective import compute_effective_intent

    state = resolved.state
    effective = compute_effective_intent(state)
    target_mode = "review-only" if review_only else "augment"
    display_name = session_name or state.name

    already = False
    current_mode: str | None = None
    already_enabled = False
    if effective.memory and effective.memory.auto_update and effective.memory.auto_update.enabled:
        already_enabled = True
        current_mode = effective.memory.auto_update.mode
        if effective.memory.auto_update.mode == target_mode:
            console.print(
                f"[dim]Memory auto-update already enabled for session " f"{display_name} (mode: {target_mode}).[/dim]"
            )
            already = True
        # Enabled with different mode -- update mode only
    if not already:
        try:
            set_session_override(
                ctx=ctx,
                session_name=session_name,
                key="memory.auto_update.enabled",
                value_str="true",
            )
            set_session_override(
                ctx=ctx,
                session_name=session_name,
                key="memory.auto_update.mode",
                value_str=json.dumps(target_mode),
            )
        except ForgeOpError as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
        if already_enabled and current_mode is not None:
            console.print(
                f"Memory auto-update mode changed for session {display_name}: " f"{current_mode} -> {target_mode}."
            )
        else:
            console.print(f"Memory auto-update enabled for session {display_name} (mode: {target_mode}).")

    docs = list(effective.memory.designated_docs) if effective.memory else []
    if docs:
        console.print(f"\n[dim]Currently tracking {len(docs)} doc(s).[/dim]")
    else:
        console.print(
            f"\n[dim]No docs tracked yet. "
            f"Use: forge memory track <path> --as <strategy> --session {display_name}[/dim]"
        )

    forge_root_str = state.forge_root or (state.worktree.path if state.worktree else None)
    if forge_root_str and docs:
        for w in _check_legacy_docs(docs, Path(forge_root_str)):
            console.print(f"[yellow]Warning:[/yellow] {w}")


# ---------------------------------------------------------------------------
# track
# ---------------------------------------------------------------------------


@memory.command("track")
@click.argument("path")
@click.option(
    "--as",
    "strategy",
    type=click.Choice(sorted(VALID_STRATEGY_NAMES)),
    default=None,
    help="Augmentation strategy.",
)
@click.option("--intent", default=None, help="Doc intent description for passport synthesis.")
@click.option("--writers", default=None, help="Writer spec (default: all-sessions).")
@click.option("--session", "-s", "session_name", default=None, help="Target session (default: active session).")
def track_cmd(
    path: str,
    strategy: str | None,
    intent: str | None,
    writers: str | None,
    session_name: str | None,
) -> None:
    """Track a memory doc for handoff agent updates.

    Adds the doc to the session's tracked list. If the doc has no passport,
    one is synthesized from the provided flags (--as is required in that case).
    Re-running updates the configuration without duplicating the entry.
    """
    try:
        ctx = ExecutionContext.from_cwd()
        docs, forge_root = _current_docs(ctx=ctx, session_name=session_name)
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    resolved_base = forge_root.resolve()
    reason = is_safe_designated_doc_path(path, forge_root, resolved_base)
    if reason:
        raise click.ClickException(f"Invalid path: {reason}")

    abs_path = (forge_root / path).resolve()
    if not abs_path.is_file():
        raise click.ClickException(f"File does not exist: {path}")

    # Read existing passport
    try:
        passport = read_passport(abs_path)
    except PassportError as e:
        raise click.ClickException(f"Malformed passport in {path}: {e}") from e

    # Reject shadow-only passports in Phase 2 (direct mode only)
    if passport and passport.update.mode == "shadow-only":
        raise click.ClickException(
            "This doc's passport uses shadow-only mode, which requires shadow tracking "
            "(not yet available). Edit the passport to use direct mode, or wait for "
            "shadow tracking support."
        )

    messages: list[str] = []
    has_flags = strategy is not None or writers is not None
    effective_passport = passport

    if passport is None and strategy is None:
        # No passport and no --as: fail with actionable command
        raise click.ClickException(
            f"This doc has no passport. Provide a strategy:\n"
            f"  forge memory track {path} --as <strategy> --session <name>\n\n"
            f"Valid strategies: {', '.join(sorted(VALID_STRATEGY_NAMES))}"
        )

    if passport is None:
        # Synthesize from flags
        try:
            effective_passport = synthesize_passport(
                strategy=strategy,  # type: ignore[arg-type]  # checked above
                intent=intent,
                writers=writers or "all-sessions",
            )
            write_passport(abs_path, effective_passport)
        except PassportError as e:
            raise click.ClickException(str(e)) from e
        messages.append(f"Passport created for {path} (strategy: {strategy}).")
    elif has_flags:
        # Apply flag overrides and rewrite passport
        try:
            resolved_pp, warnings = resolve_with_overrides(
                passport,
                strategy=strategy,
                writers=writers,
            )
        except PassportError as e:
            raise click.ClickException(str(e)) from e
        if warnings:
            write_passport(abs_path, resolved_pp)
            effective_passport = resolved_pp
            for w in warnings:
                messages.append(f"[yellow]Warning:[/yellow] {w}")
            messages.append(f"Passport updated in {path}. Future sessions will use the new values.")

    assert effective_passport is not None
    doc = DesignatedDoc(path=path, strategy=effective_passport.update.strategy)

    # Upsert
    was_update = False
    new_docs: list[DesignatedDoc] = []
    for d in docs:
        if d.path == path:
            new_docs.append(doc)
            was_update = True
        else:
            new_docs.append(d)
    if not was_update:
        new_docs.append(doc)

    # Persist docs
    try:
        _write_docs(ctx=ctx, session_name=session_name, docs=new_docs)
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    # Re-read effective for auto-enable check
    from forge.session.effective import compute_effective_intent as _compute

    resolved_session = resolve_session(ctx=ctx, session_name=session_name)
    effective_after = _compute(resolved_session.state)
    auto_enabled = _auto_enable_memory(
        ctx=ctx,
        session_name=session_name,
        effective_memory=effective_after.memory,
    )

    # Print in narrative order: tracking result, passport notices, auto-enable
    if was_update:
        console.print(f"Updated tracking for [cyan]{path}[/cyan] (strategy: {effective_passport.update.strategy}).")
    else:
        console.print(f"Tracking [cyan]{path}[/cyan] directly as {effective_passport.update.strategy}.")
    for msg in messages:
        console.print(msg)
    if auto_enabled:
        console.print("Memory auto-update enabled (mode: augment).")


# ---------------------------------------------------------------------------
# untrack
# ---------------------------------------------------------------------------


@memory.command("untrack")
@click.argument("path")
@click.option("--session", "-s", "session_name", default=None, help="Target session (default: active session).")
def untrack_cmd(path: str, session_name: str | None) -> None:
    """Stop tracking a memory doc. Passport frontmatter is left intact."""
    try:
        ctx = ExecutionContext.from_cwd()
        docs, _ = _current_docs(ctx=ctx, session_name=session_name)
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    before = len(docs)
    docs = [d for d in docs if d.path != path]
    if len(docs) == before:
        console.print(f"[dim]Not tracked: {path}[/dim]")
        return

    try:
        _write_docs(ctx=ctx, session_name=session_name, docs=docs)
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    console.print(f"Untracked [cyan]{path}[/cyan].")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@memory.command("list")
@click.option("--session", "-s", "session_name", default=None, help="Target session (default: active session).")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON.")
def list_cmd(session_name: str | None, as_json: bool) -> None:
    """List tracked memory docs for the session."""
    try:
        ctx = ExecutionContext.from_cwd()
        docs, forge_root = _current_docs(ctx=ctx, session_name=session_name)
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    # Read passport info per doc (best-effort)
    enriched: list[dict[str, object]] = []
    for doc in docs:
        passport_path = forge_root / resolve_passport_source(doc)
        has_passport = False
        pp_strategy = doc.strategy
        pp_mode = "direct"
        pp_writers = "all-sessions"
        try:
            pp = read_passport(passport_path)
            if pp is not None:
                has_passport = True
                pp_strategy = pp.update.strategy
                pp_mode = pp.update.mode
                pp_writers = pp.update.writers
        except (FileNotFoundError, PassportError):
            pass
        enriched.append(
            {
                "path": doc.path,
                "strategy": pp_strategy,
                "mode": pp_mode,
                "writers": pp_writers,
                "has_passport": has_passport,
            }
        )

    if as_json:
        click.echo(json.dumps(enriched, indent=2))
        return

    if not enriched:
        console.print("[dim]No tracked memory docs for this session.[/dim]")
        console.print("[dim]Tip: forge memory track <path> --as <strategy>[/dim]")
        return

    from rich.table import Table

    table = Table(show_header=True, header_style="bold")
    table.add_column("Path", style="cyan")
    table.add_column("Strategy")
    table.add_column("Mode")
    table.add_column("Writers")
    table.add_column("Passport")
    for entry in enriched:
        table.add_row(
            str(entry["path"]),
            str(entry["strategy"]),
            str(entry["mode"]),
            str(entry["writers"]),
            "yes" if entry["has_passport"] else "no",
        )
    console.print(table)

    for w in _check_legacy_docs(docs, forge_root):
        console.print(f"[yellow]Warning:[/yellow] {w}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@memory.command("status")
@click.option(
    "--scope",
    type=click.Choice(["project", "repo", "all"]),
    default="project",
    show_default=True,
    help="Scope for discovery.",
)
@click.option("--doc", "doc_filter", default=None, help="Filter to a specific doc path.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON.")
def status_cmd(scope: str, doc_filter: str | None, as_json: bool) -> None:
    """Show memory doc status across sessions.

    Aggregates which sessions track each doc, their strategies,
    update modes, and writer specs.
    """
    from forge.core.ops.session import list_sessions
    from forge.session.effective import compute_effective_intent
    from forge.session.manager import SessionManager

    try:
        ctx = ExecutionContext.from_cwd()
        result = list_sessions(ctx=ctx, include_incognito=False, scope=scope)
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    manager = SessionManager()
    entries: list[dict[str, object]] = []
    scanned_roots: set[str] = set()

    for item in result.sessions:
        entry = item.entry
        fr = entry.forge_root or entry.worktree_path
        if not fr:
            continue
        scanned_roots.add(fr)

        try:
            manifest = manager.get_session(item.name, forge_root=fr)
            effective = compute_effective_intent(manifest)
        except (ForgeSessionError, ForgeOpError, OSError):
            logger.debug("Failed to read manifest for session %r in %s", item.name, fr, exc_info=True)
            continue

        if not effective.memory:
            continue

        forge_root_path = Path(fr)
        for doc in effective.memory.designated_docs:
            if doc_filter and doc.path != doc_filter:
                continue

            # Best-effort passport read
            pp_strategy = doc.strategy
            pp_mode = "direct"
            pp_writers = "all-sessions"
            has_passport = False
            passport_error: str | None = None
            passport_path = forge_root_path / resolve_passport_source(doc)
            try:
                pp = read_passport(passport_path)
                if pp is not None:
                    has_passport = True
                    pp_strategy = pp.update.strategy
                    pp_mode = pp.update.mode
                    pp_writers = pp.update.writers
            except FileNotFoundError:
                pass
            except PassportError as e:
                passport_error = str(e)

            entries.append(
                {
                    "path": doc.path,
                    "session": item.name,
                    "forge_root": fr,
                    "strategy": pp_strategy,
                    "mode": pp_mode,
                    "writers": pp_writers,
                    "has_passport": has_passport,
                    "passport_error": passport_error,
                }
            )

    if as_json:
        click.echo(json.dumps({"entries": entries, "scanned_roots": sorted(scanned_roots)}, indent=2))
        return

    if not entries:
        console.print(f"[dim]No tracked memory docs found (scope: {scope}).[/dim]")
        if scanned_roots:
            console.print(f"[dim]Scanned {len(scanned_roots)} root(s).[/dim]")
        return

    from rich.table import Table

    # Group by forge_root when multiple roots
    multi_root = len(scanned_roots) > 1

    table = Table(show_header=True, header_style="bold")
    table.add_column("Doc Path", style="cyan")
    table.add_column("Session")
    if multi_root:
        table.add_column("Forge Root", style="dim")
    table.add_column("Strategy")
    table.add_column("Mode")
    table.add_column("Writers")
    table.add_column("Passport")

    for row_data in sorted(entries, key=lambda x: (str(x["path"]), str(x["session"]))):
        passport_col = "yes" if row_data["has_passport"] else "no"
        if row_data["passport_error"]:
            passport_col = "error"
        row = [str(row_data["path"]), str(row_data["session"])]
        if multi_root:
            row.append(str(row_data["forge_root"]))
        row.extend([str(row_data["strategy"]), str(row_data["mode"]), str(row_data["writers"]), passport_col])
        table.add_row(*row)

    console.print(table)
    if multi_root:
        console.print(f"\n[dim]Scanned {len(scanned_roots)} root(s).[/dim]")

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
from forge.session.models import DesignatedDoc
from forge.session.passport import (
    VALID_STRATEGY_NAMES,
    Passport,
    check_shadow_path_collision,
    derive_shadow_path,
    read_passport,
    resolve_passport_source,
    resolve_with_overrides,
    synthesize_passport,
    write_passport,
)
from forge.session.shadow_curation import ShadowEntry
from forge.session.validation import is_safe_designated_doc_path

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
@click.option("--propose", is_flag=True, default=False, help="Track via shadow proposal (shadow-only mode).")
@click.option("--shadow", "shadow_override", default=None, help="Explicit shadow file path (use with --propose).")
@click.option("--session", "-s", "session_name", default=None, help="Target session (default: active session).")
def track_cmd(
    path: str,
    strategy: str | None,
    intent: str | None,
    writers: str | None,
    propose: bool,
    shadow_override: str | None,
    session_name: str | None,
) -> None:
    """Track a memory doc for handoff agent updates.

    Adds the doc to the session's tracked list. If the doc has no passport,
    one is synthesized from the provided flags (--as is required in that case).
    Re-running updates the configuration without duplicating the entry.

    Use --propose to track via shadow proposals: the handoff agent writes
    suggestions to a shadow file instead of editing the official doc directly.
    """
    # Early flag-combination validation
    if shadow_override and not propose:
        raise click.ClickException("--shadow requires --propose.")
    if propose and strategy is not None and strategy != "suggested":
        raise click.ClickException(f"--propose requires strategy 'suggested'. Got '{strategy}'.")

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

    # Read existing passport on the official doc
    try:
        passport = read_passport(abs_path)
    except PassportError as e:
        raise click.ClickException(f"Malformed passport in {path}: {e}") from e

    if propose:
        _track_propose(
            ctx=ctx,
            path=path,
            abs_path=abs_path,
            passport=passport,
            strategy=strategy,
            intent=intent,
            writers=writers,
            shadow_override=shadow_override,
            session_name=session_name,
            docs=docs,
            forge_root=forge_root,
        )
        return

    # Shadow-only passport without --propose: honor the passport's shadow_path
    if passport and passport.update.mode == "shadow-only":
        shadow_path = passport.update.shadow_path
        if not shadow_path:
            raise click.ClickException(
                f"Passport in {path} has mode 'shadow-only' but no shadow_path. "
                "Fix the passport or re-track with --propose."
            )
        collision = check_shadow_path_collision(shadow_path, path, docs)
        if collision:
            raise click.ClickException(collision)

        messages: list[str] = []
        has_flags = strategy is not None or writers is not None
        effective_passport = passport
        if has_flags:
            try:
                resolved_pp, pp_warnings = resolve_with_overrides(
                    passport,
                    strategy=strategy,
                    writers=writers,
                )
            except PassportError as exc:
                raise click.ClickException(str(exc)) from exc
            if pp_warnings:
                write_passport(abs_path, resolved_pp)
                effective_passport = resolved_pp
                for w in pp_warnings:
                    messages.append(f"[yellow]Warning:[/yellow] {w}")
                messages.append(f"Passport updated in {path}. Future sessions will use the new values.")

        created = _auto_create_shadow(shadow_path, forge_root)
        shadow_abs = (forge_root / shadow_path).resolve()
        if not shadow_abs.is_file():
            raise click.ClickException(f"Shadow file does not exist: {shadow_path}")
        if created:
            messages.append(f"Shadow file created: {shadow_path}.")
        doc = DesignatedDoc(path=shadow_path, strategy=effective_passport.update.strategy, shadows=path)
        _upsert_and_finish(
            ctx=ctx,
            session_name=session_name,
            docs=docs,
            doc=doc,
            official_path=path,
            shadow_path=shadow_path,
            messages=messages,
        )
        return

    # --- Direct tracking flow (unchanged from Phase 2) ---
    direct_messages: list[str] = []
    has_flags = strategy is not None or writers is not None
    direct_passport: Passport | None = passport

    if passport is None and strategy is None:
        raise click.ClickException(
            f"This doc has no passport. Provide a strategy:\n"
            f"  forge memory track {path} --as <strategy> --session <name>\n\n"
            f"Valid strategies: {', '.join(sorted(VALID_STRATEGY_NAMES))}"
        )

    if passport is None:
        try:
            direct_passport = synthesize_passport(
                strategy=strategy,  # type: ignore[arg-type]  # checked above
                intent=intent,
                writers=writers or "all-sessions",
            )
            write_passport(abs_path, direct_passport)
        except PassportError as e:
            raise click.ClickException(str(e)) from e
        direct_messages.append(f"Passport created for {path} (strategy: {strategy}).")
    elif has_flags:
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
            direct_passport = resolved_pp
            for w in warnings:
                direct_messages.append(f"[yellow]Warning:[/yellow] {w}")
            direct_messages.append(f"Passport updated in {path}. Future sessions will use the new values.")

    assert direct_passport is not None
    doc = DesignatedDoc(path=path, strategy=direct_passport.update.strategy)
    _upsert_and_finish(
        ctx=ctx,
        session_name=session_name,
        docs=docs,
        doc=doc,
        official_path=path,
        shadow_path=None,
        messages=direct_messages,
    )


def _track_propose(
    *,
    ctx: ExecutionContext,
    path: str,
    abs_path: Path,
    passport: Passport | None,
    strategy: str | None,
    intent: str | None,
    writers: str | None,
    shadow_override: str | None,
    session_name: str | None,
    docs: list[DesignatedDoc],
    forge_root: Path,
) -> None:
    """Handle ``track --propose`` flow."""
    effective_strategy = strategy or "suggested"
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

    collision = check_shadow_path_collision(shadow_path, path, docs)
    if collision:
        raise click.ClickException(collision)

    # Auto-create shadow file if Forge-owned
    created = _auto_create_shadow(shadow_path, forge_root)
    shadow_abs = (forge_root / shadow_path).resolve()
    if not shadow_abs.is_file():
        raise click.ClickException(f"Shadow file does not exist: {shadow_path}")

    messages: list[str] = []
    if created:
        messages.append(f"Shadow file created: {shadow_path}.")

    # Check for direct→shadow conversion
    converting = any(d.path == path and d.shadows is None for d in docs)
    if converting:
        messages.insert(0, "[yellow]Warning:[/yellow] Converting direct tracking to shadow proposal.")

    # Passport handling: synthesize or update
    if isinstance(passport, Passport) and passport.update.mode == "shadow-only":
        # Already shadow-only — apply overrides if any
        try:
            resolved_pp, pp_warnings = resolve_with_overrides(
                passport,
                strategy=effective_strategy if effective_strategy != passport.update.strategy else None,
                shadow_path=shadow_path if shadow_path != passport.update.shadow_path else None,
                writers=writers,
            )
        except PassportError as e:
            raise click.ClickException(str(e)) from e
        if pp_warnings:
            write_passport(abs_path, resolved_pp)
            for w in pp_warnings:
                messages.append(f"[yellow]Warning:[/yellow] {w}")
            messages.append(f"Passport updated in {path}. Future sessions will use the new values.")
    elif isinstance(passport, Passport):
        # Convert existing direct passport to shadow-only
        try:
            resolved_pp, pp_warnings = resolve_with_overrides(
                passport,
                strategy=effective_strategy,
                update_mode="shadow-only",
                shadow_path=shadow_path,
                writers=writers,
            )
        except PassportError as e:
            raise click.ClickException(str(e)) from e
        write_passport(abs_path, resolved_pp)
        for w in pp_warnings:
            messages.append(f"[yellow]Warning:[/yellow] {w}")
        messages.append(f"Passport updated in {path}. Future sessions will use the new values.")
    else:
        # No passport — synthesize
        try:
            new_pp = synthesize_passport(
                strategy=effective_strategy,
                intent=intent,
                update_mode="shadow-only",
                shadow_path=shadow_path,
                writers=writers or "all-sessions",
            )
            write_passport(abs_path, new_pp)
        except PassportError as e:
            raise click.ClickException(str(e)) from e
        messages.append(f"Passport created for {path} (strategy: {effective_strategy}, mode: shadow-only).")

    doc = DesignatedDoc(path=shadow_path, strategy=effective_strategy, shadows=path)
    _upsert_and_finish(
        ctx=ctx,
        session_name=session_name,
        docs=docs,
        doc=doc,
        official_path=path,
        shadow_path=shadow_path,
        messages=messages,
    )


def _upsert_and_finish(
    *,
    ctx: ExecutionContext,
    session_name: str | None,
    docs: list[DesignatedDoc],
    doc: DesignatedDoc,
    official_path: str,
    shadow_path: str | None,
    messages: list[str],
) -> None:
    """Upsert doc into the manifest, persist, auto-enable, and print output."""
    was_update = False
    new_docs: list[DesignatedDoc] = []
    for d in docs:
        is_match = False
        if shadow_path:
            # Shadow upsert: match same shadow, same official, or direct→shadow conversion
            is_match = (
                d.path == shadow_path
                or (d.shadows is not None and d.shadows == official_path)
                or (d.path == official_path and d.shadows is None)
            )
        else:
            is_match = d.path == official_path
        if is_match:
            if not was_update:
                new_docs.append(doc)
                was_update = True
            # else: drop duplicate matches
        else:
            new_docs.append(d)
    if not was_update:
        new_docs.append(doc)

    try:
        _write_docs(ctx=ctx, session_name=session_name, docs=new_docs)
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    from forge.session.effective import compute_effective_intent as _compute

    resolved_session = resolve_session(ctx=ctx, session_name=session_name)
    effective_after = _compute(resolved_session.state)
    auto_enabled = _auto_enable_memory(
        ctx=ctx,
        session_name=session_name,
        effective_memory=effective_after.memory,
    )

    if shadow_path:
        if was_update:
            console.print(f"Updated tracking for [cyan]{official_path}[/cyan] " f"(shadow proposal at {shadow_path}).")
        else:
            console.print(f"Tracking [cyan]{official_path}[/cyan] through shadow proposal " f"at {shadow_path}.")
    else:
        if was_update:
            console.print(f"Updated tracking for [cyan]{official_path}[/cyan] " f"(strategy: {doc.strategy}).")
        else:
            console.print(f"Tracking [cyan]{official_path}[/cyan] directly as {doc.strategy}.")
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
    docs = [d for d in docs if d.path != path and d.shadows != path]
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
                "shadows": doc.shadows,
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

    has_shadows = any(e["shadows"] for e in enriched)

    table = Table(show_header=True, header_style="bold")
    table.add_column("Path", style="cyan")
    if has_shadows:
        table.add_column("Official", style="dim")
    table.add_column("Strategy")
    table.add_column("Mode")
    table.add_column("Writers")
    table.add_column("Passport")
    for entry in enriched:
        row = [str(entry["path"])]
        if has_shadows:
            row.append(str(entry["shadows"] or ""))
        row.extend(
            [
                str(entry["strategy"]),
                str(entry["mode"]),
                str(entry["writers"]),
                "yes" if entry["has_passport"] else "no",
            ]
        )
        table.add_row(*row)
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
            if doc_filter and doc.path != doc_filter and doc.shadows != doc_filter:
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
                    "shadows": doc.shadows,
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

    has_shadows = any(e["shadows"] for e in entries)

    table = Table(show_header=True, header_style="bold")
    table.add_column("Doc Path", style="cyan")
    if has_shadows:
        table.add_column("Official", style="dim")
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
        row = [str(row_data["path"])]
        if has_shadows:
            row.append(str(row_data["shadows"] or ""))
        row.append(str(row_data["session"]))
        if multi_root:
            row.append(str(row_data["forge_root"]))
        row.extend([str(row_data["strategy"]), str(row_data["mode"]), str(row_data["writers"]), passport_col])
        table.add_row(*row)

    console.print(table)
    if multi_root:
        console.print(f"\n[dim]Scanned {len(scanned_roots)} root(s).[/dim]")


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
@click.option("--session", "-s", "session_name", default=None, help="Filter to a session.")
@click.option(
    "--scope",
    type=click.Choice(["project", "repo", "all"]),
    default="project",
    show_default=True,
    help="Scope for discovery.",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON.")
def shadows_list_cmd(session_name: str | None, scope: str, as_json: bool) -> None:
    """List shadow proposals across sessions."""
    try:
        entries, scanned_roots = _collect_shadow_entries(scope, session_name)
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
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
@click.option("--session", "-s", "session_name", default=None, help="Filter to a session.")
@click.option(
    "--scope",
    type=click.Choice(["project", "repo", "all"]),
    default="project",
    show_default=True,
    help="Scope for discovery.",
)
def shadows_show_cmd(for_doc: str, session_name: str | None, scope: str) -> None:
    """Show shadow proposal content for an official doc."""
    try:
        entries, scanned_roots = _collect_shadow_entries(scope, session_name)
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    matches = [entry for entry in entries if entry.official == for_doc]
    if not matches:
        console.print(f"[dim]No shadow proposals found for {for_doc} (scope: {scope}).[/dim]")
        return

    # Deduplicate by (forge_root, shadow_path)
    seen: dict[tuple[str, str], list[str]] = {}
    for entry in matches:
        key = (entry.forge_root, entry.shadow_path)
        seen.setdefault(key, []).append(entry.session)

    multi_root = len(scanned_roots) > 1

    for (fr, shadow_path), sessions in sorted(seen.items()):
        header_parts = [f"[bold]{shadow_path}[/bold]"]
        header_parts.append(f"sessions: {', '.join(sorted(set(sessions)))}")
        if multi_root:
            header_parts.append(f"root: {fr}")
        console.print(" | ".join(header_parts))
        console.print()

        abs_path = Path(fr) / shadow_path
        if not abs_path.is_file():
            console.print("[dim](shadow file does not exist yet)[/dim]")
        else:
            content = abs_path.read_text(encoding="utf-8").strip()
            if content:
                console.print(content)
            else:
                console.print("[dim](empty)[/dim]")
        console.print()


@shadows_group.command("review")
@click.option("--for", "for_doc", required=True, help="Official doc to review.")
@click.option("--curate", is_flag=True, default=False, help="Run LLM curation.")
@click.option("--show-latest", is_flag=True, default=False, help="Show latest curation report.")
@click.option("--session", "-s", "session_name", default=None, help="Session name.")
@click.option(
    "--scope",
    type=click.Choice(["project", "repo", "all"]),
    default="project",
    show_default=True,
    help="Scope for shadow discovery.",
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON.")
def shadows_review_cmd(
    for_doc: str,
    curate: bool,
    show_latest: bool,
    session_name: str | None,
    scope: str,
    as_json: bool,
) -> None:
    """Review shadow proposals for an official doc."""
    if curate and show_latest:
        raise click.ClickException("--curate and --show-latest are mutually exclusive.")

    if show_latest:
        _review_show_latest(for_doc, session_name, scope, as_json)
        return

    if curate:
        _review_curate(for_doc, session_name, scope, as_json)
        return

    # Bare review: show raw content + hint
    ctx = click.get_current_context()
    ctx.invoke(shadows_show_cmd, for_doc=for_doc, session_name=session_name, scope=scope)
    console.print("[dim]Tip: Use --curate to run LLM synthesis, --show-latest to view the last report.[/dim]")


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
            console.print("[dim]Tip: Run with --curate to generate one.[/dim]")
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
) -> None:
    """Handle ``--curate``: run LLM curation."""
    import os

    from forge.session.handoff_agent import resolve_handoff_base_url
    from forge.session.shadow_curation import (
        collect_shadow_entries,
        run_shadow_curation,
    )

    if scope == "all":
        raise click.ClickException("Cross-project curation deferred; use --scope project or --scope repo.")

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
    base_url = resolve_handoff_base_url(
        proxy_id=config.proxy if config else None,
        confirmed_proxy_base_url=confirmed_proxy_url,
        env_base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        direct=direct,
        subprocess_proxy=effective.subprocess_proxy,
    )

    if not as_json:
        console.print(f"[dim]Curating {len(shadow_entries)} shadow source(s) for {for_doc}...[/dim]")

    result = run_shadow_curation(
        session_name=resolved.store.session_name,
        forge_root=forge_root,
        official_path=for_doc,
        official_content=official_content,
        shadow_entries=shadow_entries,
        base_url=base_url,
        direct=direct,
        scope=scope,
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
    """Inspect memory-doc passports."""


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
                        "tip": f"forge memory track {path} --as <strategy>",
                    },
                    indent=2,
                )
            )
            return
        console.print(f"[dim]No passport found in {path}.[/dim]")
        console.print(f"\n[dim]Tip: Add one with: forge memory track {path} --as <strategy>[/dim]")
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
    table.add_row("inherit_on_fork", str(passport.update.inherit_on_fork))
    if passport.update.compact_when:
        table.add_row("compact_when", passport.update.compact_when)
    if passport.update.shadow_path:
        table.add_row("shadow_path", passport.update.shadow_path)
    if passport.update.approval:
        table.add_row("approval", passport.update.approval)
    if passport.update.instruction:
        table.add_row("instruction", passport.update.instruction)

    console.print(table)

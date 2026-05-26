"""``forge memory`` -- top-level memory doc management.

Replaces ``forge session memory`` (Phase 2 of the memory enhancement proposal).
Each command manages doc participation in session manifests and passport
frontmatter. The handoff agent re-reads passports at stop time for the
authoritative contract (Phase 1 design: passport-authoritative).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import click

from forge.cli.output import print_tip
from forge.cli.session import console
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import (
    ForgeOpError,
    ResolveSessionResult,
    resolve_session,
    set_session_override,
)
from forge.session.exceptions import (
    ForgeSessionError,
    PassportError,
    ProjectMemoryConfigError,
)
from forge.session.models import DesignatedDoc
from forge.session.passport import (
    VALID_STRATEGY_NAMES,
    Passport,
    check_writer_access,
    derive_shadow_path,
    read_passport,
    resolve_passport_source,
    resolve_with_overrides,
    synthesize_passport,
    write_passport,
)
from forge.session.project_memory import (
    DEFAULT_SCAN_ROOTS,
    ActivationConfig,
    ProjectAutoUpdateConfig,
    ProjectMemoryConfig,
    check_shadow_path_collision_in_roots,
    is_under_scan_roots,
    memory_activation,
    read_project_memory_config,
    write_project_memory_config,
)
from forge.session.shadow_curation import ShadowEntry
from forge.session.validation import is_safe_designated_doc_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _current_docs(
    *, ctx: ExecutionContext, session_name: str | None
) -> tuple[list[DesignatedDoc], Path, ResolveSessionResult]:
    """Return (effective designated_docs, forge_root, resolved session).

    The resolved session is returned so callers that need the canonical name
    (``resolved.store.session_name``) or activation state can use them without
    re-resolving.
    """
    resolved = resolve_session(ctx=ctx, session_name=session_name)
    state = resolved.state
    from forge.session.effective import compute_effective_intent

    effective = compute_effective_intent(state)
    docs = list(effective.memory.designated_docs) if effective.memory else []
    forge_root_str = state.forge_root or (state.worktree.path if state.worktree else None)
    if forge_root_str is None:
        raise ForgeOpError("Could not resolve forge_root for session.")
    return docs, Path(forge_root_str), resolved


def _write_docs(*, ctx: ExecutionContext, session_name: str | None, docs: list[DesignatedDoc]) -> None:
    """Persist docs as an override on ``memory.designated_docs``."""
    payload = [{"path": d.path, "strategy": d.strategy, "shadows": d.shadows, "origin": d.origin} for d in docs]
    set_session_override(
        ctx=ctx,
        session_name=session_name,
        key="memory.designated_docs",
        value_str=json.dumps(payload),
    )


def _check_legacy_docs(docs: list[DesignatedDoc], forge_root: Path) -> list[str]:
    """Return warning lines if non-extra docs lack passports or have malformed ones.

    Entries added via ``forge memory extra add`` (``origin == "extra"``)
    intentionally have no passport and are skipped. Separates missing from
    malformed for actionable guidance. Uses ``resolve_passport_source(doc)`` so
    shadow entries check the official doc.
    """
    considered = [d for d in docs if d.origin != "extra"]
    if not considered:
        return []
    missing = 0
    malformed = 0
    for doc in considered:
        passport_path = forge_root / resolve_passport_source(doc)
        try:
            if read_passport(passport_path) is None:
                missing += 1
        except FileNotFoundError:
            missing += 1
        except PassportError:
            malformed += 1
    total = len(considered)
    warnings: list[str] = []
    if missing:
        warnings.append(
            f"{missing} of {total} tracked doc(s) have no passport (manifest-fallback behavior). "
            "Attach a project passport: forge memory track <path> --as <strategy>; "
            "or mark session-only: forge memory extra add <path> --as <strategy>."
        )
    if malformed:
        warnings.append(
            f"{malformed} of {total} tracked doc(s) have malformed passports. "
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


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------


@click.group("memory")
def memory() -> None:
    """Manage project memory docs and handoff agent tracking.

    \b
    Examples:
        forge memory enable                                    # project-scoped activation
        forge memory track docs/changelog.md --as changelog    # author a passport (sessionless)
        forge memory extra add docs/scratch.md --as generic --session planner
        forge memory list --session planner
        forge memory status --scope repo
    """


# ---------------------------------------------------------------------------
# enable
# ---------------------------------------------------------------------------


@memory.command("enable")
@click.option("--session", "-s", "session_name", default=None, help="Target session (omit for project-scoped).")
@click.option("--review-only", is_flag=True, default=False, help="Enable in review-only mode (no edits).")
def enable_cmd(session_name: str | None, review_only: bool) -> None:
    """Enable memory auto-update for the handoff agent.

    Without ``--session``, enables project-scoped activation for the whole
    checkout (writes ``.forge/memory.yaml``), applying to every session here.
    With ``--session``, sets a per-session override. Idempotent.
    """
    target_mode = "review-only" if review_only else "augment"
    if session_name is not None:
        _enable_session_scoped(session_name, target_mode)
    else:
        _enable_project_scoped(target_mode)


def _print_ambient_session_tip() -> None:
    if os.environ.get("FORGE_SESSION"):
        console.print(
            "[dim]Tip: Project-scoped enable applies to all sessions in this checkout. "
            "Use --session to target a specific session.[/dim]"
        )


def _enable_project_scoped(mode: str) -> None:
    """Enable handoff for the whole checkout via ``.forge/memory.yaml``.

    Does not consult ``$FORGE_SESSION``: project scope applies to all sessions.
    """
    ctx = ExecutionContext.from_cwd()
    if ctx.forge_root is None:
        console.print("[red]Error:[/red] Not inside a Forge project. Run 'forge extension enable' first.")
        sys.exit(1)
    forge_root = ctx.forge_root

    try:
        existing = read_project_memory_config(forge_root)
    except ProjectMemoryConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    if existing is not None and existing.auto_update.enabled and existing.auto_update.mode == mode:
        console.print(f"[dim]Memory auto-update already enabled for project (mode: {mode}).[/dim]")
        _print_ambient_session_tip()
        return

    if existing is not None:
        # Preserve roots/proxy/min_turns; only flip enable + mode.
        old_mode = existing.auto_update.mode
        was_enabled = existing.auto_update.enabled
        existing.auto_update.enabled = True
        existing.auto_update.mode = mode
        write_project_memory_config(forge_root, existing)
        if was_enabled:
            console.print(f"Memory auto-update mode changed for project: {old_mode} -> {mode}.")
        else:
            console.print(f"Memory auto-update enabled for project (mode: {mode}).")
    else:
        write_project_memory_config(
            forge_root,
            ProjectMemoryConfig(version=1, auto_update=ProjectAutoUpdateConfig(enabled=True, mode=mode)),
        )
        console.print(f"Memory auto-update enabled for project (mode: {mode}).")

    _print_ambient_session_tip()


def _enable_session_scoped(session_name: str, mode: str) -> None:
    """Enable handoff for a single session via a sparse manifest override."""
    try:
        ctx = ExecutionContext.from_cwd()
        resolved = resolve_session(ctx=ctx, session_name=session_name)
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    from forge.session.effective import compute_effective_intent

    state = resolved.state
    effective = compute_effective_intent(state)
    display_name = session_name or state.name

    already = False
    current_mode: str | None = None
    already_enabled = False
    if effective.memory and effective.memory.auto_update and effective.memory.auto_update.enabled:
        already_enabled = True
        current_mode = effective.memory.auto_update.mode
        if effective.memory.auto_update.mode == mode:
            console.print(f"[dim]Memory auto-update already enabled for session {display_name} (mode: {mode}).[/dim]")
            already = True
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
                value_str=json.dumps(mode),
            )
        except ForgeOpError as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
        if already_enabled and current_mode is not None:
            console.print(f"Memory auto-update mode changed for session {display_name}: {current_mode} -> {mode}.")
        else:
            console.print(f"Memory auto-update enabled for session {display_name} (mode: {mode}).")

    docs = list(effective.memory.designated_docs) if effective.memory else []
    if docs:
        console.print(f"\n[dim]Currently tracking {len(docs)} doc(s).[/dim]")
    else:
        console.print(
            f"\n[dim]No docs tracked yet. "
            f"Use: forge memory extra add <path> --as <strategy> --session {display_name}[/dim]"
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
@click.option("--propose", is_flag=True, default=False, help="Author a shadow-only passport (proposal mode).")
@click.option("--shadow", "shadow_override", default=None, help="Explicit shadow file path (use with --propose).")
@click.option("--session", "-s", "session_name", default=None, hidden=True, help="(removed) track is sessionless.")
def track_cmd(
    path: str,
    strategy: str | None,
    intent: str | None,
    writers: str | None,
    propose: bool,
    shadow_override: str | None,
    session_name: str | None,
) -> None:
    """Author a project-memory passport on a doc (project-lifetime, sessionless).

    Writes ``forge_memory`` frontmatter so every session in this checkout treats
    the doc as memory. Runnable from a bare terminal: it does not resolve or
    require a session. Re-running with --as/--writers updates the passport;
    with no flags on an already-passported doc it is a no-op.

    Use --propose to author a shadow-only passport: the handoff agent writes
    suggestions to a shadow file instead of editing the doc directly.

    For one-session-only participation without a passport, use
    ``forge memory extra add``.
    """
    # Tombstone: track no longer takes a session (clean break, coding-standards §5).
    if session_name is not None:
        raise click.ClickException(
            "track authors project passports and does not take a session.\n"
            "For session-only participation, use:\n"
            f"  forge memory extra add {path} --as <strategy> --session {session_name}"
        )

    # Early flag-combination validation
    if shadow_override and not propose:
        raise click.ClickException("--shadow requires --propose.")
    if propose and strategy is not None and strategy != "suggested":
        raise click.ClickException(f"--propose requires strategy 'suggested'. Got '{strategy}'.")

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
    roots, config_corrupt = _resolve_scan_roots(forge_root)

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
            config_corrupt=config_corrupt,
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
            config_corrupt=config_corrupt,
        )
        return

    # --- Direct passport authoring ---
    has_flags = strategy is not None or writers is not None

    if passport is None and strategy is None:
        raise click.ClickException(
            f"This doc has no passport. Provide a strategy:\n"
            f"  forge memory track {path} --as <strategy>\n\n"
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
        _warn_if_out_of_root(path, forge_root, roots, config_corrupt)
        return

    # Existing direct passport.
    if not has_flags:
        console.print(f"Passport already present in [cyan]{path}[/cyan] (strategy: {passport.update.strategy}).")
        _warn_if_out_of_root(path, forge_root, roots, config_corrupt)
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
    _warn_if_out_of_root(path, forge_root, roots, config_corrupt)


def _resolve_scan_roots(forge_root: Path) -> tuple[tuple[str, ...], bool]:
    """Return ``(roots, config_corrupt)`` for out-of-root and collision checks.

    A corrupt/unsupported ``.forge/memory.yaml`` only powers those advisory
    checks, so it must not block passport authoring. On corruption, warn (name
    the file via the error) and degrade to default roots with the corrupt flag
    set so callers skip the checks.
    """
    try:
        cfg = read_project_memory_config(forge_root)
    except ProjectMemoryConfigError as e:
        console.print(f"[yellow]Warning:[/yellow] {e}; out-of-root and shadow-collision checks skipped.")
        return DEFAULT_SCAN_ROOTS, True
    roots = tuple(cfg.roots) if cfg is not None else DEFAULT_SCAN_ROOTS
    return roots, False


def _warn_if_out_of_root(path: str, forge_root: Path, roots: tuple[str, ...], config_corrupt: bool) -> None:
    """Warn when a passported doc lies outside the project scan roots."""
    if config_corrupt or is_under_scan_roots(path, forge_root, roots):
        return
    console.print(
        f"[yellow]Warning:[/yellow] {path} is outside the project memory roots ({', '.join(roots)}). "
        "The passport is written, but project Stop-time memory will not process it unless you add the "
        "path to .forge/memory.yaml roots or include it for a session via 'forge memory extra add'."
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
    config_corrupt: bool,
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
    _warn_if_out_of_root(path, forge_root, roots, config_corrupt)


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
    config_corrupt: bool,
) -> None:
    """Author a shadow-only passport and materialize its shadow file.

    Passport-only and sessionless: never writes ``memory.designated_docs``,
    never auto-enables memory, never resolves a session.
    """
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

    # Shadow-path collision: scan passports under roots (skipped if config corrupt).
    if not config_corrupt:
        collision = check_shadow_path_collision_in_roots(shadow_path, path, forge_root, roots)
        if collision:
            raise click.ClickException(collision)

    # Auto-create shadow file if Forge-owned
    created = _auto_create_shadow(shadow_path, forge_root)
    shadow_abs = (forge_root / shadow_path).resolve()
    if not shadow_abs.is_file():
        raise click.ClickException(f"Shadow file does not exist: {shadow_path}")

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
                console.print(f"[yellow]Warning:[/yellow] {w}")
            console.print(f"Passport updated in [cyan]{path}[/cyan]. Future sessions will use the new values.")
        else:
            console.print(f"Passport already present in [cyan]{path}[/cyan] (shadow-only proposals at {shadow_path}).")
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
            console.print(f"[yellow]Warning:[/yellow] {w}")
        console.print(f"Passport in [cyan]{path}[/cyan] converted to shadow-only proposals at {shadow_path}.")
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
        console.print(
            f"Shadow-only passport written for [cyan]{path}[/cyan] "
            f"(strategy: {effective_strategy}, proposals at {shadow_path})."
        )

    if created:
        console.print(f"Shadow file created: {shadow_path}.")
    _warn_if_out_of_root(path, forge_root, roots, config_corrupt)


# ---------------------------------------------------------------------------
# extra (session-only participation)
# ---------------------------------------------------------------------------


def _upsert_doc(
    docs: list[DesignatedDoc],
    doc: DesignatedDoc,
    *,
    official_path: str,
    shadow_path: str | None,
) -> tuple[list[DesignatedDoc], bool]:
    """Upsert *doc* into *docs* by identity. Returns ``(new_docs, was_update)``.

    Matches an existing entry by shadow path / official doc (shadow mode) or by
    direct path, replacing it in place; otherwise appends.
    """
    was_update = False
    new_docs: list[DesignatedDoc] = []
    for d in docs:
        if shadow_path:
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
        else:
            new_docs.append(d)
    if not was_update:
        new_docs.append(doc)
    return new_docs, was_update


@memory.group("extra")
def extra_group() -> None:
    """Manage session-only memory participation (no passport)."""


@extra_group.command("add")
@click.argument("path")
@click.option(
    "--as",
    "strategy",
    type=click.Choice(sorted(VALID_STRATEGY_NAMES)),
    required=True,
    help="Augmentation strategy (passport-less fallback).",
)
@click.option("--session", "-s", "session_name", default=None, help="Target session (default: active session).")
def extra_add_cmd(path: str, strategy: str, session_name: str | None) -> None:
    """Include a doc for THIS session only (no passport).

    Unlike ``track`` (which writes a project-lifetime passport), ``extra add``
    records session-scoped participation in the manifest. Use it for a doc you
    want the handoff agent to update for one session without committing a
    passport. Session-scoped: resolves the active session when --session is
    omitted and echoes the resolved name.
    """
    try:
        ctx = ExecutionContext.from_cwd()
        docs, forge_root, resolved = _current_docs(ctx=ctx, session_name=session_name)
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    resolved_name = resolved.store.session_name

    resolved_base = forge_root.resolve()
    reason = is_safe_designated_doc_path(path, forge_root, resolved_base)
    if reason:
        raise click.ClickException(f"Invalid path: {reason}")
    abs_path = (forge_root / path).resolve()
    if not abs_path.is_file():
        raise click.ClickException(f"File does not exist: {path}")

    try:
        passport = read_passport(abs_path)
    except PassportError as e:
        raise click.ClickException(f"Malformed passport in {path}: {e}") from e

    # 'suggested' needs a shadow file, which 'extra add' cannot create. Reject
    # only when there is no passport (a shadow-only passport already declares one).
    if strategy == "suggested" and passport is None:
        raise click.ClickException(
            "strategy 'suggested' requires a shadow file, which 'extra add' cannot create.\n"
            f"Use: forge memory track {path} --propose"
        )

    doc = DesignatedDoc(path=path, strategy=strategy, origin="extra")
    new_docs, was_update = _upsert_doc(docs, doc, official_path=path, shadow_path=None)
    try:
        _write_docs(ctx=ctx, session_name=session_name, docs=new_docs)
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    verb = "Updated" if was_update else "Added"
    console.print(f"{verb} session extra [cyan]{path}[/cyan] ({strategy}) for session {resolved_name}.")

    # Resolve activation once and thread it through the advisory messaging so the
    # passport/enable hints stay consistent (no double config reads, and no
    # contradictory "already discovered" + "not enabled" pair).
    try:
        activation = memory_activation(resolved.state, forge_root)
    except ProjectMemoryConfigError:
        activation = None
    _advise_extra(path, passport, forge_root, resolved_name, strategy, activation)


def _advise_extra(
    path: str,
    passport: Passport | None,
    forge_root: Path,
    session_name: str,
    strategy: str,
    activation: ActivationConfig | None,
) -> None:
    """Advisory messages after recording a session extra (single source of hints).

    Keyed on the resolved activation:
    - veto: passport excludes this session -> filtered at Stop (enabling won't help).
    - redundant (memory on): passport authorizes + under root -> already discovered.
    - pending (memory off): passport authorizes + under root -> discovered once enabled.
    - tip: otherwise, when memory is off, nothing will process the extra yet.
    """
    activation_on = activation is not None

    # Writer veto: the passport (re-read at Stop, handoff_agent.py:404), not the
    # extra, governs writers. Enabling memory cannot un-veto, so no enable tip.
    if passport is not None and not check_writer_access(passport.update.writers, session_name):
        console.print(
            f"[yellow]Warning:[/yellow] {path} has a passport restricting writers to "
            f"'{passport.update.writers}'; this extra is filtered at Stop for session "
            f"{session_name}. Edit the passport's writers instead."
        )
        return

    if strategy == "suggested" and passport is not None:
        console.print(
            "[dim]Note: --as is a passport-less fallback only; the passport's strategy is "
            "authoritative at Stop.[/dim]"
        )

    under_root = False
    if passport is not None:
        roots = activation.roots if activation is not None else _roots_or_default(forge_root)
        under_root = roots is not None and is_under_scan_roots(path, forge_root, roots)

    if passport is not None and under_root:
        if activation_on:
            console.print(
                f"[yellow]Warning:[/yellow] {path} is already project-discovered for session "
                f"{session_name}; no extra needed."
            )
        else:
            console.print(
                f"[yellow]Warning:[/yellow] {path} has a passport under the scan roots; it will be "
                "project-discovered once memory is enabled (forge memory enable). Extra recorded anyway."
            )
        return

    # Genuine session-only state (no passport, or passported-but-out-of-root):
    # if memory is off, nothing will process the extra yet.
    if not activation_on:
        console.print(
            "[dim]Tip: memory auto-update is not enabled here. Run 'forge memory enable' "
            "(project) or 'forge memory enable --session <name>'.[/dim]"
        )


def _roots_or_default(forge_root: Path) -> tuple[str, ...] | None:
    """Effective doc roots from project config, or the default; ``None`` if corrupt."""
    try:
        cfg = read_project_memory_config(forge_root)
    except ProjectMemoryConfigError:
        return None
    return tuple(cfg.roots) if cfg is not None else DEFAULT_SCAN_ROOTS


# ---------------------------------------------------------------------------
# untrack
# ---------------------------------------------------------------------------


@memory.command("untrack")
@click.argument("path")
@click.option("--session", "-s", "session_name", default=None, help="Target session (default: active session).")
def untrack_cmd(path: str, session_name: str | None) -> None:
    """Stop tracking a memory doc for this session. Passport frontmatter is left intact.

    Slice 2: untrack is session-scoped -- it removes manifest participation
    (extras and legacy entries) only. A doc that still has a passport under the
    project scan roots stays project-discovered; removing the passport itself is
    deferred to Slice 3.
    """
    try:
        ctx = ExecutionContext.from_cwd()
        docs, forge_root, _ = _current_docs(ctx=ctx, session_name=session_name)
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    # Capture removed docs before filtering so shadow entries untracked by
    # shadow path resolve back to their official doc for the passport check.
    removed = [d for d in docs if d.path == path or d.shadows == path]
    if not removed:
        console.print(f"[dim]Not tracked: {path}[/dim]")
        return
    remaining = [d for d in docs if d.path != path and d.shadows != path]

    try:
        _write_docs(ctx=ctx, session_name=session_name, docs=remaining)
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    console.print(f"Untracked [cyan]{path}[/cyan].")
    _warn_untrack_passport_remains(removed, forge_root)


def _warn_untrack_passport_remains(removed: list[DesignatedDoc], forge_root: Path) -> None:
    """Warn for each removed doc that still has a passport under the scan roots."""
    try:
        cfg = read_project_memory_config(forge_root)
    except ProjectMemoryConfigError as e:
        logger.debug("Skipping untrack passport-warning; corrupt memory.yaml: %s", e)
        return
    roots = tuple(cfg.roots) if cfg is not None else DEFAULT_SCAN_ROOTS

    warned: set[str] = set()
    for doc in removed:
        official = resolve_passport_source(doc)
        if official in warned or not is_under_scan_roots(official, forge_root, roots):
            continue
        try:
            pp = read_passport(forge_root / official)
        except (FileNotFoundError, PassportError):
            pp = None
        if pp is not None:
            warned.add(official)
            console.print(
                f"[yellow]Warning:[/yellow] {official} still has a passport and remains "
                "project-discovered; removing the passport is deferred to Slice 3 "
                "(hand-edit the frontmatter to fully untrack)."
            )


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
        docs, forge_root, _ = _current_docs(ctx=ctx, session_name=session_name)
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
                "origin": doc.origin,
            }
        )

    if as_json:
        click.echo(json.dumps(enriched, indent=2))
        return

    if not enriched:
        console.print("[dim]No tracked memory docs for this session.[/dim]")
        print_tip("Run 'forge memory track <path> --as <strategy>'.", blank_before=False, console=console)
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
    table.add_column("Origin")
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
                "extra" if entry["origin"] == "extra" else "—",
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
                    "origin": doc.origin,
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
        print_tip(f"Run 'forge memory track {path} --as <strategy>' to add one.", console=console)
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

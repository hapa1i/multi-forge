"""Session management CLI commands.

Commands for managing Claude Code sessions:
- start: Create and start a new session
- resume: Resume a session (reattach or --fresh for context transfer)
- fork: Fork an existing session
- delete: Delete a session
- list: List all sessions
- show: Show the current or named session
- switch: Switch to a different session
- shell: Open a shell in a sidecar session
- set/reset: Manage session overrides
- incognito: Start an incognito session

Lifecycle commands (start, resume, fork, incognito) live in session_lifecycle.py.
Management commands (delete, list, clean, show, etc.) live in session_manage.py.
Both are re-exported here so ``patch("forge.cli.session.XXX")`` keeps working.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import click

from forge.cli.output import console, err_console
from forge.cli.output import handle_session_error as handle_session_error
from forge.cli.output import print_error, print_error_with_tip, print_tip
from forge.cli.session_routing import ResolvedRouting
from forge.core.paths import display_path
from forge.core.state import parse_iso
from forge.session import (
    LAUNCH_MODE_HOST,
    LAUNCH_MODE_SIDECAR,
    ActiveSessionEntry,
    ForgeSessionError,
    SessionIndexEntry,
    SessionManager,
    SessionState,
)
from forge.session.exceptions import (
    AmbiguousSessionError,
    SessionNotFoundError,
)

logger = logging.getLogger(__name__)


# --- Routing resolution ---


def _resolve_routing_from_cli(
    *,
    proxy_name: str | None,
    direct: bool,
) -> ResolvedRouting:
    """Resolve --proxy/--no-proxy CLI flags to a ResolvedRouting.

    Performs registry lookup + healthcheck for --proxy. Returns
    a direct routing for --no-proxy. Callers must validate mutual
    exclusivity before calling.

    Prints an error (plus a recovery tip where one applies) and exits 1 on
    resolution/healthcheck failure.
    """
    if direct or not proxy_name:
        return ResolvedRouting()

    from forge.cli.claude import _healthcheck_proxy
    from forge.proxy.proxies import (
        ProxyNotFoundError,
        ProxyResolutionError,
    )
    from forge.proxy.proxy_orchestrator import ProxyStartError, ensure_proxy
    from forge.session.context_limit import _get_context_limit_for_proxy

    try:
        entry, started = ensure_proxy(proxy_name)
    except (ProxyResolutionError, ProxyStartError) as e:
        if isinstance(e, ProxyNotFoundError):
            print_error_with_tip(
                str(e),
                "Run 'forge proxy template list' to see available templates.",
                console=err_console,
            )
        else:
            print_error(str(e), console=err_console)
        sys.exit(1)

    if started:
        console.print(f"[dim]Started proxy '{entry.proxy_id}' from template '{proxy_name}'.[/dim]")

    try:
        _healthcheck_proxy(
            base_url=entry.base_url,
            expected_template=entry.template,
            expected_proxy_id=entry.proxy_id,
        )
    except ValueError as e:
        if "not running" in str(e):
            print_error_with_tip(
                str(e),
                f"Run 'forge proxy start {entry.proxy_id}' to start it.",
                console=err_console,
            )
        else:
            print_error(str(e), console=err_console)
        sys.exit(1)

    return ResolvedRouting(
        template=entry.template,
        base_url=entry.base_url,
        proxy_id=entry.proxy_id,
        context_limit=_get_context_limit_for_proxy(entry.proxy_id),
    )


def _apply_routing_override_to_state(
    *,
    state: SessionState,
    routing: ResolvedRouting | None,
    direct: bool,
) -> None:
    """Apply a CLI routing override to an in-memory session state."""
    if not routing and not direct:
        return

    from forge.session.models import LaunchIntent, ProxyIntent

    # Explicit CLI routing beats any stale last-launch proxy snapshot.
    state.confirmed.started_with_proxy = None

    if direct:
        state.intent.proxy = None
        if state.intent.launch is None:
            state.intent.launch = LaunchIntent(mode=LAUNCH_MODE_HOST)
        else:
            state.intent.launch.mode = LAUNCH_MODE_HOST
            state.intent.launch.sidecar = None
        return

    assert routing is not None
    state.intent.proxy = ProxyIntent(
        template=routing.template or "",
        base_url=routing.base_url or "",
    )


def _persist_routing_override(
    *,
    forge_root: Path,
    session_name: str,
    routing: ResolvedRouting | None,
    direct: bool,
) -> None:
    """Persist a --proxy/--no-proxy CLI override into the session manifest.

    Called after manager.fork_session()/resume_session() creates the child
    so the intent reflects the override, not the inherited parent routing.
    This ensures --no-launch forks retain the requested proxy.

    Only persists intent changes -- confirmed.started_with_proxy is hook-owned
    and must not be cleared on disk before a successful launch. The in-memory
    clearing in _apply_routing_override_to_state() is sufficient for the
    current launch; the SessionStart hook will update confirmed on success.
    """
    if not routing and not direct:
        return

    from forge.session import SessionStore
    from forge.session.models import LaunchIntent, ProxyIntent

    store = SessionStore(str(forge_root), session_name)

    def _mutate(m: SessionState) -> None:
        if direct:
            m.intent.proxy = None
            if m.intent.launch is None:
                m.intent.launch = LaunchIntent(mode=LAUNCH_MODE_HOST)
            else:
                m.intent.launch.mode = LAUNCH_MODE_HOST
                m.intent.launch.sidecar = None
        elif routing is not None:
            m.intent.proxy = ProxyIntent(
                template=routing.template or "",
                base_url=routing.base_url or "",
            )

    try:
        store.update(timeout_s=5.0, mutate=_mutate)
    except Exception:
        logger.debug("Failed to persist routing override to manifest", exc_info=True)


def _session_scope_key(name: str, entry: SessionIndexEntry) -> tuple[str, str]:
    """Return the list/cleanup identity tuple for a session entry."""
    return (name, entry.forge_root or entry.worktree_path)


def _session_list_location(entry: SessionIndexEntry) -> str:
    """Return a short location label for human session-list disambiguation."""
    if entry.relative_path and entry.relative_path != ".":
        return entry.relative_path

    root = entry.forge_root or entry.worktree_path
    return Path(root).name if root else "."


def _format_relative_time(iso_timestamp: str) -> str:
    """Format an ISO timestamp as a human-readable relative time."""
    try:
        dt = parse_iso(iso_timestamp)
        now = datetime.now(UTC)
        delta = now - dt

        seconds = delta.total_seconds()
        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes} min{'s' if minutes != 1 else ''} ago"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif seconds < 604800:
            days = int(seconds / 86400)
            return f"{days} day{'s' if days != 1 else ''} ago"
        else:
            weeks = int(seconds / 604800)
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    except (ValueError, TypeError):
        return "unknown"


def _get_session_type(
    is_fork: bool,
    is_incognito: bool,
    parent_session: str | None,
) -> str:
    """Get a human-readable session type string."""
    if is_incognito:
        if is_fork and parent_session:
            return f"fork of {parent_session} (incognito)"
        return "incognito"
    if is_fork and parent_session:
        return f"fork of {parent_session}"
    return "session"


def _get_effective_proxy_for_session(
    state: SessionState,
) -> tuple[str | None, str | None, str | None]:
    """Resolve the best-known template/base_url/proxy_id for a session.

    Returns (template, base_url, proxy_id). The proxy_id (when available)
    enables deterministic context limit computation via exact registry
    lookup, avoiding active-only template resolution.
    """
    if state.confirmed.started_with_proxy:
        return (
            state.confirmed.started_with_proxy.template,
            state.confirmed.started_with_proxy.base_url,
            state.confirmed.started_with_proxy.proxy_id,
        )

    if state.intent.proxy:
        return state.intent.proxy.template, state.intent.proxy.base_url, None

    return None, None, None


def _template_display_label(template: str | None) -> str:
    """Return a user-facing routing label for list/detail views."""
    return template or "direct"


def _print_routing_summary(*, template: str | None, base_url: str | None) -> None:
    """Print routing details for a session launch summary."""
    if base_url is None:
        console.print("  Routing: direct")
        console.print("  Base URL: default Anthropic")
        return

    if template is None:
        console.print("  Routing: custom base URL")
        console.print(f"  Base URL: {base_url}")
        return

    console.print(f"  Template: {template}")
    console.print(f"  Base URL: {base_url}")


def _detect_parent_extensions(parent_project_root: Path) -> tuple[str, str] | None:
    """Detect parent's installed extensions for worktree inheritance.

    Returns (profile, mode) or None if no extensions found.
    Checks: LOCAL install at parent root -> USER install -> hook file detection fallback.
    """
    from forge.install.hooks import has_forge_hooks
    from forge.install.tracking import TrackingStore

    # Tiers 1-2: tracking store lookup (may fail if store is corrupt)
    try:
        store = TrackingStore()

        # Tier 1: LOCAL installation at parent project root
        local_install = store.get_installation("local", str(parent_project_root))
        if local_install is not None:
            return (local_install.profile, local_install.mode)

        # Tier 2: USER-scope (global) installation
        user_install = store.get_installation("user")
        if user_install is not None:
            return (user_install.profile, user_install.mode)

    except Exception:
        logger.debug(
            "Tracking store lookup failed, falling through to hook detection",
            exc_info=True,
        )

    # Tier 3: hook file detection fallback (independent of tracking store)
    try:
        if has_forge_hooks(parent_project_root):
            return ("standard", "copy")
    except Exception:
        logger.debug("Hook detection failed", exc_info=True)

    return None


def _auto_install_extensions(
    install_root: Path,
    parent_project_root: Path,
    *,
    force_extensions: bool | None = None,
) -> bool:
    """Auto-install Forge extensions in a new worktree.

    Args:
        install_root: Root inside the target worktree where ``.claude/`` lives.
            For root-level worktrees this is the checkout root; for nested Forge
            projects it is the nested project root within that checkout.
        force_extensions: True=force install, False=skip, None=auto-detect from parent.

    Returns True if extensions were installed.
    Non-blocking: catches all exceptions and warns on failure.
    """
    try:
        if force_extensions is False:
            return False

        if force_extensions is True:
            profile, mode = "standard", "copy"
        else:
            detected = _detect_parent_extensions(parent_project_root)
            if detected is None:
                console.print("[dim]  Extensions: skipped (no parent extensions detected)[/dim]")
                return False
            profile, mode = detected

        from forge.install.installer import Installer
        from forge.install.models import InstallMode, InstallProfile, InstallScope

        installer = Installer(
            scope=InstallScope.LOCAL,
            project_root=install_root,
        )
        plan = installer.init(
            profile=InstallProfile(profile),
            mode=InstallMode(mode),
        )
        if plan.has_conflicts:
            console.print("[dim]  Extensions: skipped (conflicts with existing files)[/dim]")
            return False
        n_modules = len(plan.modules)
        console.print(f"[dim]  Extensions: inherited ({profile} profile, {n_modules} modules)[/dim]")
        return True

    except Exception as e:
        logger.debug("Extension auto-install failed", exc_info=True)
        console.print(f"[dim]  Extensions: failed to install ({e})[/dim]")
        return False


def _get_active_session_entry(session_name: str, forge_root: str | None = None) -> ActiveSessionEntry | None:
    """Return live runtime state for a session, if available."""
    try:
        from forge.session.active import ActiveSessionStore

        return ActiveSessionStore().get_session(session_name, forge_root=forge_root)
    except Exception:
        logger.debug(
            "Failed to read active-session registry for '%s'",
            session_name,
            exc_info=True,
        )
        return None


def _print_active_delete_warning(session_name: str, active_entry: ActiveSessionEntry) -> None:
    """Print a warning before deleting a session that still appears live."""
    console.print(
        "[yellow]Warning:[/yellow] "
        f"Session [bold]{session_name}[/bold] appears to still be active in a running Claude Code launch."
    )
    console.print("  Deleting it will remove Forge state while the Claude session keeps running until it exits.")
    console.print(f"  Launch mode: {active_entry.launch_mode}")
    if active_entry.launcher_pid is not None:
        console.print(f"  Launcher PID: {active_entry.launcher_pid}")
    if active_entry.container_name:
        console.print(f"  Container: {active_entry.container_name}")
    console.print()


def _get_launch_preferences(
    state: SessionState,
) -> tuple[bool, tuple[str, ...], str | None]:
    """Return relaunch mode plus persisted sidecar options for a session."""
    launch = state.intent.launch
    if launch is None:
        return state.confirmed.is_sandboxed, (), None

    use_sidecar = launch.mode == LAUNCH_MODE_SIDECAR
    if not use_sidecar or launch.sidecar is None:
        return use_sidecar, (), None

    return use_sidecar, tuple(launch.sidecar.mounts), launch.sidecar.image


def _resolve_session_artifact_root(*, manager: SessionManager, state: SessionState) -> Path:
    """Return the root used for forge-root-relative artifacts for a session."""
    if state.forge_root:
        return Path(state.forge_root)

    worktree_path = Path(state.worktree.path) if state.worktree else Path.cwd()
    return Path(manager.resolve_project_root(worktree_path))


def _generate_parent_transfer_context(
    *,
    manager: SessionManager,
    manifest: SessionState,
    parent_state: SessionState | None = None,
    strategy: str = "structured",
    inline_plan: bool = False,
) -> tuple[Path | None, list[str]]:
    """Generate a fresh parent transfer-context file for a forked session.

    Writes ``<fork_forge_root>/.forge/prev_sessions/<parent>/generated.md`` (the
    regeneratable cache) and copies it into ``children/<fork_name>.md`` (the
    per-child authoritative file used at launch). Returns the child file path.
    """
    if not manifest.is_fork or not manifest.parent_session:
        return None, []

    from forge.session.prev_sessions import child_path as _child_path

    fork_worktree = Path(manifest.worktree.path) if manifest.worktree else Path.cwd()
    fork_artifact_root = Path(manifest.forge_root) if manifest.forge_root else fork_worktree
    # Fallback path used when parent_state cannot be loaded: reuse an existing
    # per-child file from a prior launch if available.
    existing_child = _child_path(fork_artifact_root, manifest.parent_session, manifest.name)

    if parent_state is None:
        parent_entry = None
        current_project_root = None
        if manifest.worktree:
            try:
                current_project_root = manager.resolve_project_root(Path(manifest.worktree.path))
            except Exception:
                current_project_root = None

        try:
            if current_project_root is not None:
                try:
                    siblings = [
                        entry
                        for name, entry in manager.list_sessions(
                            project_root_filter=current_project_root,
                            include_incognito=True,
                        )
                        if name == manifest.parent_session
                    ]
                except Exception:
                    siblings = []
                if len(siblings) == 1:
                    parent_entry = siblings[0]

            if parent_entry is None:
                parent_entry = manager.get_session_entry(manifest.parent_session)

            parent_scope = parent_entry.forge_root or parent_entry.worktree_path
            parent_state = manager.get_session(manifest.parent_session, forge_root=parent_scope)
        except ForgeSessionError:
            if existing_child.is_file():
                return existing_child.resolve(), []
            return None, []
        except Exception:
            if existing_child.is_file():
                return existing_child.resolve(), []
            return None, []

    parent_worktree = Path(parent_state.worktree.path) if parent_state.worktree else Path.cwd()

    project_root = _resolve_session_artifact_root(manager=manager, state=parent_state)

    from forge.session.transfer import ResumeStrategy, assemble_transfer_context

    try:
        resume_strategy = ResumeStrategy(strategy)
    except ValueError:
        resume_strategy = ResumeStrategy.STRUCTURED

    _parent_fr = parent_state.forge_root

    def _get_session_safe(session_name: str) -> SessionState | None:
        try:
            return manager.get_session(session_name, forge_root=_parent_fr)
        except ForgeSessionError:
            return None

    transfer_result = assemble_transfer_context(
        parent_name=manifest.parent_session,
        parent_state=parent_state,
        forge_root=project_root,
        parent_worktree_root=parent_worktree,
        output_root=(fork_artifact_root if fork_artifact_root.resolve() != project_root.resolve() else None),
        strategy=resume_strategy,
        depth=1,
        get_session=_get_session_safe,
        inline_plan=inline_plan,
        child_name=manifest.name,
    )
    if transfer_result.context_file is None:
        return None, transfer_result.warnings
    return transfer_result.context_file.resolve(), transfer_result.warnings


def _hint_cross_project_session(name: str, forge_root: str | None) -> bool:
    """Print a hint if a session exists in another forge_root.

    Handles both unique and ambiguous (duplicate-name) cases.
    Returns True if a cross-project hint was printed, False otherwise.
    """
    from rich.text import Text

    from forge.session import IndexStore

    if not forge_root:
        return False
    try:
        entry = IndexStore().get_session(name, forge_root=None)
        other_root = entry.forge_root or entry.worktree_path
        if other_root and other_root != forge_root:
            print_error(f"session '{name}' not found in current project")
            print_tip(f"Session '{name}' exists in:", console=console)
            console.print(
                Text(display_path(other_root), style="dim", no_wrap=True),
                soft_wrap=True,
            )
            console.print("[dim]Run the command from that directory instead.[/dim]")
            return True
    except AmbiguousSessionError as e:
        print_error(f"session '{name}' not found in current project")
        print_tip(f"Session '{name}' exists in multiple projects:", console=console)
        for root in e.forge_roots:
            console.print(
                Text(f"  - {display_path(root)}", style="dim", no_wrap=True),
                soft_wrap=True,
            )
        console.print("[dim]Run the command from the target project directory.[/dim]")
        return True
    except (SessionNotFoundError, OSError):
        # SessionNotFoundError: not in any project. OSError: index file unreadable.
        pass
    return False


# --- Click group ---


@click.group()
def session() -> None:
    """Manage Claude Code sessions.

    \b
    Examples:
        forge session start my-feature         # Create a new session
        forge session resume my-feature        # Resume existing session
        forge session list                     # List all sessions
    """
    pass


# Import command modules for their Click registration side effects.
from . import session_fork as session_fork  # noqa: E402,F401
from . import session_lifecycle as session_lifecycle  # noqa: E402,F401
from . import session_manage as session_manage  # noqa: E402,F401

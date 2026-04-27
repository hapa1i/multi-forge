"""Session management CLI commands.

Commands for managing Claude Code sessions:
- start: Create and start a new session
- resume: Resume a session (reattach or --fresh for context handoff)
- fork: Fork an existing session
- delete: Delete a session
- list: List all sessions
- show: Show the current or named session
- switch: Switch to a different session
- shell: Open a shell in a sidecar session
- set/reset: Manage session overrides
- incognito: Start an incognito session
"""

from __future__ import annotations

import dataclasses
import logging
import os
import shlex
import sys
import uuid as _uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from forge.core.naming import generate_unique_name
from forge.core.ops.session_context import SessionContext
from forge.core.paths import display_path
from forge.core.state import now_iso, parse_iso
from forge.session import (
    LAUNCH_MODE_HOST,
    LAUNCH_MODE_SIDECAR,
    SIDECAR_RUNTIME_BASE_URL,
    ActiveSessionEntry,
    ForgeSessionError,
    IndexStore,
    SessionExistsError,
    SessionIndexEntry,
    SessionManager,
    SessionState,
    SessionStore,
    run_with_active_session,
)
from forge.session.claude import build_claude_args, invoke_claude
from forge.session.exceptions import (
    AmbiguousSessionError,
    BranchExistsError,
    BranchInUseError,
    BranchNotMergedError,
    CannotForkIncognitoError,
    DirtyWorktreeError,
    InvalidBranchNameError,
    SessionNotFoundError,
    WorktreePathExistsError,
)
from forge.session.plan_resolution import (
    PlanInfo,
    latest_snapshot_path,
    preferred_plan_path,
    resolve_displayed_plan_path,
    resolve_path_against,
    resolve_plan_info,
    resolve_plan_launch_root,
)

logger = logging.getLogger(__name__)

# Shared console for Rich output
console = Console()


# --- Routing resolution ---


@dataclass(frozen=True)
class ResolvedRouting:
    """Resolved proxy routing for a session launch.

    Produced by _resolve_routing_from_cli() and threaded through
    launch_new_session, resume, fork, etc.
    """

    template: str | None = None
    base_url: str | None = None
    proxy_id: str | None = None
    context_limit: int | None = None

    @property
    def is_direct(self) -> bool:
        return self.base_url is None


def _resolve_routing_from_cli(
    *,
    proxy_name: str | None,
    direct: bool,
) -> ResolvedRouting:
    """Resolve --proxy/--no-proxy CLI flags to a ResolvedRouting.

    Performs registry lookup + healthcheck for --proxy. Returns
    a direct routing for --no-proxy. Callers must validate mutual
    exclusivity before calling.

    Raises click.ClickException on resolution/healthcheck failure.
    """
    if direct or not proxy_name:
        return ResolvedRouting()

    from forge.cli.claude import _get_context_limit_for_proxy, _healthcheck_proxy
    from forge.proxy.proxies import (
        ProxyRegistryCorruptedError,
        ProxyRegistryStore,
        ProxyResolutionError,
        resolve_proxy,
    )

    store = ProxyRegistryStore()
    try:
        registry = store.read()
    except ProxyRegistryCorruptedError as e:
        raise click.ClickException(str(e))

    try:
        entry = resolve_proxy(registry, proxy_name)
    except ProxyResolutionError as e:
        raise click.ClickException(str(e))

    try:
        _healthcheck_proxy(
            base_url=entry.base_url,
            expected_template=entry.template,
            expected_proxy_id=entry.proxy_id,
        )
    except ValueError as e:
        raise click.ClickException(str(e))

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

    Only persists intent changes — confirmed.started_with_proxy is hook-owned
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


def _cwd_forge_root() -> str | None:
    """Resolve forge_root from CWD for project-scoped session lookups."""
    try:
        from forge.core.ops.context import find_forge_root

        fr = find_forge_root(Path.cwd().resolve())
        return str(fr) if fr else None
    except Exception:
        return None


def _session_scope_key(name: str, entry: SessionIndexEntry) -> tuple[str, str]:
    """Return the list/cleanup identity tuple for a session entry."""
    return (name, entry.forge_root or entry.worktree_path)


def _session_list_location(entry: SessionIndexEntry) -> str:
    """Return a short location label for human session-list disambiguation."""
    if entry.relative_path and entry.relative_path != ".":
        return entry.relative_path

    root = entry.forge_root or entry.worktree_path
    return Path(root).name if root else "."


def _default_context_limit() -> int:
    from forge.runtime_config import get_runtime_config

    return get_runtime_config().context_limit


def _resolve_context_limit(proxy_ref: str | None) -> int:
    """Compute context limit by resolving a proxy for the given proxy_id or template name.

    Uses resolve_proxy_optional() which tries exact proxy_id match first,
    then unique active template match. Falls back to _default_context_limit()
    if no match, ambiguous, or config is malformed.

    Args:
        proxy_ref: Proxy ID or template name (e.g., "litellm-gemini").

    Returns:
        Context window size in tokens, or _default_context_limit() if no match found.
    """
    if not proxy_ref:
        return _default_context_limit()

    try:
        from forge.config.loader import load_proxy_instance_config
        from forge.core.models import get_context_window_tokens
        from forge.proxy.proxies import ProxyRegistryStore, resolve_proxy_optional

        store = ProxyRegistryStore()
        registry = store.read()

        entry = resolve_proxy_optional(registry, proxy_ref)
        if entry is None:
            logger.debug(f"No matching proxy found for '{proxy_ref}', using default")
            return _default_context_limit()

        proxy_config = load_proxy_instance_config(entry.proxy_id)
        if proxy_config is None:
            logger.debug(f"No proxy config found for {entry.proxy_id}, using default")
            return _default_context_limit()

        tier = proxy_config.default_tier or "sonnet"
        model = proxy_config.tiers.get(tier)
        if not model:
            logger.debug(f"No model for tier {tier} in proxy {entry.proxy_id}, using default")
            return _default_context_limit()

        context_limit = get_context_window_tokens(model)
        logger.debug(f"Computed context limit {context_limit} for '{proxy_ref}' via proxy {entry.proxy_id}")
        return context_limit
    except Exception as e:
        logger.debug(f"Failed to compute context limit for '{proxy_ref}': {e}")
        return _default_context_limit()


def _prepare_sidecar_prompt_file(
    *,
    worktree_path: Path,
    system_prompt_file: str | None,
) -> tuple[str | None, list[tuple[str, str, str]]]:
    """Map a host-side prompt file to a path visible inside the sidecar."""
    if system_prompt_file is None:
        return None, []

    prompt_path = Path(system_prompt_file).resolve()
    worktree_root = worktree_path.resolve()

    try:
        relative_prompt = prompt_path.relative_to(worktree_root)
    except ValueError:
        container_prompt = f"/tmp/{prompt_path.name}"
        return container_prompt, [(str(prompt_path), container_prompt, "ro")]

    return str(Path("/workspace") / relative_prompt), []


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


def _build_session_env(
    *,
    session_name: str,
    context_limit: int,
    template: str | None,
    base_url: str | None,
    fork_name: str | None = None,
    parent_session: str | None = None,
    forge_root: str | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Build Claude env vars plus explicit unsets for a session launch."""
    env_vars: dict[str, str] = {
        "FORGE_SESSION": session_name,
    }
    if forge_root:
        env_vars["FORGE_FORGE_ROOT"] = forge_root
    unset_env_vars: list[str] = []

    if base_url is None:
        # Direct mode: don't touch CLAUDE_CODE_AUTO_COMPACT_WINDOW — it's a
        # native CC env var the user may have set. Only scrub Forge-managed vars.
        unset_env_vars.append("ANTHROPIC_BASE_URL")
        unset_env_vars.append("ACTIVE_TEMPLATE")
    else:
        # Proxy mode: set compaction window to match the routed model's context.
        env_vars["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(context_limit)
        env_vars["ANTHROPIC_BASE_URL"] = base_url
        if template is None:
            unset_env_vars.append("ACTIVE_TEMPLATE")
        else:
            env_vars["ACTIVE_TEMPLATE"] = template

    if fork_name is not None:
        env_vars["FORGE_FORK_NAME"] = fork_name
    if parent_session is not None:
        env_vars["FORGE_PARENT_SESSION"] = parent_session

    return env_vars, unset_env_vars


def _has_confirmed_claude_session(state: SessionState) -> bool:
    """Whether this session has durable evidence of a resumable Claude conversation."""
    if not state.confirmed.claude_session_id:
        return False
    if state.confirmed.confirmed_by is not None:
        return True
    return _has_resumable_transcript(state)


def _is_resumable_session(state: SessionState) -> bool:
    """Whether this session has a resumable Claude conversation.

    Reconnect should allow the same fallback evidence as normal relaunch:
    either a hook-confirmed session or a transcript-backed session when the
    hook missed confirmation (for example, lock contention). Pre-seeded UUIDs
    without other evidence are still rejected.
    """
    return bool(state.confirmed.claude_session_id and _has_resumable_claude_session(state))


def _has_resumable_transcript(state: SessionState) -> bool:
    """Whether we can infer an existing Claude conversation from transcript state."""
    session_id = state.confirmed.claude_session_id
    if not session_id or state.confirmed.is_sandboxed:
        return False

    transcript_path = state.confirmed.transcript_path
    if transcript_path and Path(transcript_path).is_file():
        return True

    try:
        from forge.session.claude.paths import (
            get_transcript_path,
            resolve_claude_project_root,
        )

        # Check persisted launch root first, then computed root
        if state.confirmed.claude_project_root:
            if get_transcript_path(state.confirmed.claude_project_root, session_id).is_file():
                return True
        return get_transcript_path(resolve_claude_project_root(state), session_id).is_file()
    except Exception:
        return False


def _has_resumable_claude_session(state: SessionState) -> bool:
    """Whether Claude can be resumed for this session."""
    return _has_confirmed_claude_session(state) or _has_resumable_transcript(state)


def _get_deferred_same_dir_fork_resume_id(
    *,
    manager: SessionManager,
    manifest: SessionState,
) -> str | None:
    """Return the parent UUID when launching a never-started same-dir fork."""
    if not manifest.is_fork or not manifest.parent_session:
        return None

    if manifest.worktree and manifest.worktree.is_worktree:
        return None

    confirmed = manifest.confirmed
    if (
        confirmed.claude_session_id is not None
        or confirmed.transcript_path is not None
        or confirmed.confirmed_by is not None
    ):
        return None

    try:
        parent_state = manager.get_session(manifest.parent_session, forge_root=manifest.forge_root)
    except ForgeSessionError:
        return None

    return parent_state.confirmed.claude_session_id


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


def _resolve_extension_detection_root(cwd: Path) -> Path:
    """Return the Forge project root to use for extension inheritance lookup."""
    from forge.core.ops.context import find_forge_root
    from forge.session.claude.paths import find_project_root

    forge_root = find_forge_root(cwd)
    if forge_root is not None:
        return forge_root
    try:
        return find_project_root(str(cwd))
    except FileNotFoundError:
        return cwd.resolve()


def _resolve_worktree_extension_root(manifest: SessionState) -> Path | None:
    """Return where extensions should be installed inside a target worktree.

    Session state may stay anchored at the parent's forge_root for root-level
    worktree sessions, but extensions must still land inside the new checkout.
    Nested Forge projects instead install at the equivalent nested forge_root
    within the worktree.
    """
    if not manifest.worktree or not manifest.worktree.is_worktree:
        return None

    worktree_root = Path(manifest.worktree.path)
    if manifest.forge_root:
        forge_root = Path(manifest.forge_root)
        try:
            forge_root.relative_to(worktree_root)
            return forge_root
        except ValueError:
            pass
    return worktree_root


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


def _warn_if_hooks_missing(project_path: Path) -> None:
    """Warn if no Forge hooks are installed before launching Claude.

    Args:
        project_path: Forge project root (where .claude/ lives). Use forge_root,
            not worktree/checkout root, so nested projects find the correct settings.
    """
    from forge.install.hooks import has_forge_hooks

    if has_forge_hooks(project_path):
        return

    console.print(
        "[yellow]Warning:[/yellow] Forge hooks are not installed. "
        "State tracking, policy enforcement, verification, and search indexing "
        "will not be active."
    )
    console.print("[dim]Tip: Run 'forge extension enable' to install hooks.[/dim]")


def _warn_if_version_outdated() -> None:
    """Warn if Claude Code version is below the minimum required by Forge."""
    from forge.install.version import check_minimum_version

    result = check_minimum_version()
    if result.ok or result.version is None:
        return  # Don't warn if we can't detect (hooks warning covers that)

    console.print(
        f"[yellow]Warning:[/yellow] Claude Code {result.version} is below "
        f"minimum {result.minimum}. Some features may not work correctly."
    )
    console.print("[dim]Tip: Run 'claude update' to upgrade.[/dim]")


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


def _resolve_launch_mode(*, sidecar: bool, host_proxy: bool) -> str:
    """Resolve host vs sidecar launch mode from CLI flags and runtime config."""
    if sidecar:
        return LAUNCH_MODE_SIDECAR
    if host_proxy:
        return LAUNCH_MODE_HOST

    from forge.runtime_config import get_runtime_config

    return LAUNCH_MODE_SIDECAR if get_runtime_config().proxy_mode == LAUNCH_MODE_SIDECAR else LAUNCH_MODE_HOST


def _get_runtime_base_url(*, use_sidecar: bool, effective_url: str | None) -> str | None:
    """Return the base URL Claude should see for this launch."""
    return SIDECAR_RUNTIME_BASE_URL if use_sidecar else effective_url


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


def _infer_launch_confirmation(
    *,
    store: "SessionStore",
    manifest: SessionState,
    session_id: str | None,
) -> None:
    """Backfill transcript/runtime confirmation after a successful host launch."""
    if session_id is None or manifest.confirmed.is_sandboxed:
        return

    try:
        from forge.session.claude.paths import (
            get_transcript_path,
            resolve_claude_project_root,
        )
    except ImportError:
        return

    # Prefer persisted launch root; fall back to computed root
    if manifest.confirmed.claude_project_root:
        transcript_path = get_transcript_path(manifest.confirmed.claude_project_root, session_id)
    else:
        transcript_path = get_transcript_path(resolve_claude_project_root(manifest), session_id)
    if not transcript_path.is_file():
        return

    def _mutate(state: SessionState) -> None:
        # 1:1 model: overwrite UUID directly (no accumulation)
        state.confirmed.claude_session_id = session_id
        state.confirmed.transcript_path = str(transcript_path)
        state.confirmed.confirmed_at = now_iso()
        if state.confirmed.confirmed_by is None:
            state.confirmed.confirmed_by = "cli:launch:inferred"

    store.update(timeout_s=5.0, mutate=_mutate)


def _resolve_manifest_prompt_file(manifest: SessionState) -> Path | None:
    """Resolve a session's configured system prompt file, if any."""
    if manifest.intent.system_prompt is None or manifest.intent.system_prompt.file is None:
        return None
    prompt_path = Path(manifest.intent.system_prompt.file).expanduser()
    return prompt_path.resolve() if prompt_path.exists() else None


def _combine_prompt_files(*, worktree_path: Path, session_name: str, prompt_files: list[Path]) -> str | None:
    """Combine multiple prompt/context files into one appendable prompt file."""
    existing = [path.resolve() for path in prompt_files if path.is_file()]
    if not existing:
        return None
    if len(existing) == 1:
        return str(existing[0])

    launch_context_dir = worktree_path / ".forge" / "launch-context"
    launch_context_dir.mkdir(parents=True, exist_ok=True)
    combined_path = launch_context_dir / f"{session_name}.md"

    sections: list[str] = []
    for path in existing:
        try:
            content = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
        if not content:
            continue
        sections.append(f"<!-- Source: {path.name} -->\n{content}")

    combined_path.write_text("\n\n".join(sections).rstrip() + "\n", encoding="utf-8")
    return str(combined_path.resolve())


def _resolve_session_artifact_root(*, manager: SessionManager, state: SessionState) -> Path:
    """Return the root used for forge-root-relative artifacts for a session."""
    if state.forge_root:
        return Path(state.forge_root)

    worktree_path = Path(state.worktree.path) if state.worktree else Path.cwd()
    return Path(manager.resolve_project_root(worktree_path))


def _generate_parent_handoff_context(
    *,
    manager: SessionManager,
    manifest: SessionState,
    parent_state: SessionState | None = None,
    strategy: str = "structured",
    inline_plan: bool = False,
) -> tuple[Path | None, list[str]]:
    """Generate a fresh parent-context handoff file for a forked session."""
    if not manifest.is_fork or not manifest.parent_session:
        return None, []

    fork_worktree = Path(manifest.worktree.path) if manifest.worktree else Path.cwd()
    context_path = fork_worktree / ".forge" / "prev_sessions" / f"{manifest.parent_session}.md"

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
            if context_path.is_file():
                return context_path.resolve(), []
            return None, []
        except Exception:
            if context_path.is_file():
                return context_path.resolve(), []
            return None, []

    parent_worktree = Path(parent_state.worktree.path) if parent_state.worktree else Path.cwd()

    project_root = _resolve_session_artifact_root(manager=manager, state=parent_state)

    from forge.session.handoff import ResumeStrategy, process_handoff

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

    handoff_result = process_handoff(
        parent_name=manifest.parent_session,
        parent_state=parent_state,
        forge_root=project_root,
        parent_worktree_root=parent_worktree,
        output_root=fork_worktree if fork_worktree != parent_worktree else None,
        strategy=resume_strategy,
        depth=1,
        get_session=_get_session_safe,
        inline_plan=inline_plan,
    )
    if handoff_result.context_file is None:
        return None, handoff_result.warnings
    return handoff_result.context_file.resolve(), handoff_result.warnings


def _persist_fork_handoff_derivation(
    *,
    manifest: SessionState,
    strategy: str,
    context_path: Path | None,
) -> SessionState:
    """Persist handoff-specific derivation details for a worktree fork."""
    worktree_path = Path(manifest.worktree.path) if manifest.worktree else Path.cwd()
    forge_root = Path(manifest.forge_root) if manifest.forge_root else worktree_path

    context_file: str | None = None
    if context_path is not None:
        try:
            context_file = str(context_path.relative_to(worktree_path))
        except ValueError:
            context_file = str(context_path)

    def _mutate(m: SessionState) -> None:
        if m.confirmed.derivation is None:
            from forge.session.models import Derivation

            m.confirmed.derivation = Derivation(parent_session=m.parent_session or "")
        m.confirmed.derivation.resume_mode = "handoff"
        m.confirmed.derivation.strategy = strategy
        m.confirmed.derivation.context_file = context_file

    return SessionStore(str(forge_root), manifest.name).update(timeout_s=5.0, mutate=_mutate)


def _launch_claude_for_session(
    *,
    manifest: SessionState,
    session_id: str | None,
    resume_id: str | None,
    effective_template: str | None,
    runtime_base_url: str | None,
    context_limit: int,
    use_sidecar: bool,
    mounts: tuple[str, ...] = (),
    image: str | None = None,
    fork_session: bool = False,
    register_fork: bool = False,
    system_prompt_file: str | None = None,
    name: str | None = None,
    extra_args: list[str] | None = None,
    proxy_id: str | None = None,
) -> int:
    """Launch Claude for a session, handling sidecar/host split."""
    worktree_path = Path(manifest.worktree.path) if manifest.worktree else Path.cwd()
    # State lives under forge_root (may differ from worktree_path in nested projects)
    forge_root = Path(manifest.forge_root) if manifest.forge_root else worktree_path
    # Claude Code project root: where Claude finds .claude/ and stores conversations.
    # For nested projects this is forge_root; for root-level worktrees it's worktree_path.
    from forge.session.claude.paths import resolve_claude_project_root

    launch_root = Path(resolve_claude_project_root(manifest))

    # Prefer persisted launch root (set by SessionStart hook) over computed
    # root. This handles sessions created before the nested-project CWD fix
    # (7a1bbe9) where the conversation lives under the old checkout-root
    # namespace. The persisted value is authoritative; the computed root is
    # the fallback for sessions that predate the field.
    if manifest.confirmed.claude_project_root:
        launch_root = Path(manifest.confirmed.claude_project_root)

    register_fork_env = fork_session or register_fork
    fork_name = manifest.name if register_fork_env else None
    parent_session = manifest.parent_session if register_fork_env else None

    env_vars, unset_env_vars = _build_session_env(
        session_name=manifest.name,
        context_limit=context_limit,
        template=effective_template,
        base_url=runtime_base_url,
        fork_name=fork_name,
        parent_session=parent_session,
        forge_root=manifest.forge_root,
    )

    _warn_if_hooks_missing(forge_root)
    _warn_if_version_outdated()

    from forge.session import SessionStore

    store = SessionStore(str(forge_root), manifest.name)

    # Persist launch root on first launch so reconnect can use the exact CWD
    if not manifest.confirmed.claude_project_root:
        _lr = str(launch_root)
        store.update(
            timeout_s=5.0,
            mutate=lambda m: setattr(m.confirmed, "claude_project_root", _lr),
        )

    if use_sidecar:
        if effective_template is None or runtime_base_url is None:
            console.print("[red]Error:[/red] Direct sessions are not supported with --sidecar")
            sys.exit(1)

        # Recover proxy_id from base_url when not explicitly provided (relaunch paths)
        if proxy_id is None and runtime_base_url is not None:
            try:
                from forge.proxy.proxies import ProxyRegistryStore as _PStore

                _entry = _PStore().find_by_base_url(runtime_base_url)
                if _entry is not None:
                    proxy_id = _entry.proxy_id
            except Exception:
                pass  # Best-effort; falls back to template scan

        from forge.sidecar import get_secrets_for_template, run_sidecar_session
        from forge.sidecar.container import ContainerExistsError, parse_mounts
        from forge.sidecar.docker import is_docker_available

        if not is_docker_available():
            console.print("[red]Error:[/red] Docker is not available or not running")
            sys.exit(1)

        store.update(timeout_s=5.0, mutate=lambda m: setattr(m.confirmed, "is_sandboxed", True))

        try:
            extra_mounts = parse_mounts(mounts) if mounts else []
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)

        claude_dir = launch_root / ".claude"
        forge_dir = launch_root / ".forge"
        sidecar_home = forge_dir / "sidecar-home"
        claude_dir.mkdir(parents=True, exist_ok=True)
        forge_dir.mkdir(parents=True, exist_ok=True)
        sidecar_home.mkdir(parents=True, exist_ok=True)
        sidecar_prompt_file, prompt_mounts = _prepare_sidecar_prompt_file(
            worktree_path=launch_root,
            system_prompt_file=system_prompt_file,
        )
        standard_mounts = [
            (str(claude_dir), "/workspace/.claude", "rw"),
            (str(forge_dir), "/workspace/.forge", "rw"),
            (str(sidecar_home), "/root/.claude", "rw"),
        ]
        all_mounts = standard_mounts + prompt_mounts + extra_mounts
        claude_args = build_claude_args(
            session_id=session_id,
            resume_id=resume_id,
            fork_session=fork_session,
            name=name,
            model=None,
            system_prompt_file=sidecar_prompt_file,
            extra_args=extra_args,
        )

        secrets = get_secrets_for_template(effective_template)
        container_env = {**env_vars, **secrets}

        if "LITELLM_BASE_URL" not in container_env:
            try:
                from forge.config.loader import load_proxy_instance_config
                from forge.proxy.proxies import ProxyRegistryStore as _Store
                from forge.proxy.proxies import resolve_proxy_optional

                _resolved_pid = proxy_id
                if not _resolved_pid and effective_template:
                    _registry = _Store().read()
                    _resolved = resolve_proxy_optional(_registry, effective_template)
                    if _resolved:
                        _resolved_pid = _resolved.proxy_id

                if _resolved_pid:
                    _pcfg = load_proxy_instance_config(_resolved_pid)
                    if _pcfg and _pcfg.upstream_base_url:
                        container_env["LITELLM_BASE_URL"] = _pcfg.upstream_base_url
            except Exception:
                pass  # Best-effort; user can export LITELLM_BASE_URL manually

        from forge.runtime_config import get_runtime_config

        sidecar_image = image or get_runtime_config().sidecar_image
        console.print("[cyan]Starting sidecar session in container[/cyan]")
        console.print(f"  Image: {sidecar_image}")
        console.print()

        try:
            return run_with_active_session(
                session_name=manifest.name,
                worktree_path=worktree_path,
                launch_mode=LAUNCH_MODE_SIDECAR,
                forge_root=manifest.forge_root,
                claude_session_id=session_id,
                runner=lambda: run_sidecar_session(
                    image=sidecar_image,
                    template=effective_template,
                    session_name=manifest.name,
                    project_dir=launch_root,
                    extra_mounts=all_mounts,
                    context_limit=context_limit,
                    env_vars=container_env,
                    claude_args=claude_args,
                ),
            )
        except ContainerExistsError as e:
            store.update(
                timeout_s=5.0,
                mutate=lambda m: setattr(m.confirmed, "is_sandboxed", False),
            )
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
        except Exception:
            store.update(
                timeout_s=5.0,
                mutate=lambda m: setattr(m.confirmed, "is_sandboxed", False),
            )
            raise

    store.update(timeout_s=5.0, mutate=lambda m: setattr(m.confirmed, "is_sandboxed", False))

    # Direct sessions: pass configured model override when one is set
    if runtime_base_url is None:
        from forge.runtime_config import get_default_direct_model

        direct_model = get_default_direct_model()
    else:
        direct_model = None

    exit_code = run_with_active_session(
        session_name=manifest.name,
        worktree_path=worktree_path,
        launch_mode=LAUNCH_MODE_HOST,
        forge_root=manifest.forge_root,
        claude_session_id=session_id,
        runner=lambda: invoke_claude(
            session_id=session_id,
            resume_id=resume_id,
            fork_session=fork_session,
            name=name,
            model=direct_model,
            system_prompt_file=system_prompt_file,
            env_vars=env_vars,
            unset_env_vars=unset_env_vars,
            extra_args=extra_args,
            cwd=str(launch_root),
        ),
    )
    if exit_code == 0 and not fork_session:
        _infer_launch_confirmation(store=store, manifest=manifest, session_id=resume_id or session_id)

    _print_post_exit_tip(manifest)

    return exit_code


def _print_post_exit_tip(manifest: SessionState) -> None:
    """Print session tips after Claude exits.

    Printed from the parent launcher process (not a hook) because Claude
    Code suppresses SessionEnd hook output (anthropics/claude-code#9090).
    """
    if manifest.is_incognito or not manifest.name:
        return
    # Claude sometimes leaves the cursor mid-line on exit, so clear the
    # current line before printing the Forge-owned tip.
    try:
        console.file.write("\r\x1b[2K")
        console.file.flush()
    except Exception:
        logger.debug("Terminal line clear failed before post-exit tip", exc_info=True)
    resume_cmd = _resume_tip_command(manifest)
    console.print(f"\n[dim]Tip: Reconnect to this conversation with:[/dim]\n" f"[dim]  {resume_cmd}[/dim]")


def _resume_tip_command(manifest: SessionState) -> str:
    """Return the shell command to resume a session from the correct directory."""
    assert manifest.name  # callers guard on manifest.name first

    resume_cmd = f"forge session resume {shlex.quote(manifest.name)}"
    if not manifest.worktree or not manifest.worktree.is_worktree:
        return resume_cmd

    resume_root = manifest.forge_root
    if not resume_root:
        from forge.session.claude.paths import resolve_claude_project_root

        resume_root = resolve_claude_project_root(manifest)

    return f"cd {shlex.quote(display_path(resume_root))} && {resume_cmd}"


def _handle_error(e: ForgeSessionError) -> None:
    """Handle a ForgeSessionError and exit."""
    console.print(f"[red]Error:[/red] {e}", style="red")
    sys.exit(1)


def _hint_cross_project_session(name: str, forge_root: str | None) -> bool:
    """Print a hint if a session exists in another forge_root.

    Handles both unique and ambiguous (duplicate-name) cases.
    Returns True if a cross-project hint was printed, False otherwise.
    """
    if not forge_root:
        return False
    try:
        entry = IndexStore().get_session(name, forge_root=None)
        other_root = entry.forge_root or entry.worktree_path
        if other_root and other_root != forge_root:
            console.print(f"[red]Error:[/red] session '{name}' not found in current project")
            console.print(f"\n[dim]Tip: Session '{name}' exists in:[/dim]")
            console.print(
                Text(display_path(other_root), style="dim", no_wrap=True),
                soft_wrap=True,
            )
            console.print("[dim]Run the command from that directory instead.[/dim]")
            return True
    except AmbiguousSessionError as e:
        console.print(f"[red]Error:[/red] session '{name}' not found in current project")
        console.print(f"\n[dim]Tip: Session '{name}' exists in multiple projects:[/dim]")
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


def _print_branch_exists_tip(e: BranchExistsError) -> None:
    """Print contextual tip for a branch that already exists."""
    console.print(f"[red]Error:[/red] {e}")
    if e.worktree:
        console.print("\n[dim]Tip: Use --branch to specify a different branch name.[/dim]")
    else:
        console.print(
            f"\n[dim]Tip: Delete with `git branch -d {e.branch}` or use --branch to specify a different name.[/dim]"
        )


# --- Shared session creation + launch ---


def launch_new_session(
    *,
    name: str,
    template: str | None = None,
    base_url: str | None = None,
    direct: bool = False,
    incognito: bool = False,
    system_prompt: str | None = None,
    system_prompt_file: str | None = None,
    worktree: bool = False,
    branch: str | None = None,
    sidecar: bool = False,
    host_proxy: bool = False,
    mounts: tuple[str, ...] = (),
    image: str | None = None,
    no_launch: bool = False,
    extensions: bool | None = None,
    extra_args: list[str] | None = None,
    context_limit_override: int | None = None,
    proxy_display: str | None = None,
    proxy_id: str | None = None,
    supervise_target: str | None = None,
    supervisor_proxy: str | None = None,
    supervisor_direct: bool = False,
) -> int:
    """Create a new session and launch Claude.

    This is the shared implementation behind ``forge session start``,
    ``forge session incognito``, and ``forge claude start``.

    Returns the Claude exit code (0 on success).  Never calls ``sys.exit``
    so callers can wrap with cleanup (incognito) or other post-processing.
    """
    # --- flag validation ---
    if branch and not worktree:
        console.print("[red]Error:[/red] --branch requires --worktree")
        return 1
    if sidecar and host_proxy:
        console.print("[red]Error:[/red] --sidecar and --host-proxy are mutually exclusive")
        return 1
    if direct and (template or base_url):
        console.print("[red]Error:[/red] --no-proxy cannot be combined with --template or --base-url")
        return 1
    if direct and sidecar:
        console.print("[red]Error:[/red] --no-proxy cannot be combined with --sidecar")
        return 1
    if direct and host_proxy:
        console.print("[red]Error:[/red] --no-proxy cannot be combined with --host-proxy")
        return 1
    if incognito and no_launch:
        console.print("[red]Error:[/red] --incognito and --no-launch are mutually exclusive")
        return 1
    if no_launch and (system_prompt or system_prompt_file):
        console.print("[red]Error:[/red] --system-prompt is launch-only and lost with --no-launch")
        return 1

    launch_mode = LAUNCH_MODE_HOST if direct else _resolve_launch_mode(sidecar=sidecar, host_proxy=host_proxy)
    use_sidecar = launch_mode == LAUNCH_MODE_SIDECAR
    manager = SessionManager()

    # Resolve system prompt to absolute path BEFORE worktree creation
    # (worktree changes cwd so relative paths would break).
    prompt_file: str | None = None
    if system_prompt_file:
        prompt_file = str(Path(system_prompt_file).resolve())
    elif system_prompt:
        claude_dir = Path.cwd() / ".claude"
        claude_dir.mkdir(exist_ok=True)
        prompt_file_path = claude_dir / "forge.system-prompt.generated.md"
        prompt_file_path.write_text(system_prompt)
        prompt_file = str(prompt_file_path)

    # Validate supervisor target and proxy BEFORE creating the session to avoid half-created state
    _supervisor_source_state = None
    if supervise_target:
        from forge.guard.semantic.supervisor import validate_supervisor_target

        try:
            _supervisor_source_state = validate_supervisor_target(supervise_target, forge_root=_cwd_forge_root())
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            return 1
    if supervisor_proxy:
        from forge.guard.semantic.supervisor import preflight_supervisor_proxy

        try:
            supervisor_proxy = preflight_supervisor_proxy(supervisor_proxy)
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            return 1

    pre_seeded_uuid = str(_uuid.uuid4())
    try:
        manifest = manager.start_session(
            name=name,
            proxy_template=template,
            proxy_base_url=base_url,
            direct=direct,
            is_incognito=incognito,
            create_worktree=worktree,
            branch=branch,
            launch_mode=launch_mode,
            sidecar_mounts=list(mounts) if use_sidecar else None,
            sidecar_image=image if use_sidecar else None,
            claude_session_id=pre_seeded_uuid,
        )
    except SessionExistsError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print(f"\n[dim]Tip: Use 'forge session resume {name}' to continue,[/dim]")
        console.print(f"[dim]or 'forge session delete {name}' to remove it first.[/dim]")
        return 1
    except BranchExistsError as e:
        _print_branch_exists_tip(e)
        return 1
    except WorktreePathExistsError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print("\n[dim]Tip: Remove the directory or use a different session name.[/dim]")
        return 1
    except InvalidBranchNameError as e:
        console.print(f"[red]Error:[/red] {e}")
        return 1
    except ForgeSessionError as e:
        console.print(f"[red]Error:[/red] {e}", style="red")
        return 1
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}", style="red")
        return 1

    # --- wire supervisor (if requested) ---
    if supervise_target and _supervisor_source_state is not None:
        from forge.guard.semantic.supervisor import (
            apply_supervisor_routing,
            apply_supervisor_to_intent,
        )
        from forge.session.models import SupervisorConfig
        from forge.session.store import SessionStore

        _sup_forge_root = manifest.forge_root or (manifest.worktree.path if manifest.worktree else str(Path.cwd()))
        sup_config = SupervisorConfig(
            resume_id=supervise_target,
            forge_root=_supervisor_source_state.forge_root or _sup_forge_root,
        )
        apply_supervisor_routing(
            sup_config,
            _supervisor_source_state,
            supervisor_proxy=supervisor_proxy,
            supervisor_direct=supervisor_direct,
            current_proxy_id=proxy_id,
            current_template=template,
            current_direct=direct,
        )

        forge_root = _sup_forge_root
        store = SessionStore(forge_root, manifest.name)
        store.update(timeout_s=5.0, mutate=lambda m: apply_supervisor_to_intent(m, sup_config))
        manifest = store.read()

    # --- compute launch parameters ---
    effective_template = manifest.intent.proxy.template if manifest.intent.proxy else None
    effective_url = manifest.intent.proxy.base_url if manifest.intent.proxy else None

    context_limit = (
        context_limit_override if context_limit_override is not None else _resolve_context_limit(effective_template)
    )
    runtime_base_url = _get_runtime_base_url(use_sidecar=use_sidecar, effective_url=effective_url)

    # --- output ---
    label = "incognito session" if incognito else "session"
    console.print(f"Created {label} [green]{manifest.name}[/green]")
    if proxy_display:
        console.print(f"  Proxy: {proxy_display} ({effective_template}) @ {runtime_base_url}")
    else:
        _print_routing_summary(template=effective_template, base_url=runtime_base_url)
    if manifest.worktree and manifest.worktree.is_worktree:
        console.print(f"  Worktree: {display_path(manifest.worktree.path)}")
        console.print(f"  Branch:   {manifest.worktree.branch}")
    if supervise_target:
        console.print(f"  Supervisor: {supervise_target}")
    if incognito:
        console.print("[yellow]  (will auto-delete on exit)[/yellow]")

    # --- extensions ---
    if manifest.worktree and manifest.worktree.is_worktree:
        extension_root = _resolve_worktree_extension_root(manifest)
        if extension_root is not None:
            _auto_install_extensions(
                install_root=extension_root,
                parent_project_root=_resolve_extension_detection_root(Path.cwd()),
                force_extensions=extensions,
            )
    elif extensions is True:
        console.print("[dim]Tip: --extensions only applies with --worktree.[/dim]")
    console.print()

    # --- no-launch early exit ---
    if no_launch:
        console.print("[dim]Session created (--no-launch: Claude not started)[/dim]")
        return 0

    # --- launch Claude ---
    # Incognito cleanup wraps only the launch phase so that validation/creation
    # failures do NOT trigger deletion of a potentially pre-existing session.
    if incognito:
        exit_code = 0
        try:
            exit_code = _launch_claude_for_session(
                manifest=manifest,
                session_id=pre_seeded_uuid,
                resume_id=None,
                effective_template=effective_template,
                runtime_base_url=runtime_base_url,
                context_limit=context_limit,
                use_sidecar=use_sidecar,
                mounts=mounts,
                image=image,
                system_prompt_file=prompt_file,
                name=manifest.name,
                extra_args=extra_args,
                proxy_id=proxy_id,
            )
        finally:
            console.print(f"\n[dim]Cleaning up incognito session '{manifest.name}'...[/dim]")
            try:
                SessionManager().delete_session(
                    manifest.name,
                    delete_transcripts=True,
                    force=True,
                    forge_root=manifest.forge_root,
                )
                console.print("[green]Cleanup complete.[/green]")
            except ForgeSessionError as e:
                console.print(f"[yellow]Cleanup warning:[/yellow] {e}")
        return exit_code

    return _launch_claude_for_session(
        manifest=manifest,
        session_id=pre_seeded_uuid,
        resume_id=None,
        effective_template=effective_template,
        runtime_base_url=runtime_base_url,
        context_limit=context_limit,
        use_sidecar=use_sidecar,
        mounts=mounts,
        image=image,
        system_prompt_file=prompt_file,
        name=manifest.name,
        extra_args=extra_args,
        proxy_id=proxy_id,
    )


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


@session.command()
@click.argument("name", required=False)
@click.option(
    "--proxy",
    "proxy_name",
    type=str,
    default=None,
    help="Proxy to use (proxy_id or template name)",
)
@click.option("--no-proxy", "direct", is_flag=True, help="Bypass the proxy and talk to Anthropic directly")
@click.option("--direct", "direct_deprecated", is_flag=True, hidden=True, help="Deprecated alias for --no-proxy")
@click.option("--incognito", "-i", is_flag=True, help="Auto-delete session on exit")
@click.option("--system-prompt", "-s", help="Append system prompt text")
@click.option(
    "--system-prompt-file",
    "-S",
    type=click.Path(exists=True),
    help="Append system prompt from file",
)
@click.option("--worktree", "-w", is_flag=True, help="Create git worktree for session isolation")
@click.option("--branch", "-b", help="Override branch name (requires --worktree)")
@click.option("--sidecar", is_flag=True, help="Run with bundled proxy in Docker container")
@click.option("--host-proxy", is_flag=True, help="Use host proxy (overrides config)")
@click.option("--mount", "mounts", multiple=True, help="Extra mounts (host:container[:ro|rw])")
@click.option("--image", default=None, help="Docker image for sidecar mode")
@click.option(
    "--no-launch",
    is_flag=True,
    help="Create session without launching Claude",
)
@click.option(
    "--extensions/--no-extensions",
    default=None,
    help="Auto-install extensions in worktree (default: inherit from parent)",
)
@click.option(
    "--supervise",
    "supervise_target",
    type=str,
    default=None,
    help="Session name to use as plan supervisor (enables policy enforcement)",
)
@click.option("--supervisor-proxy", type=str, default=None, help="Proxy for supervisor routing (requires --supervise)")
@click.option(
    "--no-supervisor-proxy",
    "supervisor_direct",
    is_flag=True,
    default=False,
    help="Force supervisor to use direct Anthropic routing (requires --supervise)",
)
def start(
    name: str | None,
    proxy_name: str | None,
    direct: bool,
    incognito: bool,
    system_prompt: str | None,
    system_prompt_file: str | None,
    worktree: bool,
    branch: str | None,
    sidecar: bool,
    host_proxy: bool,
    mounts: tuple[str, ...],
    image: str | None,
    no_launch: bool,
    extensions: bool | None,
    supervise_target: str | None,
    supervisor_proxy: str | None,
    supervisor_direct: bool,
    direct_deprecated: bool,
) -> None:
    """Create and start a new session.

    With --worktree/-w, creates an isolated git worktree for the session.
    This enables parallel work without manifest conflicts.

    With --sidecar, runs Claude Code and proxy inside a Docker container
    with lifecycle coupling. The project directory is mounted at /workspace.

    For resuming existing sessions, use ``forge session resume``.

    \b
    Examples:
        forge session start                                      # Auto-named, no proxy
        forge session start my-feature                           # Named session, no proxy
        forge session start my-feature --proxy litellm-gemini    # With proxy routing
        forge session start my-feature --worktree                # Isolated worktree
        forge session start my-feature --supervise planner       # With plan supervision
    """
    direct = direct or direct_deprecated
    if direct and proxy_name:
        console.print("[red]Error:[/red] --no-proxy and --proxy are mutually exclusive")
        sys.exit(1)
    if supervisor_proxy and supervisor_direct:
        console.print("[red]Error:[/red] --supervisor-proxy and --no-supervisor-proxy are mutually exclusive")
        sys.exit(1)
    if (supervisor_proxy or supervisor_direct) and not supervise_target:
        console.print("[red]Error:[/red] --supervisor-proxy/--no-supervisor-proxy require --supervise")
        sys.exit(1)

    # Default to direct mode when neither --proxy nor --no-proxy is given,
    # unless --sidecar or --host-proxy is specified (both imply proxy mode).
    if not proxy_name and not direct and not sidecar and not host_proxy:
        direct = True

    routing: ResolvedRouting | None = None
    if proxy_name:
        routing = _resolve_routing_from_cli(proxy_name=proxy_name, direct=False)

    # CWD validation: must be at repo root; --worktree requires main repo
    from forge.cli.guards import require_main_repo_root, require_repo_root

    if worktree:
        require_main_repo_root()
    else:
        require_repo_root()

    if name is None:
        _fr = _cwd_forge_root()
        existing = {n for n, _ in SessionManager().list_sessions(forge_root_filter=_fr)}
        name = generate_unique_name(existing)

    sys.exit(
        launch_new_session(
            name=name,
            template=routing.template if routing else None,
            base_url=routing.base_url if routing else None,
            direct=direct,
            incognito=incognito,
            system_prompt=system_prompt,
            system_prompt_file=system_prompt_file,
            worktree=worktree,
            branch=branch,
            sidecar=sidecar,
            host_proxy=host_proxy,
            mounts=mounts,
            image=image,
            no_launch=no_launch,
            extensions=extensions,
            proxy_id=routing.proxy_id if routing else None,
            proxy_display=routing.proxy_id if routing else None,
            context_limit_override=routing.context_limit if routing else None,
            supervise_target=supervise_target,
            supervisor_proxy=supervisor_proxy,
            supervisor_direct=supervisor_direct,
        )
    )


@session.command()
@click.argument("name", required=False)
@click.option(
    "--proxy",
    "proxy_name",
    type=str,
    default=None,
    help="Proxy to use (proxy_id or template name)",
)
@click.option(
    "--no-proxy", "direct", is_flag=True, default=False, help="Bypass the proxy and talk to Anthropic directly"
)
@click.option("--direct", "direct_deprecated", is_flag=True, hidden=True, help="Deprecated alias for --no-proxy")
@click.option(
    "--fresh",
    is_flag=True,
    default=False,
    help="Start a fresh Claude conversation with context assembled from the session's history",
)
@click.option(
    "--child-name",
    "-n",
    "child_name",
    help="Name for the derived session (only with --fresh, auto-generated if not provided)",
)
@click.option(
    "--strategy",
    "-s",
    type=click.Choice(["minimal", "structured", "full", "ai-curated"]),
    default="structured",
    help="Context assembly strategy (only with --fresh, default: structured)",
)
@click.option(
    "--depth",
    "-d",
    type=int,
    default=1,
    help="Lineage traversal depth (only with --fresh, 1=parent only)",
)
@click.option(
    "--resume-mode",
    "resume_mode",
    type=click.Choice(["native", "handoff"]),
    default=None,
    help="Context transfer: native (full conversation via --fork-session) or handoff (assembled summary). Default: handoff.",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Bypass active-session guard (launches as new child)",
)
def resume(
    name: str | None,
    proxy_name: str | None,
    direct: bool,
    fresh: bool,
    child_name: str | None,
    strategy: str,
    depth: int,
    resume_mode: str | None,
    force: bool,
    direct_deprecated: bool,
) -> None:
    """Resume a session.

    By default, reattaches to the existing Claude conversation (Ctrl+C
    recovery). If the session was never launched, launches it in-place.

    Use --fresh to start a new Claude conversation with context assembled
    from the session's history. This is useful when context approaches
    limits and you want a clean slate with a summary of what happened.

    Use --fresh --resume-mode native to carry full conversation history
    via --fork-session (lossless but lost on /compact).

    \b
    Examples:
      forge session resume my-session                    # Reattach to conversation
      forge session resume my-session --fresh            # Fresh conversation with context
      forge session resume my-session --fresh -s full    # Full transcript in context
      forge session resume my-session --fresh --resume-mode native  # Full conversation history
      forge session resume my-session --proxy my-proxy   # Reattach with different routing
      forge session resume my-session --fresh --no-proxy # Fresh conversation, direct mode
    """
    direct = direct or direct_deprecated
    if direct and proxy_name:
        console.print("[red]Error:[/red] --no-proxy and --proxy are mutually exclusive")
        sys.exit(1)

    if resume_mode and not fresh:
        console.print("[red]Error:[/red] --resume-mode requires --fresh")
        sys.exit(1)

    if not fresh and child_name:
        console.print("[red]Error:[/red] --child-name requires --fresh")
        sys.exit(1)

    routing: ResolvedRouting | None = None
    if proxy_name:
        routing = _resolve_routing_from_cli(proxy_name=proxy_name, direct=False)

    manager = SessionManager()

    if name is None:
        sessions = manager.list_sessions(include_incognito=True)
        if not sessions:
            console.print("[dim]No sessions to resume.[/dim]")
            console.print("\n[dim]Tip: Run 'forge session start <name>'.[/dim]")
            return

        name = _pick_session(sessions, manager, prompt="Select session to resume")
        if name is None:
            console.print("[dim]Cancelled[/dim]")
            sys.exit(0)

    _fr = _cwd_forge_root()
    try:
        manifest = manager.get_session(name, forge_root=_fr)
    except SessionNotFoundError:
        if not _hint_cross_project_session(name, _fr):
            console.print(f"[red]Error:[/red] session '{name}' not found")
        sys.exit(1)
    except ForgeSessionError as e:
        _handle_error(e)
        return

    if fresh:
        effective_resume_mode = resume_mode or "handoff"

        # Warn about handoff-only flags with native mode
        if effective_resume_mode == "native":
            ctx = click.get_current_context()
            if ctx.get_parameter_source("strategy") == click.core.ParameterSource.COMMANDLINE:
                console.print("[dim]Tip: --strategy is ignored with --resume-mode native.[/dim]")
            if ctx.get_parameter_source("depth") == click.core.ParameterSource.COMMANDLINE:
                console.print("[dim]Tip: --depth is ignored with --resume-mode native.[/dim]")

        if effective_resume_mode == "native":
            # Native requires a hook-confirmed session (UUID + confirmed_by/transcript evidence).
            # A pre-seeded UUID alone is not enough — there must be a real conversation to resume.
            if not _is_resumable_session(manifest):
                console.print(
                    "[red]Error:[/red] --resume-mode native requires a parent with a confirmed "
                    "Claude session (hook-confirmed or transcript-backed). "
                    "Use --resume-mode handoff for transcript-artifact-based resume."
                )
                sys.exit(1)
            _resume_fresh_native(
                manager=manager,
                parent=name,
                parent_state=manifest,
                child_name=child_name,
                routing=routing,
                direct=direct,
            )
        else:
            _resume_fresh(
                manager=manager,
                parent=name,
                parent_state=manifest,
                child_name=child_name,
                strategy=strategy,
                depth=depth,
                routing=routing,
                direct=direct,
            )
    elif not _has_confirmed_claude_session(manifest):
        _launch_in_place(
            manager=manager,
            name=name,
            manifest=manifest,
            routing=routing,
            direct=direct,
        )
    elif _is_resumable_session(manifest):
        active_entry = _get_active_session_entry(name, forge_root=manifest.forge_root)
        if active_entry is not None and not force:
            console.print(
                f"[red]Error:[/red] Cannot reconnect: session [bold]{name}[/bold] appears to still be active."
            )
            console.print(f"  Launch mode: {active_entry.launch_mode}")
            if active_entry.launcher_pid is not None:
                console.print(f"  Launcher PID: {active_entry.launcher_pid}")
            if active_entry.container_name:
                console.print(f"  Container: {active_entry.container_name}")
            console.print(
                "[dim]Tip: Reconnect is only available after the previous launch has exited."
                " Return to that launch if it is still running, or stop it cleanly and retry.[/dim]"
            )
            sys.exit(1)
        elif active_entry is not None and force:
            console.print(
                f"[yellow]Warning:[/yellow] Session [bold]{name}[/bold] appears active "
                f"(PID {active_entry.launcher_pid}). Launching as new child (--force)."
            )
            _launch_as_child(
                manager=manager,
                parent_name=name,
                parent=manifest,
                routing=routing,
                direct=direct,
            )
        else:
            _reconnect_in_place(
                manager=manager,
                name=name,
                manifest=manifest,
                routing=routing,
                direct=direct,
            )
    else:
        _launch_as_child(
            manager=manager,
            parent_name=name,
            parent=manifest,
            routing=routing,
            direct=direct,
        )


def _launch_in_place(
    *,
    manager: SessionManager,
    name: str,
    manifest: SessionState,
    routing: ResolvedRouting | None = None,
    direct: bool = False,
) -> None:
    """Launch a never-used session in-place (satisfies 1:1)."""
    manager.switch_session(name, forge_root=manifest.forge_root)

    worktree_path = Path(manifest.worktree.path) if manifest.worktree else Path.cwd()
    _apply_routing_override_to_state(state=manifest, routing=routing, direct=direct)
    _persist_routing_override(
        forge_root=Path(manifest.forge_root) if manifest.forge_root else worktree_path,
        session_name=manifest.name,
        routing=routing,
        direct=direct,
    )

    effective_template, effective_url, effective_proxy_id = _get_effective_proxy_for_session(manifest)
    context_limit = _resolve_context_limit(effective_proxy_id or effective_template)
    use_sidecar, mounts, image = _get_launch_preferences(manifest)
    prompt_files: list[Path] = []

    configured_prompt = _resolve_manifest_prompt_file(manifest)
    if configured_prompt is not None:
        prompt_files.append(configured_prompt)

    # Check for deferred same-dir fork (never-started fork should resume parent)
    fork_session = False
    resume_id: str | None = None
    session_id: str | None = None
    prompt_warnings: list[str] = []
    parent_resume_id = _get_deferred_same_dir_fork_resume_id(manager=manager, manifest=manifest)
    if parent_resume_id is not None:
        resume_id = parent_resume_id
        fork_session = True
        launch_action = "Fork parent Claude conversation"
    else:
        session_id = str(_uuid.uuid4())
        fork_context, prompt_warnings = _generate_parent_handoff_context(manager=manager, manifest=manifest)
        if fork_context is not None:
            prompt_files.append(fork_context)
            launch_action = "Start fresh Claude session with parent context"
        else:
            launch_action = "Start fresh Claude session"

    # Write pre-seeded UUID to manifest + index (after worktree_path is resolved)
    forge_root_path = Path(manifest.forge_root) if manifest.forge_root else worktree_path
    if session_id is not None:
        try:
            from forge.session import SessionStore

            store = SessionStore(str(forge_root_path), manifest.name)
            store.update(
                timeout_s=5.0,
                mutate=lambda m: setattr(m.confirmed, "claude_session_id", session_id),
            )
            manager.index_store.sync_uuid_from_state(manifest.name, store.read())
        except Exception:
            logger.debug("Pre-seed UUID write failed (hook will reconcile)", exc_info=True)
    runtime_base_url = _get_runtime_base_url(use_sidecar=use_sidecar, effective_url=effective_url)
    prompt_file = _combine_prompt_files(
        worktree_path=worktree_path,
        session_name=manifest.name,
        prompt_files=prompt_files,
    )

    console.print(f"Launching session [green]{manifest.name}[/green]")
    _print_routing_summary(template=effective_template, base_url=runtime_base_url)
    console.print(f"  Action:   {launch_action}")
    if manifest.worktree and manifest.worktree.is_worktree:
        console.print(f"  Worktree: {display_path(worktree_path)}")
        console.print(f"  Branch:   {manifest.worktree.branch}")
    if prompt_file:
        _print_context_path(prompt_file, worktree_path)
    for w in prompt_warnings:
        console.print(f"[yellow]Warning:[/yellow] {w}")
    console.print()

    exit_code = _launch_claude_for_session(
        manifest=manifest,
        session_id=session_id,
        resume_id=resume_id,
        effective_template=effective_template,
        runtime_base_url=runtime_base_url,
        context_limit=context_limit,
        use_sidecar=use_sidecar,
        mounts=mounts,
        image=image,
        fork_session=fork_session,
        system_prompt_file=prompt_file,
        name=manifest.name,
    )
    sys.exit(exit_code)


def _reconnect_in_place(
    *,
    manager: SessionManager,
    name: str,
    manifest: SessionState,
    routing: ResolvedRouting | None = None,
    direct: bool = False,
) -> None:
    """Reconnect to the same Claude conversation without creating a child.

    Advanced escape hatch for resuming in-place after the previous launch has
    fully ended. Relaxes the 1:1 invariant (new process invocation on the same
    Forge session) but is gated: a resumable conversation must exist.

    The caller is responsible for the active-session check (see resume()
    dispatch) — this function assumes the session is not active.
    """
    if not _is_resumable_session(manifest):
        console.print("[red]Error:[/red] Cannot reconnect: no resumable Claude conversation was found.")
        console.print(
            f"[dim]Tip: Use 'forge session resume {name}' to reattach, or --fresh to start a new conversation.[/dim]"
        )
        sys.exit(1)

    claude_session_id = manifest.confirmed.claude_session_id
    assert claude_session_id is not None  # _is_resumable_session guarantees this

    manager.switch_session(name, forge_root=manifest.forge_root)

    worktree_path = Path(manifest.worktree.path) if manifest.worktree else Path.cwd()
    _apply_routing_override_to_state(state=manifest, routing=routing, direct=direct)
    _persist_routing_override(
        forge_root=Path(manifest.forge_root) if manifest.forge_root else worktree_path,
        session_name=manifest.name,
        routing=routing,
        direct=direct,
    )

    effective_template, effective_url, effective_proxy_id = _get_effective_proxy_for_session(manifest)
    context_limit = _resolve_context_limit(effective_proxy_id or effective_template)
    use_sidecar, mounts, image = _get_launch_preferences(manifest)
    runtime_base_url = _get_runtime_base_url(use_sidecar=use_sidecar, effective_url=effective_url)

    console.print(f"Reconnecting to session [green]{name}[/green]")
    _print_routing_summary(template=effective_template, base_url=runtime_base_url)
    console.print("  Action:   Reconnect to existing Claude conversation")
    console.print(f"  UUID:     {claude_session_id[:8]}...")
    if manifest.worktree and manifest.worktree.is_worktree:
        console.print(f"  Worktree: {display_path(worktree_path)}")
        console.print(f"  Branch:   {manifest.worktree.branch}")
    console.print()

    exit_code = _launch_claude_for_session(
        manifest=manifest,
        session_id=None,
        resume_id=claude_session_id,
        effective_template=effective_template,
        runtime_base_url=runtime_base_url,
        context_limit=context_limit,
        use_sidecar=use_sidecar,
        mounts=mounts,
        image=image,
        fork_session=False,
        name=manifest.name,
    )
    sys.exit(exit_code)


def _launch_as_child(
    *,
    manager: SessionManager,
    parent_name: str,
    parent: SessionState,
    routing: ResolvedRouting | None = None,
    direct: bool = False,
) -> None:
    """Create a child session and resume the parent's Claude conversation.

    Routes through _launch_claude_for_session() so sidecar sessions relaunch
    through the sidecar path with stored mounts/image settings.
    """
    try:
        parent, child = manager.relaunch_session(parent_name, forge_root=parent.forge_root)
    except ForgeSessionError as e:
        _handle_error(e)
        return

    worktree_path = Path(child.worktree.path) if child.worktree else Path.cwd()
    _apply_routing_override_to_state(state=child, routing=routing, direct=direct)
    _persist_routing_override(
        forge_root=Path(child.forge_root) if child.forge_root else worktree_path,
        session_name=child.name,
        routing=routing,
        direct=direct,
    )

    effective_template, effective_url, effective_proxy_id = _get_effective_proxy_for_session(child)
    context_limit = _resolve_context_limit(effective_proxy_id or effective_template)
    use_sidecar, mounts, image = _get_launch_preferences(child)

    runtime_base_url = _get_runtime_base_url(use_sidecar=use_sidecar, effective_url=effective_url)

    console.print(f"Relaunching [green]{parent_name}[/green] as [green]{child.name}[/green]")
    _print_routing_summary(template=effective_template, base_url=runtime_base_url)
    console.print("  Action:   Resume parent conversation in new session")
    console.print(f"  Parent:   {parent_name}")
    if child.worktree and child.worktree.is_worktree:
        console.print(f"  Worktree: {display_path(worktree_path)}")
        console.print(f"  Branch:   {child.worktree.branch}")
    console.print()

    # Child is a same-dir fork: use --resume --fork-session with parent's UUID
    exit_code = _launch_claude_for_session(
        manifest=child,
        session_id=None,
        resume_id=parent.confirmed.claude_session_id,
        effective_template=effective_template,
        runtime_base_url=runtime_base_url,
        context_limit=context_limit,
        use_sidecar=use_sidecar,
        mounts=mounts,
        image=image,
        fork_session=True,
        name=child.name,
        proxy_id=effective_proxy_id,
    )
    sys.exit(exit_code)


def _print_context_path(prompt_file: str, worktree_path: Path) -> None:
    """Print context file path, relative if possible."""
    prompt_path = Path(prompt_file)
    try:
        console.print(f"  Context:  {prompt_path.relative_to(worktree_path)}")
    except ValueError:
        console.print(f"  Context:  {display_path(prompt_path)}")


def _pick_session(
    sessions: list[tuple[str, SessionIndexEntry]],
    manager: SessionManager,
    prompt: str = "Select a session",
) -> str | None:
    """Interactive session picker using Rich.

    Args:
        sessions: List of (name, entry) tuples.
        manager: SessionManager for looking up manifest details.
        prompt: Prompt text to display.

    Returns:
        Selected session name, or None if cancelled.
    """
    if not sessions:
        return None

    console.print(f"\n[bold]{prompt}:[/bold]\n")

    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("#", justify="right", width=3)
    table.add_column("NAME")
    table.add_column("TEMPLATE")
    table.add_column("LAST USED")

    for i, (session_name, entry) in enumerate(sessions, 1):
        proxy_template = "direct"
        try:
            manifest = manager.get_session(session_name, forge_root=entry.forge_root)
            if manifest.intent.proxy:
                proxy_template = manifest.intent.proxy.template
        except ForgeSessionError:
            pass

        last_used = _format_relative_time(entry.last_accessed_at)

        table.add_row(str(i), session_name, proxy_template, last_used)

    console.print(table)
    console.print()

    try:
        choice = click.prompt("Enter number (or 'q' to cancel)", default="1")
        if choice.lower() in ("q", "quit", "cancel"):
            return None

        choice_int = int(choice)
        if choice_int < 1 or choice_int > len(sessions):
            console.print("[red]Invalid choice[/red]")
            return None

        return sessions[choice_int - 1][0]
    except (ValueError, click.Abort):
        return None


def _resume_fresh(
    *,
    manager: SessionManager,
    parent: str,
    parent_state: SessionState,
    child_name: str | None,
    strategy: str,
    depth: int,
    routing: ResolvedRouting | None,
    direct: bool,
) -> None:
    """Create a fresh child session with context assembled from parent.

    This is the --fresh path of ``forge session resume``. Creates a new
    derived session with a context summary, then launches Claude fresh.
    """
    # Routing for context limit: --proxy/--no-proxy override > parent's effective routing.
    if routing:
        effective_proxy_ref = routing.proxy_id
    elif direct:
        effective_proxy_ref = None
    else:
        effective_template, _, effective_proxy_id = _get_effective_proxy_for_session(parent_state)
        effective_proxy_ref = effective_proxy_id or effective_template

    context_limit = _resolve_context_limit(effective_proxy_ref)

    try:
        child_manifest, handoff_result = manager.resume_session(
            parent,
            child_name=child_name,
            strategy=strategy,
            depth=depth,
            context_limit=context_limit,
            forge_root=parent_state.forge_root,
        )
    except ForgeSessionError as e:
        _handle_error(e)
        return

    child_worktree_path = Path(child_manifest.worktree.path) if child_manifest.worktree else Path.cwd()
    _persist_routing_override(
        forge_root=Path(child_manifest.forge_root) if child_manifest.forge_root else child_worktree_path,
        session_name=child_manifest.name,
        routing=routing,
        direct=direct,
    )
    _apply_routing_override_to_state(state=child_manifest, routing=routing, direct=direct)

    console.print(f"[dim]Context assembled: {handoff_result.context_file_rel}[/dim]")
    if handoff_result.warnings:
        for warning in handoff_result.warnings:
            console.print(f"[yellow]Warning:[/yellow] {warning}")
    console.print()

    console.print(f"Created derived session [green]{child_manifest.name}[/green] from [cyan]{parent}[/cyan]")
    console.print(f"[dim]Strategy: {strategy}, Depth: {depth}[/dim]")
    console.print()

    # Launch Claude as a NEW session (not resuming parent's conversation)
    child_worktree = Path(child_manifest.worktree.path) if child_manifest.worktree else Path.cwd()
    prompt_files: list[Path] = []
    configured_prompt = _resolve_manifest_prompt_file(child_manifest)
    if configured_prompt is not None:
        prompt_files.append(configured_prompt)
    if handoff_result.context_file is not None:
        prompt_files.append(handoff_result.context_file.resolve())
    prompt_file = _combine_prompt_files(
        worktree_path=child_worktree,
        session_name=child_manifest.name,
        prompt_files=prompt_files,
    )

    launch_template, launch_base_url, launch_proxy_id = _get_effective_proxy_for_session(child_manifest)

    use_sidecar, mounts, image = _get_launch_preferences(child_manifest)
    runtime_base_url = _get_runtime_base_url(use_sidecar=use_sidecar, effective_url=launch_base_url)

    pre_seeded_uuid = str(_uuid.uuid4())
    try:
        from forge.session import SessionStore

        _store_root = Path(child_manifest.forge_root) if child_manifest.forge_root else child_worktree_path
        _store = SessionStore(str(_store_root), child_manifest.name)
        _store.update(
            timeout_s=5.0,
            mutate=lambda m: setattr(m.confirmed, "claude_session_id", pre_seeded_uuid),
        )
        manager.index_store.sync_uuid_from_state(child_manifest.name, _store.read())
    except Exception:
        logger.debug("Pre-seed UUID write failed (hook will reconcile)", exc_info=True)

    _print_routing_summary(template=launch_template, base_url=runtime_base_url)
    console.print()

    exit_code = _launch_claude_for_session(
        manifest=child_manifest,
        session_id=pre_seeded_uuid,
        resume_id=None,
        effective_template=launch_template,
        runtime_base_url=runtime_base_url,
        context_limit=context_limit,
        use_sidecar=use_sidecar,
        mounts=mounts,
        image=image,
        fork_session=False,
        system_prompt_file=prompt_file,
        name=child_manifest.name,
        proxy_id=launch_proxy_id,
    )

    sys.exit(exit_code)


def _resume_fresh_native(
    *,
    manager: SessionManager,
    parent: str,
    parent_state: SessionState,
    child_name: str | None,
    routing: ResolvedRouting | None,
    direct: bool,
) -> None:
    """Create a child session with native conversation resume.

    Uses --resume --fork-session to carry full conversation history into a new
    Forge session. No context assembly or system_prompt_file generation.

    Requires the parent to have a confirmed claude_session_id (caller validates).
    """
    # Routing for context limit: --proxy/--no-proxy override > parent's effective routing.
    if routing:
        effective_proxy_ref = routing.proxy_id
    elif direct:
        effective_proxy_ref = None
    else:
        effective_template, _, effective_proxy_id = _get_effective_proxy_for_session(parent_state)
        effective_proxy_ref = effective_proxy_id or effective_template

    context_limit = _resolve_context_limit(effective_proxy_ref)

    try:
        child_manifest, _handoff = manager.resume_session(
            parent,
            child_name=child_name,
            resume_mode="native",
            forge_root=parent_state.forge_root,
        )
    except ForgeSessionError as e:
        _handle_error(e)
        return

    child_worktree_path = Path(child_manifest.worktree.path) if child_manifest.worktree else Path.cwd()
    _persist_routing_override(
        forge_root=Path(child_manifest.forge_root) if child_manifest.forge_root else child_worktree_path,
        session_name=child_manifest.name,
        routing=routing,
        direct=direct,
    )
    _apply_routing_override_to_state(state=child_manifest, routing=routing, direct=direct)

    parent_uuid = parent_state.confirmed.claude_session_id
    assert parent_uuid is not None  # caller validated

    console.print(f"Created derived session [green]{child_manifest.name}[/green] from [cyan]{parent}[/cyan]")
    console.print("[dim]Mode: Native resume (full conversation history via --fork-session)[/dim]")
    console.print()

    launch_template, launch_base_url, launch_proxy_id = _get_effective_proxy_for_session(child_manifest)
    use_sidecar, mounts, image = _get_launch_preferences(child_manifest)
    runtime_base_url = _get_runtime_base_url(use_sidecar=use_sidecar, effective_url=launch_base_url)

    _print_routing_summary(template=launch_template, base_url=runtime_base_url)
    console.print()

    exit_code = _launch_claude_for_session(
        manifest=child_manifest,
        session_id=None,
        resume_id=parent_uuid,
        effective_template=launch_template,
        runtime_base_url=runtime_base_url,
        context_limit=context_limit,
        use_sidecar=use_sidecar,
        mounts=mounts,
        image=image,
        fork_session=True,
        name=child_manifest.name,
        proxy_id=launch_proxy_id,
    )

    sys.exit(exit_code)


@session.command()
@click.argument("parent")
@click.option(
    "--name",
    "-n",
    default=None,
    help="Name for the fork (auto-generated if not provided)",
)
@click.option(
    "--proxy",
    "proxy_name",
    type=str,
    default=None,
    help="Proxy to use (proxy_id or template name)",
)
@click.option("--no-proxy", "direct", is_flag=True, help="Bypass the proxy and talk to Anthropic directly")
@click.option("--direct", "direct_deprecated", is_flag=True, hidden=True, help="Deprecated alias for --no-proxy")
@click.option("--incognito", "-i", is_flag=True, help="Auto-delete fork on exit")
@click.option("--worktree", "-w", is_flag=True, help="Create git worktree for fork isolation")
@click.option("--branch", "-b", help="Override branch name (implies --worktree)")
@click.option("--no-launch", is_flag=True, help="Create fork without launching Claude")
@click.option(
    "--extensions/--no-extensions",
    default=None,
    help="Auto-install extensions in worktree (default: inherit from parent)",
)
@click.option(
    "--strategy",
    type=click.Choice(["minimal", "structured", "full", "ai-curated"]),
    default="structured",
    help="Context assembly strategy for worktree forks (default: structured)",
)
@click.option(
    "--inline-plan",
    is_flag=True,
    default=False,
    help="Inline the approved plan content in handoff context",
)
@click.option(
    "--into",
    "into_path",
    type=click.Path(exists=True),
    default=None,
    help="Fork into an existing non-main worktree directory",
)
@click.option(
    "--supervise",
    "supervise_target",
    is_flag=True,
    default=False,
    help="Set parent as plan supervisor for the fork (enables policy enforcement)",
)
@click.option("--supervisor-proxy", type=str, default=None, help="Proxy for supervisor routing (requires --supervise)")
@click.option(
    "--no-supervisor-proxy",
    "supervisor_direct",
    is_flag=True,
    default=False,
    help="Force supervisor to use direct Anthropic routing (requires --supervise)",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Replace existing branch/worktree and skip budget preflight",
)
def fork(
    parent: str,
    name: str | None,
    proxy_name: str | None,
    direct: bool,
    direct_deprecated: bool,
    incognito: bool,
    worktree: bool,
    branch: str | None,
    no_launch: bool,
    extensions: bool | None,
    strategy: str,
    inline_plan: bool,
    into_path: str | None,
    supervise_target: bool,
    supervisor_proxy: str | None,
    supervisor_direct: bool,
    force: bool,
) -> None:
    """Fork an existing session.

    By default the fork shares the parent's directory so Claude's
    conversation carries over via --fork-session.  Use --worktree for
    code isolation in a separate git worktree, or --into for an existing
    non-main worktree.

    Use --no-proxy to bypass the proxy, or --proxy to route through
    a specific proxy instead of the parent's.

    \b
    Examples:
        forge session fork parent-session                      # Fork, same directory
        forge session fork parent-session --worktree           # Fork with worktree
        forge session fork parent-session -n child-session     # Custom fork name
        forge session fork parent-session --no-proxy           # Fork, bypass proxy
    """
    direct = direct or direct_deprecated
    if direct and proxy_name:
        console.print("[red]Error:[/red] --no-proxy and --proxy are mutually exclusive")
        sys.exit(1)
    if supervisor_proxy and supervisor_direct:
        console.print("[red]Error:[/red] --supervisor-proxy and --no-supervisor-proxy are mutually exclusive")
        sys.exit(1)
    if (supervisor_proxy or supervisor_direct) and not supervise_target:
        console.print("[red]Error:[/red] --supervisor-proxy/--no-supervisor-proxy require --supervise")
        sys.exit(1)

    if branch:
        worktree = True

    # --into validation
    into_resolved: str | None = None
    into_branch: str | None = None
    into_target_common: str | None = None
    if into_path is not None:
        if worktree:
            console.print("[red]Error:[/red] --into and --worktree are mutually exclusive")
            sys.exit(1)
        if branch:
            console.print("[red]Error:[/red] --into and --branch are mutually exclusive")
            sys.exit(1)

        import subprocess as _sp

        try:
            into_resolved = _sp.run(
                ["git", "-C", into_path, "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except _sp.CalledProcessError:
            console.print(f"[red]Error:[/red] '{display_path(into_path)}' is not inside a git repository")
            sys.exit(1)

        # Resolve git-common-dir for the target (absolute, to avoid .git relative path bug)
        try:
            target_common_raw = _sp.run(
                ["git", "-C", into_resolved, "rev-parse", "--git-common-dir"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            # git returns relative paths from the checkout root; resolve against it
            target_common = str((Path(into_resolved) / target_common_raw).resolve())
        except _sp.CalledProcessError:
            console.print("[red]Error:[/red] Failed to resolve git repository for --into target")
            sys.exit(1)

        # Store for deferred comparison after parent session is loaded
        into_target_common = target_common

        # Reject main checkout: the main checkout's --show-toplevel == its own path
        # A real worktree has a different toplevel than the main repo
        try:
            # Use git-common-dir to find the main repo's toplevel
            main_git_dir = _sp.run(
                ["git", "-C", into_resolved, "rev-parse", "--git-common-dir"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            main_git_dir_abs = (Path(into_resolved) / main_git_dir).resolve()
            # Main repo root is the parent of the .git directory
            main_repo_root = main_git_dir_abs.parent if main_git_dir_abs.name == ".git" else main_git_dir_abs
            if Path(into_resolved).resolve() == main_repo_root:
                console.print(
                    "[red]Error:[/red] --into targets existing worktrees, not the main checkout. "
                    "Use a same-directory fork instead."
                )
                sys.exit(1)
        except _sp.CalledProcessError:
            pass  # Can't determine; allow

        try:
            into_branch = _sp.run(
                ["git", "-C", into_resolved, "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except _sp.CalledProcessError:
            into_branch = None

    # CWD validation (skip for --into, which has its own path resolution)
    if into_path is None:
        from forge.cli.guards import require_main_repo_root, require_repo_root

        if worktree:
            require_main_repo_root()
        else:
            require_repo_root()

    ctx = click.get_current_context()
    _strategy_explicit = ctx.get_parameter_source("strategy") == click.core.ParameterSource.COMMANDLINE
    _inline_plan_explicit = ctx.get_parameter_source("inline_plan") == click.core.ParameterSource.COMMANDLINE

    manager = SessionManager()
    _fr = _cwd_forge_root()

    # --into cross-repo preflight: reject before fork_session() to avoid orphaned sessions
    if into_resolved is not None and into_target_common is not None:
        import subprocess as _sp2

        try:
            parent_state_pre = manager.get_session(parent, forge_root=_fr)
            parent_wt_pre = parent_state_pre.worktree.path if parent_state_pre.worktree else None
            if parent_wt_pre:
                parent_common_raw = _sp2.run(
                    ["git", "-C", parent_wt_pre, "rev-parse", "--git-common-dir"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
                parent_common = str((Path(parent_wt_pre) / parent_common_raw).resolve())
                if into_target_common != parent_common:
                    console.print(
                        "[red]Error:[/red] --into target is not part of the same repository as the parent session"
                    )
                    sys.exit(1)
        except _sp2.CalledProcessError:
            pass  # Can't resolve parent repo; allow
        except ForgeSessionError:
            pass  # Parent not found; fork_session() will raise the right error

    # Budget preflight for --strategy full (before fork_session to avoid orphaned sessions/worktrees)
    # Use the child's effective routing: --no-proxy means no proxy, --proxy overrides parent
    is_cross_dir = worktree or into_resolved is not None
    # Resolve --proxy early for preflight (reuses routing resolved later for launch)
    _preflight_routing: ResolvedRouting | None = None
    if proxy_name:
        _preflight_routing = _resolve_routing_from_cli(proxy_name=proxy_name, direct=False)
    if is_cross_dir and strategy == "full" and not direct:
        try:
            from forge.session.artifacts import resolve_artifact_path

            parent_state = manager.get_session(parent, forge_root=_fr)
            # --proxy override > parent's proxy for budget check
            if _preflight_routing:
                preflight_ref = _preflight_routing.proxy_id
            else:
                child_template = parent_state.intent.proxy.template if parent_state.intent.proxy else None
                preflight_ref = child_template
            context_limit_preflight = _resolve_context_limit(preflight_ref)
            if context_limit_preflight is not None:
                from forge.session.handoff import estimate_transcript_tokens

                artifact_root = _resolve_session_artifact_root(manager=manager, state=parent_state)
                transcripts = parent_state.confirmed.artifacts.get("transcripts", [])
                if transcripts and isinstance(transcripts, list):
                    latest = transcripts[-1]
                    if isinstance(latest, dict):
                        copied_path = latest.get("copied_path")
                        if isinstance(copied_path, str):
                            transcript_path = resolve_artifact_path(artifact_root, copied_path)
                            if transcript_path is not None and transcript_path.is_file():
                                token_est = estimate_transcript_tokens(transcript_path)
                                if token_est > context_limit_preflight:
                                    if force:
                                        console.print(
                                            f"[yellow]Warning:[/yellow] Parent transcript ({token_est:,} tokens) "
                                            f"exceeds context limit ({context_limit_preflight:,}). "
                                            "Proceeding anyway (--force)."
                                        )
                                    else:
                                        console.print(
                                            f"[red]Error:[/red] Parent transcript ({token_est:,} tokens) exceeds "
                                            f"context limit ({context_limit_preflight:,})."
                                        )
                                        console.print(
                                            "[dim]Tip: Use --strategy structured or --strategy ai-curated instead.[/dim]"
                                        )
                                        sys.exit(1)
        except ForgeSessionError:
            pass  # Parent not found; fork_session() will raise the right error

    # Preflight supervisor proxy BEFORE fork_session() to avoid half-created state
    if supervisor_proxy:
        from forge.guard.semantic.supervisor import preflight_supervisor_proxy

        try:
            supervisor_proxy = preflight_supervisor_proxy(supervisor_proxy)
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)

    try:
        parent_manifest, fork_manifest = manager.fork_session(
            parent_name=parent,
            fork_name=name,
            direct=direct,
            is_incognito=incognito,
            create_worktree=worktree,
            branch=into_branch if into_resolved else branch,
            into_path=into_resolved,
            forge_root=_fr,
            force=force,
        )
    except CannotForkIncognitoError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print("\n[dim]Tip: Incognito sessions cannot be forked.[/dim]")
        sys.exit(1)
    except BranchExistsError as e:
        _print_branch_exists_tip(e)
        sys.exit(1)
    except BranchInUseError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print("\n[dim]Tip: The branch is checked out in another worktree. Remove that worktree first.[/dim]")
        sys.exit(1)
    except BranchNotMergedError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print("\n[dim]Tip: Merge or delete the branch manually before using --force.[/dim]")
        sys.exit(1)
    except WorktreePathExistsError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print("\n[dim]Tip: Remove the directory or use a different fork name.[/dim]")
        sys.exit(1)
    except InvalidBranchNameError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except SessionNotFoundError:
        if not _hint_cross_project_session(parent, _fr):
            console.print(f"[red]Error:[/red] session '{parent}' not found")
        sys.exit(1)
    except ForgeSessionError as e:
        _handle_error(e)
        return

    # Persist routing override to manifest (ensures --no-launch retains proxy choice)
    fork_worktree_path = Path(fork_manifest.worktree.path) if fork_manifest.worktree else Path.cwd()
    _persist_routing_override(
        forge_root=Path(fork_manifest.forge_root) if fork_manifest.forge_root else fork_worktree_path,
        session_name=fork_manifest.name,
        routing=_preflight_routing,
        direct=direct,
    )
    _apply_routing_override_to_state(state=fork_manifest, routing=_preflight_routing, direct=direct)

    # --- wire supervisor (if --supervise flag set) ---
    if supervise_target:
        from forge.guard.semantic.supervisor import (
            apply_supervisor_routing,
            apply_supervisor_to_intent,
        )
        from forge.session.models import SupervisorConfig
        from forge.session.store import SessionStore

        fork_forge_root = fork_manifest.forge_root or str(fork_worktree_path)
        sup_config = SupervisorConfig(
            resume_id=parent,
            forge_root=parent_manifest.forge_root or fork_forge_root,
        )
        apply_supervisor_routing(
            sup_config,
            parent_manifest,
            supervisor_proxy=supervisor_proxy,
            supervisor_direct=supervisor_direct,
            current_proxy_id=_preflight_routing.proxy_id if _preflight_routing else None,
            current_template=_preflight_routing.template if _preflight_routing else None,
            current_direct=direct,
        )
        fork_store = SessionStore(fork_forge_root, fork_manifest.name)
        fork_store.update(timeout_s=5.0, mutate=lambda m: apply_supervisor_to_intent(m, sup_config))
        fork_manifest = fork_store.read()

    if _preflight_routing:
        effective_template = _preflight_routing.template
        effective_url = _preflight_routing.base_url
        effective_proxy_id = _preflight_routing.proxy_id
    elif proxy_name:
        routing = _resolve_routing_from_cli(proxy_name=proxy_name, direct=False)
        effective_template = routing.template
        effective_url = routing.base_url
        effective_proxy_id = routing.proxy_id
    else:
        effective_template, effective_url, effective_proxy_id = _get_effective_proxy_for_session(fork_manifest)

    # Compute context limit (uses exact proxy_id when available for deterministic result)
    context_limit = _resolve_context_limit(effective_proxy_id or effective_template)

    console.print(f"Forked [cyan]{parent}[/cyan] -> [green]{fork_manifest.name}[/green]")
    _print_routing_summary(template=effective_template, base_url=effective_url)
    if fork_manifest.worktree and fork_manifest.worktree.is_worktree:
        console.print(f"  Worktree: {display_path(fork_manifest.worktree.path)}")
        console.print(f"  Branch:   {fork_manifest.worktree.branch}")
    if supervise_target:
        console.print(f"  Supervisor: {parent}")
    if incognito:
        console.print("[yellow]  (will auto-delete on exit)[/yellow]")
    console.print()

    parent_session_id = parent_manifest.confirmed.claude_session_id
    if not parent_session_id:
        console.print("[red]Error:[/red] Parent session has no UUID")
        console.print("The parent session may not have been started yet.")
        sys.exit(1)

    # Set env vars for fork registration (hook uses FORGE_FORK_NAME for fork detection)
    env_vars, unset_env_vars = _build_session_env(
        session_name=fork_manifest.name,
        context_limit=context_limit,
        template=effective_template,
        base_url=effective_url,
        fork_name=fork_manifest.name,
        parent_session=parent,
        forge_root=fork_manifest.forge_root,
    )
    fork_name = fork_manifest.name  # Capture for cleanup
    is_worktree_fork = bool(fork_manifest.worktree and fork_manifest.worktree.is_worktree)
    if effective_url is None:
        from forge.runtime_config import get_default_direct_model

        fork_direct_model = get_default_direct_model()
    else:
        fork_direct_model = None

    # Warn about --strategy/--inline-plan on same-directory forks (only if user explicitly set them)
    if not is_worktree_fork and (_strategy_explicit or _inline_plan_explicit):
        console.print(
            "[dim]Tip: --strategy/--inline-plan only apply to worktree forks "
            "(ignored for same-directory forks).[/dim]"
        )

    # Worktree forks: Claude Code stores sessions at ~/.claude/projects/<encoded-cwd>/,
    # so --resume --fork-session cannot find the parent's conversation from a different
    # directory. Tested 2026-04-02 with Claude Code 2.1.90: all cross-CWD scenarios fail
    # with "No conversation found." See scripts/experiments/native-resume/.
    # Use handoff (assembled context via --append-system-prompt-file) instead.
    if is_worktree_fork:
        worktree_path = Path(fork_manifest.worktree.path)  # type: ignore[union-attr]
        fork_context, prompt_warnings = _generate_parent_handoff_context(
            manager=manager,
            manifest=fork_manifest,
            parent_state=parent_manifest,
            strategy=strategy,
            inline_plan=inline_plan,
        )
        prompt_files: list[Path] = []
        if fork_context is not None:
            prompt_files.append(fork_context)
        configured_prompt = _resolve_manifest_prompt_file(fork_manifest)
        if configured_prompt is not None:
            prompt_files.append(configured_prompt)
        prompt_file = _combine_prompt_files(
            worktree_path=worktree_path,
            session_name=fork_manifest.name,
            prompt_files=prompt_files,
        )
        if prompt_file:
            prompt_path = Path(prompt_file)
            try:
                console.print(f"  Context:  {prompt_path.relative_to(worktree_path)}")
            except ValueError:
                console.print(f"  Context:  {display_path(prompt_path)}")
        for warning in prompt_warnings:
            console.print(f"[yellow]Warning:[/yellow] {warning}")

        try:
            fork_manifest = _persist_fork_handoff_derivation(
                manifest=fork_manifest,
                strategy=strategy,
                context_path=fork_context,
            )
        except Exception:
            logger.warning("Failed to persist fork derivation handoff details", exc_info=True)

        _fork_uuid = str(_uuid.uuid4())
        try:
            from forge.session import SessionStore as _ForkStore

            _fork_wt = Path(fork_manifest.worktree.path) if fork_manifest.worktree else Path.cwd()
            _fork_store_root = Path(fork_manifest.forge_root) if fork_manifest.forge_root else _fork_wt
            _fork_store = _ForkStore(str(_fork_store_root), fork_manifest.name)
            from forge.session.claude.paths import (
                resolve_claude_project_root as _resolve_fork_root_preseed,
            )

            _fork_cwd_preseed = _resolve_fork_root_preseed(fork_manifest)

            def _preseed_mutate(m: SessionState) -> None:
                m.confirmed.claude_session_id = _fork_uuid
                m.confirmed.claude_project_root = _fork_cwd_preseed

            _fork_store.update(timeout_s=5.0, mutate=_preseed_mutate)
            manager.index_store.sync_uuid_from_state(fork_manifest.name, _fork_store.read())
        except Exception:
            logger.debug("Pre-seed UUID write failed (hook will reconcile)", exc_info=True)

        from forge.session.claude.paths import (
            resolve_claude_project_root as _resolve_fork_root,
        )

        _fork_cwd = _resolve_fork_root(fork_manifest)

        def _invoke_fork() -> int:
            return invoke_claude(
                session_id=_fork_uuid,
                name=fork_manifest.name,
                model=fork_direct_model,
                system_prompt_file=prompt_file,
                env_vars=env_vars,
                unset_env_vars=unset_env_vars,
                cwd=_fork_cwd,
            )

    # Same-directory forks: --resume --fork-session works natively.
    else:
        from forge.session.claude.paths import (
            resolve_claude_project_root as _resolve_fork_root,
        )

        _fork_cwd = _resolve_fork_root(fork_manifest)

        def _invoke_fork() -> int:
            return invoke_claude(
                resume_id=parent_session_id,
                fork_session=True,
                name=fork_manifest.name,
                model=fork_direct_model,
                env_vars=env_vars,
                unset_env_vars=unset_env_vars,
                cwd=_fork_cwd,
            )

    # Auto-install extensions in worktree forks (before no_launch check so --no-launch still prepares the worktree)
    if is_worktree_fork:
        extension_root = _resolve_worktree_extension_root(fork_manifest)
        # For --into, skip if the target already has a local Forge install
        _skip_extensions = False
        if into_resolved is not None and extension_root is not None:
            try:
                from forge.install.tracking import TrackingStore as _TSCheck

                if _TSCheck().get_installation("local", str(extension_root)) is not None:
                    _skip_extensions = True
                    logger.debug("Skipping auto-install: target worktree has existing local install")
            except Exception:
                pass

        if not _skip_extensions and extension_root is not None:
            # Use forge_root (where .claude/ and .forge/ live), not checkout_root.
            # The tracking store keys by forge_root, so get_repo_root() misses when
            # forge_root != checkout_root (e.g., nested .claude/ in a subdirectory).
            _parent_forge_root = Path(
                parent_manifest.forge_root
                or (parent_manifest.worktree.path if parent_manifest.worktree else str(Path.cwd()))
            )
            _auto_install_extensions(
                install_root=extension_root,
                parent_project_root=_parent_forge_root,
                force_extensions=extensions,
            )
    elif extensions is True:
        console.print("[dim]Tip: --extensions only applies with --worktree.[/dim]")

    if no_launch:
        console.print("[dim]Fork created (--no-launch: Claude not started)[/dim]")
        if is_worktree_fork:
            console.print(f"\n[dim]Tip: {_resume_tip_command(fork_manifest)}[/dim]")
        sys.exit(0)

    use_sidecar, mounts, image = _get_launch_preferences(fork_manifest)
    runtime_base_url = _get_runtime_base_url(use_sidecar=use_sidecar, effective_url=effective_url)

    if use_sidecar:
        exit_code = 0
        try:
            exit_code = _launch_claude_for_session(
                manifest=fork_manifest,
                session_id=_fork_uuid if is_worktree_fork else None,
                resume_id=None if is_worktree_fork else parent_session_id,
                effective_template=effective_template,
                runtime_base_url=runtime_base_url,
                context_limit=context_limit,
                use_sidecar=True,
                mounts=mounts,
                image=image,
                fork_session=not is_worktree_fork,
                register_fork=is_worktree_fork,
                system_prompt_file=prompt_file if is_worktree_fork else None,
                name=fork_manifest.name,
                proxy_id=effective_proxy_id,
            )
        finally:
            if incognito:
                console.print(f"\n[dim]Cleaning up incognito fork '{fork_name}'...[/dim]")
                try:
                    manager.delete_session(
                        fork_name,
                        delete_transcripts=True,
                        force=True,
                        forge_root=fork_manifest.forge_root,
                    )
                    console.print("[green]Cleanup complete.[/green]")
                except ForgeSessionError as e:
                    console.print(f"[yellow]Cleanup warning:[/yellow] {e}")
        sys.exit(exit_code)

    fork_worktree = Path(fork_manifest.worktree.path) if fork_manifest.worktree else Path.cwd()
    # Check hooks from forge_root (where .claude/ lives), not checkout root
    _fork_forge_root = Path(fork_manifest.forge_root) if fork_manifest.forge_root else fork_worktree
    _warn_if_hooks_missing(_fork_forge_root)
    _warn_if_version_outdated()
    active_claude_session_id = _fork_uuid if is_worktree_fork else None

    if incognito:
        exit_code = 0
        try:
            exit_code = run_with_active_session(
                session_name=fork_name,
                worktree_path=fork_worktree,
                launch_mode=LAUNCH_MODE_HOST,
                forge_root=fork_manifest.forge_root,
                claude_session_id=active_claude_session_id,
                runner=_invoke_fork,
            )
        finally:
            console.print(f"\n[dim]Cleaning up incognito fork '{fork_name}'...[/dim]")
            try:
                manager.delete_session(
                    fork_name,
                    delete_transcripts=True,
                    force=True,
                    forge_root=fork_manifest.forge_root,
                )
                console.print("[green]Cleanup complete.[/green]")
            except ForgeSessionError as e:
                console.print(f"[yellow]Cleanup warning:[/yellow] {e}")
        sys.exit(exit_code)
    else:
        exit_code = run_with_active_session(
            session_name=fork_name,
            worktree_path=fork_worktree,
            launch_mode=LAUNCH_MODE_HOST,
            forge_root=fork_manifest.forge_root,
            claude_session_id=active_claude_session_id,
            runner=_invoke_fork,
        )
        _print_post_exit_tip(fork_manifest)
        sys.exit(exit_code)


@session.command()
@click.argument("names", nargs=-1)
@click.option("--all", "-a", "delete_all", is_flag=True, help="Delete all sessions")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompts")
@click.option("--force", "-f", is_flag=True, help="Override dirty-worktree and corruption guards")
@click.option("--keep-transcripts", "-k", is_flag=True, help="Keep transcript files")
@click.option("--keep-worktree", "-K", is_flag=True, help="Preserve worktree directory")
@click.option("--delete-branch", "-d", is_flag=True, help="Also delete git branch")
def delete(
    names: tuple[str, ...],
    delete_all: bool,
    yes: bool,
    force: bool,
    keep_transcripts: bool,
    keep_worktree: bool,
    delete_branch: bool,
) -> None:
    """Delete one or more sessions and their data.

    \b
    Examples:
      forge session delete my-session
      forge session delete my-session --yes             # Skip confirmation
      forge session delete my-session --yes --force     # Skip confirmation + override dirty worktree
      forge session delete --all --yes

    By default, removes the worktree directory but keeps the git branch.
    Use --delete-branch to also delete the branch.
    Use --keep-worktree to preserve the worktree directory.
    """
    if delete_all and names:
        console.print("[red]Error:[/red] Cannot combine --all with explicit session names")
        sys.exit(1)

    if not delete_all and not names:
        console.print("[red]Error:[/red] Provide session name(s) or use --all")
        sys.exit(1)

    manager = SessionManager()
    _fr = _cwd_forge_root()

    if delete_all:
        if _fr is None:
            console.print("[red]Error:[/red] --all requires being inside a Forge project (directory with .forge/)")
            console.print("[dim]Tip: Use explicit session names instead, or cd into a Forge project.[/dim]")
            sys.exit(1)
        all_sessions = manager.list_sessions(include_incognito=True, forge_root_filter=_fr)
        if not all_sessions:
            console.print("[dim]No sessions to delete.[/dim]")
            return
        targets = [name for name, _ in all_sessions]

        active_targets = [
            (target, active_entry)
            for target in targets
            if (active_entry := _get_active_session_entry(target, forge_root=_fr)) is not None
        ]
        console.print(f"About to delete [bold]all {len(targets)} session(s)[/bold]:")
        for t in targets:
            console.print(f"  - {t}")
        if active_targets:
            console.print()
            console.print(
                "[yellow]Warning:[/yellow] "
                "The following sessions appear to still be active in running Claude Code launches:"
            )
            for target, active_entry in active_targets:
                details = [active_entry.launch_mode]
                if active_entry.container_name:
                    details.append(active_entry.container_name)
                elif active_entry.launcher_pid is not None:
                    details.append(f"pid {active_entry.launcher_pid}")
                console.print(f"  - {target} ({', '.join(details)})")
            console.print(
                "  Deleting them will remove Forge state while Claude keeps running until those launches exit."
            )
        console.print()
        if not yes:
            if not click.confirm("Are you sure you want to delete all sessions?"):
                console.print("[dim]Cancelled[/dim]")
                sys.exit(0)
    else:
        targets = list(dict.fromkeys(names))

    deleted = 0
    failed = 0

    for name in targets:
        # Resolve across forge_roots within the repo (named deletes only)
        actual_fr = _fr
        if not delete_all:
            try:
                from forge.core.ops.resolution import resolve_session_repo_wide

                resolved = resolve_session_repo_wide(name, _fr, manager=manager)
                actual_fr = resolved.forge_root
                if resolved.is_cross_project:
                    console.print(f"[dim]Deleting session from {display_path(actual_fr)}[/dim]")
            except AmbiguousSessionError as e:
                console.print(f"[red]Error:[/red] {e}")
                failed += 1
                continue
            except SessionNotFoundError:
                pass  # Fall through to _delete_single_session for orphan handling
            except ForgeSessionError:
                # Manifest corrupt but session exists in index — resolve the
                # forge_root from the index so force-delete can clean it up.
                try:
                    entry = IndexStore().get_session(name, forge_root=None)
                    idx_fr = entry.root
                    if idx_fr:
                        actual_fr = idx_fr
                except (SessionNotFoundError, AmbiguousSessionError, ForgeSessionError):
                    pass

        try:
            _delete_single_session(
                manager=manager,
                name=name,
                yes=yes or delete_all,
                force=force,
                keep_transcripts=keep_transcripts,
                keep_worktree=keep_worktree,
                delete_branch=delete_branch,
                forge_root=actual_fr,
            )
            console.print(f"Deleted session [green]{name}[/green]")
            deleted += 1
        except SystemExit as e:
            if len(targets) == 1:
                raise
            if e.code not in (0, None):
                failed += 1
        except DirtyWorktreeError as e:
            if len(targets) == 1:
                console.print(f"[red]Error:[/red] {e}")
                console.print("\n[dim]Tip: Use --force to remove anyway, or commit/stash your changes first.[/dim]")
                raise SystemExit(1)
            console.print(f"[red]Error:[/red] {name}: {e}")
            failed += 1
        except ForgeSessionError as e:
            if len(targets) == 1:
                _handle_error(e)
            else:
                console.print(f"[red]Error:[/red] {name}: {e}")
                failed += 1
        except Exception as e:
            console.print(f"[red]Error:[/red] {name}: {e}")
            failed += 1

    if len(targets) > 1:
        parts = [f"{deleted} deleted"]
        if failed:
            parts.append(f"{failed} failed")
        console.print(f"\n[dim]Summary: {', '.join(parts)}[/dim]")

    if failed:
        sys.exit(1)


def _delete_single_session(
    *,
    manager: SessionManager,
    name: str,
    yes: bool,
    force: bool,
    keep_transcripts: bool,
    keep_worktree: bool,
    delete_branch: bool,
    forge_root: str | None = None,
) -> None:
    """Delete a single session, handling orphans and confirmation.

    Args:
        yes: Skip confirmation prompts (informational output stays visible).
        force: Override dirty-worktree and corruption guards.

    Raises:
        SystemExit: If user cancels or session not found.
        DirtyWorktreeError: If worktree has uncommitted changes and not force.
        ForgeSessionError: On other session errors.
    """
    if not manager.session_exists(name, forge_root=forge_root):
        from forge.session.store import SessionStore

        orphan_store = SessionStore(str(Path.cwd()), name)
        if orphan_store.session_dir.is_dir():
            import shutil

            console.print(
                f"Found orphaned session directory [bold]{name}[/bold] " "(exists on disk but not in session index)"
            )
            console.print(f"  Path: {display_path(orphan_store.session_dir)}")
            if not yes:
                if not click.confirm("Delete this orphaned session directory?"):
                    console.print("[dim]Cancelled[/dim]")
                    raise SystemExit(0)

            shutil.rmtree(orphan_store.session_dir)
            try:
                from forge.session.active import ActiveSessionStore

                ActiveSessionStore().clear_session(name, forge_root=forge_root)
            except Exception:
                logger.debug(
                    "Failed to clear active-session entry for orphan '%s'",
                    name,
                    exc_info=True,
                )
            console.print(f"Cleaned up orphaned session directory [green]{name}[/green]")
            return
        console.print(f"[red]Error:[/red] session '{name}' not found")
        raise SystemExit(1)

    # Informational output — always visible (--yes only skips prompts, not info)
    active_entry = _get_active_session_entry(name, forge_root=forge_root)
    if active_entry is not None:
        _print_active_delete_warning(name, active_entry)
    try:
        manifest = manager.get_session(name, forge_root=forge_root)

        console.print(f"About to delete session [bold]{name}[/bold]")

        if manifest.confirmed.claude_session_id:
            console.print(f"  UUID: {manifest.confirmed.claude_session_id}")

        if manifest.worktree and manifest.worktree.is_worktree:
            if keep_worktree:
                console.print(f"  [dim]Worktree will be kept: {display_path(manifest.worktree.path)}[/dim]")
            else:
                console.print(f"  Worktree will be removed: {display_path(manifest.worktree.path)}")
            if delete_branch:
                console.print(f"  Branch will be deleted: {manifest.worktree.branch}")
            else:
                console.print(f"  [dim]Branch will be kept: {manifest.worktree.branch}[/dim]")

        if not keep_transcripts:
            console.print("  [dim]Transcript files will also be deleted[/dim]")
        else:
            console.print("  [dim]Transcript files will be kept[/dim]")

        console.print()
    except ForgeSessionError:
        pass

    if not yes:
        if not click.confirm("Are you sure you want to delete this session?"):
            console.print("[dim]Cancelled[/dim]")
            raise SystemExit(0)

    manager.delete_session(
        name,
        delete_transcripts=not keep_transcripts,
        delete_worktree=not keep_worktree,
        delete_branch=delete_branch,
        force=force,
        forge_root=forge_root,
    )


@session.command("list")
@click.option(
    "--include-incognito/--no-incognito",
    "-i/-I",
    default=True,
    help="Include incognito sessions",
)
@click.option(
    "--older-than",
    type=int,
    default=None,
    metavar="DAYS",
    help="Only show sessions not accessed in DAYS days",
)
@click.option(
    "--scope",
    type=click.Choice(["repo", "project", "all"], case_sensitive=False),
    default="repo",
    help="Scope: repo (default, same logical repo), project (same forge_root), all (global)",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def list_sessions(include_incognito: bool, older_than: int | None, scope: str, as_json: bool) -> None:
    """List sessions.

    \b
    Examples:
        forge session list                  # Sessions in current repo
        forge session list --scope all      # All sessions globally
        forge session list --older-than 30  # Old sessions in current repo
    """
    if older_than is not None and older_than < 1:
        console.print("[red]Error:[/red] --older-than must be >= 1")
        sys.exit(1)

    from forge.core.ops.context import ExecutionContext
    from forge.core.ops.session import ForgeOpError
    from forge.core.ops.session import list_sessions as list_sessions_op

    ctx = ExecutionContext.from_cwd()

    if older_than is not None:
        from forge.core.ops.session import _scope_filters, list_sessions_older_than

        pr_filter, fr_filter = _scope_filters(ctx, scope)
        old_sessions = list_sessions_older_than(
            older_than_days=older_than,
            include_incognito=include_incognito,
            project_root_filter=pr_filter,
            forge_root_filter=fr_filter,
        )
        old_scope_keys = {_session_scope_key(name, entry) for name, entry in old_sessions}
    else:
        old_scope_keys = None

    try:
        result = list_sessions_op(ctx=ctx, include_incognito=include_incognito, scope=scope)
    except ForgeOpError as e:
        if as_json:
            import json

            click.echo(json.dumps({"error": str(e)}, indent=2), err=True)
        else:
            console.print(f"[red]Error:[/red] {e}", style="red")
        sys.exit(1)

    items = result.sessions
    if old_scope_keys is not None:
        items = [item for item in items if _session_scope_key(item.name, item.entry) in old_scope_keys]

    if as_json:
        import json

        data = []
        for item in items:
            data.append(
                {
                    "name": item.name,
                    "proxy_template": item.proxy_template,
                    "last_accessed_at": item.entry.last_accessed_at,
                    "is_active": item.is_active,
                    "worktree_path": item.entry.worktree_path,
                    "forge_root": item.entry.forge_root,
                    "checkout_root": item.entry.checkout_root,
                    "relative_path": item.entry.relative_path,
                    "is_fork": item.entry.is_fork,
                    "is_incognito": item.entry.is_incognito,
                    "parent_session": item.entry.parent_session,
                }
            )
        click.echo(json.dumps(data, indent=2, default=str))
        return

    if not items:
        if older_than is not None:
            console.print(f"[dim]No sessions older than {older_than} days.[/dim]")
        else:
            console.print("[dim]No sessions found.[/dim]")
            console.print("\n[dim]Tip: Run 'forge session start <name>'.[/dim]")
        return

    duplicate_names = {item.name for item in items if sum(1 for other in items if other.name == item.name) > 1}

    table = Table(show_header=True, header_style="bold")
    table.add_column("NAME")
    if duplicate_names:
        table.add_column("LOCATION")
    table.add_column("TEMPLATE")
    table.add_column("LAST USED")

    for item in items:
        entry = item.entry
        proxy_template = item.proxy_template or "direct"
        last_used = _format_relative_time(entry.last_accessed_at)
        row = [item.name]
        if duplicate_names:
            row.append(_session_list_location(entry))
        row.extend([proxy_template, last_used])
        table.add_row(*row)

    console.print(table)

    if older_than is None:
        _print_session_list_tips(items)


def _print_session_list_tips(items: list) -> None:
    """Print contextual tips after session list output."""
    count = len(items)

    if count == 1:
        name = items[0].name if hasattr(items[0], "name") else "name"
        console.print("\n[dim]Tip: Resume or start a session:[/dim]")
        console.print(f"[dim]  forge session resume {name}                  # resume this session[/dim]")
        console.print("[dim]  forge session start <name>                    # start a new session[/dim]")
    elif count > 0:
        console.print("\n[dim]Tip: Work with sessions:[/dim]")
        console.print("[dim]  forge session resume <name>                   # resume a session[/dim]")
        console.print("[dim]  forge session show <name>                     # inspect session details[/dim]")

    console.print("\n[dim]Tip: Clean up sessions:[/dim]")
    console.print("[dim]  forge session delete <name>                   # delete a specific session[/dim]")
    console.print("[dim]  forge session clean --older-than 30           # bulk clean old sessions[/dim]")
    console.print("[dim]  forge config set session_retention_days=90    # auto-cleanup on startup[/dim]")


@session.command("clean")
@click.option(
    "--older-than",
    type=int,
    required=True,
    metavar="DAYS",
    help="Delete sessions not accessed in DAYS days",
)
@click.option("--dry-run", "-n", is_flag=True, help="Show what would be deleted without deleting")
@click.option("--force", "-f", is_flag=True, help="Bypass dirty-worktree protection")
@click.option(
    "--keep-transcripts",
    "-k",
    is_flag=True,
    help="Keep Claude transcript files (~/.claude/projects/*.jsonl). Forge artifact snapshots (.forge/artifacts/) are always preserved",
)
@click.option(
    "--delete-worktree",
    is_flag=True,
    help="Also remove worktree directories (default: keep)",
)
@click.option(
    "--delete-branch",
    "-d",
    is_flag=True,
    help="Also delete git branches (requires --delete-worktree)",
)
def clean(
    older_than: int,
    dry_run: bool,
    force: bool,
    keep_transcripts: bool,
    delete_worktree: bool,
    delete_branch: bool,
) -> None:
    """Delete sessions older than a given age.

    \b
    Examples:
        forge session clean --older-than 30          # Delete sessions > 30 days old
        forge session clean --older-than 30 --dry-run # Preview what would be cleaned
        forge session clean --older-than 90 -k       # Keep transcript files

    Active sessions are always skipped. Worktrees are preserved by default
    (use --delete-worktree to remove them).
    """
    if older_than < 1:
        console.print("[red]Error:[/red] --older-than must be >= 1")
        sys.exit(1)

    if delete_branch and not delete_worktree:
        console.print("[red]Error:[/red] --delete-branch requires --delete-worktree")
        sys.exit(1)

    if dry_run:
        _clean_sessions_dry_run(older_than)
        return

    from forge.session.cleanup import clean_old_sessions

    result = clean_old_sessions(
        older_than_days=older_than,
        delete_transcripts=not keep_transcripts,
        delete_worktree=delete_worktree,
        delete_branch=delete_branch,
        force=force,
    )

    if result.is_empty:
        console.print(f"[dim]No sessions older than {older_than} days found.[/dim]")
        return

    if result.aborted:
        console.print("[red]Error:[/red] Session cleanup aborted before evaluation completed.")
        console.print(f"  [dim]{result.aborted_error}[/dim]")
    elif result.has_only_skips:
        console.print("[dim]No sessions cleaned.[/dim]")

    if result.deleted:
        console.print(
            f"Cleaned {len(result.deleted)} session{'s' if len(result.deleted) != 1 else ''}"
            f" older than {older_than} days."
        )
    elif not result.aborted:
        console.print("[dim]No sessions cleaned.[/dim]")

    if result.skipped_active:
        console.print(
            f"[dim]Kept {len(result.skipped_active)} active session{'s' if len(result.skipped_active) != 1 else ''}.[/dim]"
        )

    if result.skipped_unparseable:
        console.print(
            f"[dim]Skipped {len(result.skipped_unparseable)} session{'s' if len(result.skipped_unparseable) != 1 else ''}"
            f" with unparseable timestamps.[/dim]"
        )

    if result.should_exit_nonzero:
        console.print(
            f"[yellow]Encountered {result.summary_failed_count} cleanup {result.summary_failed_label}.[/yellow]"
        )
        for name, err in result.failure_items():
            console.print(f"  [dim]{name}: {err}[/dim]")
        sys.exit(1)


def _clean_sessions_dry_run(older_than_days: int) -> None:
    """Preview which sessions would be cleaned.

    Iterates all sessions directly (same path as clean_old_sessions) so that
    unparseable timestamps and active-registry errors are visible in the preview.
    """
    from forge.session.active import ActiveSessionStore

    manager = SessionManager()
    all_sessions = manager.list_sessions(include_incognito=True)

    # One-pass active lookup — fail-closed matches cleanup behavior
    active_store = ActiveSessionStore()
    registry_error = False
    try:
        active_entries = active_store.list_sessions()
        active_identities = {(name, ae.forge_root or ae.worktree_path) for name, ae in active_entries}
    except Exception:
        active_identities = set()
        registry_error = True

    table = Table(show_header=True, header_style="bold")
    table.add_column("SESSION")
    table.add_column("AGE")
    table.add_column("STATUS")

    deletable = 0
    skipped = 0
    any_old = False
    for name, entry in all_sessions:
        try:
            dt = parse_iso(entry.last_accessed_at)
            age_days = int((datetime.now(UTC) - dt).total_seconds() / 86400)
        except (ValueError, TypeError, AttributeError):
            table.add_row(name, "?", "[dim]unparseable timestamp (skip)[/dim]")
            skipped += 1
            any_old = True
            continue

        if age_days <= older_than_days:
            continue

        any_old = True
        age_str = f"{age_days}d"
        if (name, entry.forge_root or entry.worktree_path) in active_identities:
            table.add_row(name, age_str, "[yellow]active (skip)[/yellow]")
            skipped += 1
        else:
            table.add_row(name, age_str, "[green]will delete[/green]")
            deletable += 1

    if not any_old:
        console.print(f"[dim]No sessions older than {older_than_days} days found.[/dim]")
        return

    console.print(table)

    if registry_error:
        console.print(
            "[yellow]Warning:[/yellow] Could not read active session registry."
            " Actual cleanup would abort to protect running sessions."
        )

    console.print(
        f"\n[dim]Would delete {deletable} session{'s' if deletable != 1 else ''}"
        + (f", skip {skipped}" if skipped else "")
        + ".[/dim]"
    )


@session.command()
@click.argument("session_id", required=False)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option(
    "--field",
    "field_path",
    help="Extract a single dotted field (e.g., model_family, proxy.template). Missing path exits 1; null value prints empty.",
)
def show(session_id: str | None, as_json: bool, field_path: str | None) -> None:
    """Show session details.

    SESSION_ID can be a Forge session name or a Claude session UUID.
    Without SESSION_ID, resolves from $FORGE_SESSION.

    \b
    Examples:
        forge session show my-session                     # Full details
        forge session show                                # Current session
        forge session show my-session --json              # JSON output
        forge session show my-session --field model_family  # Extract field
    """
    import json

    from forge.core.ops.session_context import (
        SessionContextError,
        extract_field,
        get_session_context,
    )

    # When no argument and no env var: for human mode, show a helpful message.
    # For --json/--field, fall through to get_session_context() which builds
    # env-derived context (backward compat with old `session context --json`).
    if session_id is None and not os.environ.get("FORGE_SESSION") and not (as_json or field_path):
        console.print("[dim]No session specified. Use a name or launch through Forge.[/dim]")
        return

    try:
        ctx = get_session_context(session_id)
    except AmbiguousSessionError as e:
        if as_json:
            click.echo(json.dumps({"error": str(e)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except SessionContextError as e:
        if as_json:
            click.echo(json.dumps({"error": str(e)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    # Resolve the forge_root once — either from get_session_context's prior
    # UUID/name lookup (preserves exact scope for UUIDs) or via the two-tier
    # repo-wide resolver as fallback.
    from forge.core.ops.resolution import resolve_session_repo_wide
    from forge.core.ops.session_context import resolve_session_identifier

    manager = SessionManager()
    _fr = _cwd_forge_root()

    # get_session_context already resolved the identifier (UUID or name) to
    # an exact (name, forge_root). Reuse that forge_root so UUID lookups
    # don't get re-resolved by name (which could pick the wrong duplicate).
    resolved_fr: str | None = None
    try:
        _, id_forge_root = resolve_session_identifier(session_id)
        resolved_fr = id_forge_root
    except Exception:
        pass

    def _load_state_and_entry() -> tuple[SessionState | None, SessionIndexEntry | None, bool]:
        """Load manifest + entry, returning (state, entry, is_cross_project)."""
        if resolved_fr is not None:
            try:
                st = manager.get_session(ctx.session_name, forge_root=resolved_fr)
                ent = manager.get_session_entry(ctx.session_name, forge_root=resolved_fr)
                is_cross = resolved_fr != _fr if _fr else False
                return st, ent, is_cross
            except ForgeSessionError:
                pass
        # Fallback: two-tier repo-wide resolution
        try:
            res = resolve_session_repo_wide(ctx.session_name, _fr, manager=manager)
            return res.state, res.entry, res.is_cross_project
        except (SessionNotFoundError, AmbiguousSessionError, ForgeSessionError):
            return None, None, False

    if as_json or field_path:
        state, _, _ = _load_state_and_entry()
        data = _build_show_json(state, ctx)

        if field_path:
            try:
                value = extract_field(data, field_path)
            except KeyError:
                console.print(f"[red]Error:[/red] Field '{field_path}' not found")
                sys.exit(1)
            if value is None:
                click.echo("")
            elif isinstance(value, str):
                click.echo(value)
            else:
                click.echo(json.dumps(value))
            return

        click.echo(json.dumps(data, indent=2, default=str))
        return

    state, entry, is_cross_project = _load_state_and_entry()
    if state is None or entry is None:
        console.print(f"[red]Error:[/red] session '{ctx.session_name}' not found")
        sys.exit(1)

    if is_cross_project:
        console.print(f"[dim]Showing session from {display_path(resolved_fr or '')}[/dim]\n")

    _print_session_detail(state, entry, ctx)


@session.command("context", hidden=True)
@click.argument("session_id", required=False)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option(
    "--field",
    "field_path",
    help="Extract a single dotted field (e.g., model_family, proxy.template). Missing path exits 1; null value prints empty.",
)
def context_cmd(session_id: str | None, as_json: bool, field_path: str | None) -> None:
    """Show session context (metadata, proxy, model family).

    Deprecated: use ``forge session show`` instead.

    SESSION_ID can be a Forge session name or a Claude session UUID.
    Without SESSION_ID, resolves from $FORGE_SESSION.

    \b
    Examples:
        forge session context                        # current session
        forge session context --json                 # full JSON
        forge session context --field model_family   # just the family
        forge session context abc-123-uuid --json    # by Claude UUID
    """
    import json

    from forge.core.ops.session_context import (
        SessionContextError,
        extract_field,
        get_session_context,
    )

    try:
        ctx = get_session_context(session_id)
    except SessionContextError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1) from None

    data = ctx.to_dict()

    if field_path:
        try:
            value = extract_field(data, field_path)
        except KeyError:
            console.print(f"[red]Error:[/red] Field '{field_path}' not found")
            raise SystemExit(1) from None
        # Raw value output for scripting — no JSON wrapper, no quotes for strings.
        # None prints empty (jq -r convention) so callers can tell "field exists but unset".
        if value is None:
            click.echo("")
        elif isinstance(value, str):
            click.echo(value)
        else:
            click.echo(json.dumps(value))
        return

    if as_json:
        click.echo(json.dumps(data, indent=2))
        return

    _print_session_context(ctx)


def _build_show_json(
    state: SessionState | None,
    ctx: SessionContext,
) -> dict[str, Any]:
    """Build merged JSON for ``session show --json``.

    Manifest data at the top level, computed context nested under ``context``.
    """
    data: dict[str, Any] = {
        "session_name": ctx.session_name,
        "claude_session_id": ctx.claude_session_id,
        "created_at": ctx.created_at,
        "is_fork": ctx.is_fork,
        "is_incognito": ctx.is_incognito,
        "parent_session": ctx.parent_session,
    }

    if state:
        data["last_accessed_at"] = state.last_accessed_at
        data["intent"] = {
            "agent": state.intent.agent,
            "proxy": (
                {
                    "template": state.intent.proxy.template,
                    "base_url": state.intent.proxy.base_url,
                }
                if state.intent.proxy
                else None
            ),
        }
        data["confirmed"] = {
            "claude_session_id": state.confirmed.claude_session_id,
            "transcript_path": state.confirmed.transcript_path,
            "confirmed_at": state.confirmed.confirmed_at,
            "confirmed_by": state.confirmed.confirmed_by,
            "latest_plan_path": state.confirmed.latest_plan_path,
            "artifacts": dict(state.confirmed.artifacts),
            "derivation": (dataclasses.asdict(state.confirmed.derivation) if state.confirmed.derivation else None),
            "is_sandboxed": state.confirmed.is_sandboxed,
            "claude_project_root": state.confirmed.claude_project_root,
            "policy": (dataclasses.asdict(state.confirmed.policy) if state.confirmed.policy else None),
        }
        data["overrides"] = dict(state.overrides)
        data["worktree"] = {"path": state.worktree.path, "branch": state.worktree.branch} if state.worktree else None
    else:
        data["last_accessed_at"] = None
        data["intent"] = None
        data["confirmed"] = None
        data["overrides"] = {}
        data["worktree"] = {"path": ctx.worktree_path} if ctx.worktree_path else None

    data["plan"] = _build_show_plan_json(state)
    data["project_root"] = ctx.project_root

    data["context"] = {
        "model_family": ctx.model_family,
        "models": dict(ctx.models),
        "proxy": {
            "template": ctx.proxy.template,
            "base_url": ctx.proxy.base_url,
            "proxy_id": ctx.proxy.proxy_id,
            "is_direct": ctx.proxy.is_direct,
        },
        "policy": {
            "enabled": ctx.policy.enabled,
            "fail_mode": ctx.policy.fail_mode,
            "bundles": list(ctx.policy.bundles),
            "supervisor_resume_id": ctx.policy.supervisor_resume_id,
        },
    }

    # Top-level aliases for backward compat with old `session context --field`
    data["model_family"] = ctx.model_family
    data["models"] = dict(ctx.models)
    data["proxy"] = data["context"]["proxy"]
    data["policy"] = data["context"]["policy"]

    return data


def _empty_show_plan_json() -> dict[str, Any]:
    """Return the resolved plan shape used by `session show --json`."""
    return {
        "source": None,
        "parent_session": None,
        "draft_path": None,
        "approved_snapshots": [],
        "preferred_path": None,
        "display_path": None,
        "exists": None,
        "kind": None,
    }


def _build_show_plan_json(state: SessionState | None) -> dict[str, Any]:
    """Build the resolved/inherited plan view for machine-readable output."""
    if state is None:
        return _empty_show_plan_json()

    current_forge_root = state.forge_root or (state.worktree.path if state.worktree else None)
    if current_forge_root is None:
        return _empty_show_plan_json()

    plan_info = resolve_plan_info(state, current_forge_root=current_forge_root)
    displayed = resolve_displayed_plan_path(
        plan_info,
        current_forge_root=current_forge_root,
        current_launch_root=resolve_plan_launch_root(state),
    )

    if plan_info.approved_snapshots:
        kind = "approved"
    elif plan_info.draft_path:
        kind = "draft"
    else:
        kind = None

    return {
        "source": plan_info.source,
        "parent_session": plan_info.parent_session,
        "draft_path": plan_info.draft_path,
        "approved_snapshots": list(plan_info.approved_snapshots),
        "preferred_path": preferred_plan_path(plan_info),
        "display_path": displayed.path if displayed else None,
        "exists": displayed.exists if displayed else None,
        "kind": kind,
    }


def _print_session_context(ctx: SessionContext) -> None:
    """Print session context in human-readable format."""

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="dim")
    table.add_column("Value")

    table.add_row("Session", ctx.session_name)
    if ctx.claude_session_id:
        table.add_row("Claude UUID", ctx.claude_session_id)
    table.add_row("Model Family", f"[cyan]{ctx.model_family}[/cyan]")

    if ctx.proxy.is_direct:
        table.add_row("Proxy", "[dim]direct (no proxy)[/dim]")
    else:
        proxy_parts = []
        if ctx.proxy.template:
            proxy_parts.append(ctx.proxy.template)
        if ctx.proxy.base_url:
            proxy_parts.append(ctx.proxy.base_url)
        table.add_row("Proxy", " | ".join(proxy_parts))

    if ctx.models:
        model_str = ", ".join(f"{t}={m}" for t, m in ctx.models.items())
        table.add_row("Models", model_str)

    if ctx.worktree_path:
        table.add_row("Worktree", ctx.worktree_path)

    if ctx.parent_session:
        table.add_row("Parent", ctx.parent_session)

    if ctx.is_fork:
        table.add_row("Fork", "yes")

    if ctx.policy.enabled:
        table.add_row("Policy", f"enabled (bundles: {', '.join(ctx.policy.bundles) or 'none'})")

    console.print(table)


@session.command()
@click.argument("name", required=False)
def shell(name: str | None) -> None:
    """Open a shell in a sidecar session container.

    Without NAME, resolves from $FORGE_SESSION.
    Only works for sessions started with --sidecar.
    """
    from forge.sidecar import exec_in_container, is_container_running

    manager = SessionManager()

    if name is None:
        env_name = os.environ.get("FORGE_SESSION")
        if env_name:
            name = env_name
        else:
            console.print("[red]Error:[/red] No session specified. Use a name or launch through Forge.")
            console.print("\n[dim]Tip: Run 'forge session start <name> --sidecar'.[/dim]")
            sys.exit(1)

    _fr = _cwd_forge_root()
    if not manager.session_exists(name, forge_root=_fr):
        if not _hint_cross_project_session(name, _fr):
            console.print(f"[red]Error:[/red] Session '{name}' not found")
        sys.exit(1)

    try:
        manifest = manager.get_session(name, forge_root=_fr)
    except ForgeSessionError as e:
        _handle_error(e)
        return

    if not manifest.confirmed.is_sandboxed:
        console.print(f"[red]Error:[/red] Session '{name}' is not a sidecar session")
        console.print("\nOnly sessions started with --sidecar can use shell.")
        console.print("Start a sidecar session with: [cyan]forge session start <name> --sidecar[/cyan]")
        sys.exit(1)

    # Check if container is running (deterministic naming)
    container_name = f"forge-{name}"
    if not is_container_running(container_name):
        console.print(f"[red]Error:[/red] Container '{container_name}' is not running")
        console.print("\nThe sidecar session may have exited.")
        sys.exit(1)

    console.print(f"Opening shell in container [cyan]{container_name}[/cyan]...")
    exit_code = exec_in_container(container_name, ["/bin/bash"])
    sys.exit(exit_code)


@session.command("set")
@click.argument("key")
@click.argument("value")
@click.option("--session", "-s", "session_name", help="Target session (default: current from cwd)")
def set_override(key: str, value: str, session_name: str | None) -> None:
    """Set a mid-session override.

    KEY is a dot-notation path relative to intent (e.g., agent, proxy.template).
    VALUE is parsed as JSON first, then as string.

    \b
    Examples:
        forge session set agent custom-agent
        forge session set memory.tags '["tag1","tag2"]'
        forge session set proxy.* null  # Clear all proxy fields
    """
    from forge.core.ops.context import ExecutionContext
    from forge.core.ops.session import ForgeOpError
    from forge.core.ops.session import set_session_override as set_override_op

    try:
        ctx = ExecutionContext.from_cwd()
        result = set_override_op(ctx=ctx, session_name=session_name, key=key, value_str=value)
        display_value = _format_value(result.value)
        console.print(f"Set [cyan]{result.key}[/cyan] = {display_value} [dim](override)[/dim]")

        if key.startswith("verification"):
            from forge.install.hooks import has_forge_hook

            if not has_forge_hook(ctx.worktree_root, "Stop"):
                console.print(
                    "[yellow]Warning:[/yellow] Verification configured but Stop hook is not installed. "
                    "Enforcement will not be active."
                )
                console.print("[dim]Tip: Run 'forge extension enable' to install hooks.[/dim]")
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@session.command()
@click.argument("key", required=False)
@click.option("--all", "-a", "clear_all", is_flag=True, help="Clear all overrides")
@click.option("--session", "-s", "session_name", help="Target session (default: current from cwd)")
def reset(key: str | None, clear_all: bool, session_name: str | None) -> None:
    """Reset overrides, reverting to intent values.

    If KEY is provided, resets only that key.
    If --all or no key, clears all overrides.

    Examples:

        forge session reset agent          # Reset single key

        forge session reset               # Clear all overrides

        forge session reset --all         # Clear all overrides (explicit)

        forge session reset memory.*      # Reset all memory.* overrides
    """
    from forge.core.ops.context import ExecutionContext
    from forge.core.ops.session import ForgeOpError
    from forge.core.ops.session import reset_session_overrides as reset_overrides_op

    if key and clear_all:
        console.print("[red]Error:[/red] Cannot specify both KEY and --all")
        sys.exit(1)

    try:
        ctx = ExecutionContext.from_cwd()
        result = reset_overrides_op(ctx=ctx, session_name=session_name, key=key)

        if result.cleared_all:
            if result.was_present:
                console.print("[green]Cleared all overrides[/green]")
            else:
                console.print("[dim]No overrides to clear[/dim]")
        else:
            if result.was_present:
                console.print(f"Reset [cyan]{result.key}[/cyan] [dim](now using intent value)[/dim]")
            else:
                console.print(f"[dim]No override for {result.key} (no-op)[/dim]")
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@session.command()
@click.argument("name", required=False)
@click.option(
    "--proxy",
    "proxy_name",
    type=str,
    default=None,
    help="Proxy to use (proxy_id or template name)",
)
@click.option("--no-proxy", "direct", is_flag=True, help="Bypass the proxy and talk to Anthropic directly")
@click.option("--direct", "direct_deprecated", is_flag=True, hidden=True, help="Deprecated alias for --no-proxy")
@click.option("--system-prompt", "-s", help="Append system prompt text")
@click.option(
    "--system-prompt-file",
    "-S",
    type=click.Path(exists=True),
    help="Append system prompt from file",
)
@click.option("--worktree", "-w", is_flag=True, help="Create git worktree for session isolation")
@click.option("--branch", "-b", help="Override branch name (requires --worktree)")
@click.option("--sidecar", is_flag=True, help="Run with bundled proxy in Docker container")
@click.option("--host-proxy", is_flag=True, help="Use host proxy (overrides config)")
@click.option("--mount", "mounts", multiple=True, help="Extra mounts (host:container[:ro|rw])")
@click.option("--image", default=None, help="Docker image for sidecar mode")
@click.option(
    "--extensions/--no-extensions",
    default=None,
    help="Auto-install extensions in worktree (default: inherit from parent)",
)
def incognito(
    name: str | None,
    proxy_name: str | None,
    direct: bool,
    direct_deprecated: bool,
    system_prompt: str | None,
    system_prompt_file: str | None,
    worktree: bool,
    branch: str | None,
    sidecar: bool,
    host_proxy: bool,
    mounts: tuple[str, ...],
    image: str | None,
    extensions: bool | None,
) -> None:
    """Start an incognito session.

    Shortcut for ``forge session start --incognito``. The session is
    automatically deleted when exited.

    \b
    Examples:
        forge session incognito                          # Auto-named
        forge session incognito --proxy litellm-gemini   # With proxy
        forge session incognito my-test                  # Custom name
    """
    direct = direct or direct_deprecated
    if direct and proxy_name:
        console.print("[red]Error:[/red] --no-proxy and --proxy are mutually exclusive")
        sys.exit(1)

    # Default to direct mode when neither --proxy nor --no-proxy is given,
    # unless --sidecar or --host-proxy is specified (both imply proxy mode).
    if not proxy_name and not direct and not sidecar and not host_proxy:
        direct = True

    routing: ResolvedRouting | None = None
    if proxy_name:
        routing = _resolve_routing_from_cli(proxy_name=proxy_name, direct=False)

    from forge.cli.guards import require_repo_root

    require_repo_root()

    if name is None:
        _fr = _cwd_forge_root()
        existing = {n for n, _ in SessionManager().list_sessions(forge_root_filter=_fr)}
        name = generate_unique_name(existing)

    # Incognito cleanup is handled inside launch_new_session() so that
    # validation/creation failures don't trigger deletion of existing sessions.
    sys.exit(
        launch_new_session(
            name=name,
            template=routing.template if routing else None,
            base_url=routing.base_url if routing else None,
            direct=direct,
            incognito=True,
            system_prompt=system_prompt,
            system_prompt_file=system_prompt_file,
            worktree=worktree,
            branch=branch,
            sidecar=sidecar,
            host_proxy=host_proxy,
            mounts=mounts,
            image=image,
            no_launch=False,
            extensions=extensions,
            proxy_id=routing.proxy_id if routing else None,
            proxy_display=routing.proxy_id if routing else None,
            context_limit_override=routing.context_limit if routing else None,
        )
    )


def _print_session_summary(state: SessionState) -> None:
    """Print a brief session summary."""
    console.print(f"[green]{state.name}[/green]", end="")

    parts = [_template_display_label(state.intent.proxy.template) if state.intent.proxy else "direct"]
    console.print(f" ({', '.join(parts)})")

    if state.worktree:
        console.print(f"  [dim]{display_path(state.worktree.path)}[/dim]")


def _print_plan_info(plan_info: PlanInfo, *, current_forge_root: str, current_launch_root: str | None) -> None:
    """Print a Plan subsection for `forge session show`, if any plan info applies.

    Parent (inherited): one line, approved snapshot preferred.
    Self: approved snapshot line AND draft line when both exist (the draft is
    the live pointer for in-progress edits; the snapshot is the last approval).
    Paths are absolute, with ``(file missing)`` when not on disk.
    """
    if plan_info.source is None:
        return

    if plan_info.source == "parent":
        displayed = resolve_displayed_plan_path(
            plan_info,
            current_forge_root=current_forge_root,
            current_launch_root=current_launch_root,
        )
        if displayed is None:
            return
        kind = "approved snapshot" if plan_info.approved_snapshots else "draft"
        missing = "" if displayed.exists else " [dim](file missing)[/dim]"
        console.print(
            f"  Plan (inherited from {plan_info.parent_session}, {kind}): {display_path(displayed.path)}{missing}"
        )
        return

    if plan_info.approved_snapshots:
        snap_rel = latest_snapshot_path(plan_info.approved_snapshots)
        if snap_rel is not None:
            d = resolve_path_against(snap_rel, current_forge_root)
            missing = "" if d.exists else " [dim](file missing)[/dim]"
            count = len(plan_info.approved_snapshots)
            console.print(f"  Plans approved: {count} (latest: {display_path(d.path)}){missing}")
    if plan_info.draft_path:
        d = resolve_path_against(plan_info.draft_path, current_launch_root)
        missing = "" if d.exists else " [dim](file missing)[/dim]"
        console.print(f"  Plan (draft): {display_path(d.path)}{missing}")


def _print_session_detail(
    state: SessionState,
    entry: SessionIndexEntry,
    ctx: SessionContext | None = None,
) -> None:
    """Print detailed session information with optional computed context."""

    console.print(f"Session: [bold]{state.name}[/bold]")
    console.print("=" * 50)
    console.print()

    console.print("[bold]Basic Info[/bold]")
    if state.confirmed.claude_session_id:
        console.print(f"  UUID:         {state.confirmed.claude_session_id}")
    console.print(f"  Created:      {state.created_at}")
    console.print(f"  Last Used:    {state.last_accessed_at}")

    session_type = _get_session_type(state.is_fork, state.is_incognito, state.parent_session)
    console.print(f"  Type:         {session_type}")
    console.print()

    console.print("[bold]Configuration (Intent)[/bold]")
    console.print(f"  Agent:        {state.intent.agent}")
    if state.intent.proxy:
        console.print(f"  Routing:      {_template_display_label(state.intent.proxy.template)}")
        console.print(f"  Base URL:     {state.intent.proxy.base_url}")
    else:
        console.print("  Routing:      direct")
        console.print("  Base URL:     default Anthropic")
    console.print()

    if state.worktree:
        console.print("[bold]Worktree[/bold]")
        console.print(f"  Path:         {display_path(state.worktree.path)}")
        console.print(f"  Branch:       {state.worktree.branch}")
        console.print()

    current_forge_root = (
        entry.forge_root or state.forge_root or (state.worktree.path if state.worktree else str(Path.cwd()))
    )
    plan_info = resolve_plan_info(state, current_forge_root=current_forge_root)
    current_launch_root = resolve_plan_launch_root(state)

    # Confirmed state (from hooks)
    has_confirmed = (
        state.confirmed.claude_session_id
        or state.confirmed.transcript_path
        or plan_info.source
        or (state.confirmed.policy and state.confirmed.policy.decisions)
    )
    if has_confirmed:
        console.print("[bold]Confirmed State[/bold]")
        if state.confirmed.transcript_path:
            console.print(f"  Transcript:   {display_path(state.confirmed.transcript_path)}")
        if state.confirmed.confirmed_at:
            console.print(f"  Confirmed At: {state.confirmed.confirmed_at}")
        if state.confirmed.confirmed_by:
            console.print(f"  Confirmed By: {state.confirmed.confirmed_by}")
        _print_plan_info(
            plan_info,
            current_forge_root=current_forge_root,
            current_launch_root=current_launch_root,
        )
        if state.confirmed.policy and state.confirmed.policy.decisions:
            pc = state.confirmed.policy
            n = len(pc.decisions)
            last = pc.decisions[-1] if pc.decisions else None
            last_label = ""
            if last and isinstance(last, dict):
                last_decision = last.get("final_decision", "?")
                last_context = last.get("context_summary", "")
                last_label = f", last: {last_decision}"
                if last_context:
                    last_label += f" ({last_context})"
            console.print(f"  Policy Evals: {n} evaluation{'s' if n != 1 else ''}{last_label}")

    # Active overrides
    if state.overrides:
        console.print()
        console.print("[bold]Active Overrides[/bold]")
        for key, value in _flatten_overrides(state.overrides):
            console.print(f"  {key}: {_format_value(value)}")

    if ctx:
        console.print()
        console.print("[bold]Computed Context[/bold]")
        console.print(f"  Model Family: [cyan]{ctx.model_family}[/cyan]")
        if ctx.models:
            model_str = ", ".join(f"{t}={m}" for t, m in ctx.models.items())
            console.print(f"  Models:       {model_str}")
        if ctx.policy.enabled:
            bundles_str = ", ".join(ctx.policy.bundles) or "none"
            console.print(f"  Policy:       enabled (bundles: {bundles_str})")


def _flatten_overrides(
    overrides: dict,
    prefix: str = "",
) -> list[tuple[str, object]]:
    """Flatten nested override dict to dot-notation key-value pairs."""
    result: list[tuple[str, object]] = []
    for key, value in overrides.items():
        full_key = f"{prefix}{key}" if prefix else key
        if isinstance(value, dict):
            result.extend(_flatten_overrides(value, f"{full_key}."))
        else:
            result.append((full_key, value))
    return result


def _format_value(value: object) -> str:
    """Format a value for display."""
    if value is None:
        return "[dim]null[/dim]"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        return f'"{value}"'
    return repr(value)

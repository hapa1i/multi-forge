"""Session lifecycle commands: start, resume, fork, incognito.

Split from session.py for file-size compliance. All public and private
names are re-exported by session.py so that ``patch("forge.cli.session.XXX")``
continues to work.
"""

from __future__ import annotations

import shlex
import sys
import uuid as _uuid
from datetime import datetime
from pathlib import Path
from typing import cast

import click

from forge.core.effort import CLAUDE_EFFORT_LEVELS
from forge.core.llm.types import REASONING_EFFORT_LEVELS
from forge.core.ops.claude_session import (
    ClaudeLaunchPreferences,
    ClaudeResumeAction,
    ClaudeResumeResult,
    ClaudeResumeRouting,
    ClaudeResumeWarning,
    ClaudeSessionLaunchResult,
    ClaudeSidecarLaunch,
    ClaudeStartCreated,
    ClaudeStartError,
    ClaudeStartExtensions,
    ResumeLaunchPlan,
    ResumePrepared,
    SupervisorWiring,
    launch_claude_session,
    resolve_and_validate_system_prompt,
    resume_claude_session,
    start_claude_session,
)
from forge.core.ops.context import _cwd_forge_root
from forge.core.ops.session import ForgeOpError
from forge.core.paths import display_path
from forge.policy.semantic.supervisor import (
    CHECKER_PROVIDER_CHOICES,
    supervisor_lane_runtimes,
    validate_checker_model,
)
from forge.session import (
    LAUNCH_MODE_HOST,
    LAUNCH_MODE_SIDECAR,
    ForgeSessionError,
    SessionIndexEntry,
    SessionManager,
    SessionState,
    SessionStore,
)
from forge.session.context_limit import _resolve_context_limit
from forge.session.direct_model import (
    DirectModelPin,
    resolve_direct_model_pin,
    token_estimate_multiplier_for_direct_model,
)
from forge.session.exceptions import (
    BranchExistsError,
    SessionNotFoundError,
)
from forge.session.launch import (
    _combine_prompt_files,
    _resolve_extension_detection_root,
    _resolve_launch_mode,
)
from forge.session.model_pin import (
    _validate_direct_model_pin_for_routing,
    _validate_proxy_model_pin,
)
from forge.session.prev_sessions import (
    ensure_notes_overlay,
    notes_for_snapshot,
    notes_has_user_content,
)
from forge.session.transfer import ResumeStrategy


# Names that tests patch on forge.cli.session (invoke_claude,
# run_with_active_session, SessionManager, generate_unique_name) must be
# accessed through the parent module at call time. We use _sess() to get
# the module from sys.modules (already loaded by the time any function runs).
def _sess():  # type: ignore[return]
    return sys.modules["forge.cli.session"]


from forge.cli.editor import open_in_editor  # noqa: E402
from forge.cli.output import print_error, print_error_with_tip, print_tip  # noqa: E402
from forge.cli.session import (  # noqa: E402
    ResolvedRouting,
    _get_active_session_entry,
    _get_effective_proxy_for_session,
    _get_launch_preferences,
    _hint_cross_project_session,
    _print_routing_summary,
    console,
    handle_session_error,
    logger,
)
from forge.cli.session import session as _session_untyped  # noqa: E402

session = cast(click.Group, _session_untyped)  # type: ignore[has-type]  # circular re-export

from forge.cli.session_codex import (  # noqa: E402
    codex_resume_options,
    codex_start_options,
    reject_codex_flags_for_claude,
    run_codex_resume,
    run_codex_start,
)
from forge.cli.session_resume_modes import (  # noqa: E402
    _resume_fresh_native,
    _resume_fresh_rewind,
)
from forge.cli.session_rewind import (  # noqa: E402
    _persist_rewind_derivation,
    _prepare_rewind_launch_artifacts,
)

# Functions below are accessed through _sess() because tests patch them
# on forge.cli.session. Direct imports would bypass those patches.
# _auto_install_extensions, _detect_parent_extensions,
# _generate_parent_transfer_context

__all__ = [
    # Public functions
    "launch_new_session",
    # Click commands
    "start",
    "resume",
    "incognito",
    # Private helpers (needed for re-export to forge.cli.session namespace)
    "_launch_claude_for_session",
    "_launch_in_place",
    "_reconnect_in_place",
    "_launch_as_child",
    "_resume_fresh",
    "_resume_fresh_rewind",
    "_resume_fresh_native",
    "_pick_session",
    "_print_context_path",
    "_print_post_exit_tip",
    "_resume_tip_command",
    "_print_branch_exists_tip",
    "_execute_resume_launch_plan",
    "_get_resume_launch_preferences",
    "_resume_launch_preferences_for_op",
    "_resume_routing_for_op",
    "_has_confirmed_claude_session",
    "_is_resumable_session",
    "_has_resumable_transcript",
    "_has_resumable_claude_session",
    "_get_deferred_same_dir_fork_resume_id",
    "_resolve_manifest_prompt_file",
    "_persist_fork_transfer_derivation",
    "_persist_rewind_derivation",
    "_prepare_rewind_launch_artifacts",
    "_warn_if_hooks_missing",
    "_warn_if_version_outdated",
]


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

    # A same-directory TRANSFER fork must never deferred-resume as a native parent fork, even if the
    # best-effort UUID pre-seed failed (leaving claude_session_id unset). Recorded transfer intent is
    # authoritative, so it falls through to the transfer-context path in _launch_in_place.
    derivation = manifest.confirmed.derivation
    if derivation is not None and derivation.resume_mode == "transfer":
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
    print_tip("Run 'forge extension enable' to install hooks.", blank_before=False, console=console)


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
    print_tip("Run 'claude update' to upgrade.", blank_before=False, console=console)


def _resolve_manifest_prompt_file(manifest: SessionState) -> Path | None:
    """Resolve a session's configured system prompt file, if any."""
    if manifest.intent.system_prompt is None or manifest.intent.system_prompt.file is None:
        return None
    prompt_path = Path(manifest.intent.system_prompt.file).expanduser()
    return prompt_path.resolve() if prompt_path.exists() else None


def _persist_fork_transfer_derivation(
    *,
    manifest: SessionState,
    strategy: str,
    context_path: Path | None,
) -> SessionState:
    """Persist transfer-specific derivation details for a worktree fork."""
    worktree_path = Path(manifest.worktree.path) if manifest.worktree else Path.cwd()
    forge_root = Path(manifest.forge_root) if manifest.forge_root else worktree_path

    context_file: str | None = None
    if context_path is not None:
        try:
            context_file = str(context_path.relative_to(forge_root))
        except ValueError:
            context_file = str(context_path)

    def _mutate(m: SessionState) -> None:
        if m.confirmed.derivation is None:
            from forge.session.models import Derivation

            m.confirmed.derivation = Derivation(parent_session=m.parent_session or "")
        m.confirmed.derivation.resume_mode = "transfer"
        m.confirmed.derivation.strategy = strategy
        m.confirmed.derivation.context_file = context_file

    return SessionStore(str(forge_root), manifest.name).update(timeout_s=5.0, mutate=_mutate)


def _is_legacy_flat_transfer_path(path: Path) -> bool:
    """Return True for pre-0.2.0 ``.forge/prev_sessions/<parent>.md`` artifacts."""
    return path.suffix == ".md" and path.parent.name == "prev_sessions"


def _validate_resume_mode(_ctx: click.Context, _param: click.Parameter, value: str | None) -> str | None:
    """Validate ``--resume-mode``; the flag is optional, so pass ``None`` through.

    Accepts ``native`` / ``transfer``.
    """
    if value is None:
        return None
    if value not in {"native", "transfer"}:
        raise click.BadParameter(f"{value!r} is not one of 'native', 'transfer'.")
    return value


def _resolve_derivation_context_file(manifest: SessionState) -> Path | None:
    """Resolve a persisted transfer context file for a never-launched child."""
    derivation = manifest.confirmed.derivation
    if derivation is None or not derivation.context_file:
        return None

    context_path = Path(derivation.context_file).expanduser()
    if _is_legacy_flat_transfer_path(context_path):
        parent = derivation.parent_session or manifest.parent_session or "<parent>"
        print_error_with_tip(
            f"Legacy transfer artifact format is no longer supported: {display_path(context_path)}",
            f"Run 'forge session resume {parent} --fresh' to regenerate a per-child transfer artifact.",
            console=console,
        )
        sys.exit(1)
    if not context_path.is_absolute():
        worktree_path = Path(manifest.worktree.path) if manifest.worktree else Path.cwd()
        forge_root = Path(manifest.forge_root) if manifest.forge_root else worktree_path
        context_path = forge_root / context_path

    return context_path.resolve() if context_path.is_file() else None


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
    try:
        result = launch_claude_session(
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
            register_fork=register_fork,
            system_prompt_file=system_prompt_file,
            name=name,
            extra_args=extra_args,
            proxy_id=proxy_id,
            before_launch=_warn_before_claude_launch,
            on_sidecar_launch=_render_sidecar_launch,
            invoke=_sess().invoke_claude,
            run_active=_sess().run_with_active_session,
        )
    except ForgeOpError as e:
        print_error(str(e), console=console)
        return 1
    return _render_claude_launch_result(result)


def _warn_before_claude_launch(forge_root: Path) -> None:
    _sess()._warn_if_hooks_missing(forge_root)
    _sess()._warn_if_version_outdated()


def _render_sidecar_launch(event: ClaudeSidecarLaunch) -> None:
    console.print("[cyan]Starting sidecar session in container[/cyan]")
    console.print(f"  Image: {event.image}")
    if event.proxy_id and event.intercept_mode:
        console.print(f"  Intercept: {event.intercept_mode} (proxy '{event.proxy_id}')")
        if event.audit_path is not None:
            console.print(f"  Audit: host-visible at {display_path(event.audit_path)}")
    console.print()


def _render_claude_launch_result(result: ClaudeSessionLaunchResult) -> int:
    for warning in result.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")
    return _post_exit_render(
        result.manifest,
        store_exists=result.store_exists,
        exit_code=result.exit_code,
        since=result.operation_started_at,
    )


def _post_exit_render(
    manifest: SessionState,
    *,
    store_exists: bool,
    exit_code: int,
    since: datetime | None,
) -> int:
    """Shared post-exit output for host, sidecar, and fork launches.

    Prints the Forge activity summary (best-effort) then the reconnect tip when the
    session still exists; returns ``exit_code`` unchanged so callers can ``return`` it.
    """
    if store_exists:
        _print_session_activity_summary(manifest, since=since)
        _print_post_exit_tip(manifest)
    elif not manifest.is_incognito and manifest.name:
        console.print(f"\n[dim]Session '{manifest.name}' was deleted during this run.[/dim]")
    return exit_code


def _print_session_activity_summary(manifest: SessionState, *, since: datetime | None) -> None:
    """Print a one-line summary of what Forge did this run. Best-effort; never raises.

    Reads the manifest fresh from disk (via the ops builder) because hooks wrote
    ``confirmed.policy`` / ``subagents`` during the session, after the launcher's
    in-memory copy was taken.
    """
    if manifest.is_incognito or not manifest.name or not manifest.forge_root:
        return
    try:
        from forge.core.ops.usage_summary import (
            build_session_activity_summary,
            render_summary_line,
        )

        summary = build_session_activity_summary(manifest.name, manifest.forge_root, since=since)
        line = render_summary_line(summary)
        if line:
            console.print(f"\n[dim]{line}[/dim]")
    except Exception:
        logger.debug("session activity summary failed", exc_info=True)


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
    print_tip("Reconnect to this conversation with:", commands=[resume_cmd], console=console)


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


def _print_branch_exists_tip(e: BranchExistsError) -> None:
    """Print contextual tip for a branch that already exists."""
    if e.worktree:
        print_error_with_tip(str(e), "Use --branch to specify a different branch name.", console=console)
    else:
        print_error_with_tip(
            str(e),
            f"Run 'git branch -d {e.branch}' to delete it, or use --branch to specify a different name.",
            console=console,
        )


def _resume_token_estimate_multiplier(
    *,
    parent_state: SessionState,
    effective_proxy_ref: str | None,
    direct_model_override: str | None = None,
) -> float:
    """Return a model-specific heuristic multiplier for fresh full-resume checks."""
    if effective_proxy_ref is not None:
        # v1 only applies tokenizer safety margins to direct Claude pins. Avoid
        # proxy config I/O in the resume hot path until proxy-routed 4.8 needs it.
        return 1.0

    from forge.runtime_config import get_default_direct_model

    direct_model = direct_model_override or (
        parent_state.intent.launch.direct_model if parent_state.intent.launch else None
    )
    direct_model = direct_model or get_default_direct_model()
    if not direct_model:
        return 1.0
    try:
        return token_estimate_multiplier_for_direct_model(direct_model)
    except ValueError:
        return 1.0


# --- Shared session creation + launch ---


class _ClaudeStartCliPresenter:
    """CLI-side renderer for ``start_claude_session`` (implements ClaudeStartPresenter).

    Each hook is the exact console output the pre-op ``launch_new_session`` produced at
    that point; the op owns the timing, this owns the content.
    """

    def __init__(self, *, session_name: str) -> None:
        self._session_name = session_name

    def on_created(self, event: ClaudeStartCreated) -> None:
        label = "incognito session" if event.incognito else "session"
        console.print(f"Created {label} [green]{event.session}[/green]")
        if event.proxy_display:
            console.print(f"  Proxy: {event.proxy_display} ({event.effective_template}) @ {event.runtime_base_url}")
        else:
            _print_routing_summary(template=event.effective_template, base_url=event.runtime_base_url)
        if event.worktree_path is not None:
            console.print(f"  Worktree: {display_path(event.worktree_path)}")
            console.print(f"  Branch:   {event.worktree_branch}")
        if event.supervise_target:
            console.print(f"  Supervisor: {event.supervise_target}")
        if event.incognito:
            console.print("[yellow]  (will auto-delete on exit)[/yellow]")

    def on_extensions(self, event: ClaudeStartExtensions) -> None:
        if event.is_worktree:
            if event.extension_root is not None:
                _sess()._auto_install_extensions(
                    install_root=event.extension_root,
                    parent_project_root=_resolve_extension_detection_root(Path.cwd()),
                    force_extensions=event.extensions_flag,
                )
        elif event.extensions_flag is True:
            print_tip("--extensions only applies with --worktree.", blank_before=False, console=console)
        console.print()

    def on_no_launch(self) -> None:
        console.print("[dim]Session created (--no-launch: Claude not started)[/dim]")

    def before_launch(self, forge_root: Path) -> None:
        _warn_before_claude_launch(forge_root)

    def on_sidecar_launch(self, event: ClaudeSidecarLaunch) -> None:
        _render_sidecar_launch(event)

    def on_launch_error(self, error: ForgeOpError) -> None:
        print_error(f"{error}", console=console)

    def on_incognito_cleanup_start(self) -> None:
        console.print(f"\n[dim]Cleaning up incognito session '{self._session_name}'...[/dim]")

    def on_incognito_cleanup_ok(self) -> None:
        console.print("[green]Cleanup complete.[/green]")

    def on_incognito_cleanup_warning(self, message: str) -> None:
        console.print(f"[yellow]Cleanup warning:[/yellow] {message}")


class _ClaudeResumeCliPresenter:
    """CLI-side renderer for ``resume_claude_session`` events."""

    def on_warning(self, warning: ClaudeResumeWarning) -> None:
        console.print(f"[yellow]Warning:[/yellow] {warning.message}")
        if warning.tip:
            print_tip(warning.tip, blank_before=False, console=console)

    def on_resume_prepared(self, event: ResumePrepared) -> None:
        if event.action in {
            ClaudeResumeAction.FORK_PARENT_CONVERSATION,
            ClaudeResumeAction.START_FRESH,
            ClaudeResumeAction.START_FRESH_WITH_PARENT_CONTEXT,
        }:
            console.print(f"Launching session [green]{event.session}[/green]")
        elif event.action is ClaudeResumeAction.RECONNECT:
            console.print(f"Reconnecting to session [green]{event.session}[/green]")
        elif event.action is ClaudeResumeAction.RELAUNCH_AS_CHILD:
            console.print(f"Relaunching [green]{event.parent_name}[/green] as [green]{event.session}[/green]")

        _print_routing_summary(template=event.effective_template, base_url=event.runtime_base_url)

        if event.action is ClaudeResumeAction.FORK_PARENT_CONVERSATION:
            console.print("  Action:   Fork parent Claude conversation")
        elif event.action is ClaudeResumeAction.START_FRESH_WITH_PARENT_CONTEXT:
            console.print("  Action:   Start fresh Claude session with parent context")
        elif event.action is ClaudeResumeAction.START_FRESH:
            console.print("  Action:   Start fresh Claude session")
        elif event.action is ClaudeResumeAction.RECONNECT:
            console.print("  Action:   Reconnect to existing Claude conversation")
            if event.resume_id is not None:
                console.print(f"  UUID:     {event.resume_id[:8]}...")
        elif event.action is ClaudeResumeAction.RELAUNCH_AS_CHILD:
            console.print("  Action:   Resume parent conversation in new session")
            if event.parent_name is not None:
                console.print(f"  Parent:   {event.parent_name}")

        if event.is_worktree and event.action is not ClaudeResumeAction.FRESH_DERIVED:
            console.print(f"  Worktree: {display_path(event.worktree_path)}")
            console.print(f"  Branch:   {event.worktree_branch}")
        if event.context_path is not None and event.action in {
            ClaudeResumeAction.FORK_PARENT_CONVERSATION,
            ClaudeResumeAction.START_FRESH,
            ClaudeResumeAction.START_FRESH_WITH_PARENT_CONTEXT,
        }:
            _print_context_path(str(event.context_path), event.worktree_path)
        for warning in event.prompt_warnings:
            console.print(f"[yellow]Warning:[/yellow] {warning}")
        console.print()

    def before_launch(self, forge_root: Path) -> None:
        _warn_before_claude_launch(forge_root)

    def on_sidecar_launch(self, event: ClaudeSidecarLaunch) -> None:
        _render_sidecar_launch(event)

    def on_launch_error(self, error: ForgeOpError) -> None:
        print_error(str(error), console=console)


def _resume_routing_for_op(routing: ResolvedRouting | None) -> ClaudeResumeRouting | None:
    if routing is None:
        return None

    return ClaudeResumeRouting(
        template=routing.template,
        base_url=routing.base_url,
        proxy_id=routing.proxy_id,
    )


def _resume_context_ref(
    *,
    state: SessionState,
    routing: ResolvedRouting | None,
    direct: bool,
) -> str | None:
    if routing:
        return routing.proxy_id or routing.template
    if direct:
        return None
    effective_template, _, effective_proxy_id = _get_effective_proxy_for_session(state)
    return effective_proxy_id or effective_template


def _get_resume_launch_preferences(
    state: SessionState,
    *,
    direct: bool,
) -> tuple[bool, tuple[str, ...], str | None]:
    if direct:
        return False, (), None
    return _get_launch_preferences(state)


def _resume_launch_preferences_for_op(
    use_sidecar: bool,
    mounts: tuple[str, ...],
    image: str | None,
) -> ClaudeLaunchPreferences:
    return ClaudeLaunchPreferences(use_sidecar=use_sidecar, mounts=mounts, image=image)


def _render_claude_resume_result(result: ClaudeResumeResult) -> int:
    for warning in result.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")
    if not result.did_run:
        return result.exit_code
    return _post_exit_render(
        result.manifest,
        store_exists=result.store_exists,
        exit_code=result.exit_code,
        since=result.operation_started_at,
    )


def _execute_resume_launch_plan(*, manager: SessionManager, plan: ResumeLaunchPlan) -> None:
    result = resume_claude_session(
        manager=manager,
        plan=plan,
        presenter=_ClaudeResumeCliPresenter(),
        invoke=_sess().invoke_claude,
        run_active=_sess().run_with_active_session,
    )
    sys.exit(_render_claude_resume_result(result))


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
    cascade_flag: bool = False,
    checker_model: str | None = None,
    checker_provider: str | None = None,
    checker_effort: str | None = None,
    supervisor_effort: str | None = None,
    supervisor_runtime: str | None = None,
    subprocess_proxy: str | None = None,
    direct_model: str | None = None,
    memory_flag: bool | None = None,
) -> int:
    """Create a new session and launch Claude.

    This is the shared implementation behind ``forge session start``,
    ``forge session incognito``, and ``forge claude start``.

    Returns the Claude exit code (0 on success).  Never calls ``sys.exit``
    so callers can wrap with cleanup (incognito) or other post-processing.
    """
    # --- flag validation ---
    if branch and not worktree:
        print_error("--branch requires --worktree", console=console)
        return 1
    if sidecar and host_proxy:
        print_error("--sidecar and --host-proxy are mutually exclusive", console=console)
        return 1
    if direct and (template or base_url):
        print_error("--no-proxy cannot be combined with proxy routing (--proxy)", console=console)
        return 1
    if direct and sidecar:
        print_error("--no-proxy cannot be combined with --sidecar", console=console)
        return 1
    if direct and host_proxy:
        print_error("--no-proxy cannot be combined with --host-proxy", console=console)
        return 1
    if direct_model and sidecar:
        print_error("--model cannot be combined with --sidecar", console=console)
        return 1
    if direct_model and host_proxy:
        print_error("--model cannot be combined with --host-proxy", console=console)
        return 1
    if incognito and no_launch:
        print_error("--incognito and --no-launch are mutually exclusive", console=console)
        return 1
    if no_launch and (system_prompt or system_prompt_file):
        print_error("--system-prompt is launch-only and lost with --no-launch", console=console)
        return 1

    launch_mode = LAUNCH_MODE_HOST if direct else _resolve_launch_mode(sidecar=sidecar, host_proxy=host_proxy)
    use_sidecar = launch_mode == LAUNCH_MODE_SIDECAR
    manager = _sess().SessionManager()

    normalized_direct_model: str | None = None
    direct_model_pin = None
    if direct_model:
        try:
            direct_model_pin = resolve_direct_model_pin(direct_model)
            normalized_direct_model = direct_model_pin.env_model
        except ValueError as e:
            print_error(f"{e}", console=console)
            return 1

    # Validate --model against proxy model_alternatives when in proxy mode
    if direct_model_pin and proxy_id and not direct:
        error = _validate_proxy_model_pin(proxy_id, direct_model_pin)
        if error:
            print_error(f"{error}", console=console)
            return 1

    # Resolve system prompt to absolute path BEFORE worktree creation
    # (worktree changes cwd so relative paths would break).
    prompt_path = resolve_and_validate_system_prompt(
        system_prompt=system_prompt,
        system_prompt_file=system_prompt_file,
        cwd=Path.cwd(),
    )
    prompt_file = str(prompt_path) if prompt_path is not None else None

    # Validate supervisor target and proxy BEFORE creating the session to avoid half-created state
    _supervisor_source_state = None
    if supervise_target:
        from forge.policy.semantic.supervisor import validate_supervisor_target

        try:
            _supervisor_source_state = validate_supervisor_target(supervise_target, forge_root=_cwd_forge_root())
        except ValueError as e:
            print_error(f"{e}", console=console)
            return 1
    if supervisor_proxy:
        from forge.policy.semantic.supervisor import ensure_supervisor_proxy

        try:
            _sup_proxy_id, _sup_started = ensure_supervisor_proxy(supervisor_proxy)
        except ValueError as e:
            print_error(f"{e}", console=console)
            return 1
        if _sup_started:
            console.print(f"[dim]Started proxy '{_sup_proxy_id}' from template '{supervisor_proxy}'.[/dim]")
        supervisor_proxy = _sup_proxy_id

    supervisor_wiring: SupervisorWiring | None = None
    if supervise_target and _supervisor_source_state is not None:
        supervisor_wiring = SupervisorWiring(
            target=supervise_target,
            source_state=_supervisor_source_state,
            supervisor_proxy=supervisor_proxy,
            supervisor_direct=supervisor_direct,
            cascade=cascade_flag,
            checker_model=checker_model,
            checker_provider=checker_provider,
            checker_effort=checker_effort,
            supervisor_effort=supervisor_effort,
            supervisor_runtime=supervisor_runtime,
        )

    try:
        result = start_claude_session(
            manager=manager,
            name=name,
            template=template,
            base_url=base_url,
            direct=direct,
            incognito=incognito,
            worktree=worktree,
            branch=branch,
            launch_mode=launch_mode,
            use_sidecar=use_sidecar,
            mounts=mounts,
            image=image,
            no_launch=no_launch,
            extensions=extensions,
            extra_args=extra_args,
            context_limit_override=context_limit_override,
            proxy_display=proxy_display,
            proxy_id=proxy_id,
            normalized_direct_model=normalized_direct_model,
            prompt_file=prompt_file,
            memory_flag=memory_flag,
            subprocess_proxy=subprocess_proxy,
            supervisor=supervisor_wiring,
            presenter=_ClaudeStartCliPresenter(session_name=name),
            invoke=_sess().invoke_claude,
            run_active=_sess().run_with_active_session,
        )
    except ClaudeStartError as e:
        print_error_with_tip(str(e), *e.tip_lines, commands=list(e.commands) or None, console=console)
        return 1
    except ForgeOpError as e:
        print_error(f"{e}", console=console)
        return 1

    if result.did_run:
        for warning in result.warnings:
            console.print(f"[yellow]Warning:[/yellow] {warning}")
        return _post_exit_render(
            result.manifest,
            store_exists=result.store_exists,
            exit_code=result.exit_code,
            since=result.operation_started_at,
        )
    return result.exit_code


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
    "--no-proxy",
    "direct",
    is_flag=True,
    help="Bypass the proxy and talk to Anthropic directly",
)
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
@click.option(
    "--model",
    "direct_model",
    type=str,
    default=None,
    help="Pin the Claude model for direct sessions (for example: claude-opus-4-8 or claude-sonnet-4-6[1m])",
)
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
@click.option(
    "--supervisor-proxy",
    type=str,
    default=None,
    help="Proxy for supervisor routing (requires --supervise)",
)
@click.option(
    "--no-supervisor-proxy",
    "supervisor_direct",
    is_flag=True,
    default=False,
    help="Force supervisor to use direct Anthropic routing (requires --supervise)",
)
@click.option(
    "--cascade",
    "cascade_flag",
    is_flag=True,
    default=False,
    help="Enable the tier-1 plan check before the frontier supervisor (requires --supervise)",
)
@click.option(
    "--checker-model",
    "checker_model",
    default=None,
    help="Tier-1 checker model (prefixed id; requires --supervise)",
)
@click.option(
    "--checker-provider",
    "checker_provider",
    type=click.Choice(list(CHECKER_PROVIDER_CHOICES)),
    default=None,
    help="Tier-1 checker provider (requires --supervise)",
)
@click.option(
    "--checker-effort",
    "checker_effort",
    type=click.Choice(list(REASONING_EFFORT_LEVELS)),
    default=None,
    help="Tier-1 checker reasoning effort (none/low/medium/high/xhigh; requires --supervise)",
)
@click.option(
    "--supervisor-effort",
    "supervisor_effort",
    type=click.Choice(list(CLAUDE_EFFORT_LEVELS)),
    default=None,
    help="Frontier supervisor effort (claude --effort: low/medium/high/xhigh/max; requires --supervise)",
)
@click.option(
    "--supervisor-runtime",
    "supervisor_runtime",
    type=click.Choice(list(supervisor_lane_runtimes())),
    default=None,
    help="Supervisor lane runtime (claude_code/codex; requires --supervise)",
)
@click.option(
    "--subprocess-proxy",
    "subprocess_proxy",
    type=str,
    default=None,
    help="Route subprocesses (supervisor, panel, memory-writer) through this proxy while main session is direct",
)
@click.option(
    "--memory",
    "memory_flag",
    type=click.Choice(["on", "off"]),
    default=None,
    help="Enable/disable memory auto-update for this session (default: off).",
)
@codex_start_options
def start(
    name: str | None,
    proxy_name: str | None,
    direct: bool,
    incognito: bool,
    system_prompt: str | None,
    system_prompt_file: str | None,
    worktree: bool,
    branch: str | None,
    direct_model: str | None,
    sidecar: bool,
    host_proxy: bool,
    mounts: tuple[str, ...],
    image: str | None,
    no_launch: bool,
    extensions: bool | None,
    supervise_target: str | None,
    supervisor_proxy: str | None,
    supervisor_direct: bool,
    cascade_flag: bool,
    checker_model: str | None,
    checker_provider: str | None,
    checker_effort: str | None,
    supervisor_effort: str | None,
    supervisor_runtime: str | None,
    subprocess_proxy: str | None,
    memory_flag: str | None,
    runtime: str,
    resume_from: str | None,
    task: str | None,
    transfer_strategy: str | None,
    depth: int | None,
    sandbox: str | None,
    context_delivery: str | None,
) -> None:
    """Create and start a new session.

    With --worktree/-w, creates an isolated git worktree for the session.
    This enables parallel work without manifest conflicts.

    With --sidecar, runs Claude Code and proxy inside a Docker container
    with lifecycle coupling. The project directory is mounted at /workspace.

    With --subprocess-proxy, the main session talks to Anthropic directly
    (free subscription) while panels, supervisors, and memory writers route
    through the named proxy for cost tracking and multi-model access.

    For resuming existing sessions, use ``forge session resume``.

    \b
    Examples:
        forge session start                                                    # Auto-named, no proxy
        forge session start my-feature                                         # Named session, no proxy
        forge session start my-feature --proxy openrouter-gemini               # With proxy routing
        forge session start my-feature --subprocess-proxy openrouter-anthropic # Direct + proxied subprocesses
        forge session start my-feature --worktree                              # Isolated worktree
        forge session start my-feature --supervise planner                     # With plan supervision
        forge session start impl --runtime codex --resume-from planner --task "Build it"
    """
    if runtime == "codex":
        sys.exit(run_codex_start(click.get_current_context()))

    # Codex-only flags are meaningless on the Claude path: reject, don't ignore.
    codex_rc = reject_codex_flags_for_claude(click.get_current_context().params)
    if codex_rc is not None:
        sys.exit(codex_rc)

    if direct and proxy_name:
        print_error("--no-proxy and --proxy are mutually exclusive", console=console)
        sys.exit(1)
    if supervisor_proxy and supervisor_direct:
        print_error("--supervisor-proxy and --no-supervisor-proxy are mutually exclusive", console=console)
        sys.exit(1)
    if (supervisor_proxy or supervisor_direct) and not supervise_target:
        print_error("--supervisor-proxy/--no-supervisor-proxy require --supervise", console=console)
        sys.exit(1)
    if (
        cascade_flag or checker_model or checker_provider or checker_effort or supervisor_effort or supervisor_runtime
    ) and not supervise_target:
        print_error(
            "--cascade/--checker-*/--supervisor-effort/--supervisor-runtime require --supervise", console=console
        )
        sys.exit(1)
    try:
        validate_checker_model(checker_model)
    except ValueError as e:
        print_error(f"{e}", console=console)
        sys.exit(1)
    if subprocess_proxy and proxy_name:
        print_error(
            "--subprocess-proxy is for direct-mode sessions; use --proxy alone for full proxy routing",
            console=console,
        )
        sys.exit(1)

    # Default to direct mode when neither --proxy nor --no-proxy is given,
    # unless --sidecar or --host-proxy is specified (both imply proxy mode).
    if not proxy_name and not direct and not sidecar and not host_proxy:
        direct = True

    routing: ResolvedRouting | None = None
    if proxy_name:
        routing = _sess()._resolve_routing_from_cli(proxy_name=proxy_name, direct=False)

    # CWD validation: must be at repo root; --worktree requires main repo
    from forge.cli.guards import require_main_repo_root, require_repo_root

    if worktree:
        require_main_repo_root()
    else:
        require_repo_root()

    if name is None:
        _fr = _cwd_forge_root()
        existing = {n for n, _ in _sess().SessionManager().list_sessions(forge_root_filter=_fr)}
        name = _sess().generate_unique_name(existing)
    assert name is not None  # generated above when None

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
            cascade_flag=cascade_flag,
            checker_model=checker_model,
            checker_provider=checker_provider,
            checker_effort=checker_effort,
            supervisor_effort=supervisor_effort,
            supervisor_runtime=supervisor_runtime,
            subprocess_proxy=subprocess_proxy,
            direct_model=direct_model,
            memory_flag={"on": True, "off": False}.get(memory_flag) if memory_flag else None,
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
    "--no-proxy",
    "direct",
    is_flag=True,
    default=False,
    help="Bypass the proxy and talk to Anthropic directly",
)
@click.option(
    "--model",
    "direct_model",
    type=str,
    default=None,
    help="Pin the Claude model for this and future resumes (for example: claude-opus-4-6 or claude-opus-4-8)",
)
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
    type=click.Choice(["minimal", "structured", "full", "ai-curated", "rewind"]),
    default="structured",
    help="Context assembly strategy (only with --fresh, default: structured)",
)
@click.option(
    "--drop-last",
    type=int,
    default=None,
    help="Required with --strategy rewind: number of tail conversational turns to drop.",
)
@click.option(
    "--depth",
    "-d",
    type=int,
    default=1,
    help="Lineage traversal depth (only with --fresh, 1=parent only)",
)
# Value asymmetry with `session fork`'s --resume-mode ({transfer, native-relocate}): resume
# stays in the same directory, so the full conversation is reachable via Claude's --fork-session
# in place -- no JSONL relocation needed -- hence `native`, not `native-relocate`.
@click.option(
    "--resume-mode",
    "resume_mode",
    callback=_validate_resume_mode,
    default=None,
    help="Context transfer: native (full conversation via --fork-session) or transfer (assembled summary). Default: transfer.",
)
@click.option(
    "--review",
    is_flag=True,
    default=False,
    help="Open the generated child context in $EDITOR before launch (only with --fresh transfer mode).",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Bypass active-session guard (launches as new child)",
)
@click.option(
    "--memory",
    "memory_flag",
    type=click.Choice(["on", "off"]),
    default=None,
    help="Override child memory activation (default: inherit parent).",
)
@codex_resume_options
@click.pass_context
def resume(
    ctx: click.Context,
    name: str | None,
    proxy_name: str | None,
    direct: bool,
    direct_model: str | None,
    fresh: bool,
    child_name: str | None,
    strategy: str,
    drop_last: int | None,
    depth: int,
    resume_mode: str | None,
    review: bool,
    force: bool,
    memory_flag: str | None,
    task: str | None,
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
    if direct and proxy_name:
        print_error("--no-proxy and --proxy are mutually exclusive", console=console)
        sys.exit(1)

    _drop_last_explicit = ctx.get_parameter_source("drop_last") == click.core.ParameterSource.COMMANDLINE
    rewind_requested = strategy == ResumeStrategy.REWIND.value
    if _drop_last_explicit and not rewind_requested:
        print_error("--drop-last requires --strategy rewind", console=console)
        sys.exit(1)
    if rewind_requested:
        if not fresh:
            print_error("--strategy rewind requires --fresh", console=console)
            sys.exit(1)
        if drop_last is None:
            print_error("--strategy rewind requires --drop-last N", console=console)
            sys.exit(1)
        if drop_last < 0:
            print_error("--drop-last must be non-negative", console=console)
            sys.exit(1)
        if resume_mode == "transfer":
            print_error("--strategy rewind cannot be combined with --resume-mode transfer", console=console)
            sys.exit(1)
        if review:
            print_error(
                "--review is only supported for transfer-mode fresh resumes, not --strategy rewind", console=console
            )
            sys.exit(1)

    normalized_direct_model: str | None = None
    direct_model_pin: DirectModelPin | None = None
    if direct_model:
        try:
            direct_model_pin = resolve_direct_model_pin(direct_model)
            normalized_direct_model = direct_model_pin.env_model
        except ValueError as e:
            print_error(f"{e}", console=console)
            sys.exit(1)

    if resume_mode and not fresh:
        print_error("--resume-mode requires --fresh", console=console)
        sys.exit(1)

    if not fresh and child_name:
        print_error("--child-name requires --fresh", console=console)
        sys.exit(1)

    if memory_flag and not fresh:
        print_error(
            "--memory requires --fresh (creates a new child session). Add --fresh or omit --memory.",
            console=console,
        )
        sys.exit(1)

    if review and not fresh:
        print_error("--review requires --fresh", console=console)
        sys.exit(1)

    if review and resume_mode == "native":
        print_error(
            "--review is only meaningful in transfer mode; "
            "native resume carries the parent conversation verbatim with no editable artifact.",
            console=console,
        )
        sys.exit(1)

    routing: ResolvedRouting | None = None
    if proxy_name:
        routing = _sess()._resolve_routing_from_cli(proxy_name=proxy_name, direct=False)

    manager = _sess().SessionManager()

    if name is None:
        sessions = manager.list_sessions(include_incognito=True)
        if not sessions:
            console.print("[dim]No sessions to resume.[/dim]")
            print_tip("Run 'forge session start <name>'.", console=console)
            return

        name = _pick_session(sessions, manager, prompt="Select session to resume")
        if name is None:
            console.print("[dim]Cancelled[/dim]")
            sys.exit(0)

    _fr = _cwd_forge_root()
    # Cross-project resolution happens BEFORE the runtime is knowable (the runtime
    # lives in the manifest), so a scoped miss always tries the unscoped lookup;
    # whether a cross-project hit is usable is decided per-runtime below.
    cross_project = False
    try:
        manifest = manager.get_session(name, forge_root=_fr)
    except SessionNotFoundError:
        if _fr is None:
            # The scoped lookup WAS the global lookup; nothing else to try.
            if not _hint_cross_project_session(name, _fr):
                print_error_with_tip(
                    f"session '{name}' not found",
                    f"Run 'forge session start {name}' to create it.",
                    console=console,
                )
            sys.exit(1)
        try:
            manifest = manager.get_session(name, forge_root=None)
            cross_project = True
        except SessionNotFoundError:
            if not _hint_cross_project_session(name, _fr):
                print_error_with_tip(
                    f"session '{name}' not found",
                    f"Run 'forge session start {name}' to create it.",
                    console=console,
                )
            sys.exit(1)
        except ForgeSessionError as e:
            handle_session_error(e)
            return
    except ForgeSessionError as e:
        handle_session_error(e)
        return

    # Runtime dispatch BEFORE any Claude predicate: a Codex session has no Claude
    # conversation to reattach, so the Claude resume machinery below never applies.
    # Codex resume is cross-CWD by design (the turn runs in the recorded worktree).
    manifest_runtime = manifest.intent.launch.runtime if manifest.intent.launch else "claude_code"
    if manifest_runtime == "codex":
        sys.exit(run_codex_resume(ctx, name, task, manifest))

    if task is not None:
        print_error("--task is only supported for Codex sessions", console=console)
        sys.exit(1)

    if cross_project:
        # Claude resume is genuinely project-scoped: keep the pre-lookup refusal.
        if not _hint_cross_project_session(name, _fr):
            print_error_with_tip(
                f"session '{name}' not found",
                f"Run 'forge session start {name}' to create it.",
                console=console,
            )
        sys.exit(1)

    _, validation_base_url, validation_proxy_id = _get_effective_proxy_for_session(manifest)
    if routing:
        validation_base_url = routing.base_url
        validation_proxy_id = routing.proxy_id
    elif direct:
        validation_base_url = None
        validation_proxy_id = None
    if direct_model_pin:
        error = _validate_direct_model_pin_for_routing(
            pin=direct_model_pin,
            proxy_id=validation_proxy_id,
            base_url=validation_base_url,
            surface="resume",
        )
        if error:
            print_error(f"{error}", console=console)
            sys.exit(1)

    if fresh:
        effective_resume_mode = ResumeStrategy.REWIND.value if rewind_requested else resume_mode or "transfer"

        # Warn about transfer-only flags with native mode
        if effective_resume_mode in {"native", ResumeStrategy.REWIND.value}:
            ctx = click.get_current_context()
            if (
                effective_resume_mode == "native"
                and ctx.get_parameter_source("strategy") == click.core.ParameterSource.COMMANDLINE
            ):
                print_tip("--strategy is ignored with --resume-mode native.", blank_before=False, console=console)
            if ctx.get_parameter_source("depth") == click.core.ParameterSource.COMMANDLINE:
                depth_surface = (
                    "--strategy rewind"
                    if effective_resume_mode == ResumeStrategy.REWIND.value
                    else "--resume-mode native"
                )
                print_tip(f"--depth is ignored with {depth_surface}.", blank_before=False, console=console)

        if effective_resume_mode == ResumeStrategy.REWIND.value:
            if not _is_resumable_session(manifest):
                print_error(
                    "--strategy rewind requires a parent with a confirmed Claude session "
                    "(hook-confirmed or transcript-backed).",
                    console=console,
                )
                sys.exit(1)
            _parent_launch = manifest.intent.launch
            _parent_is_sidecar = manifest.confirmed.is_sandboxed or (
                _parent_launch is not None and _parent_launch.mode == LAUNCH_MODE_SIDECAR
            )
            if not direct and _parent_is_sidecar:
                print_error_with_tip(
                    "--strategy rewind is not supported with sidecar mode.",
                    "Rewind writes to the host ~/.claude store; run in host mode (e.g. --no-proxy) "
                    "or use transfer mode.",
                    console=console,
                )
                sys.exit(1)
            if drop_last == 0:
                console.print("[dim]--drop-last 0 uses plain native resume; no rewind context generated.[/dim]")
                _resume_fresh_native(
                    manager=manager,
                    parent=name,
                    parent_state=manifest,
                    child_name=child_name,
                    routing=routing,
                    direct=direct,
                    direct_model_override=normalized_direct_model,
                    memory_flag={"on": True, "off": False}.get(memory_flag) if memory_flag else None,
                )
                return
            assert drop_last is not None
            _resume_fresh_rewind(
                manager=manager,
                parent=name,
                parent_state=manifest,
                child_name=child_name,
                drop_last=drop_last,
                routing=routing,
                direct=direct,
                direct_model_override=normalized_direct_model,
                memory_flag={"on": True, "off": False}.get(memory_flag) if memory_flag else None,
            )
        elif effective_resume_mode == "native":
            # Native requires a hook-confirmed session (UUID + confirmed_by/transcript evidence).
            # A pre-seeded UUID alone is not enough — there must be a real conversation to resume.
            if not _is_resumable_session(manifest):
                print_error(
                    "--resume-mode native requires a parent with a confirmed "
                    "Claude session (hook-confirmed or transcript-backed). "
                    "Use --resume-mode transfer for transcript-artifact-based resume.",
                    console=console,
                )
                sys.exit(1)
            _resume_fresh_native(
                manager=manager,
                parent=name,
                parent_state=manifest,
                child_name=child_name,
                routing=routing,
                direct=direct,
                direct_model_override=normalized_direct_model,
                memory_flag={"on": True, "off": False}.get(memory_flag) if memory_flag else None,
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
                review=review,
                direct_model_override=normalized_direct_model,
                memory_flag={"on": True, "off": False}.get(memory_flag) if memory_flag else None,
            )
    elif not _has_confirmed_claude_session(manifest):
        _launch_in_place(
            manager=manager,
            name=name,
            manifest=manifest,
            routing=routing,
            direct=direct,
            direct_model_override=normalized_direct_model,
        )
    elif _is_resumable_session(manifest):
        active_entry = _get_active_session_entry(name, forge_root=manifest.forge_root)
        if active_entry is not None and not force:
            print_error(
                f"Cannot reconnect: session [bold]{name}[/bold] appears to still be active.",
                console=console,
            )
            console.print(f"  Launch mode: {active_entry.launch_mode}")
            if active_entry.launcher_pid is not None:
                console.print(f"  Launcher PID: {active_entry.launcher_pid}")
            if active_entry.container_name:
                console.print(f"  Container: {active_entry.container_name}")
            print_tip(
                "Reconnect is only available after the previous launch has exited. "
                "Return to that launch if it is still running, or stop it cleanly and retry.",
                blank_before=False,
                console=console,
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
                direct_model_override=normalized_direct_model,
            )
        else:
            _reconnect_in_place(
                manager=manager,
                name=name,
                manifest=manifest,
                routing=routing,
                direct=direct,
                direct_model_override=normalized_direct_model,
            )
    else:
        _launch_as_child(
            manager=manager,
            parent_name=name,
            parent=manifest,
            routing=routing,
            direct=direct,
            direct_model_override=normalized_direct_model,
        )


def _launch_in_place(
    *,
    manager: SessionManager,
    name: str,
    manifest: SessionState,
    routing: ResolvedRouting | None = None,
    direct: bool = False,
    direct_model_override: str | None = None,
) -> None:
    """Launch a never-used session in-place (satisfies 1:1)."""
    manager.switch_session(name, forge_root=manifest.forge_root)

    worktree_path = Path(manifest.worktree.path) if manifest.worktree else Path.cwd()
    context_limit = _resolve_context_limit(_resume_context_ref(state=manifest, routing=routing, direct=direct))
    use_sidecar, mounts, image = _get_resume_launch_preferences(manifest, direct=direct)
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
        launch_action = ClaudeResumeAction.FORK_PARENT_CONVERSATION
    else:
        session_id = str(_uuid.uuid4())
        persisted_context = _resolve_derivation_context_file(manifest)
        if persisted_context is not None:
            prompt_files.append(persisted_context)
            notes_overlay = notes_for_snapshot(persisted_context)
            if notes_has_user_content(notes_overlay):
                prompt_files.append(notes_overlay)
            launch_action = ClaudeResumeAction.START_FRESH_WITH_PARENT_CONTEXT
        else:
            fork_context, prompt_warnings = _sess()._generate_parent_transfer_context(
                manager=manager, manifest=manifest
            )
            if fork_context is not None:
                prompt_files.append(fork_context)
                launch_action = ClaudeResumeAction.START_FRESH_WITH_PARENT_CONTEXT
            else:
                launch_action = ClaudeResumeAction.START_FRESH

    prompt_file = _combine_prompt_files(
        worktree_path=worktree_path,
        session_name=manifest.name,
        prompt_files=prompt_files,
    )

    _execute_resume_launch_plan(
        manager=manager,
        plan=ResumeLaunchPlan(
            manifest=manifest,
            routing=_resume_routing_for_op(routing),
            direct=direct,
            resume_id=resume_id,
            session_id=session_id,
            fork_session=fork_session,
            prompt_file=Path(prompt_file) if prompt_file else None,
            action=launch_action,
            context_limit=context_limit,
            launch_preferences=_resume_launch_preferences_for_op(use_sidecar, mounts, image),
            direct_model_override=direct_model_override,
            prompt_warnings=tuple(prompt_warnings),
        ),
    )


def _reconnect_in_place(
    *,
    manager: SessionManager,
    name: str,
    manifest: SessionState,
    routing: ResolvedRouting | None = None,
    direct: bool = False,
    direct_model_override: str | None = None,
) -> None:
    """Reconnect to the same Claude conversation without creating a child.

    Advanced escape hatch for resuming in-place after the previous launch has
    fully ended. Relaxes the 1:1 invariant (new process invocation on the same
    Forge session) but is gated: a resumable conversation must exist.

    The caller is responsible for the active-session check (see resume()
    dispatch) -- this function assumes the session is not active.
    """
    if not _is_resumable_session(manifest):
        print_error_with_tip(
            "Cannot reconnect: no resumable Claude conversation was found.",
            f"Run 'forge session resume {name}' to reattach, or use --fresh to start a new conversation.",
            console=console,
        )
        sys.exit(1)

    claude_session_id = manifest.confirmed.claude_session_id
    assert claude_session_id is not None  # _is_resumable_session guarantees this

    manager.switch_session(name, forge_root=manifest.forge_root)

    context_limit = _resolve_context_limit(_resume_context_ref(state=manifest, routing=routing, direct=direct))
    use_sidecar, mounts, image = _get_resume_launch_preferences(manifest, direct=direct)

    _execute_resume_launch_plan(
        manager=manager,
        plan=ResumeLaunchPlan(
            manifest=manifest,
            routing=_resume_routing_for_op(routing),
            direct=direct,
            resume_id=claude_session_id,
            session_id=None,
            fork_session=False,
            prompt_file=None,
            action=ClaudeResumeAction.RECONNECT,
            context_limit=context_limit,
            launch_preferences=_resume_launch_preferences_for_op(use_sidecar, mounts, image),
            direct_model_override=direct_model_override,
        ),
    )


def _launch_as_child(
    *,
    manager: SessionManager,
    parent_name: str,
    parent: SessionState,
    routing: ResolvedRouting | None = None,
    direct: bool = False,
    direct_model_override: str | None = None,
) -> None:
    """Create a child session and resume the parent's Claude conversation.

    Routes through the resume op so sidecar sessions relaunch through the
    sidecar path with stored mounts/image settings.
    """
    try:
        parent, child = manager.relaunch_session(parent_name, forge_root=parent.forge_root)
    except ForgeSessionError as e:
        handle_session_error(e)
        return

    context_limit = _resolve_context_limit(_resume_context_ref(state=child, routing=routing, direct=direct))
    use_sidecar, mounts, image = _get_resume_launch_preferences(child, direct=direct)

    # Child is a same-dir fork: use --resume --fork-session with parent's UUID
    _execute_resume_launch_plan(
        manager=manager,
        plan=ResumeLaunchPlan(
            manifest=child,
            routing=_resume_routing_for_op(routing),
            direct=direct,
            resume_id=parent.confirmed.claude_session_id,
            session_id=None,
            fork_session=True,
            prompt_file=None,
            action=ClaudeResumeAction.RELAUNCH_AS_CHILD,
            context_limit=context_limit,
            launch_preferences=_resume_launch_preferences_for_op(use_sidecar, mounts, image),
            direct_model_override=direct_model_override,
            parent_name=parent_name,
        ),
    )


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
    from rich.table import Table

    from forge.cli.session import _format_relative_time

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
    review: bool = False,
    direct_model_override: str | None = None,
    memory_flag: bool | None = None,
) -> None:
    """Create a fresh child session with context assembled from parent.

    This is the --fresh path of ``forge session resume``. Creates a new
    derived session with a context summary, then launches Claude fresh.
    When ``review`` is True, opens the per-child transfer file in $EDITOR
    before launching (user can curate the context).
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
    token_multiplier = _resume_token_estimate_multiplier(
        parent_state=parent_state,
        effective_proxy_ref=effective_proxy_ref,
        direct_model_override=direct_model_override,
    )

    try:
        child_manifest, transfer_result = manager.resume_session(
            parent,
            child_name=child_name,
            strategy=strategy,
            depth=depth,
            context_limit=context_limit,
            token_estimate_multiplier=token_multiplier,
            forge_root=parent_state.forge_root,
            memory_flag=memory_flag,
        )
    except ForgeSessionError as e:
        handle_session_error(e)
        return

    console.print(f"[dim]Context assembled: {transfer_result.context_file_rel}[/dim]")
    if transfer_result.warnings:
        for warning in transfer_result.warnings:
            console.print(f"[yellow]Warning:[/yellow] {warning}")
    console.print()

    if review and transfer_result.context_file is not None:
        # Unify on the overlay: --review edits the user-notes overlay, never the
        # pure AI snapshot. Notes are merged into the launch context below.
        notes_overlay = ensure_notes_overlay(transfer_result.context_file)
        console.print(
            f"[dim]Opening notes overlay {display_path(notes_overlay)} in $EDITOR "
            f"(AI snapshot at {transfer_result.context_file_rel} stays read-only)...[/dim]"
        )
        open_in_editor(
            notes_overlay,
            console=console,
            abort_tip=(
                f"Your notes at {display_path(notes_overlay)} are preserved. "
                f"Run 'forge session resume {child_manifest.name}' to launch with the current content."
            ),
        )

    console.print(f"Created derived session [green]{child_manifest.name}[/green] from [cyan]{parent}[/cyan]")
    console.print(f"[dim]Strategy: {strategy}, Depth: {depth}[/dim]")
    console.print()

    # Launch Claude as a NEW session (not resuming parent's conversation)
    child_worktree = Path(child_manifest.worktree.path) if child_manifest.worktree else Path.cwd()
    prompt_files: list[Path] = []
    configured_prompt = _resolve_manifest_prompt_file(child_manifest)
    if configured_prompt is not None:
        prompt_files.append(configured_prompt)
    if transfer_result.context_file is not None:
        snapshot = transfer_result.context_file.resolve()
        prompt_files.append(snapshot)
        # Merge the user-notes overlay (e.g. just authored via --review) after
        # the pure AI snapshot. _combine_prompt_files concatenates both into one
        # appended system-prompt file; the snapshot itself is never edited.
        notes_overlay = notes_for_snapshot(snapshot)
        if notes_has_user_content(notes_overlay):
            prompt_files.append(notes_overlay)
    prompt_file = _combine_prompt_files(
        worktree_path=child_worktree,
        session_name=child_manifest.name,
        prompt_files=prompt_files,
    )

    use_sidecar, mounts, image = _get_resume_launch_preferences(child_manifest, direct=direct)

    _execute_resume_launch_plan(
        manager=manager,
        plan=ResumeLaunchPlan(
            manifest=child_manifest,
            routing=_resume_routing_for_op(routing),
            direct=direct,
            resume_id=None,
            session_id=str(_uuid.uuid4()),
            fork_session=False,
            prompt_file=Path(prompt_file) if prompt_file else None,
            action=ClaudeResumeAction.FRESH_DERIVED,
            context_limit=context_limit,
            launch_preferences=_resume_launch_preferences_for_op(use_sidecar, mounts, image),
            direct_model_override=direct_model_override,
            parent_name=parent,
        ),
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
    "--no-proxy",
    "direct",
    is_flag=True,
    help="Bypass the proxy and talk to Anthropic directly",
)
@click.option(
    "--model",
    "direct_model",
    type=str,
    default=None,
    help="Pin the Claude model for this incognito session (for example: claude-opus-4-6 or claude-opus-4-8)",
)
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
    direct_model: str | None,
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
        forge session incognito --proxy openrouter-gemini # With proxy
        forge session incognito my-test                  # Custom name
    """
    if direct and proxy_name:
        print_error("--no-proxy and --proxy are mutually exclusive", console=console)
        sys.exit(1)

    # Default to direct mode when neither --proxy nor --no-proxy is given,
    # unless --sidecar or --host-proxy is specified (both imply proxy mode).
    if not proxy_name and not direct and not sidecar and not host_proxy:
        direct = True

    routing: ResolvedRouting | None = None
    if proxy_name:
        routing = _sess()._resolve_routing_from_cli(proxy_name=proxy_name, direct=False)

    from forge.cli.guards import require_repo_root

    require_repo_root()

    if name is None:
        _fr = _cwd_forge_root()
        existing = {n for n, _ in _sess().SessionManager().list_sessions(forge_root_filter=_fr)}
        name = _sess().generate_unique_name(existing)
    assert name is not None  # generated above when None

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
            direct_model=direct_model,
        )
    )

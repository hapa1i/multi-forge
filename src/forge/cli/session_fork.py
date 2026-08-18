"""Session fork command."""

from __future__ import annotations

import sys
import uuid as _uuid
from pathlib import Path
from typing import cast

import click

from forge.cli.output import err_console, print_error, print_error_with_tip, print_tip
from forge.cli.session import (  # noqa: E402
    ResolvedRouting,
    _apply_routing_override_to_state,
    _auto_install_extensions,
    _generate_parent_transfer_context,
    _get_effective_proxy_for_session,
    _get_launch_preferences,
    _hint_cross_project_session,
    _persist_routing_override,
    _print_routing_summary,
    _resolve_routing_from_cli,
    console,
    handle_session_error,
    logger,
)
from forge.cli.session_lifecycle import (  # noqa: E402
    _persist_fork_transfer_derivation,
    _post_exit_render,
    _print_branch_exists_tip,
    _render_sidecar_launch,
    _resolve_manifest_prompt_file,
    _resume_tip_command,
    _rollback_created_session,
    _warn_before_claude_launch,
)
from forge.cli.session_lifecycle import session as _session_untyped  # noqa: E402
from forge.cli.session_model_pin import (  # noqa: E402
    _apply_and_persist_direct_model_override,
)
from forge.cli.session_rewind import _prepare_rewind_launch_artifacts  # noqa: E402
from forge.cli.session_supervisor_options import supervisor_options
from forge.core.ops.claude_session import (
    ClaudeForkResult,
    ClaudeLaunchPreferences,
    ClaudeSidecarLaunch,
    ForkLaunchPlan,
    SupervisorWiring,
    _apply_supervisor_wiring,
    fork_claude_session,
    resolve_claude_session_state_context,
)
from forge.core.ops.context import _cwd_forge_root
from forge.core.ops.session import ForgeOpError
from forge.core.ops.session_fork_preflight import (
    ForkPreflightError,
    ForkPreflightNotice,
    ForkPreflightRequest,
    plan_session_fork,
    validate_session_fork_routing,
)
from forge.core.paths import display_path
from forge.install.project_compat import (
    ProjectCompatibilityError,
)
from forge.session import (
    ForgeSessionError,
    SessionManager,
    SessionState,
)
from forge.session.context_limit import _resolve_context_limit
from forge.session.exceptions import (
    BranchExistsError,
    BranchInUseError,
    BranchNotMergedError,
    CannotForkIncognitoError,
    InvalidBranchNameError,
    SessionNotFoundError,
    WorktreePathExistsError,
)
from forge.session.launch import (
    _combine_prompt_files,
    _get_runtime_base_url,
    _resolve_worktree_extension_root,
)

session = cast(click.Group, _session_untyped)  # type: ignore[has-type]  # circular re-export

__all__ = ["fork"]


class _ClaudeForkCliPresenter:
    """CLI-side renderer for ``fork_claude_session`` events."""

    def __init__(self, *, session_name: str) -> None:
        self._session_name = session_name

    def before_launch(self, forge_root: Path) -> None:
        _warn_before_claude_launch(forge_root)

    def on_sidecar_launch(self, event: ClaudeSidecarLaunch) -> None:
        _render_sidecar_launch(event)

    def on_launch_error(self, error: ForgeOpError) -> None:
        print_error(str(error))

    def on_incognito_cleanup_start(self) -> None:
        console.print(f"\n[dim]Cleaning up incognito fork '{self._session_name}'...[/dim]")

    def on_incognito_cleanup_ok(self) -> None:
        console.print("[green]Cleanup complete.[/green]")

    def on_incognito_cleanup_warning(self, message: str) -> None:
        console.print(f"[yellow]Cleanup warning:[/yellow] {message}")


def _render_claude_fork_result(result: ClaudeForkResult) -> int:
    for warning in result.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")
    if not result.did_run or not result.render_post_exit:
        return result.exit_code
    return _post_exit_render(
        result.manifest,
        store_exists=result.store_exists,
        exit_code=result.exit_code,
        since=result.operation_started_at,
    )


def _render_fork_preflight_error(error: ForkPreflightError) -> None:
    """Render one typed command-core refusal on the established CLI surface."""
    if error.tip is not None:
        print_error_with_tip(str(error), error.tip, commands=error.commands or None)
    else:
        print_error(str(error))
    if error.detail is not None:
        err_console.print(error.detail)


def _render_fork_preflight_notice(notice: ForkPreflightNotice) -> None:
    """Render a non-fatal preflight event after planning succeeds."""
    if notice.level == "warning":
        console.print(f"[yellow]Warning:[/yellow] {notice.message}")
    elif notice.level == "tip":
        print_tip(notice.message, blank_before=False, console=console)
    else:
        console.print(f"[dim]{notice.message}[/dim]")


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
    help="Pin the Claude model for this fork and future resumes (for example: claude-opus-5 or claude-opus-4-8)",
)
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
    type=click.Choice(["minimal", "structured", "full", "ai-curated", "rewind"]),
    default="structured",
    help="Context assembly strategy for transfer forks, or rewind for a native-relocate fork with dropped tail turns. "
    "On a same-directory fork, setting a transfer strategy switches the fork to transfer mode. Default: structured",
)
@click.option(
    "--drop-last",
    type=int,
    default=None,
    help="Required with --strategy rewind: number of tail conversational turns to drop.",
)
@click.option(
    "--inline-plan",
    is_flag=True,
    default=False,
    help="Embed approved plan text in the transfer (any transfer fork; switches a same-directory fork to "
    "transfer mode); default is a parent plan-path reference",
)
@click.option(
    "--into",
    "into_path",
    type=click.Path(exists=True),
    default=None,
    help="Fork into an existing non-main worktree directory",
)
# Value asymmetry with `session resume`'s --resume-mode ({native, transfer}): a fork can target a
# different worktree/--into directory, so byte-faithful Claude resume must relocate the parent JSONL
# into the child's dir -- hence `native-relocate`, not bare `native`.
@click.option(
    "--resume-mode",
    "resume_mode",
    type=click.Choice(["transfer", "native-relocate"]),
    default=None,
    help="Resume mode: transfer (assembled context; legal for same-directory forks too) or "
    "native-relocate (byte-faithful Claude resume; relocates the parent JSONL; worktree/--into only).",
)
@click.option(
    "--supervise",
    "supervise_target",
    is_flag=True,
    default=False,
    help="Set parent as plan supervisor for the fork (enables policy enforcement)",
)
@supervisor_options
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Replace existing branch/worktree and skip budget preflight",
)
@click.option(
    "--memory",
    "memory_flag",
    type=click.Choice(["on", "off"]),
    default=None,
    help="Override child memory activation (default: inherit parent).",
)
@click.pass_context
def fork(
    ctx: click.Context,
    parent: str,
    name: str | None,
    proxy_name: str | None,
    direct: bool,
    direct_model: str | None,
    incognito: bool,
    worktree: bool,
    branch: str | None,
    no_launch: bool,
    extensions: bool | None,
    strategy: str,
    drop_last: int | None,
    inline_plan: bool,
    into_path: str | None,
    resume_mode: str | None,
    supervise_target: bool,
    supervisor_proxy: str | None,
    supervisor_direct: bool,
    cascade_flag: bool,
    checker_model: str | None,
    checker_provider: str | None,
    checker_effort: str | None,
    supervisor_effort: str | None,
    supervisor_runtime: str | None,
    force: bool,
    memory_flag: str | None,
) -> None:
    """Fork an existing session.

    By default the fork shares the parent's directory so Claude's
    conversation carries over via --fork-session.  Use --worktree for
    code isolation in a separate git worktree, or --into for an existing
    non-main worktree.

    Worktree/--into forks default to transfer context (a distilled summary).
    Pass --resume-mode native-relocate to instead relocate the parent JSONL
    and resume the full conversation byte-for-byte (host mode only).

    Use --no-proxy to bypass the proxy, or --proxy to route through
    a specific proxy instead of the parent's.

    \b
    Examples:
        forge session fork parent-session                      # Fork, same directory
        forge session fork parent-session --worktree           # Fork with worktree (transfer)
        forge session fork parent-session -w --resume-mode native-relocate  # Byte-faithful resume
        forge session fork parent-session -n child-session     # Custom fork name
        forge session fork parent-session --no-proxy           # Fork, bypass proxy
    """
    ctx = click.get_current_context()
    strategy_explicit = ctx.get_parameter_source("strategy") == click.core.ParameterSource.COMMANDLINE
    drop_last_explicit = ctx.get_parameter_source("drop_last") == click.core.ParameterSource.COMMANDLINE
    inline_plan_explicit = ctx.get_parameter_source("inline_plan") == click.core.ParameterSource.COMMANDLINE

    manager = SessionManager()
    forge_root = _cwd_forge_root()
    request = ForkPreflightRequest(
        parent_name=parent,
        fork_name=name,
        cwd=Path.cwd(),
        forge_root=forge_root,
        proxy_name=proxy_name,
        direct=direct,
        direct_model=direct_model,
        is_incognito=incognito,
        create_worktree=worktree,
        branch=branch,
        no_launch=no_launch,
        extensions=extensions,
        strategy=strategy,
        drop_last=drop_last,
        inline_plan=inline_plan,
        into_path=into_path,
        resume_mode=resume_mode,
        supervise_target=supervise_target,
        supervisor_proxy=supervisor_proxy,
        supervisor_direct=supervisor_direct,
        cascade_flag=cascade_flag,
        checker_model=checker_model,
        checker_provider=checker_provider,
        checker_effort=checker_effort,
        supervisor_effort=supervisor_effort,
        supervisor_runtime=supervisor_runtime,
        force=force,
        memory_flag=memory_flag,
        strategy_explicit=strategy_explicit,
        drop_last_explicit=drop_last_explicit,
        inline_plan_explicit=inline_plan_explicit,
    )
    preflight_notices: list[ForkPreflightNotice] = []
    try:
        try:
            preflight = plan_session_fork(
                request,
                manager=manager,
                context_limit_resolver=_resolve_context_limit,
                notices_sink=preflight_notices,
            )
        except Exception:
            # Planning may collect an explanatory status/tip before a later
            # refusal. Preserve the established output order on those failure
            # paths even though successful notices travel on the typed plan.
            for notice in preflight_notices:
                _render_fork_preflight_notice(notice)
            raise
    except ForkPreflightError as e:
        _render_fork_preflight_error(e)
        sys.exit(1)
    except CannotForkIncognitoError as e:
        print_error_with_tip(str(e), "Incognito sessions cannot be forked.")
        sys.exit(1)
    except BranchExistsError as e:
        _print_branch_exists_tip(e)
        sys.exit(1)
    except BranchInUseError as e:
        print_error_with_tip(
            str(e),
            "The branch is checked out in another worktree. Remove that worktree first.",
        )
        sys.exit(1)
    except BranchNotMergedError as e:
        print_error_with_tip(
            str(e),
            "Merge or delete the branch manually before using --force.",
        )
        sys.exit(1)
    except WorktreePathExistsError as e:
        print_error_with_tip(
            str(e),
            "Remove the directory or use a different fork name.",
        )
        sys.exit(1)
    except InvalidBranchNameError as e:
        print_error(str(e))
        sys.exit(1)
    except ProjectCompatibilityError as e:
        print_error(str(e))
        sys.exit(1)
    except SessionNotFoundError:
        if not _hint_cross_project_session(parent, forge_root):
            print_error(f"session '{parent}' not found")
        sys.exit(1)
    except ForgeSessionError as e:
        handle_session_error(e)
        return

    for notice in preflight.notices:
        _render_fork_preflight_notice(notice)

    # Runtime realization remains CLI-owned. The read-only plan runs first, so
    # deterministic refusals cannot start a proxy or supervisor process.
    preflight_routing: ResolvedRouting | None = None
    if proxy_name:
        preflight_routing = _resolve_routing_from_cli(proxy_name=proxy_name, direct=False)
        try:
            validate_session_fork_routing(
                preflight,
                proxy_id=preflight_routing.proxy_id,
                base_url=preflight_routing.base_url,
                context_limit=getattr(preflight_routing, "context_limit", None),
            )
        except ForkPreflightError as e:
            _render_fork_preflight_error(e)
            sys.exit(1)

    if supervisor_proxy:
        from forge.policy.semantic.supervisor import ensure_supervisor_proxy

        try:
            supervisor_proxy_id, supervisor_started = ensure_supervisor_proxy(supervisor_proxy)
        except ValueError as e:
            print_error(str(e))
            sys.exit(1)
        if supervisor_started:
            console.print(f"[dim]Started proxy '{supervisor_proxy_id}' from template '{supervisor_proxy}'.[/dim]")
        supervisor_proxy = supervisor_proxy_id

    # Keep the established local names for the order-32 execution tail.
    worktree = request.create_worktree or request.branch is not None
    into_resolved = str(preflight.target.checkout_root) if preflight.target.is_into else None
    into_branch = preflight.target.branch if preflight.target.is_into else None
    resume_mode = preflight.manager_resume_mode
    rewind_requested = preflight.rewind_requested
    parent_session_id = preflight.parent_session_id
    normalized_direct_model = preflight.normalized_direct_model
    _preflight_routing = preflight_routing
    _fr = forge_root
    fork_warnings: list[str] = []
    try:
        parent_manifest, fork_manifest = manager.fork_session(
            parent_name=parent,
            fork_name=preflight.fork_name,
            direct=direct,
            is_incognito=incognito,
            create_worktree=worktree,
            branch=into_branch if into_resolved else branch,
            into_path=into_resolved,
            forge_root=_fr,
            force=force,
            memory_flag=({"on": True, "off": False}.get(memory_flag) if memory_flag else None),
            resume_mode=resume_mode,
            warnings_sink=fork_warnings,
        )
    except CannotForkIncognitoError as e:
        print_error_with_tip(str(e), "Incognito sessions cannot be forked.")
        sys.exit(1)
    except BranchExistsError as e:
        _print_branch_exists_tip(e)
        sys.exit(1)
    except BranchInUseError as e:
        print_error_with_tip(
            str(e),
            "The branch is checked out in another worktree. Remove that worktree first.",
        )
        sys.exit(1)
    except BranchNotMergedError as e:
        print_error_with_tip(
            str(e),
            "Merge or delete the branch manually before using --force.",
        )
        sys.exit(1)
    except WorktreePathExistsError as e:
        print_error_with_tip(
            str(e),
            "Remove the directory or use a different fork name.",
        )
        sys.exit(1)
    except InvalidBranchNameError as e:
        print_error(f"{e}")
        sys.exit(1)
    except ProjectCompatibilityError as e:
        print_error(str(e))
        sys.exit(1)
    except SessionNotFoundError:
        if not _hint_cross_project_session(parent, _fr):
            print_error(f"session '{parent}' not found")
        sys.exit(1)
    except ForgeSessionError as e:
        handle_session_error(e)
        return

    for w in fork_warnings:
        if w.startswith("[warn]"):
            console.print(f"[yellow]Warning:[/yellow] {w.removeprefix('[warn]')}")
        else:
            console.print(f"[dim]{w}[/dim]")

    # Persist routing override to manifest (ensures --no-launch retains proxy choice)
    fork_operation_cwd = Path.cwd()
    fork_state_context = resolve_claude_session_state_context(fork_manifest, cwd=fork_operation_cwd)
    _persist_routing_override(
        forge_root=fork_state_context.forge_root,
        session_name=fork_manifest.name,
        routing=_preflight_routing,
        direct=direct,
    )
    _apply_routing_override_to_state(state=fork_manifest, routing=_preflight_routing, direct=direct)

    # --- wire supervisor (if --supervise flag set) ---
    if supervise_target:
        wiring = SupervisorWiring(
            target=parent,
            source_state=parent_manifest,
            supervisor_proxy=supervisor_proxy,
            supervisor_direct=supervisor_direct,
            cascade=cascade_flag,
            checker_model=checker_model,
            checker_provider=checker_provider,
            checker_effort=checker_effort,
            supervisor_effort=supervisor_effort,
            supervisor_runtime=supervisor_runtime,
        )
        fork_manifest = _apply_supervisor_wiring(
            fork_state_context,
            wiring,
            proxy_id=_preflight_routing.proxy_id if _preflight_routing else None,
            template=_preflight_routing.template if _preflight_routing else None,
            direct=direct,
        )
        fork_state_context = resolve_claude_session_state_context(fork_manifest, cwd=fork_operation_cwd)

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

    if parent_session_id is None:
        parent_session_id = parent_manifest.confirmed.claude_session_id

    use_sidecar, mounts, image = _get_launch_preferences(fork_manifest)
    _apply_and_persist_direct_model_override(
        state=fork_manifest,
        direct_model=normalized_direct_model,
        forge_root=fork_state_context.forge_root,
        use_sidecar=use_sidecar,
        surface="fork",
    )

    fork_name = fork_manifest.name  # Capture for cleanup
    is_worktree_fork = bool(fork_manifest.worktree and fork_manifest.worktree.is_worktree)
    rewind_active = rewind_requested and drop_last is not None and drop_last > 0
    native_relocate = is_worktree_fork and resume_mode == "native-relocate" and not rewind_active
    same_dir_transfer = not is_worktree_fork and resume_mode == "transfer"
    if rewind_active and use_sidecar:
        print_error_with_tip(
            "--strategy rewind is not supported with sidecar mode.",
            "Rewind writes to the host ~/.claude store; run in host mode (e.g. --no-proxy) or use transfer mode.",
        )
        sys.exit(1)
    # Forks that pre-seed a fresh child UUID and carry a generated transfer doc: worktree transfer
    # OR same-directory transfer. native-relocate is a byte-faithful native resume (not a fresh
    # transfer), and rewind is a native-relocate variant with its own fresh transcript UUID.
    uses_fresh_transfer = ((is_worktree_fork and not native_relocate) or same_dir_transfer) and not rewind_active

    # Assigned only in the fresh-transfer branch (worktree transfer or same-dir transfer);
    # pre-declared so the same-directory native path leaves them bound (consumed under
    # `uses_fresh_transfer` guards below).
    _fork_uuid: str | None = None
    _rewind_resume_id: str | None = None
    launch_prompt_file: str | None = None
    launch_session_id: str | None = None
    launch_resume_id: str | None = parent_session_id
    launch_fork_session: bool | None = True
    launch_register_fork = False
    if rewind_requested and drop_last == 0:
        console.print("[dim]--drop-last 0 uses plain native-relocate; no rewind context generated.[/dim]")

    # Worktree forks default to transfer: Claude stores sessions per CWD-encoded project dir
    # (~/.claude/projects/<encoded-cwd>/), so a bare --resume can't cross the boundary (2.1.90
    # and 2.1.158 both fail "No conversation found"). The opt-in --resume-mode native-relocate
    # instead copies the parent JSONL into the child's encoded dir and resumes natively (Phase 3
    # spike: scripts/experiments/native-resume/ + the contract test). Transfer stays the default
    # (inspectable, editable, survives /compact); native-relocate is byte-faithful but opaque,
    # lost on /compact, and its historical tool paths still point at the parent checkout.
    if native_relocate:
        assert parent_session_id is not None  # UUID preflight above covers every launched native-relocate path
        from forge.session.claude import (
            RelocateConflictError,
            RelocateSameDirError,
            relocate_transcript,
        )
        from forge.session.claude.paths import resolve_claude_project_root

        _fork_cwd = resolve_claude_project_root(fork_manifest)
        _parent_cwd = parent_manifest.confirmed.claude_project_root or resolve_claude_project_root(parent_manifest)
        try:
            relocate_transcript(
                session_id=parent_session_id,
                source_project_root=_parent_cwd,
                dest_project_root=_fork_cwd,
            )
        except (OSError, RelocateSameDirError) as exc:
            # Any relocate failure (RelocateConflictError/RelocateSourceMissingError are OSError
            # subclasses, plus real permission/disk/os.replace errors) rolls back the just-created
            # fork so nothing is left orphaned and no traceback escapes. delete_transcripts=False is
            # critical: on a conflict the destination holds a *different* pre-existing transcript that
            # relocate refused to clobber, and the native-relocate cleanup branch would otherwise
            # delete that exact file. The fork never launched, so it owns no transcript to clean.
            # owns_worktree-aware deletion keeps an --into target.
            if isinstance(exc, RelocateSameDirError):
                error = (
                    "--resume-mode native-relocate requires a different CWD than the parent; "
                    "the fork resolves to the parent's own Claude project dir."
                )
                tip = "Fork into a fresh --worktree, or use the default transfer mode."
            elif isinstance(exc, RelocateConflictError):
                error = f"The destination worktree already holds a different transcript for parent '{parent}'."
                tip = "Fork into a fresh worktree, or use the default transfer mode."
            else:
                error = f"Could not relocate the parent transcript for native resume: {exc}"
                tip = "Use the default transfer mode, or fork into a fresh worktree."
            error, tip = _rollback_created_session(
                manager=manager,
                session_name=fork_name,
                forge_root=fork_manifest.forge_root,
                delete_worktree=True,
                error=error,
                tip=tip,
                log_context="native-relocate",
            )
            print_error_with_tip(error, tip)
            sys.exit(1)

        console.print(
            "[yellow]Warning:[/yellow] Native-relocate preserves Claude history across CWDs, but historical "
            "tool paths may still point at the parent checkout -- path rewriting is not enabled."
        )

        # Pre-seed claude_project_root so cleanup targets the child's encoded dir even before the
        # hook reconciles. No --session-id: --fork-session assigns the child UUID (hook records it).
        try:
            _nr_store = fork_state_context.store

            def _preseed_cpr(m: SessionState) -> None:
                m.confirmed.claude_project_root = _fork_cwd

            _nr_store.update(timeout_s=5.0, mutate=_preseed_cpr)
        except Exception:
            logger.debug(
                "native-relocate claude_project_root pre-seed failed (hook will reconcile)",
                exc_info=True,
            )

        launch_resume_id = parent_session_id
        launch_fork_session = True

    elif rewind_active:
        assert parent_session_id is not None  # rewind is a launched native-relocate path
        assert drop_last is not None
        from forge.session.claude.paths import (
            resolve_claude_project_root as _resolve_fork_root,
        )

        _fork_cwd = _resolve_fork_root(fork_manifest)
        _rewind_artifacts = _prepare_rewind_launch_artifacts(
            manifest=fork_manifest,
            parent_name=parent,
            parent_state=parent_manifest,
            parent_uuid=parent_session_id,
            drop_last=drop_last,
        )
        _rewind_resume_id = _rewind_artifacts.resume_id
        if _rewind_artifacts.context_path is not None:
            console.print(f"  Context:  {display_path(_rewind_artifacts.context_path)}")
        for warning in _rewind_artifacts.warnings:
            console.print(f"[yellow]Warning:[/yellow] {warning}")
        if not _rewind_artifacts.resume_transcript_ready:
            error, tip = _rollback_created_session(
                manager=manager,
                session_name=fork_name,
                forge_root=fork_manifest.forge_root,
                delete_worktree=True,
                error="Rewind fallback could not prepare a resumable transcript in the fork worktree.",
                tip="Use the default transfer fork, or retry after fixing Claude transcript store access.",
                log_context="rewind fallback",
            )
            print_error_with_tip(error, tip)
            sys.exit(1)

        _rewind_worktree = fork_state_context.worktree_path
        _rewind_prompt_files: list[Path] = []
        if _rewind_artifacts.context_path is not None:
            _rewind_prompt_files.append(_rewind_artifacts.context_path)
        _rewind_configured_prompt = _resolve_manifest_prompt_file(fork_manifest)
        if _rewind_configured_prompt is not None:
            _rewind_prompt_files.append(_rewind_configured_prompt)
        launch_prompt_file = _combine_prompt_files(
            worktree_path=_rewind_worktree,
            session_name=fork_manifest.name,
            prompt_files=_rewind_prompt_files,
        )
        launch_resume_id = _rewind_resume_id
        launch_fork_session = True

    elif uses_fresh_transfer:
        # Shared transfer-launch path: worktree transfer AND same-directory transfer. The only
        # difference is the base dir for the combined prompt -- a worktree fork writes under its
        # checkout; a same-directory fork writes under forge_root (same CWD as the parent). Gate on
        # is_worktree (a same-dir fork carries a non-None Worktree with is_worktree=False).
        if is_worktree_fork:
            prompt_base_dir = fork_state_context.worktree_path
        else:
            prompt_base_dir = fork_state_context.forge_root
        if is_worktree_fork and resume_mode is None:
            print_tip(
                "Worktree fork uses transfer context by default.",
                "Use --resume-mode native-relocate for byte-faithful Claude resume.",
                blank_before=False,
                console=console,
            )
        fork_context, prompt_warnings = _generate_parent_transfer_context(
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
        launch_prompt_file = _combine_prompt_files(
            worktree_path=prompt_base_dir,
            session_name=fork_manifest.name,
            prompt_files=prompt_files,
        )
        if launch_prompt_file:
            prompt_path = Path(launch_prompt_file)
            try:
                console.print(f"  Context:  {prompt_path.relative_to(prompt_base_dir)}")
            except ValueError:
                console.print(f"  Context:  {display_path(prompt_path)}")
        for warning in prompt_warnings:
            console.print(f"[yellow]Warning:[/yellow] {warning}")

        try:
            fork_manifest = _persist_fork_transfer_derivation(
                manifest=fork_manifest,
                strategy=strategy,
                context_path=fork_context,
            )
        except Exception:
            logger.warning("Failed to persist fork derivation transfer details", exc_info=True)
        fork_state_context = resolve_claude_session_state_context(fork_manifest, cwd=fork_operation_cwd)

        _fork_uuid = str(_uuid.uuid4())
        try:
            _fork_store = fork_state_context.store
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

        launch_session_id = _fork_uuid
        launch_resume_id = None
        launch_fork_session = False if use_sidecar else None
        launch_register_fork = True

    # Same-directory forks: --resume --fork-session works natively.
    else:
        launch_resume_id = parent_session_id
        launch_fork_session = True

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

        if extension_root is not None:
            try:
                from forge.install.project_registry import ProjectRegistryStore

                # Managed worktree creation is the trust event; extension install may be skipped.
                ProjectRegistryStore().enroll(extension_root, "worktree")
            except Exception:
                logger.debug("Worktree registry enrollment failed", exc_info=True)

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
        print_tip(
            "--extensions only applies with --worktree.",
            blank_before=False,
            console=console,
        )

    if no_launch:
        console.print("[dim]Fork created (--no-launch: Claude not started)[/dim]")
        if is_worktree_fork or same_dir_transfer:
            print_tip(
                "Resume this fork with:",
                commands=[_resume_tip_command(fork_manifest)],
                console=console,
            )
        sys.exit(0)

    runtime_base_url = _get_runtime_base_url(use_sidecar=use_sidecar, effective_url=effective_url)
    result = fork_claude_session(
        manager=manager,
        plan=ForkLaunchPlan(
            manifest=fork_manifest,
            session_id=launch_session_id,
            resume_id=launch_resume_id,
            fork_session=launch_fork_session,
            register_fork=launch_register_fork,
            prompt_file=(Path(launch_prompt_file) if launch_prompt_file is not None else None),
            context_limit=context_limit,
            launch_preferences=ClaudeLaunchPreferences(
                use_sidecar=use_sidecar,
                mounts=mounts,
                image=image,
            ),
            effective_template=effective_template,
            runtime_base_url=runtime_base_url,
            proxy_id=effective_proxy_id,
            incognito=incognito,
            render_post_exit=(not incognito or use_sidecar),
        ),
        presenter=_ClaudeForkCliPresenter(session_name=fork_name),
    )
    sys.exit(_render_claude_fork_result(result))

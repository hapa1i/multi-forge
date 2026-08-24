"""Session fork command."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

import click

from forge.cli.output import err_console, print_error, print_error_with_tip, print_tip
from forge.cli.session import (  # noqa: E402
    ResolvedRouting,
    _generate_parent_transfer_context,
    _hint_cross_project_session,
    _print_routing_summary,
    _resolve_routing_from_cli,
    console,
    handle_session_error,
)
from forge.cli.session_authority_options import (
    authority_creation_options,
    parse_creation_authority,
)
from forge.cli.session_lifecycle import (  # noqa: E402
    _MODEL_TIER_HELP,
    _plan_interactive_session_model_route,
    _post_exit_render,
    _print_branch_exists_tip,
    _realize_interactive_session_model_route,
    _render_model_route_payload,
    _render_sidecar_launch,
    _resume_tip_command,
    _routing_from_model_route,
    _warn_before_claude_launch,
)
from forge.cli.session_lifecycle import session as _session_untyped  # noqa: E402
from forge.cli.session_rewind import _prepare_rewind_launch_artifacts  # noqa: E402
from forge.cli.session_supervisor_options import supervisor_options
from forge.core.ops.claude_session import (
    ClaudeForkResult,
    ClaudeSidecarLaunch,
    fork_claude_session,
)
from forge.core.ops.context import _cwd_forge_root
from forge.core.ops.session import ForgeOpError
from forge.core.ops.session_fork_execution import (
    ForkContextPrepared,
    ForkCreated,
    ForkExecutionError,
    ForkExecutionEvent,
    ForkExecutionNotice,
    ForkExtensionPrepared,
    ForkModelOverridePersistenceWarning,
    execute_session_fork,
)
from forge.core.ops.session_fork_preflight import (
    ForkPreflightError,
    ForkPreflightNotice,
    ForkPreflightRequest,
    plan_session_fork,
    validate_session_fork_routing,
)
from forge.core.ops.session_model_routing import (
    ResolvedModelRoute,
    SessionModelRoutingError,
    preserved_model_route_request,
)
from forge.core.paths import display_path
from forge.install.project_compat import (
    ProjectCompatibilityError,
)
from forge.session import (
    ForgeSessionError,
    SessionManager,
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

session = cast(click.Group, _session_untyped)  # type: ignore[has-type]  # circular re-export

__all__ = ["fork"]


class _ClaudeForkCliPresenter:
    """CLI-side renderer for ``fork_claude_session`` events."""

    def __init__(self, *, session_name: str) -> None:
        self._session_name = session_name

    def before_launch(self, forge_root: Path) -> None:
        _warn_before_claude_launch(forge_root)

    def on_routing_payload(self, payload: dict[str, Any]) -> None:
        _render_model_route_payload(payload)

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


def _render_fork_execution_event(event: ForkExecutionEvent) -> None:
    """Render one command-core preparation event in its established order."""
    if isinstance(event, ForkCreated):
        console.print(f"Forked [cyan]{event.parent_name}[/cyan] -> [green]{event.session_name}[/green]")
        _print_routing_summary(template=event.effective_template, base_url=event.effective_url)
        if event.worktree_path is not None:
            console.print(f"  Worktree: {display_path(event.worktree_path)}")
            console.print(f"  Branch:   {event.worktree_branch}")
        if event.supervisor_target is not None:
            console.print(f"  Supervisor: {event.supervisor_target}")
        if event.incognito:
            console.print("[yellow]  (will auto-delete on exit)[/yellow]")
        console.print()
        return

    if isinstance(event, ForkContextPrepared):
        display = display_path(event.path)
        if event.display_relative_to is not None:
            try:
                display = str(event.path.relative_to(event.display_relative_to))
            except ValueError:
                pass
        console.print(f"  Context:  {display}")
        return

    if isinstance(event, ForkExtensionPrepared):
        if event.status == "skipped_parent":
            console.print("[dim]  Extensions: skipped (no parent extensions detected)[/dim]")
        elif event.status == "skipped_conflict":
            console.print("[dim]  Extensions: skipped (conflicts with existing files)[/dim]")
        elif event.status == "installed":
            console.print(f"[dim]  Extensions: inherited ({event.profile} profile, {event.module_count} modules)[/dim]")
        else:
            console.print(f"[dim]  Extensions: failed to install ({event.error})[/dim]")
        return

    if isinstance(event, ForkModelOverridePersistenceWarning):
        console.print(
            f"[yellow]Warning:[/yellow] Could not persist --model override for session "
            f"[green]{event.session_name}[/green]: {event.error}"
        )
        print_tip(event.continuation, blank_before=False, console=console)
        return

    if not isinstance(event, ForkExecutionNotice):
        raise TypeError(f"Unsupported fork execution event: {type(event).__name__}")
    if event.level == "warning":
        console.print(f"[yellow]Warning:[/yellow] {event.message}")
        if event.continuation is not None:
            print_tip(event.continuation, blank_before=False, console=console)
    elif event.level == "tip":
        lines = (event.message,) if event.continuation is None else (event.message, event.continuation)
        print_tip(*lines, commands=event.commands or None, blank_before=False, console=console)
    else:
        console.print(f"[dim]{event.message}[/dim]")


def _render_fork_execution_error(error: ForkExecutionError) -> None:
    for event in error.events:
        _render_fork_execution_event(event)
    if error.tip is not None:
        print_error_with_tip(str(error), error.tip)
    else:
        print_error(str(error))


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
    help="Select the model for this fork and future resumes (catalog id or alias)",
)
@click.option(
    "--model-tier",
    type=click.Choice(["haiku", "sonnet", "opus"]),
    default=None,
    help=_MODEL_TIER_HELP,
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
@authority_creation_options
@click.pass_context
def fork(
    ctx: click.Context,
    parent: str,
    name: str | None,
    proxy_name: str | None,
    direct: bool,
    direct_model: str | None,
    model_tier: str | None,
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
    authority_role: str | None,
    authority_tier: str | None,
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
    try:
        authority, authority_explicit = parse_creation_authority(authority_role, authority_tier)
    except ValueError as e:
        print_error(str(e))
        sys.exit(1)

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
        model_tier=model_tier,
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
        authority=authority,
        authority_explicit=authority_explicit,
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
    model_route_selection: ResolvedModelRoute | None = None
    route_model = direct_model
    route_tier = model_tier
    allow_route_replacement = True
    parent_launch = preflight.parent.intent.launch
    neutral_route = parent_launch.model_route if parent_launch is not None else None
    if route_model is None and proxy_name is None and not direct and neutral_route is not None:
        try:
            route_model = preserved_model_route_request(preflight.parent)
            route_tier = neutral_route.selected_tier
            allow_route_replacement = False
        except SessionModelRoutingError as e:
            print_error(str(e))
            sys.exit(1)

    if route_model is not None:
        inherited_sidecar = preflight.parent.confirmed.is_sandboxed or (
            parent_launch is not None and parent_launch.mode == "sidecar"
        )
        if direct_model is not None and inherited_sidecar and not direct:
            print_error("--model cannot be combined with sidecar fork")
            sys.exit(1)
        try:
            model_plan = _plan_interactive_session_model_route(
                route_model,
                model_tier=route_tier,
                proxy_name=proxy_name,
                direct=direct,
                state=preflight.parent,
                allow_replacement=allow_route_replacement,
            )
            if (
                preflight.parent.intent.subprocess_proxy
                and model_plan.kind == "proxy"
                and model_plan.request.claude_tier is None
            ):
                raise SessionModelRoutingError(
                    "a non-Claude main-session route cannot be combined with persisted subprocess-proxy intent"
                )
            model_route_selection = _realize_interactive_session_model_route(model_plan)
        except SessionModelRoutingError as e:
            print_error(str(e))
            sys.exit(1)
        preflight_routing = _routing_from_model_route(model_route_selection)
        try:
            validate_session_fork_routing(
                preflight,
                proxy_id=model_route_selection.proxy_id,
                base_url=model_route_selection.proxy_base_url,
                context_limit=model_route_selection.context_limit,
            )
        except ForkPreflightError as e:
            _render_fork_preflight_error(e)
            sys.exit(1)
    elif proxy_name:
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

    try:
        execution = execute_session_fork(
            preflight,
            manager=manager,
            routing=preflight_routing,
            supervisor_proxy=supervisor_proxy,
            transfer_context_factory=_generate_parent_transfer_context,
            rewind_artifact_factory=_prepare_rewind_launch_artifacts,
            model_route_selection=model_route_selection,
        )
    except ForkExecutionError as e:
        _render_fork_execution_error(e)
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

    for event in execution.events:
        _render_fork_execution_event(event)

    if execution.launch_plan is None:
        if execution.show_resume_tip:
            print_tip(
                "Resume this fork with:",
                commands=[_resume_tip_command(execution.manifest)],
                console=console,
            )
        sys.exit(0)

    result = fork_claude_session(
        manager=manager,
        plan=execution.launch_plan,
        presenter=_ClaudeForkCliPresenter(session_name=execution.manifest.name),
    )
    sys.exit(_render_claude_fork_result(result))

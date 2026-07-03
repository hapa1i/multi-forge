"""Session fork command.

Extracted from session_lifecycle.py for file-size compliance.
Re-exported via session.py so patch("forge.cli.session.fork") works.
"""

from __future__ import annotations

import sys
import uuid as _uuid
from pathlib import Path
from typing import cast

import click

from forge.cli.output import print_error, print_error_with_tip, print_tip
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
    _resolve_session_artifact_root,
    console,
    handle_session_error,
    logger,
)
from forge.cli.session_lifecycle import (  # noqa: E402
    _persist_fork_transfer_derivation,
    _post_exit_render,
    _prepare_rewind_launch_artifacts,
    _print_branch_exists_tip,
    _render_sidecar_launch,
    _resolve_manifest_prompt_file,
    _resume_tip_command,
    _warn_before_claude_launch,
)
from forge.cli.session_lifecycle import session as _session_untyped  # noqa: E402
from forge.cli.session_model_pin import (  # noqa: E402
    _apply_and_persist_direct_model_override,
)
from forge.core.effort import CLAUDE_EFFORT_LEVELS
from forge.core.llm.types import REASONING_EFFORT_LEVELS
from forge.core.ops.claude_session import (
    ClaudeForkResult,
    ClaudeLaunchPreferences,
    ClaudeSidecarLaunch,
    ForkLaunchPlan,
    SupervisorWiring,
    _apply_supervisor_wiring,
    fork_claude_session,
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
    LAUNCH_MODE_SIDECAR,
    ForgeSessionError,
    SessionManager,
    SessionState,
)
from forge.session.context_limit import _resolve_context_limit
from forge.session.direct_model import (
    DirectModelPin,
    resolve_direct_model_pin,
)
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
from forge.session.model_pin import (
    _validate_direct_model_pin_for_routing,
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
        print_error(str(error), console=console)

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
    help="Pin the Claude model for this fork and future resumes (for example: claude-opus-4-6 or claude-opus-4-8)",
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
    if direct and proxy_name:
        print_error("--no-proxy and --proxy are mutually exclusive", console=console)
        sys.exit(1)
    if supervisor_proxy and supervisor_direct:
        print_error(
            "--supervisor-proxy and --no-supervisor-proxy are mutually exclusive",
            console=console,
        )
        sys.exit(1)
    if (supervisor_proxy or supervisor_direct) and not supervise_target:
        print_error(
            "--supervisor-proxy/--no-supervisor-proxy require --supervise",
            console=console,
        )
        sys.exit(1)
    if (
        cascade_flag or checker_model or checker_provider or checker_effort or supervisor_effort or supervisor_runtime
    ) and not supervise_target:
        print_error(
            "--cascade/--checker-*/--supervisor-effort/--supervisor-runtime require --supervise",
            console=console,
        )
        sys.exit(1)
    try:
        validate_checker_model(checker_model)
    except ValueError as e:
        print_error(f"{e}", console=console)
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

    if branch:
        worktree = True

    # --into validation
    into_resolved: str | None = None
    into_branch: str | None = None
    into_target_common: str | None = None
    if into_path is not None:
        if worktree:
            print_error("--into and --worktree are mutually exclusive", console=console)
            sys.exit(1)
        if branch:
            print_error("--into and --branch are mutually exclusive", console=console)
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
            print_error(
                f"'{display_path(into_path)}' is not inside a git repository",
                console=console,
            )
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
            print_error("Failed to resolve git repository for --into target", console=console)
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
                print_error(
                    "--into targets existing worktrees, not the main checkout. Use a same-directory fork instead.",
                    console=console,
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
    _drop_last_explicit = ctx.get_parameter_source("drop_last") == click.core.ParameterSource.COMMANDLINE
    _inline_plan_explicit = ctx.get_parameter_source("inline_plan") == click.core.ParameterSource.COMMANDLINE

    manager = SessionManager()
    _fr = _cwd_forge_root()

    # Reject a Codex parent BEFORE fork_session() creates orphaned child state. `fork`
    # is Claude-specific: it carries the conversation via --fork-session + the parent's
    # confirmed.claude_session_id, which a Codex session never has (it would fail later at
    # the "Parent session has no UUID" check, after a child manifest/worktree was created).
    # Manifests store the registry id "codex" (CLI maps --runtime); not found/unreadable
    # falls through so fork_session() raises the right error.
    try:
        _parent_runtime_state = manager.get_session(parent, forge_root=_fr)
    except ForgeSessionError:
        _parent_runtime_state = None
    if _parent_runtime_state is not None:
        _parent_launch = _parent_runtime_state.intent.launch
        if _parent_launch is not None and _parent_launch.runtime == "codex":
            print_error_with_tip(
                f"Session '{parent}' is a Codex session; 'forge session fork' is Claude-only.",
                "Continue the Codex thread, or branch a new Codex session from it:",
                commands=[
                    f"forge session resume {parent} --task <next step>",
                    f"forge session start <name> --runtime codex --resume-from {parent} --task <task>",
                ],
                console=console,
            )
            sys.exit(1)

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
                    print_error(
                        "--into target is not part of the same repository as the parent session",
                        console=console,
                    )
                    sys.exit(1)
        except _sp2.CalledProcessError:
            pass  # Can't resolve parent repo; allow
        except ForgeSessionError:
            pass  # Parent not found; fork_session() will raise the right error

    # Budget preflight for --strategy full (before fork_session to avoid orphaned sessions/worktrees)
    # Use the child's effective routing: --no-proxy means no proxy, --proxy overrides parent
    is_cross_dir = worktree or into_resolved is not None
    rewind_requested = strategy == "rewind"
    if _drop_last_explicit and not rewind_requested:
        print_error("--drop-last requires --strategy rewind", console=console)
        sys.exit(1)
    if rewind_requested:
        if drop_last is None:
            print_error("--strategy rewind requires --drop-last N", console=console)
            sys.exit(1)
        if drop_last < 0:
            print_error("--drop-last must be non-negative", console=console)
            sys.exit(1)
        if _inline_plan_explicit:
            print_error(
                "--inline-plan applies only to transfer forks, not --strategy rewind",
                console=console,
            )
            sys.exit(1)
        if resume_mode == "transfer":
            print_error(
                "--strategy rewind cannot be combined with --resume-mode transfer",
                console=console,
            )
            sys.exit(1)
        if not is_cross_dir:
            print_error_with_tip(
                "--strategy rewind on fork requires --worktree or --into.",
                "Use 'forge session resume <name> --fresh --strategy rewind --drop-last N' for a same-directory child.",
                console=console,
            )
            sys.exit(1)
        resume_mode = "native-relocate"

    # Auto-switch a same-directory fork into transfer mode when the user explicitly set a
    # transfer-only flag (--strategy/--inline-plan) without an explicit --resume-mode. Resolving
    # resume_mode here keeps every downstream site (notice, budget gate, manager call, launch,
    # derivation) keyed uniformly on "transfer". Gated on `resume_mode is None`, so an explicit
    # --resume-mode native-relocate never auto-switches.
    if (
        not is_cross_dir
        and resume_mode is None
        and not rewind_requested
        and (_strategy_explicit or _inline_plan_explicit)
    ):
        resume_mode = "transfer"
        # Status notice (an action Forge took), not a recovery hint -- per CLAUDE.md UX guidelines,
        # informational output is an unprefixed dim line, distinct from print_tip recovery suggestions.
        console.print(
            "[dim]Same-directory fork switched to transfer mode "
            "(--strategy/--inline-plan implies a transfer fork).[/dim]"
        )

    # Native-relocate (opt-in) preflights -- reject before fork_session() to avoid orphaned state.
    if resume_mode == "native-relocate" and is_cross_dir:
        if no_launch:
            print_error_with_tip(
                "--resume-mode native-relocate cannot be combined with --no-launch.",
                "Native-relocate relocates and resumes at launch; omit --no-launch.",
                console=console,
            )
            sys.exit(1)
        try:
            _parent_nr = manager.get_session(parent, forge_root=_fr)
        except ForgeSessionError as e:
            handle_session_error(e)
            return
        # --no-proxy/--direct force host (manager.fork_session), so a direct fork is host-compatible
        # even when the parent is sidecar; only a real (non-direct) sidecar fork is rejected.
        _nr_launch = _parent_nr.intent.launch
        _parent_is_sidecar = _parent_nr.confirmed.is_sandboxed or (
            _nr_launch is not None and _nr_launch.mode == LAUNCH_MODE_SIDECAR
        )
        if not direct and _parent_is_sidecar:
            print_error_with_tip(
                "--resume-mode native-relocate is not supported with sidecar mode.",
                "Relocation writes to the host ~/.claude store; run in host mode (e.g. --no-proxy) "
                "or use the default transfer mode.",
                console=console,
            )
            sys.exit(1)
        from forge.session.claude.paths import (
            get_project_encoded_dir,
            get_transcript_path,
            resolve_claude_project_root,
        )

        _nr_uuid = _parent_nr.confirmed.claude_session_id
        _nr_parent_cwd = _parent_nr.confirmed.claude_project_root or resolve_claude_project_root(_parent_nr)
        if not _nr_uuid or not get_transcript_path(_nr_parent_cwd, _nr_uuid).is_file():
            print_error_with_tip(
                f"Parent session '{parent}' has no Claude transcript to relocate.",
                "Start the parent session so it has a conversation to fork, or use the default transfer mode.",
                console=console,
            )
            sys.exit(1)
        # Reject a fork whose CWD encodes to the parent's OWN Claude dir: relocation would be a
        # no-op that later makes child-deletion delete the parent's original transcript. Only the
        # --into target is known pre-fork; --worktree's new dir is guarded at the relocate seam.
        if into_resolved is not None and get_project_encoded_dir(_nr_parent_cwd) == get_project_encoded_dir(
            str(into_resolved)
        ):
            print_error_with_tip(
                "--resume-mode native-relocate requires a different CWD than the parent; "
                "the --into target resolves to the parent's own Claude project dir.",
                "Fork into a fresh --worktree, or use the default transfer mode.",
                console=console,
            )
            sys.exit(1)
        if not rewind_requested and (_strategy_explicit or _inline_plan_explicit):
            print_tip(
                "--strategy/--inline-plan apply only to transfer forks; ignored with --resume-mode native-relocate.",
                blank_before=False,
                console=console,
            )
    elif resume_mode == "native-relocate" and not is_cross_dir:
        print_tip(
            "--resume-mode native-relocate only applies to --worktree/--into forks; "
            "same-directory forks use native resume or --resume-mode transfer.",
            blank_before=False,
            console=console,
        )

    # Resolve --proxy early for preflight (reuses routing resolved later for launch)
    _preflight_routing: ResolvedRouting | None = None
    if proxy_name:
        _preflight_routing = _resolve_routing_from_cli(proxy_name=proxy_name, direct=False)

    if direct_model_pin:
        try:
            parent_state_for_model = manager.get_session(parent, forge_root=_fr)
        except SessionNotFoundError:
            if not _hint_cross_project_session(parent, _fr):
                print_error(f"session '{parent}' not found", console=console)
            sys.exit(1)
        except ForgeSessionError as e:
            handle_session_error(e)
            return

        if not direct:
            inherited_launch = parent_state_for_model.intent.launch
            inherited_sidecar = parent_state_for_model.confirmed.is_sandboxed or (
                inherited_launch is not None and inherited_launch.mode == LAUNCH_MODE_SIDECAR
            )
            if inherited_sidecar:
                print_error("--model cannot be combined with sidecar fork", console=console)
                sys.exit(1)

            _, inherited_base_url, inherited_proxy_id = _get_effective_proxy_for_session(parent_state_for_model)
            error = _validate_direct_model_pin_for_routing(
                pin=direct_model_pin,
                proxy_id=_preflight_routing.proxy_id if _preflight_routing else inherited_proxy_id,
                base_url=_preflight_routing.base_url if _preflight_routing else inherited_base_url,
                surface="fork",
            )
            if error:
                print_error(f"{error}", console=console)
                sys.exit(1)

    if (is_cross_dir or resume_mode == "transfer") and strategy == "full" and not direct:
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
                from forge.session.transfer import estimate_transcript_tokens

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
                                        print_error_with_tip(
                                            f"Parent transcript ({token_est:,} tokens) exceeds "
                                            f"context limit ({context_limit_preflight:,}).",
                                            "Use --strategy structured or --strategy ai-curated instead.",
                                            console=console,
                                        )
                                        sys.exit(1)
        except ForgeSessionError:
            pass  # Parent not found; fork_session() will raise the right error

    # Preflight supervisor proxy BEFORE fork_session() to avoid half-created state
    if supervisor_proxy:
        from forge.policy.semantic.supervisor import ensure_supervisor_proxy

        try:
            _sup_proxy_id, _sup_started = ensure_supervisor_proxy(supervisor_proxy)
        except ValueError as e:
            print_error(f"{e}", console=console)
            sys.exit(1)
        if _sup_started:
            console.print(f"[dim]Started proxy '{_sup_proxy_id}' from template '{supervisor_proxy}'.[/dim]")
        supervisor_proxy = _sup_proxy_id

    fork_warnings: list[str] = []
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
            memory_flag={"on": True, "off": False}.get(memory_flag) if memory_flag else None,
            resume_mode=resume_mode,
            warnings_sink=fork_warnings,
        )
    except CannotForkIncognitoError as e:
        print_error_with_tip(str(e), "Incognito sessions cannot be forked.", console=console)
        sys.exit(1)
    except BranchExistsError as e:
        _print_branch_exists_tip(e)
        sys.exit(1)
    except BranchInUseError as e:
        print_error_with_tip(
            str(e),
            "The branch is checked out in another worktree. Remove that worktree first.",
            console=console,
        )
        sys.exit(1)
    except BranchNotMergedError as e:
        print_error_with_tip(
            str(e),
            "Merge or delete the branch manually before using --force.",
            console=console,
        )
        sys.exit(1)
    except WorktreePathExistsError as e:
        print_error_with_tip(
            str(e),
            "Remove the directory or use a different fork name.",
            console=console,
        )
        sys.exit(1)
    except InvalidBranchNameError as e:
        print_error(f"{e}", console=console)
        sys.exit(1)
    except SessionNotFoundError:
        if not _hint_cross_project_session(parent, _fr):
            print_error(f"session '{parent}' not found", console=console)
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
            fork_manifest,
            wiring,
            proxy_id=_preflight_routing.proxy_id if _preflight_routing else None,
            template=_preflight_routing.template if _preflight_routing else None,
            direct=direct,
        )

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
        print_error("Parent session has no UUID", console=console)
        console.print("The parent session may not have been started yet.")
        sys.exit(1)

    use_sidecar, mounts, image = _get_launch_preferences(fork_manifest)
    _apply_and_persist_direct_model_override(
        state=fork_manifest,
        direct_model=normalized_direct_model,
        forge_root=Path(fork_manifest.forge_root) if fork_manifest.forge_root else fork_worktree_path,
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
            console=console,
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
            try:
                manager.delete_session(
                    fork_name,
                    delete_worktree=True,
                    delete_transcripts=False,
                    force=True,
                    forge_root=fork_manifest.forge_root,
                )
            except Exception:
                logger.debug("native-relocate rollback delete failed", exc_info=True)
            if isinstance(exc, RelocateSameDirError):
                print_error_with_tip(
                    "--resume-mode native-relocate requires a different CWD than the parent; "
                    "the fork resolves to the parent's own Claude project dir.",
                    "Fork into a fresh --worktree, or use the default transfer mode.",
                    console=console,
                )
            elif isinstance(exc, RelocateConflictError):
                print_error_with_tip(
                    f"The destination worktree already holds a different transcript for parent '{parent}'.",
                    "Fork into a fresh worktree, or use the default transfer mode.",
                    console=console,
                )
            else:
                print_error_with_tip(
                    f"Could not relocate the parent transcript for native resume: {exc}",
                    "Use the default transfer mode, or fork into a fresh worktree.",
                    console=console,
                )
            sys.exit(1)

        console.print(
            "[yellow]Warning:[/yellow] Native-relocate preserves Claude history across CWDs, but historical "
            "tool paths may still point at the parent checkout -- path rewriting is not enabled."
        )

        # Pre-seed claude_project_root so cleanup targets the child's encoded dir even before the
        # hook reconciles. No --session-id: --fork-session assigns the child UUID (hook records it).
        try:
            from forge.session import SessionStore as _ForkStore

            _nr_store_root = Path(fork_manifest.forge_root) if fork_manifest.forge_root else Path(_fork_cwd)
            _nr_store = _ForkStore(str(_nr_store_root), fork_manifest.name)

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
            try:
                manager.delete_session(
                    fork_name,
                    delete_worktree=True,
                    delete_transcripts=False,
                    force=True,
                    forge_root=fork_manifest.forge_root,
                )
            except Exception:
                logger.debug("rewind fallback rollback delete failed", exc_info=True)
            print_error_with_tip(
                "Rewind fallback could not prepare a resumable transcript in the fork worktree.",
                "Use the default transfer fork, or retry after fixing Claude transcript store access.",
                console=console,
            )
            sys.exit(1)

        _rewind_worktree = Path(fork_manifest.worktree.path) if fork_manifest.worktree else Path.cwd()
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
            worktree_path = Path(fork_manifest.worktree.path)  # type: ignore[union-attr]
        else:
            worktree_path = Path(fork_manifest.forge_root) if fork_manifest.forge_root else Path.cwd()
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
            worktree_path=worktree_path,
            session_name=fork_manifest.name,
            prompt_files=prompt_files,
        )
        if launch_prompt_file:
            prompt_path = Path(launch_prompt_file)
            try:
                console.print(f"  Context:  {prompt_path.relative_to(worktree_path)}")
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
            prompt_file=Path(launch_prompt_file) if launch_prompt_file is not None else None,
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

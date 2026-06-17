"""Session fork command.

Extracted from session_lifecycle.py for file-size compliance.
Re-exported via session.py so patch("forge.cli.session.fork") works.
"""

from __future__ import annotations

import sys
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path

import click

from forge.cli.output import print_error_with_tip, print_tip
from forge.cli.session_addendum import (
    resolve_addendum_content_for_proxy,
    write_managed_addendum,
)
from forge.core.effort import CLAUDE_EFFORT_LEVELS
from forge.core.llm.types import REASONING_EFFORT_LEVELS
from forge.core.paths import display_path
from forge.policy.semantic.supervisor import (
    CHECKER_PROVIDER_CHOICES,
    apply_checker_options,
    validate_checker_model,
)
from forge.session import (
    LAUNCH_MODE_HOST,
    LAUNCH_MODE_SIDECAR,
    ForgeSessionError,
    SessionState,
)
from forge.session.direct_model import (
    DirectModelPin,
    apply_direct_model_env,
    apply_proxy_context_model_defaults,
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


def _sess():  # type: ignore[return]
    return sys.modules["forge.cli.session"]


from forge.cli.launch_confirmation import (  # noqa: E402
    _routing_mode_for,
    record_launch_confirmed,
)
from forge.cli.session import (  # noqa: E402
    ResolvedRouting,
    _apply_routing_override_to_state,
    _combine_prompt_files,
    _get_effective_proxy_for_session,
    _get_launch_preferences,
    _get_runtime_base_url,
    _hint_cross_project_session,
    _persist_routing_override,
    _print_routing_summary,
    _resolve_session_artifact_root,
    _resolve_worktree_extension_root,
    console,
    handle_session_error,
    logger,
)
from forge.cli.session_lifecycle import (  # noqa: E402
    _launch_claude_for_session,
    _persist_fork_transfer_derivation,
    _print_branch_exists_tip,
    _print_post_exit_tip,
    _print_session_activity_summary,
    _resolve_manifest_prompt_file,
    _resume_tip_command,
    session,
)
from forge.cli.session_model_pin import (  # noqa: E402
    _apply_and_persist_direct_model_override,
    _apply_direct_model_env_if_supported,
    _validate_direct_model_pin_for_routing,
)
from forge.core.reactive.env import compute_interactive_api_key_decision  # noqa: E402

__all__ = ["fork"]


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
    type=click.Choice(["minimal", "structured", "full", "ai-curated"]),
    default="structured",
    help="Context assembly strategy for transfer forks (worktree, --into, or same-directory transfer). "
    "On a same-directory fork, setting it switches the fork to transfer mode. Default: structured",
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
        console.print("[red]Error:[/red] --no-proxy and --proxy are mutually exclusive")
        sys.exit(1)
    if supervisor_proxy and supervisor_direct:
        console.print("[red]Error:[/red] --supervisor-proxy and --no-supervisor-proxy are mutually exclusive")
        sys.exit(1)
    if (supervisor_proxy or supervisor_direct) and not supervise_target:
        console.print("[red]Error:[/red] --supervisor-proxy/--no-supervisor-proxy require --supervise")
        sys.exit(1)
    if (
        cascade_flag or checker_model or checker_provider or checker_effort or supervisor_effort
    ) and not supervise_target:
        console.print("[red]Error:[/red] --cascade/--checker-*/--supervisor-effort require --supervise")
        sys.exit(1)
    try:
        validate_checker_model(checker_model)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    normalized_direct_model: str | None = None
    direct_model_pin: DirectModelPin | None = None
    if direct_model:
        try:
            direct_model_pin = resolve_direct_model_pin(direct_model)
            normalized_direct_model = direct_model_pin.env_model
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
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

    manager = _sess().SessionManager()
    _fr = _sess()._cwd_forge_root()

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

    # Auto-switch a same-directory fork into transfer mode when the user explicitly set a
    # transfer-only flag (--strategy/--inline-plan) without an explicit --resume-mode. Resolving
    # resume_mode here keeps every downstream site (notice, budget gate, manager call, launch,
    # derivation) keyed uniformly on "transfer". Gated on `resume_mode is None`, so an explicit
    # --resume-mode native-relocate never auto-switches.
    if not is_cross_dir and resume_mode is None and (_strategy_explicit or _inline_plan_explicit):
        resume_mode = "transfer"
        # Status notice (an action Forge took), not a recovery Tip -- per CLAUDE.md UX guidelines,
        # informational output is an unprefixed dim line; 'Tip:' is reserved for recovery suggestions.
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
        if _strategy_explicit or _inline_plan_explicit:
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
        _preflight_routing = _sess()._resolve_routing_from_cli(proxy_name=proxy_name, direct=False)

    if direct_model_pin:
        try:
            parent_state_for_model = manager.get_session(parent, forge_root=_fr)
        except SessionNotFoundError:
            if not _hint_cross_project_session(parent, _fr):
                console.print(f"[red]Error:[/red] session '{parent}' not found")
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
                console.print("[red]Error:[/red] --model cannot be combined with sidecar fork")
                sys.exit(1)

            _, inherited_base_url, inherited_proxy_id = _get_effective_proxy_for_session(parent_state_for_model)
            error = _validate_direct_model_pin_for_routing(
                pin=direct_model_pin,
                proxy_id=_preflight_routing.proxy_id if _preflight_routing else inherited_proxy_id,
                base_url=_preflight_routing.base_url if _preflight_routing else inherited_base_url,
                surface="fork",
            )
            if error:
                console.print(f"[red]Error:[/red] {error}")
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
            context_limit_preflight = _sess()._resolve_context_limit(preflight_ref)
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
            console.print(f"[red]Error:[/red] {e}")
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
        print_error_with_tip(str(e), "Merge or delete the branch manually before using --force.", console=console)
        sys.exit(1)
    except WorktreePathExistsError as e:
        print_error_with_tip(str(e), "Remove the directory or use a different fork name.", console=console)
        sys.exit(1)
    except InvalidBranchNameError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except SessionNotFoundError:
        if not _hint_cross_project_session(parent, _fr):
            console.print(f"[red]Error:[/red] session '{parent}' not found")
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
        from forge.policy.semantic.supervisor import (
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
        # Cascade-at-launch sets the flag only; the runtime hook resolves the plan at
        # eval time (a fresh child has no approved snapshot yet -- it safely escalates
        # to the frontier supervisor until a plan is approved).
        if cascade_flag:
            sup_config.cascade = True
        apply_checker_options(
            sup_config,
            checker_model=checker_model,
            checker_provider=checker_provider,
            checker_effort=checker_effort,
        )
        if supervisor_effort is not None:
            sup_config.supervisor_effort = supervisor_effort
        fork_store = SessionStore(fork_forge_root, fork_manifest.name)
        fork_store.update(timeout_s=5.0, mutate=lambda m: apply_supervisor_to_intent(m, sup_config))
        fork_manifest = fork_store.read()

    if _preflight_routing:
        effective_template = _preflight_routing.template
        effective_url = _preflight_routing.base_url
        effective_proxy_id = _preflight_routing.proxy_id
    elif proxy_name:
        routing = _sess()._resolve_routing_from_cli(proxy_name=proxy_name, direct=False)
        effective_template = routing.template
        effective_url = routing.base_url
        effective_proxy_id = routing.proxy_id
    else:
        effective_template, effective_url, effective_proxy_id = _get_effective_proxy_for_session(fork_manifest)

    # Compute context limit (uses exact proxy_id when available for deterministic result)
    context_limit = _sess()._resolve_context_limit(effective_proxy_id or effective_template)

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

    use_sidecar, mounts, image = _get_launch_preferences(fork_manifest)
    _apply_and_persist_direct_model_override(
        state=fork_manifest,
        direct_model=normalized_direct_model,
        forge_root=Path(fork_manifest.forge_root) if fork_manifest.forge_root else fork_worktree_path,
        use_sidecar=use_sidecar,
        surface="fork",
    )

    # Set env vars for fork registration (hook uses FORGE_FORK_NAME for fork detection)
    env_vars, unset_env_vars = _sess()._build_session_env(
        session_name=fork_manifest.name,
        context_limit=context_limit,
        template=effective_template,
        base_url=effective_url,
        fork_name=fork_manifest.name,
        parent_session=parent,
        forge_root=fork_manifest.forge_root,
        subprocess_proxy=fork_manifest.intent.subprocess_proxy,
        sidecar=use_sidecar,
    )
    if effective_url is not None:
        apply_proxy_context_model_defaults(env_vars, context_limit)
    fork_name = fork_manifest.name  # Capture for cleanup
    is_worktree_fork = bool(fork_manifest.worktree and fork_manifest.worktree.is_worktree)
    native_relocate = is_worktree_fork and resume_mode == "native-relocate"
    same_dir_transfer = not is_worktree_fork and resume_mode == "transfer"
    # Forks that pre-seed a fresh child UUID and carry a generated transfer doc: worktree transfer
    # OR same-directory transfer. native-relocate is a byte-faithful native resume (not a fresh
    # transfer), so it is excluded even though is_worktree_fork is True for it.
    uses_fresh_transfer = (is_worktree_fork and not native_relocate) or same_dir_transfer
    if effective_url is None:
        from forge.runtime_config import get_default_direct_model

        fork_direct_model = fork_manifest.intent.launch.direct_model if fork_manifest.intent.launch else None
        fork_direct_model = fork_direct_model or get_default_direct_model()
        error = apply_direct_model_env(env_vars, fork_direct_model)
        if error:
            console.print(f"[red]Error:[/red] {error}")
            sys.exit(1)
    elif fork_manifest.intent.launch and fork_manifest.intent.launch.direct_model and effective_proxy_id:
        error = _apply_direct_model_env_if_supported(
            env_vars, effective_proxy_id, fork_manifest.intent.launch.direct_model
        )
        if error:
            console.print(f"[red]Error:[/red] {error}")
            sys.exit(1)

    # Assigned only in the fresh-transfer branch (worktree transfer or same-dir transfer);
    # pre-declared so the same-directory native path leaves them bound (consumed under
    # `uses_fresh_transfer` guards below).
    _fork_uuid: str | None = None
    prompt_file: str | None = None

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
            logger.debug("native-relocate claude_project_root pre-seed failed (hook will reconcile)", exc_info=True)

        _nr_addendum = resolve_addendum_content_for_proxy(effective_proxy_id)
        _nr_prompt: str | None = None
        if _nr_addendum:
            _nr_forge_root = Path(fork_manifest.forge_root) if fork_manifest.forge_root else Path(_fork_cwd)
            _nr_prompt = str(write_managed_addendum(_nr_forge_root, fork_manifest.name, _nr_addendum))

        def _invoke_fork() -> int:
            return _sess().invoke_claude(
                resume_id=parent_session_id,
                fork_session=True,
                name=fork_manifest.name,
                model=None,
                system_prompt_file=_nr_prompt,
                env_vars=env_vars,
                unset_env_vars=unset_env_vars,
                cwd=_fork_cwd,
            )

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
        fork_context, prompt_warnings = _sess()._generate_parent_transfer_context(
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

        from forge.session.claude.paths import (
            resolve_claude_project_root as _resolve_fork_root,
        )

        _fork_cwd = _resolve_fork_root(fork_manifest)

        _wt_addendum = resolve_addendum_content_for_proxy(effective_proxy_id)
        _wt_prompt = prompt_file
        if _wt_addendum:
            _wt_forge_root = Path(fork_manifest.forge_root) if fork_manifest.forge_root else Path.cwd()
            _wt_addendum_path = write_managed_addendum(_wt_forge_root, fork_manifest.name, _wt_addendum)
            _wt_files: list[Path] = [_wt_addendum_path]
            if _wt_prompt:
                _wt_files.append(Path(_wt_prompt))
            _wt_prompt = _combine_prompt_files(
                worktree_path=worktree_path,
                session_name=fork_manifest.name,
                prompt_files=_wt_files,
            )

        def _invoke_fork() -> int:
            return _sess().invoke_claude(
                session_id=_fork_uuid,
                name=fork_manifest.name,
                model=None,
                system_prompt_file=_wt_prompt,
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
        _samedir_addendum = resolve_addendum_content_for_proxy(effective_proxy_id)
        _samedir_prompt: str | None = None
        if _samedir_addendum:
            _samedir_forge_root = Path(fork_manifest.forge_root) if fork_manifest.forge_root else Path.cwd()
            _samedir_prompt = str(write_managed_addendum(_samedir_forge_root, fork_manifest.name, _samedir_addendum))

        def _invoke_fork() -> int:
            return _sess().invoke_claude(
                resume_id=parent_session_id,
                fork_session=True,
                name=fork_manifest.name,
                model=None,
                system_prompt_file=_samedir_prompt,
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
            _sess()._auto_install_extensions(
                install_root=extension_root,
                parent_project_root=_parent_forge_root,
                force_extensions=extensions,
            )
    elif extensions is True:
        print_tip("--extensions only applies with --worktree.", blank_before=False, console=console)

    if no_launch:
        console.print("[dim]Fork created (--no-launch: Claude not started)[/dim]")
        if is_worktree_fork or same_dir_transfer:
            print_tip("Resume this fork with:", commands=[_resume_tip_command(fork_manifest)], console=console)
        sys.exit(0)

    runtime_base_url = _get_runtime_base_url(use_sidecar=use_sidecar, effective_url=effective_url)

    if use_sidecar:
        exit_code = 0
        try:
            exit_code = _launch_claude_for_session(
                manifest=fork_manifest,
                session_id=_fork_uuid if uses_fresh_transfer else None,
                resume_id=None if uses_fresh_transfer else parent_session_id,
                effective_template=effective_template,
                runtime_base_url=runtime_base_url,
                context_limit=context_limit,
                use_sidecar=True,
                mounts=mounts,
                image=image,
                fork_session=not uses_fresh_transfer,
                register_fork=uses_fresh_transfer,
                system_prompt_file=prompt_file if uses_fresh_transfer else None,
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
    _sess()._warn_if_hooks_missing(_fork_forge_root)
    _sess()._warn_if_version_outdated()

    # Host forks launch via the local _invoke_fork closures (not _launch_claude_for_session),
    # so record launch facts here. compute mirrors the interactive finalizer's resolution.
    from forge.session.store import SessionStore as _LaunchStore

    record_launch_confirmed(
        _LaunchStore(str(_fork_forge_root), fork_manifest.name),
        routing_mode=_routing_mode_for(runtime_base_url, effective_proxy_id),
        proxy_id=effective_proxy_id,
        base_url=runtime_base_url,
        decision=compute_interactive_api_key_decision(interactive=True),
    )

    active_claude_session_id = _fork_uuid if uses_fresh_transfer else None

    # Scope the post-exit summary to this run (hooks write during the session).
    launch_started_at = datetime.now(timezone.utc)

    if incognito:
        exit_code = 0
        try:
            exit_code = _sess().run_with_active_session(
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
        exit_code = _sess().run_with_active_session(
            session_name=fork_name,
            worktree_path=fork_worktree,
            launch_mode=LAUNCH_MODE_HOST,
            forge_root=fork_manifest.forge_root,
            claude_session_id=active_claude_session_id,
            runner=_invoke_fork,
        )
        _print_session_activity_summary(fork_manifest, since=launch_started_at)
        _print_post_exit_tip(fork_manifest)
        sys.exit(exit_code)

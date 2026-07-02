"""CLI front for Codex-runtime sessions (codex_frontend Phase 2).

Split from ``session_lifecycle.py`` (file-size compliance, the
``launch_confirmation.py`` precedent): the whole Codex CLI surface lives here -- the
``session start``/``resume`` Click options (composite decorators), the flag matrix,
and the dispatch + rendering over the command-core ops in
:mod:`forge.core.ops.codex_session`. ``session_lifecycle`` only branches on the
runtime and hands over its Click context.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import click

from forge.cli.output import print_error, print_error_with_tip, print_tip
from forge.cli.session import _get_active_session_entry, console
from forge.core.invoker import HeadlessResult
from forge.core.invoker.codex import CodexSandbox
from forge.core.naming import generate_unique_name
from forge.core.ops.codex_interactive import (
    CodexInteractiveLaunch,
    CodexInteractiveResult,
    reattach_codex_session,
    start_interactive_codex_session,
)
from forge.core.ops.codex_session import (
    CONTEXT_DELIVERY_HOOK,
    CONTEXT_DELIVERY_UNDELIVERED,
    CodexSessionResumeResult,
    CodexSessionStartResult,
    ContextDeliveryMode,
    continue_codex_session,
    start_codex_session,
)
from forge.core.ops.context import ExecutionContext, _cwd_forge_root
from forge.core.ops.session import ForgeOpError
from forge.session import SessionManager, SessionState

logger = logging.getLogger(__name__)


def _codex_ok(codex: HeadlessResult) -> bool:
    """True iff the Codex turn truly succeeded: the process exited 0 AND the JSONL stream
    reported no runtime error. ``HeadlessResult.success`` is returncode-only, so a
    ``turn.failed``/``error`` event riding an exit-0 would otherwise read as success.
    """
    return codex.success and not codex.runtime_is_error


def codex_start_options(f: Callable[..., Any]) -> Callable[..., Any]:
    """Codex-path Click options for ``session start`` (kept with their handler)."""
    options = [
        click.option(
            "--runtime",
            type=click.Choice(["claude", "codex"]),
            default="claude",
            help="Agent runtime for this session (default: claude).",
        ),
        click.option(
            "--resume-from",
            "resume_from",
            type=str,
            default=None,
            help="Parent session to derive context from (requires --runtime codex)",
        ),
        click.option(
            "--task",
            type=str,
            default=None,
            help="Task for the headless Codex turn (requires --runtime codex)",
        ),
        click.option(
            "--strategy",
            "transfer_strategy",
            type=click.Choice(["minimal", "structured", "full", "ai-curated"]),
            default=None,
            help="Transfer strategy for --resume-from (requires --runtime codex; default: ai-curated)",
        ),
        click.option(
            "--depth",
            type=int,
            default=None,
            help="Lineage traversal depth for --resume-from (requires --runtime codex; default: 1)",
        ),
        click.option(
            "--sandbox",
            type=click.Choice(["read-only", "workspace-write", "danger-full-access"]),
            default=None,
            help="Codex sandbox mode (requires --runtime codex; default: workspace-write)",
        ),
        # Click default stays None: reject_codex_flags_for_claude rejects any non-None
        # codex-only value on the Claude path, so the real default resolves below.
        click.option(
            "--context-delivery",
            "context_delivery",
            type=click.Choice(["initial-message", "hook"]),
            default=None,
            help=(
                "Transfer delivery for the first Codex turn (requires --runtime codex; "
                "default: initial-message). 'hook' needs a trust-enrolled "
                "codex-session-start hook."
            ),
        ),
    ]
    for option in reversed(options):
        f = option(f)
    return f


def codex_resume_options(f: Callable[..., Any]) -> Callable[..., Any]:
    """Codex-path Click options for ``session resume``."""
    return click.option(
        "--task",
        type=str,
        default=None,
        help="Task for the next headless Codex turn (Codex sessions only)",
    )(f)


def run_codex_start(ctx: click.Context) -> int:
    """Validate the ``--runtime codex`` flag matrix on ``session start`` and dispatch.

    Reads the start command's full parameter dict from ``ctx.params``; returns the
    process exit code. ``--task`` selects the headless ``codex exec`` turn (requires
    a parent); omitting it launches the interactive ``codex`` TUI (Phase 5), with or
    without a parent.
    """
    p = ctx.params
    if p["task"] and not p["resume_from"]:
        print_error(
            "--task requires --resume-from <parent> -- headless Codex turns "
            "derive from a parent session; omit --task for an interactive session",
            console=console,
        )
        return 1
    interactive = not p["task"]
    if interactive and not p["resume_from"]:
        # Bare interactive start: the transfer-shaping flags have no transfer to shape.
        for key, flag in [
            ("transfer_strategy", "--strategy"),
            ("depth", "--depth"),
            ("context_delivery", "--context-delivery"),
        ]:
            if p[key] is not None:
                print_error(f"{flag} requires --resume-from <parent>", console=console)
                return 1
    # Codex runs direct-to-OpenAI with no hooks: Claude routing, sidecar,
    # supervision, memory, and prompt-injection flags have no Codex meaning.
    rejected_for_codex: list[tuple[object, str]] = [
        (p["proxy_name"], "--proxy"),
        (p["direct"], "--no-proxy"),
        (p["sidecar"], "--sidecar"),
        (p["host_proxy"], "--host-proxy"),
        (p["subprocess_proxy"], "--subprocess-proxy"),
        (p["system_prompt"], "--system-prompt"),
        (p["system_prompt_file"], "--system-prompt-file"),
        (p["incognito"], "--incognito"),
        (p["direct_model"], "--model"),
        (p["no_launch"], "--no-launch"),
        (p["extensions"] is not None, "--extensions/--no-extensions"),
        (p["supervise_target"], "--supervise"),
        (p["supervisor_proxy"], "--supervisor-proxy"),
        (p["supervisor_direct"], "--no-supervisor-proxy"),
        (p["cascade_flag"], "--cascade"),
        (p["checker_model"], "--checker-model"),
        (p["checker_provider"], "--checker-provider"),
        (p["checker_effort"], "--checker-effort"),
        (p["supervisor_effort"], "--supervisor-effort"),
        (p["memory_flag"], "--memory"),
        (p["mounts"], "--mount"),
        (p["image"], "--image"),
    ]
    for value, flag in rejected_for_codex:
        if value:
            print_error(f"{flag} is not supported with --runtime codex", console=console)
            return 1
    if p["branch"] and not p["worktree"]:
        print_error("--branch requires --worktree", console=console)
        return 1

    from forge.cli.guards import require_main_repo_root, require_repo_root

    if p["worktree"]:
        require_main_repo_root()
    else:
        require_repo_root()
    name = p["name"]
    if name is None:
        _fr = _cwd_forge_root()
        existing = {n for n, _ in SessionManager().list_sessions(forge_root_filter=_fr)}
        name = generate_unique_name(existing)

    if interactive:
        return launch_interactive_codex_session(
            name=name,
            parent=p["resume_from"],
            strategy=p["transfer_strategy"] or "ai-curated",
            depth=p["depth"] if p["depth"] is not None else 1,
            sandbox=p["sandbox"] or "workspace-write",
            worktree=p["worktree"],
            branch=p["branch"],
            context_delivery=p["context_delivery"] or "initial-message",
        )
    return launch_codex_session(
        name=name,
        parent=p["resume_from"],
        task=p["task"],
        strategy=p["transfer_strategy"] or "ai-curated",
        depth=p["depth"] if p["depth"] is not None else 1,
        sandbox=p["sandbox"] or "workspace-write",
        worktree=p["worktree"],
        branch=p["branch"],
        context_delivery=p["context_delivery"] or "initial-message",
    )


def reject_codex_flags_for_claude(params: dict[str, Any]) -> int | None:
    """Reject codex-only start flags on the Claude path (don't silently ignore)."""
    for key, codex_flag in [
        ("resume_from", "--resume-from"),
        ("task", "--task"),
        ("transfer_strategy", "--strategy"),
        ("depth", "--depth"),
        ("sandbox", "--sandbox"),
        ("context_delivery", "--context-delivery"),
    ]:
        if params[key] is not None:
            print_error(f"{codex_flag} requires --runtime codex", console=console)
            return 1
    return None


def run_codex_resume(ctx: click.Context, name: str, task: str | None, manifest: SessionState) -> int:
    """Validate and dispatch ``session resume`` for a Codex-runtime session.

    ``--task`` runs the next headless ``codex exec`` turn (Phase 2, unchanged);
    omitting it reattaches the foreground TUI via ``codex resume <thread_id>``.
    Claude-only flags are rejected on explicit use (defaults pass through):
    silently ignoring them would hide a real user mistake.
    """
    claude_only_flags = [
        ("proxy_name", "--proxy"),
        ("direct", "--no-proxy"),
        ("direct_model", "--model"),
        ("fresh", "--fresh"),
        ("child_name", "--child-name"),
        ("strategy", "--strategy"),
        ("depth", "--depth"),
        ("resume_mode", "--resume-mode"),
        ("review", "--review"),
        ("force", "--force"),
        ("memory_flag", "--memory"),
    ]
    for param, flag in claude_only_flags:
        if ctx.get_parameter_source(param) == click.core.ParameterSource.COMMANDLINE:
            print_error(f"{flag} is not supported for Codex sessions", console=console)
            return 1
    if task:
        return resume_codex_session(name=name, task=task, sandbox="workspace-write")

    # Claude reconnect parity: refuse while a launch is still registered. No --force
    # escape -- two TUIs on one thread would interleave a single rollout.
    active_entry = _get_active_session_entry(name, forge_root=manifest.forge_root)
    if active_entry is not None:
        print_error(f"Cannot reconnect: session [bold]{name}[/bold] appears to still be active.", console=console)
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
        return 1

    return reattach_interactive_codex_session(name=name)


def launch_codex_session(
    *,
    name: str,
    parent: str,
    task: str,
    strategy: str,
    depth: int,
    sandbox: CodexSandbox,
    worktree: bool,
    branch: str | None,
    context_delivery: ContextDeliveryMode = "initial-message",
) -> int:
    """Run ``forge session start --runtime codex``; returns the process exit code."""
    try:
        result = start_codex_session(
            ctx=ExecutionContext.from_cwd(),
            name=name,
            parent=parent,
            task=task,
            strategy=strategy,
            depth=depth,
            sandbox=sandbox,
            create_worktree=worktree,
            branch=branch,
            context_delivery=context_delivery,
        )
    except ForgeOpError as e:
        print_error(f"{e}", console=console)
        return 1

    _render_start(result)
    if result.context_delivery == CONTEXT_DELIVERY_UNDELIVERED:
        # The turn ran WITHOUT the parent context -- the handoff failed even if the
        # codex turn itself succeeded. Fail loud (the session is kept).
        print_error_with_tip(
            f"The SessionStart hook did not deliver the transfer context; the first turn ran without it "
            f"(recorded context_delivery=hook_undelivered on '{result.session}').",
            "Enroll the hook (one-time 'codex' trust ceremony in this project), or delete and retry "
            "with the default delivery:",
            commands=[f"forge session delete {result.session}"],
            console=console,
        )
        return 1
    return 0 if _codex_ok(result.codex) else (result.codex.returncode or 1)


def resume_codex_session(*, name: str, task: str, sandbox: CodexSandbox) -> int:
    """Run ``forge session resume`` for a Codex session; returns the exit code."""
    try:
        result = continue_codex_session(
            ctx=ExecutionContext.from_cwd(),
            name=name,
            task=task,
            sandbox=sandbox,
        )
    except ForgeOpError as e:
        print_error(f"{e}", console=console)
        return 1

    _render_resume(result)
    return 0 if _codex_ok(result.codex) else (result.codex.returncode or 1)


def launch_interactive_codex_session(
    *,
    name: str,
    parent: str | None,
    strategy: str,
    depth: int,
    sandbox: CodexSandbox,
    worktree: bool,
    branch: str | None,
    context_delivery: ContextDeliveryMode = "initial-message",
) -> int:
    """Run the interactive (no ``--task``) form of ``session start --runtime codex``."""
    try:
        result = start_interactive_codex_session(
            ctx=ExecutionContext.from_cwd(),
            name=name,
            parent=parent,
            strategy=strategy,
            depth=depth,
            sandbox=sandbox,
            create_worktree=worktree,
            branch=branch,
            context_delivery=context_delivery,
            announce=_render_interactive_launch,
        )
    except ForgeOpError as e:
        print_error(f"{e}", console=console)
        return 1

    return _finish_interactive(result)


def reattach_interactive_codex_session(*, name: str) -> int:
    """Reattach a Codex session's thread as a foreground TUI (bare ``session resume``)."""
    try:
        result = reattach_codex_session(
            ctx=ExecutionContext.from_cwd(),
            name=name,
            sandbox="workspace-write",
            announce=_render_interactive_launch,
        )
    except ForgeOpError as e:
        print_error(f"{e}", console=console)
        return 1

    return _finish_interactive(result)


def _render_interactive_launch(launch: CodexInteractiveLaunch) -> None:
    """Pre-launch announce: the TUI takes the terminal next, so print context now."""
    if launch.reattach_thread_id:
        console.print(
            f"[green]Reattaching Codex session:[/green] {launch.session} (thread {launch.reattach_thread_id})"
        )
    elif launch.parent:
        console.print(f"[green]Created Codex session:[/green] {launch.session} (from '{launch.parent}')")
    else:
        console.print(f"[green]Created Codex session:[/green] {launch.session}")
    console.print("[dim]Routing: direct (OpenAI via codex CLI)[/dim]")
    if launch.worktree_path:
        console.print(f"[dim]Worktree: {launch.worktree_path}[/dim]")
    if launch.transfer_path:
        console.print(f"[dim]Transfer: {launch.transfer_path}[/dim]")
    if launch.context_delivery == "hook":
        console.print("[dim]Context delivery: SessionStart hook (receipt reconciled)[/dim]")


def _finish_interactive(result: CodexInteractiveResult) -> int:
    """Post-exit rendering shared by interactive start and reattach."""
    for warning in result.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")
    if result.thread_id:
        console.print(f"[dim]Thread: {result.thread_id}[/dim]")
    _render_interactive_post_exit(result)
    if result.context_delivery == CONTEXT_DELIVERY_UNDELIVERED:
        # The TUI ran WITHOUT the parent context. Fail loud (the session is kept).
        print_error_with_tip(
            f"The SessionStart hook did not deliver the transfer context; the session ran without it "
            f"(recorded context_delivery=hook_undelivered on '{result.session}').",
            "Enroll the hook (one-time 'codex' trust ceremony in this project), or delete and retry "
            "with the default delivery:",
            commands=[f"forge session delete {result.session}"],
            console=console,
        )
        return 1
    return result.exit_code


def _render_interactive_post_exit(result: CodexInteractiveResult) -> None:
    """Activity summary + reconnect tip via the shared post-exit renderer. Best-effort.

    Lazy import: ``session_lifecycle`` top-level-imports this module, so importing
    ``_post_exit_render`` back at module level would be a cycle.
    """
    try:
        from forge.cli.session_lifecycle import _post_exit_render

        manifest = SessionManager().get_session(result.session, forge_root=result.forge_root)
        _post_exit_render(
            manifest,
            store_exists=True,
            exit_code=result.exit_code,
            since=result.operation_started_at,
        )
    except Exception:
        logger.debug("interactive post-exit render failed", exc_info=True)


def _render_start(result: CodexSessionStartResult) -> None:
    console.print(f"[green]Created Codex session:[/green] {result.session} (from '{result.parent}')")
    console.print("[dim]Routing: direct (OpenAI via codex CLI)[/dim]")
    if result.worktree_path:
        console.print(f"[dim]Worktree: {result.worktree_path}[/dim]")
    console.print(f"[dim]Transfer: {result.transfer_path}[/dim]")
    if result.context_delivery == CONTEXT_DELIVERY_HOOK:
        console.print("[dim]Context delivery: SessionStart hook (receipt reconciled)[/dim]")
    if result.thread_id:
        console.print(f"[dim]Thread: {result.thread_id}[/dim]")
    _render_codex_outcome(result.codex.stdout, _codex_ok(result.codex), result.codex.stderr)
    for warning in result.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")
    if result.thread_id and _codex_ok(result.codex):
        print_tip(
            f"Run 'forge session resume {result.session} --task <next step>' to continue this thread.",
            console=console,
        )


def _render_resume(result: CodexSessionResumeResult) -> None:
    console.print(f"[green]Resumed Codex session:[/green] {result.session} (thread {result.thread_id})")
    _render_codex_outcome(result.codex.stdout, _codex_ok(result.codex), result.codex.stderr)
    for warning in result.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")


def _render_codex_outcome(stdout: str, ok: bool, stderr: str) -> None:
    if stdout:
        console.print()
        console.print(stdout)
    if not ok:
        console.print(f"[red]Codex turn failed.[/red] {stderr or ''}".rstrip())

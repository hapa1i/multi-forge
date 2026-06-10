"""CLI front for Codex-runtime sessions (codex_frontend Phase 2).

Split from ``session_lifecycle.py`` (file-size compliance, the
``launch_confirmation.py`` precedent): the whole Codex CLI surface lives here -- the
``session start``/``resume`` Click options (composite decorators), the flag matrix,
and the dispatch + rendering over the command-core ops in
:mod:`forge.core.ops.codex_session`. ``session_lifecycle`` only branches on the
runtime and hands over its Click context.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click

from forge.cli.output import print_tip
from forge.cli.session import console
from forge.core.invoker.codex import CodexSandbox
from forge.core.ops.codex_session import (
    CodexSessionResumeResult,
    CodexSessionStartResult,
    continue_codex_session,
    start_codex_session,
)
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import ForgeOpError


def _sess() -> Any:
    """Access forge.cli.session at runtime so tests can patch its attributes."""
    import forge.cli.session

    return forge.cli.session


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
    process exit code.
    """
    p = ctx.params
    if not p["resume_from"]:
        console.print(
            "[red]Error:[/red] --runtime codex requires --resume-from <parent> "
            "(starting Codex without a parent session is not yet supported)"
        )
        return 1
    if not p["task"]:
        console.print("[red]Error:[/red] --runtime codex requires --task (the headless Codex turn needs a prompt)")
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
        (p["memory_flag"], "--memory"),
        (p["mounts"], "--mount"),
        (p["image"], "--image"),
    ]
    for value, flag in rejected_for_codex:
        if value:
            console.print(f"[red]Error:[/red] {flag} is not supported with --runtime codex")
            return 1
    if p["branch"] and not p["worktree"]:
        console.print("[red]Error:[/red] --branch requires --worktree")
        return 1

    from forge.cli.guards import require_main_repo_root, require_repo_root

    if p["worktree"]:
        require_main_repo_root()
    else:
        require_repo_root()
    name = p["name"]
    if name is None:
        _fr = _sess()._cwd_forge_root()
        existing = {n for n, _ in _sess().SessionManager().list_sessions(forge_root_filter=_fr)}
        name = _sess().generate_unique_name(existing)

    return launch_codex_session(
        name=name,
        parent=p["resume_from"],
        task=p["task"],
        strategy=p["transfer_strategy"] or "ai-curated",
        depth=p["depth"] if p["depth"] is not None else 1,
        sandbox=p["sandbox"] or "workspace-write",
        worktree=p["worktree"],
        branch=p["branch"],
    )


def reject_codex_flags_for_claude(params: dict[str, Any]) -> int | None:
    """Reject codex-only start flags on the Claude path (don't silently ignore)."""
    for key, codex_flag in [
        ("resume_from", "--resume-from"),
        ("task", "--task"),
        ("transfer_strategy", "--strategy"),
        ("depth", "--depth"),
        ("sandbox", "--sandbox"),
    ]:
        if params[key] is not None:
            console.print(f"[red]Error:[/red] {codex_flag} requires --runtime codex")
            return 1
    return None


def run_codex_resume(ctx: click.Context, name: str, task: str | None) -> int:
    """Validate and dispatch ``session resume`` for a Codex-runtime session.

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
            console.print(f"[red]Error:[/red] {flag} is not supported for Codex sessions")
            return 1
    if not task:
        console.print(
            "[red]Error:[/red] resuming a Codex session requires --task (the next headless turn needs a prompt)"
        )
        return 1

    return resume_codex_session(name=name, task=task, sandbox="workspace-write")


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
        )
    except ForgeOpError as e:
        console.print(f"[red]Error:[/red] {e}")
        return 1

    _render_start(result)
    return result.codex.returncode if not result.codex.success else 0


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
        console.print(f"[red]Error:[/red] {e}")
        return 1

    _render_resume(result)
    return result.codex.returncode if not result.codex.success else 0


def _render_start(result: CodexSessionStartResult) -> None:
    console.print(f"[green]Created Codex session:[/green] {result.session} (from '{result.parent}')")
    console.print("[dim]Routing: direct (OpenAI via codex CLI)[/dim]")
    if result.worktree_path:
        console.print(f"[dim]Worktree: {result.worktree_path}[/dim]")
    console.print(f"[dim]Transfer: {result.transfer_path}[/dim]")
    if result.thread_id:
        console.print(f"[dim]Thread: {result.thread_id}[/dim]")
    _render_codex_outcome(result.codex.stdout, result.codex.success, result.codex.stderr)
    for warning in result.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")
    if result.thread_id and result.codex.success:
        print_tip(
            f"Run 'forge session resume {result.session} --task <next step>' to continue this thread.",
            console=console,
        )


def _render_resume(result: CodexSessionResumeResult) -> None:
    console.print(f"[green]Resumed Codex session:[/green] {result.session} (thread {result.thread_id})")
    _render_codex_outcome(result.codex.stdout, result.codex.success, result.codex.stderr)
    for warning in result.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")


def _render_codex_outcome(stdout: str, success: bool, stderr: str) -> None:
    if stdout:
        console.print()
        console.print(stdout)
    if not success:
        console.print(f"[red]Codex turn failed.[/red] {stderr or ''}".rstrip())

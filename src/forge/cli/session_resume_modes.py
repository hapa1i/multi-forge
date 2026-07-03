"""Fresh resume launch helpers for native-style resume modes."""

from __future__ import annotations

import sys
from pathlib import Path

from forge.cli.output import console, handle_session_error, print_error_with_tip
from forge.cli.session_routing import ResolvedRouting
from forge.core.ops.claude_session import ClaudeResumeAction, ResumeLaunchPlan
from forge.core.paths import display_path
from forge.session import ForgeSessionError, SessionManager, SessionState
from forge.session.context_limit import _resolve_context_limit
from forge.session.launch import _combine_prompt_files

from .session_rewind import _prepare_rewind_launch_artifacts


def _resume_fresh_rewind(
    *,
    manager: SessionManager,
    parent: str,
    parent_state: SessionState,
    child_name: str | None,
    drop_last: int,
    routing: ResolvedRouting | None,
    direct: bool,
    direct_model_override: str | None = None,
    memory_flag: bool | None = None,
) -> None:
    """Create a child session that resumes from a truncated parent transcript copy."""
    from forge.cli.session import _get_effective_proxy_for_session
    from forge.cli.session_lifecycle import (
        _execute_resume_launch_plan,
        _get_resume_launch_preferences,
        _resolve_manifest_prompt_file,
        _resume_launch_preferences_for_op,
        _resume_routing_for_op,
    )

    if routing:
        effective_proxy_ref = routing.proxy_id
    elif direct:
        effective_proxy_ref = None
    else:
        effective_template, _, effective_proxy_id = _get_effective_proxy_for_session(parent_state)
        effective_proxy_ref = effective_proxy_id or effective_template

    context_limit = _resolve_context_limit(effective_proxy_ref)

    try:
        child_manifest, transfer_result = manager.resume_session(
            parent,
            child_name=child_name,
            resume_mode="native",
            forge_root=parent_state.forge_root,
            memory_flag=memory_flag,
        )
    except ForgeSessionError as e:
        handle_session_error(e)
        return

    parent_uuid = parent_state.confirmed.claude_session_id
    assert parent_uuid is not None  # caller validated
    rewind_artifacts = _prepare_rewind_launch_artifacts(
        manifest=child_manifest,
        parent_name=parent,
        parent_state=parent_state,
        parent_uuid=parent_uuid,
        drop_last=drop_last,
    )

    if transfer_result.warnings:
        for warning in transfer_result.warnings:
            console.print(f"[yellow]Warning:[/yellow] {warning}")
    for warning in rewind_artifacts.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")

    console.print(f"Created derived session [green]{child_manifest.name}[/green] from [cyan]{parent}[/cyan]")
    if rewind_artifacts.rewind_relocated_session_id is not None:
        console.print(f"[dim]Mode: Rewind native resume (--drop-last {drop_last})[/dim]")
    else:
        console.print("[dim]Mode: Native resume fallback (full conversation history via --fork-session)[/dim]")
    if rewind_artifacts.context_path is not None:
        console.print(f"  Context:  {display_path(rewind_artifacts.context_path)}")
    console.print()

    prompt_files: list[Path] = []
    child_worktree_path = Path(child_manifest.worktree.path) if child_manifest.worktree else Path.cwd()
    configured_prompt = _resolve_manifest_prompt_file(child_manifest)
    if configured_prompt is not None:
        prompt_files.append(configured_prompt)
    if rewind_artifacts.context_path is not None:
        prompt_files.append(rewind_artifacts.context_path)
    prompt_file = _combine_prompt_files(
        worktree_path=child_worktree_path,
        session_name=child_manifest.name,
        prompt_files=prompt_files,
    )

    use_sidecar, mounts, image = _get_resume_launch_preferences(child_manifest, direct=direct)
    if use_sidecar:
        print_error_with_tip(
            "--strategy rewind is not supported with sidecar mode.",
            "Rewind writes to the host ~/.claude store; run in host mode (e.g. --no-proxy) or use transfer mode.",
            console=console,
        )
        sys.exit(1)
    _execute_resume_launch_plan(
        manager=manager,
        plan=ResumeLaunchPlan(
            manifest=child_manifest,
            routing=_resume_routing_for_op(routing),
            direct=direct,
            resume_id=rewind_artifacts.resume_id,
            session_id=None,
            fork_session=True,
            prompt_file=Path(prompt_file) if prompt_file else None,
            action=ClaudeResumeAction.FRESH_DERIVED,
            context_limit=context_limit,
            launch_preferences=_resume_launch_preferences_for_op(use_sidecar, mounts, image),
            direct_model_override=direct_model_override,
            parent_name=parent,
        ),
    )


def _resume_fresh_native(
    *,
    manager: SessionManager,
    parent: str,
    parent_state: SessionState,
    child_name: str | None,
    routing: ResolvedRouting | None,
    direct: bool,
    direct_model_override: str | None = None,
    memory_flag: bool | None = None,
) -> None:
    """Create a child session with native conversation resume."""
    from forge.cli.session import _get_effective_proxy_for_session
    from forge.cli.session_lifecycle import (
        _execute_resume_launch_plan,
        _get_resume_launch_preferences,
        _resume_launch_preferences_for_op,
        _resume_routing_for_op,
    )

    if routing:
        effective_proxy_ref = routing.proxy_id
    elif direct:
        effective_proxy_ref = None
    else:
        effective_template, _, effective_proxy_id = _get_effective_proxy_for_session(parent_state)
        effective_proxy_ref = effective_proxy_id or effective_template

    context_limit = _resolve_context_limit(effective_proxy_ref)

    try:
        child_manifest, transfer_result = manager.resume_session(
            parent,
            child_name=child_name,
            resume_mode="native",
            forge_root=parent_state.forge_root,
            memory_flag=memory_flag,
        )
    except ForgeSessionError as e:
        handle_session_error(e)
        return

    if transfer_result.warnings:
        for warning in transfer_result.warnings:
            console.print(f"[yellow]Warning:[/yellow] {warning}")

    parent_uuid = parent_state.confirmed.claude_session_id
    assert parent_uuid is not None  # caller validated

    console.print(f"Created derived session [green]{child_manifest.name}[/green] from [cyan]{parent}[/cyan]")
    console.print("[dim]Mode: Native resume (full conversation history via --fork-session)[/dim]")
    console.print()

    use_sidecar, mounts, image = _get_resume_launch_preferences(child_manifest, direct=direct)
    _execute_resume_launch_plan(
        manager=manager,
        plan=ResumeLaunchPlan(
            manifest=child_manifest,
            routing=_resume_routing_for_op(routing),
            direct=direct,
            resume_id=parent_uuid,
            session_id=None,
            fork_session=True,
            prompt_file=None,
            action=ClaudeResumeAction.FRESH_DERIVED,
            context_limit=context_limit,
            launch_preferences=_resume_launch_preferences_for_op(use_sidecar, mounts, image),
            direct_model_override=direct_model_override,
            parent_name=parent,
        ),
    )

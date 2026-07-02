"""Claude session command-core helpers.

This module is the first slice of moving Claude session launch/resume behavior
out of the CLI layer. Helpers here must stay UI-agnostic and let callers render
errors.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from forge.core.reactive.env import (
    InteractiveApiKeyDecision,
    compute_interactive_api_key_decision,
)
from forge.session import (
    LAUNCH_MODE_HOST,
    LAUNCH_MODE_SIDECAR,
    SessionState,
    SessionStore,
    run_with_active_session,
)
from forge.session.addendum import (
    resolve_addendum_content_for_proxy,
    write_managed_addendum,
)
from forge.session.claude import build_claude_args, invoke_claude
from forge.session.direct_model import (
    apply_direct_model_env,
    apply_proxy_context_model_defaults,
)
from forge.session.launch import (
    _build_session_env,
    _combine_prompt_files,
    _prepare_sidecar_prompt_file,
)
from forge.session.launch_confirmation import (
    _infer_launch_confirmation,
    _routing_mode_for,
    read_proxy_cost_baseline,
    record_launch_confirmed,
)
from forge.session.model_pin import _apply_direct_model_env_if_supported

from .session import ForgeOpError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaudeSidecarLaunch:
    """Render payload emitted immediately before a sidecar launch."""

    image: str
    proxy_id: str | None
    intercept_mode: str | None = None
    audit_path: Path | None = None


@dataclass(frozen=True)
class ClaudeSessionLaunchResult:
    """Outcome of an interactive Claude launch."""

    exit_code: int
    session: str
    manifest: SessionState
    worktree_path: str | None
    warnings: tuple[str, ...]
    operation_started_at: datetime
    routing_mode: str
    proxy_id: str | None
    base_url: str | None
    is_sandboxed: bool
    claude_project_root: str | None
    store_exists: bool


def resolve_and_validate_system_prompt(
    *,
    system_prompt: str | None,
    system_prompt_file: str | None,
    cwd: Path,
) -> Path | None:
    """Resolve launch-only system-prompt input to a prompt file path."""
    if system_prompt_file:
        prompt_path = Path(system_prompt_file)
        if not prompt_path.is_absolute():
            prompt_path = cwd / prompt_path
        return prompt_path.resolve()

    if system_prompt:
        claude_dir = cwd / ".claude"
        claude_dir.mkdir(exist_ok=True)
        prompt_file_path = claude_dir / "forge.system-prompt.generated.md"
        prompt_file_path.write_text(system_prompt)
        return prompt_file_path

    return None


def launch_claude_session(
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
    before_launch: Callable[[Path], None] | None = None,
    on_sidecar_launch: Callable[[ClaudeSidecarLaunch], None] | None = None,
    invoke: Callable[..., int] | None = None,
    run_active: Callable[..., int] | None = None,
) -> ClaudeSessionLaunchResult:
    """Launch Claude for a session, handling sidecar/host split without rendering."""
    _runtime = manifest.intent.launch.runtime if manifest.intent.launch else "claude_code"
    if _runtime != "claude_code":
        raise ForgeOpError(
            f"session '{manifest.name}' has runtime '{_runtime}' "
            "and cannot be launched with Claude. Use the matching runtime command."
        )

    worktree_path = Path(manifest.worktree.path) if manifest.worktree else Path.cwd()
    forge_root = Path(manifest.forge_root) if manifest.forge_root else worktree_path

    from forge.session.claude.paths import resolve_claude_project_root

    launch_root = Path(resolve_claude_project_root(manifest))
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
        proxy_id=proxy_id,
        fork_name=fork_name,
        parent_session=parent_session,
        forge_root=manifest.forge_root,
        subprocess_proxy=manifest.intent.subprocess_proxy,
        sidecar=use_sidecar,
    )
    if runtime_base_url is not None:
        apply_proxy_context_model_defaults(env_vars, context_limit)

    if before_launch is not None:
        before_launch(forge_root)

    addendum_content = resolve_addendum_content_for_proxy(proxy_id)
    if addendum_content:
        addendum_path = write_managed_addendum(forge_root, manifest.name, addendum_content)
        prompt_files = [addendum_path]
        if system_prompt_file:
            prompt_files.append(Path(system_prompt_file))
        system_prompt_file = _combine_prompt_files(
            worktree_path=worktree_path,
            session_name=manifest.name,
            prompt_files=prompt_files,
        )

    store = SessionStore(str(forge_root), manifest.name)

    if not manifest.confirmed.claude_project_root:
        _lr = str(launch_root)
        store.update(
            timeout_s=5.0,
            mutate=lambda m: setattr(m.confirmed, "claude_project_root", _lr),
        )

    launch_started_at = datetime.now(timezone.utc)
    active_runner = run_active or run_with_active_session
    warnings: list[str] = []

    if use_sidecar:
        return _run_sidecar_claude_session(
            manifest=manifest,
            store=store,
            session_id=session_id,
            resume_id=resume_id,
            effective_template=effective_template,
            runtime_base_url=runtime_base_url,
            context_limit=context_limit,
            mounts=mounts,
            image=image,
            fork_session=fork_session,
            system_prompt_file=system_prompt_file,
            name=name,
            extra_args=extra_args,
            proxy_id=proxy_id,
            worktree_path=worktree_path,
            launch_root=launch_root,
            launch_started_at=launch_started_at,
            env_vars=env_vars,
            active_runner=active_runner,
            on_sidecar_launch=on_sidecar_launch,
            warnings=warnings,
        )

    return _run_host_claude_session(
        manifest=manifest,
        store=store,
        session_id=session_id,
        resume_id=resume_id,
        runtime_base_url=runtime_base_url,
        proxy_id=proxy_id,
        context_limit=context_limit,
        fork_session=fork_session,
        system_prompt_file=system_prompt_file,
        name=name,
        extra_args=extra_args,
        worktree_path=worktree_path,
        launch_root=launch_root,
        launch_started_at=launch_started_at,
        env_vars=env_vars,
        unset_env_vars=unset_env_vars,
        active_runner=active_runner,
        invoke=invoke or invoke_claude,
        warnings=warnings,
    )


def _run_sidecar_claude_session(
    *,
    manifest: SessionState,
    store: SessionStore,
    session_id: str | None,
    resume_id: str | None,
    effective_template: str | None,
    runtime_base_url: str | None,
    context_limit: int,
    mounts: tuple[str, ...],
    image: str | None,
    fork_session: bool,
    system_prompt_file: str | None,
    name: str | None,
    extra_args: list[str] | None,
    proxy_id: str | None,
    worktree_path: Path,
    launch_root: Path,
    launch_started_at: datetime,
    env_vars: dict[str, str],
    active_runner: Callable[..., int],
    on_sidecar_launch: Callable[[ClaudeSidecarLaunch], None] | None,
    warnings: list[str],
) -> ClaudeSessionLaunchResult:
    if effective_template is None or runtime_base_url is None:
        raise ForgeOpError("Direct sessions are not supported with --sidecar")

    if proxy_id is None and runtime_base_url is not None:
        try:
            from forge.proxy.proxies import ProxyRegistryStore as _PStore

            _entry = _PStore().find_by_base_url(runtime_base_url)
            if _entry is not None:
                proxy_id = _entry.proxy_id
        except Exception:
            pass

    from forge.sidecar import get_secrets_for_template, run_sidecar_session
    from forge.sidecar.container import ContainerExistsError, parse_mounts
    from forge.sidecar.docker import is_docker_available

    if not is_docker_available():
        raise ForgeOpError("Docker is not available or not running")

    store.update(timeout_s=5.0, mutate=lambda m: setattr(m.confirmed, "is_sandboxed", True))

    try:
        extra_mounts = parse_mounts(mounts) if mounts else []
    except ValueError as e:
        raise ForgeOpError(str(e)) from e

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
            pass

    from forge.runtime_config import get_runtime_config

    _runtime_config = get_runtime_config()
    _omit_interactive_key = _runtime_config.interactive_anthropic_api_key == "omit"
    if _omit_interactive_key:
        container_env["FORGE_OMIT_INTERACTIVE_KEY"] = "1"

    if _omit_interactive_key:
        _sidecar_key = InteractiveApiKeyDecision(available=False, source="omitted_by_config")
    else:
        _has_container_key = bool(container_env.get("ANTHROPIC_API_KEY"))
        _sidecar_key = InteractiveApiKeyDecision(
            available=_has_container_key,
            source="env" if _has_container_key else "none",
        )
    _sidecar_cost_baseline = read_proxy_cost_baseline(runtime_base_url)
    record_launch_confirmed(
        store,
        routing_mode="proxy",
        proxy_id=proxy_id,
        base_url=runtime_base_url,
        decision=_sidecar_key,
        proxy_cost_baseline_micros=_sidecar_cost_baseline.cost_micros if _sidecar_cost_baseline else None,
        proxy_cost_baseline_started_at=_sidecar_cost_baseline.started_at if _sidecar_cost_baseline else None,
    )

    sidecar_image = image or _runtime_config.sidecar_image
    if on_sidecar_launch is not None:
        on_sidecar_launch(_build_sidecar_launch_payload(sidecar_image, proxy_id))

    try:
        sidecar_exit = active_runner(
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
                proxy_id=proxy_id,
                extra_mounts=all_mounts,
                context_limit=context_limit,
                env_vars=container_env,
                claude_args=claude_args,
            ),
        )
    except ContainerExistsError as e:
        store.update(timeout_s=5.0, mutate=lambda m: setattr(m.confirmed, "is_sandboxed", False))
        raise ForgeOpError(str(e)) from e
    except Exception:
        store.update(timeout_s=5.0, mutate=lambda m: setattr(m.confirmed, "is_sandboxed", False))
        raise

    return ClaudeSessionLaunchResult(
        exit_code=sidecar_exit,
        session=manifest.name,
        manifest=manifest,
        worktree_path=str(worktree_path),
        warnings=tuple(warnings),
        operation_started_at=launch_started_at,
        routing_mode="proxy",
        proxy_id=proxy_id,
        base_url=runtime_base_url,
        is_sandboxed=True,
        claude_project_root=str(launch_root),
        store_exists=store.exists(),
    )


def _run_host_claude_session(
    *,
    manifest: SessionState,
    store: SessionStore,
    session_id: str | None,
    resume_id: str | None,
    runtime_base_url: str | None,
    proxy_id: str | None,
    context_limit: int,
    fork_session: bool,
    system_prompt_file: str | None,
    name: str | None,
    extra_args: list[str] | None,
    worktree_path: Path,
    launch_root: Path,
    launch_started_at: datetime,
    env_vars: dict[str, str],
    unset_env_vars: list[str],
    active_runner: Callable[..., int],
    invoke: Callable[..., int],
    warnings: list[str],
) -> ClaudeSessionLaunchResult:
    store.update(timeout_s=5.0, mutate=lambda m: setattr(m.confirmed, "is_sandboxed", False))

    if proxy_id is None and runtime_base_url is not None:
        try:
            from forge.proxy.proxies import ProxyRegistryStore as _PRS

            _entry = _PRS().find_by_base_url(runtime_base_url)
            if _entry is not None:
                proxy_id = _entry.proxy_id
        except Exception:
            logger.debug("proxy_id recovery from base_url failed", exc_info=True)

    routing_mode = _routing_mode_for(runtime_base_url, proxy_id)
    _proxy_cost_baseline = read_proxy_cost_baseline(runtime_base_url)
    record_launch_confirmed(
        store,
        routing_mode=routing_mode,
        proxy_id=proxy_id,
        base_url=runtime_base_url,
        decision=compute_interactive_api_key_decision(interactive=True),
        proxy_cost_baseline_micros=_proxy_cost_baseline.cost_micros if _proxy_cost_baseline else None,
        proxy_cost_baseline_started_at=_proxy_cost_baseline.started_at if _proxy_cost_baseline else None,
    )

    if runtime_base_url is None:
        from forge.runtime_config import get_default_direct_model

        direct_model = manifest.intent.launch.direct_model if manifest.intent.launch else None
        direct_model = direct_model or get_default_direct_model()
        error = apply_direct_model_env(env_vars, direct_model)
        if error:
            raise ForgeOpError(error)
    elif manifest.intent.launch and manifest.intent.launch.direct_model and proxy_id:
        error = _apply_direct_model_env_if_supported(env_vars, proxy_id, manifest.intent.launch.direct_model)
        if error:
            raise ForgeOpError(error)

    exit_code = active_runner(
        session_name=manifest.name,
        worktree_path=worktree_path,
        launch_mode=LAUNCH_MODE_HOST,
        forge_root=manifest.forge_root,
        claude_session_id=session_id,
        runner=lambda: invoke(
            session_id=session_id,
            resume_id=resume_id,
            fork_session=fork_session,
            name=name,
            model=None,
            system_prompt_file=system_prompt_file,
            env_vars=env_vars,
            unset_env_vars=unset_env_vars,
            extra_args=extra_args,
            cwd=str(launch_root),
        ),
    )
    if exit_code == 0 and not fork_session:
        _infer_launch_confirmation(store=store, manifest=manifest, session_id=resume_id or session_id)

    return ClaudeSessionLaunchResult(
        exit_code=exit_code,
        session=manifest.name,
        manifest=manifest,
        worktree_path=str(worktree_path),
        warnings=tuple(warnings),
        operation_started_at=launch_started_at,
        routing_mode=routing_mode,
        proxy_id=proxy_id,
        base_url=runtime_base_url,
        is_sandboxed=False,
        claude_project_root=str(launch_root),
        store_exists=store.exists(),
    )


def _build_sidecar_launch_payload(sidecar_image: str, proxy_id: str | None) -> ClaudeSidecarLaunch:
    intercept_mode: str | None = None
    audit_path: Path | None = None
    if proxy_id:
        try:
            from forge.config.loader import load_proxy_instance_config

            _icfg = load_proxy_instance_config(proxy_id)
            if _icfg is not None:
                intercept_mode = _icfg.intercept.mode
                if _icfg.intercept.mode != "passthrough":
                    from forge.core.paths import get_forge_home

                    audit_path = get_forge_home() / "audit"
        except Exception:
            logger.debug("sidecar intercept preflight failed", exc_info=True)
    return ClaudeSidecarLaunch(
        image=sidecar_image,
        proxy_id=proxy_id,
        intercept_mode=intercept_mode,
        audit_path=audit_path,
    )

"""Claude session command-core helpers.

This module is the first slice of moving Claude session launch/resume behavior
out of the CLI layer. Helpers here must stay UI-agnostic and let callers render
errors.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from forge.core.reactive.env import (
    InteractiveApiKeyDecision,
    compute_interactive_api_key_decision,
)
from forge.core.state import FileLockTimeoutError
from forge.core.state.exceptions import StateCorruptedError, StateUnreadableError
from forge.session import (
    LAUNCH_MODE_HOST,
    LAUNCH_MODE_SIDECAR,
    ForgeSessionError,
    SessionManager,
    SessionState,
    SessionStore,
    run_with_active_session,
)
from forge.session.addendum import (
    resolve_addendum_content_for_proxy,
    write_managed_addendum,
)
from forge.session.claude import build_claude_args, invoke_claude
from forge.session.context_limit import _resolve_context_limit
from forge.session.direct_model import (
    apply_direct_model_env,
    apply_proxy_context_model_defaults,
)
from forge.session.exceptions import (
    BranchExistsError,
    InvalidBranchNameError,
    InvalidSessionNameError,
    ManifestCorruptedError,
    ManifestValidationError,
    SessionExistsError,
    SessionFileNotFoundError,
    WorktreePathExistsError,
)
from forge.session.launch import (
    _build_session_env,
    _combine_prompt_files,
    _get_runtime_base_url,
    _prepare_sidecar_prompt_file,
    _resolve_worktree_extension_root,
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
    # Reserved for start-op reconciliation warnings; the bridge path emits none today.
    warnings: tuple[str, ...]
    operation_started_at: datetime
    routing_mode: str
    proxy_id: str | None
    base_url: str | None
    is_sandboxed: bool
    claude_project_root: str | None
    store_exists: bool


class ClaudeStartError(ForgeOpError):
    """Session-creation failure carrying a structured recovery tip for the CLI to render.

    The op stays render-free, so the specific ``Tip:`` shown for SessionExists /
    BranchExists / WorktreePathExists is carried as data and rendered by the caller.
    """

    def __init__(
        self,
        message: str,
        *,
        tip_lines: tuple[str, ...] = (),
        commands: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.tip_lines = tip_lines
        self.commands = commands


@dataclass(frozen=True)
class ClaudeStartCreated:
    """Render payload for the post-create routing/worktree summary."""

    session: str
    incognito: bool
    proxy_display: str | None
    effective_template: str | None
    runtime_base_url: str | None
    worktree_path: str | None  # None unless the session owns a worktree
    worktree_branch: str | None
    supervise_target: str | None


@dataclass(frozen=True)
class ClaudeStartExtensions:
    """Render payload for the extension-inheritance decision (install or tip)."""

    is_worktree: bool
    extension_root: Path | None
    extensions_flag: bool | None


@dataclass(frozen=True)
class SupervisorWiring:
    """CLI-validated supervisor inputs threaded into the create transaction (row 4)."""

    target: str
    source_state: SessionState
    supervisor_proxy: str | None
    supervisor_direct: bool
    cascade: bool
    checker_model: str | None
    checker_provider: str | None
    checker_effort: str | None
    supervisor_effort: str | None
    supervisor_runtime: str | None


class ClaudeIncognitoCleanupPresenter(Protocol):
    """Render hooks for incognito cleanup owned by interactive ops."""

    def on_incognito_cleanup_start(self) -> None: ...
    def on_incognito_cleanup_ok(self) -> None: ...
    def on_incognito_cleanup_warning(self, message: str) -> None: ...


class ClaudeStartPresenter(ClaudeIncognitoCleanupPresenter, Protocol):
    """Render hooks the CLI implements so the op can stay render-free.

    Ordering matters: ``on_created`` -> ``on_extensions`` -> (``on_no_launch`` |
    launch). On a launch failure ``on_launch_error`` fires BEFORE the incognito
    cleanup hooks, preserving today's error-then-cleanup output order.
    """

    def on_created(self, event: ClaudeStartCreated) -> None: ...
    def on_extensions(self, event: ClaudeStartExtensions) -> None: ...
    def on_no_launch(self) -> None: ...
    def before_launch(self, forge_root: Path) -> None: ...
    def on_sidecar_launch(self, event: ClaudeSidecarLaunch) -> None: ...
    def on_launch_error(self, error: ForgeOpError) -> None: ...


@dataclass(frozen=True)
class ClaudeSessionStartResult:
    """Outcome of ``start_claude_session`` (create + optional interactive launch)."""

    exit_code: int
    session: str
    manifest: SessionState
    operation_started_at: datetime
    did_run: bool  # True only when the child actually launched -> CLI post-exit renders
    store_exists: bool
    worktree_path: str | None
    warnings: tuple[str, ...]


class ClaudeResumeAction(Enum):
    """Structured resume actions the CLI maps to existing display text."""

    FORK_PARENT_CONVERSATION = "fork_parent_conversation"
    START_FRESH = "start_fresh"
    START_FRESH_WITH_PARENT_CONTEXT = "start_fresh_with_parent_context"
    RECONNECT = "reconnect"
    RELAUNCH_AS_CHILD = "relaunch_as_child"
    FRESH_DERIVED = "fresh_derived"


@dataclass(frozen=True)
class ClaudeResumeRouting:
    """CLI-resolved routing override carried into the render-free resume op."""

    template: str | None = None
    base_url: str | None = None
    proxy_id: str | None = None


@dataclass(frozen=True)
class ClaudeLaunchPreferences:
    """CLI-computed launch preferences for resume paths."""

    use_sidecar: bool
    mounts: tuple[str, ...]
    image: str | None


@dataclass(frozen=True)
class ResumeLaunchPlan:
    """Mode-specific resume facts prepared by the CLI before the shared launch tail."""

    manifest: SessionState
    routing: ClaudeResumeRouting | None
    direct: bool
    resume_id: str | None
    session_id: str | None
    fork_session: bool
    prompt_file: Path | None
    action: ClaudeResumeAction
    context_limit: int
    launch_preferences: ClaudeLaunchPreferences
    direct_model_override: str | None = None
    parent_name: str | None = None
    prompt_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ForkLaunchPlan:
    """Prepared fork launch facts passed from the CLI into the render-free op."""

    manifest: SessionState
    session_id: str | None
    resume_id: str | None
    fork_session: bool | None
    register_fork: bool
    prompt_file: Path | None
    context_limit: int
    launch_preferences: ClaudeLaunchPreferences
    effective_template: str | None
    runtime_base_url: str | None
    proxy_id: str | None
    incognito: bool
    render_post_exit: bool


@dataclass(frozen=True)
class ResumePrepared:
    """Render payload emitted after shared resume mutations and before launch."""

    session: str
    action: ClaudeResumeAction
    parent_name: str | None
    resume_id: str | None
    effective_template: str | None
    runtime_base_url: str | None
    worktree_path: Path
    worktree_branch: str | None
    is_worktree: bool
    context_path: Path | None
    prompt_warnings: tuple[str, ...]


@dataclass(frozen=True)
class ClaudeResumeWarning:
    """Pre-launch warning emitted by the resume op without carrying UI formatting."""

    message: str
    tip: str | None = None


class ClaudeResumePresenter(Protocol):
    """Render hooks the CLI implements for resume launches."""

    def on_warning(self, warning: ClaudeResumeWarning) -> None: ...
    def on_resume_prepared(self, event: ResumePrepared) -> None: ...
    def before_launch(self, forge_root: Path) -> None: ...
    def on_sidecar_launch(self, event: ClaudeSidecarLaunch) -> None: ...
    def on_launch_error(self, error: ForgeOpError) -> None: ...


class ClaudeForkPresenter(ClaudeIncognitoCleanupPresenter, Protocol):
    """Render hooks the CLI implements for fork launches."""

    def before_launch(self, forge_root: Path) -> None: ...
    def on_sidecar_launch(self, event: ClaudeSidecarLaunch) -> None: ...
    def on_launch_error(self, error: ForgeOpError) -> None: ...


@dataclass(frozen=True)
class ClaudeResumeResult:
    """Outcome of ``resume_claude_session`` shared launch tail."""

    exit_code: int
    session: str
    manifest: SessionState
    operation_started_at: datetime
    did_run: bool
    store_exists: bool
    worktree_path: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ClaudeForkResult:
    """Outcome of ``fork_claude_session`` shared launch tail."""

    exit_code: int
    session: str
    manifest: SessionState
    operation_started_at: datetime
    did_run: bool
    store_exists: bool
    worktree_path: str | None
    warnings: tuple[str, ...]
    render_post_exit: bool


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
    fork_session: bool | None = False,
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

    register_fork_env = bool(fork_session) or register_fork
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
        _update_manifest_best_effort(
            store,
            mutate=lambda m: setattr(m.confirmed, "claude_project_root", _lr),
            label="claude_project_root preseed",
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


def start_claude_session(
    *,
    manager: SessionManager,
    name: str,
    template: str | None,
    base_url: str | None,
    direct: bool,
    incognito: bool,
    worktree: bool,
    branch: str | None,
    launch_mode: str,
    use_sidecar: bool,
    mounts: tuple[str, ...],
    image: str | None,
    no_launch: bool,
    extensions: bool | None,
    extra_args: list[str] | None,
    context_limit_override: int | None,
    proxy_display: str | None,
    proxy_id: str | None,
    normalized_direct_model: str | None,
    prompt_file: str | None,
    memory_flag: bool | None,
    subprocess_proxy: str | None,
    supervisor: SupervisorWiring | None,
    presenter: ClaudeStartPresenter,
    invoke: Callable[..., int] | None = None,
    run_active: Callable[..., int] | None = None,
) -> ClaudeSessionStartResult:
    """Create a Claude session and (unless ``no_launch``) run it interactively.

    Render-free: the CLI supplies ``presenter`` for all output. ``invoke`` and
    ``run_active`` are injectable test seams; when omitted, the op uses its
    module-level launcher dependencies. Raises ``ClaudeStartError`` / ``ForgeOpError``
    for create and launch-prep failures; ``StateCorrupted*`` propagate bare to the
    top-level reset handler.
    """
    operation_started_at = datetime.now(timezone.utc)
    pre_seeded_uuid = str(uuid.uuid4())

    manifest = _create_claude_session(
        manager,
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
        normalized_direct_model=normalized_direct_model,
        pre_seeded_uuid=pre_seeded_uuid,
    )

    # Post-create mutations (rows 2-4): reassign manifest as each store write lands.
    if memory_flag is True:
        manifest = _apply_memory_activation(manifest)
    if subprocess_proxy:
        manifest = _apply_subprocess_proxy(manifest, subprocess_proxy)
    if supervisor is not None:
        manifest = _apply_supervisor_wiring(manifest, supervisor, proxy_id=proxy_id, template=template, direct=direct)

    effective_template = manifest.intent.proxy.template if manifest.intent.proxy else None
    effective_url = manifest.intent.proxy.base_url if manifest.intent.proxy else None
    context_limit = (
        context_limit_override if context_limit_override is not None else _resolve_context_limit(effective_template)
    )
    runtime_base_url = _get_runtime_base_url(use_sidecar=use_sidecar, effective_url=effective_url)

    is_worktree = bool(manifest.worktree and manifest.worktree.is_worktree)
    presenter.on_created(
        ClaudeStartCreated(
            session=manifest.name,
            incognito=incognito,
            proxy_display=proxy_display,
            effective_template=effective_template,
            runtime_base_url=runtime_base_url,
            worktree_path=manifest.worktree.path if is_worktree and manifest.worktree else None,
            worktree_branch=manifest.worktree.branch if is_worktree and manifest.worktree else None,
            supervise_target=supervisor.target if supervisor is not None else None,
        )
    )
    presenter.on_extensions(
        ClaudeStartExtensions(
            is_worktree=is_worktree,
            extension_root=_resolve_worktree_extension_root(manifest) if is_worktree else None,
            extensions_flag=extensions,
        )
    )

    if no_launch:
        presenter.on_no_launch()
        return ClaudeSessionStartResult(
            exit_code=0,
            session=manifest.name,
            manifest=manifest,
            operation_started_at=operation_started_at,
            did_run=False,
            store_exists=True,
            worktree_path=manifest.worktree.path if manifest.worktree else None,
            warnings=(),
        )

    launch_result: ClaudeSessionLaunchResult | None = None
    launch_failed = False
    try:
        try:
            launch_result = launch_claude_session(
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
                before_launch=presenter.before_launch,
                on_sidecar_launch=presenter.on_sidecar_launch,
                invoke=invoke or invoke_claude,
                run_active=run_active or run_with_active_session,
            )
        except ForgeOpError as e:
            # Render the launch error BEFORE the incognito finally so the output order
            # (error -> "Cleaning up...") matches the pre-op launcher.
            presenter.on_launch_error(e)
            launch_failed = True
    finally:
        if incognito:
            _run_incognito_cleanup(manager, manifest, presenter)

    if launch_failed or launch_result is None:
        return ClaudeSessionStartResult(
            exit_code=1,
            session=manifest.name,
            manifest=manifest,
            operation_started_at=operation_started_at,
            did_run=False,
            store_exists=False,
            worktree_path=manifest.worktree.path if manifest.worktree else None,
            warnings=(),
        )

    return ClaudeSessionStartResult(
        exit_code=launch_result.exit_code,
        session=manifest.name,
        manifest=launch_result.manifest,
        operation_started_at=operation_started_at,
        did_run=True,
        store_exists=launch_result.store_exists,
        worktree_path=launch_result.worktree_path,
        warnings=launch_result.warnings,
    )


def resume_claude_session(
    *,
    manager: SessionManager,
    plan: ResumeLaunchPlan,
    presenter: ClaudeResumePresenter,
    invoke: Callable[..., int] | None = None,
    run_active: Callable[..., int] | None = None,
) -> ClaudeResumeResult:
    """Run the shared Claude resume mutation/launch tail without rendering."""
    operation_started_at = datetime.now(timezone.utc)
    manifest = plan.manifest
    worktree_path = Path(manifest.worktree.path) if manifest.worktree else Path.cwd()
    forge_root = Path(manifest.forge_root) if manifest.forge_root else worktree_path
    store = SessionStore(str(forge_root), manifest.name)

    try:
        _persist_resume_routing_override(
            forge_root=forge_root,
            session_name=manifest.name,
            routing=plan.routing,
            direct=plan.direct,
        )
        _apply_resume_routing_override_to_state(state=manifest, routing=plan.routing, direct=plan.direct)

        effective_template, effective_url, effective_proxy_id = _get_effective_proxy_for_resume(manifest)
        if plan.routing and plan.routing.proxy_id:
            effective_proxy_id = plan.routing.proxy_id

        preferences = plan.launch_preferences
        _apply_resume_direct_model_override(
            state=manifest,
            direct_model=plan.direct_model_override,
            forge_root=forge_root,
            use_sidecar=preferences.use_sidecar,
            presenter=presenter,
        )
        runtime_base_url = _get_runtime_base_url(
            use_sidecar=preferences.use_sidecar,
            effective_url=effective_url,
        )

        if plan.session_id is not None:
            _preseed_resume_session_uuid(
                manager=manager,
                store=store,
                session_name=manifest.name,
                session_id=plan.session_id,
            )

        presenter.on_resume_prepared(
            ResumePrepared(
                session=manifest.name,
                action=plan.action,
                parent_name=plan.parent_name,
                resume_id=plan.resume_id,
                effective_template=effective_template,
                runtime_base_url=runtime_base_url,
                worktree_path=worktree_path,
                worktree_branch=manifest.worktree.branch if manifest.worktree else None,
                is_worktree=bool(manifest.worktree and manifest.worktree.is_worktree),
                context_path=plan.prompt_file,
                prompt_warnings=plan.prompt_warnings,
            )
        )

        launch_result = launch_claude_session(
            manifest=manifest,
            session_id=plan.session_id,
            resume_id=plan.resume_id,
            effective_template=effective_template,
            runtime_base_url=runtime_base_url,
            context_limit=plan.context_limit,
            use_sidecar=preferences.use_sidecar,
            mounts=preferences.mounts,
            image=preferences.image,
            fork_session=plan.fork_session,
            system_prompt_file=str(plan.prompt_file) if plan.prompt_file is not None else None,
            name=manifest.name,
            proxy_id=effective_proxy_id,
            before_launch=presenter.before_launch,
            on_sidecar_launch=presenter.on_sidecar_launch,
            invoke=invoke or invoke_claude,
            run_active=run_active or run_with_active_session,
        )
    except ForgeOpError as e:
        presenter.on_launch_error(e)
        return ClaudeResumeResult(
            exit_code=1,
            session=manifest.name,
            manifest=manifest,
            operation_started_at=operation_started_at,
            did_run=False,
            store_exists=store.exists(),
            worktree_path=str(worktree_path),
            warnings=(),
        )

    return ClaudeResumeResult(
        exit_code=launch_result.exit_code,
        session=manifest.name,
        manifest=launch_result.manifest,
        operation_started_at=operation_started_at,
        did_run=True,
        store_exists=launch_result.store_exists,
        worktree_path=launch_result.worktree_path,
        warnings=launch_result.warnings,
    )


def fork_claude_session(
    *,
    manager: SessionManager,
    plan: ForkLaunchPlan,
    presenter: ClaudeForkPresenter,
    invoke: Callable[..., int] | None = None,
    run_active: Callable[..., int] | None = None,
) -> ClaudeForkResult:
    """Run a prepared Claude fork launch without rendering."""
    operation_started_at = datetime.now(timezone.utc)
    manifest = plan.manifest
    worktree_path = Path(manifest.worktree.path) if manifest.worktree else Path.cwd()
    forge_root = Path(manifest.forge_root) if manifest.forge_root else worktree_path
    store = SessionStore(str(forge_root), manifest.name)
    preferences = plan.launch_preferences

    try:
        launch_result = launch_claude_session(
            manifest=manifest,
            session_id=plan.session_id,
            resume_id=plan.resume_id,
            effective_template=plan.effective_template,
            runtime_base_url=plan.runtime_base_url,
            context_limit=plan.context_limit,
            use_sidecar=preferences.use_sidecar,
            mounts=preferences.mounts,
            image=preferences.image,
            fork_session=plan.fork_session,
            register_fork=plan.register_fork,
            system_prompt_file=str(plan.prompt_file) if plan.prompt_file is not None else None,
            name=manifest.name,
            proxy_id=plan.proxy_id,
            before_launch=presenter.before_launch,
            on_sidecar_launch=presenter.on_sidecar_launch,
            invoke=invoke or invoke_claude,
            run_active=run_active or run_with_active_session,
        )
    except ForgeOpError as e:
        presenter.on_launch_error(e)
        if plan.incognito and preferences.use_sidecar:
            _run_incognito_cleanup(manager, manifest, presenter)
        return ClaudeForkResult(
            exit_code=1,
            session=manifest.name,
            manifest=manifest,
            operation_started_at=operation_started_at,
            did_run=False,
            store_exists=store.exists(),
            worktree_path=str(worktree_path),
            warnings=(),
            render_post_exit=False,
        )
    except Exception:
        if plan.incognito:
            _run_incognito_cleanup(manager, manifest, presenter)
        raise

    if plan.incognito:
        _run_incognito_cleanup(manager, manifest, presenter)

    return ClaudeForkResult(
        exit_code=launch_result.exit_code,
        session=manifest.name,
        manifest=launch_result.manifest,
        operation_started_at=operation_started_at,
        did_run=True,
        # The old host fork branch always printed the reconnect tip after launch;
        # sidecar forks already used the shared store-aware launch renderer.
        store_exists=launch_result.store_exists if preferences.use_sidecar else True,
        worktree_path=launch_result.worktree_path,
        warnings=launch_result.warnings,
        render_post_exit=plan.render_post_exit,
    )


def _apply_resume_routing_override_to_state(
    *,
    state: SessionState,
    routing: ClaudeResumeRouting | None,
    direct: bool,
) -> None:
    """Apply a CLI routing override to the in-memory state used for launch."""
    if not routing and not direct:
        return

    from forge.session.models import LaunchIntent, ProxyIntent

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


def _persist_resume_routing_override(
    *,
    forge_root: Path,
    session_name: str,
    routing: ClaudeResumeRouting | None,
    direct: bool,
) -> None:
    """Persist resume routing intent without touching hook-owned confirmation."""
    if not routing and not direct:
        return

    from forge.session.models import LaunchIntent, ProxyIntent

    store = SessionStore(str(forge_root), session_name)

    def _mutate(manifest: SessionState) -> None:
        if direct:
            manifest.intent.proxy = None
            if manifest.intent.launch is None:
                manifest.intent.launch = LaunchIntent(mode=LAUNCH_MODE_HOST)
            else:
                manifest.intent.launch.mode = LAUNCH_MODE_HOST
                manifest.intent.launch.sidecar = None
        elif routing is not None:
            manifest.intent.proxy = ProxyIntent(
                template=routing.template or "",
                base_url=routing.base_url or "",
            )

    try:
        store.update(timeout_s=5.0, mutate=_mutate)
    except Exception:
        logger.debug("Failed to persist routing override to manifest", exc_info=True)


def _get_effective_proxy_for_resume(
    state: SessionState,
) -> tuple[str | None, str | None, str | None]:
    """Resolve template/base_url/proxy_id without depending on the CLI module."""
    if state.confirmed.started_with_proxy:
        return (
            state.confirmed.started_with_proxy.template,
            state.confirmed.started_with_proxy.base_url,
            state.confirmed.started_with_proxy.proxy_id,
        )
    if state.intent.proxy:
        return state.intent.proxy.template, state.intent.proxy.base_url, None
    return None, None, None


def _apply_resume_direct_model_override(
    *,
    state: SessionState,
    direct_model: str | None,
    forge_root: Path,
    use_sidecar: bool,
    presenter: ClaudeResumePresenter,
) -> None:
    """Apply and persist a resume ``--model`` override with render-free warnings."""
    if direct_model is None:
        return
    if use_sidecar:
        raise ForgeOpError("--model cannot be combined with sidecar resume")

    from forge.session.models import LaunchIntent

    if state.intent.launch is None:
        state.intent.launch = LaunchIntent()
    state.intent.launch.direct_model = direct_model

    store = SessionStore(str(forge_root), state.name)

    def _mutate(manifest: SessionState) -> None:
        if manifest.intent.launch is None:
            manifest.intent.launch = LaunchIntent()
        manifest.intent.launch.direct_model = direct_model

    try:
        store.update(timeout_s=5.0, mutate=_mutate)
    except FileLockTimeoutError as e:
        logger.warning("Failed to persist direct model override to manifest", exc_info=True)
        presenter.on_warning(
            ClaudeResumeWarning(
                message=f"Could not persist --model override for session {state.name}: {e}",
                tip=(
                    "If this command launches Claude, it will use the requested model for this run, "
                    "but future resumes may use the previous stored model. Retry after current Forge state updates finish."
                ),
            )
        )
    except (
        InvalidSessionNameError,
        ManifestCorruptedError,
        ManifestValidationError,
        OSError,
        SessionFileNotFoundError,
        ValueError,
    ) as e:
        logger.warning("Failed to persist direct model override to manifest", exc_info=True)
        presenter.on_warning(
            ClaudeResumeWarning(
                message=f"Could not persist --model override for session {state.name}: {e}",
                tip=(
                    "If this command launches Claude, it will use the requested model for this run, "
                    "but future resumes may use the previous stored model. Check the session manifest before relying on this pin."
                ),
            )
        )


def _preseed_resume_session_uuid(
    *,
    manager: SessionManager,
    store: SessionStore,
    session_name: str,
    session_id: str,
) -> None:
    """Best-effort write of a fresh Claude UUID before launching a resume child."""
    try:
        store.update(
            timeout_s=5.0,
            mutate=lambda manifest: setattr(manifest.confirmed, "claude_session_id", session_id),
        )
        manager.index_store.sync_uuid_from_state(session_name, store.read())
    except Exception:
        logger.debug("Pre-seed UUID write failed (hook will reconcile)", exc_info=True)


def _create_claude_session(
    manager: SessionManager,
    *,
    name: str,
    template: str | None,
    base_url: str | None,
    direct: bool,
    incognito: bool,
    worktree: bool,
    branch: str | None,
    launch_mode: str,
    use_sidecar: bool,
    mounts: tuple[str, ...],
    image: str | None,
    normalized_direct_model: str | None,
    pre_seeded_uuid: str,
) -> SessionState:
    """Create the session (row 1), mapping create failures to structured op errors."""
    try:
        return manager.start_session(
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
            direct_model=normalized_direct_model,
            claude_session_id=pre_seeded_uuid,
        )
    except SessionExistsError as e:
        raise ClaudeStartError(
            str(e),
            tip_lines=(
                f"Run 'forge session resume {name}' to continue, or 'forge session delete {name}' to remove it first.",
            ),
        ) from e
    except BranchExistsError as e:
        if e.worktree:
            tip = ("Use --branch to specify a different branch name.",)
        else:
            tip = (f"Run 'git branch -d {e.branch}' to delete it, or use --branch to specify a different name.",)
        raise ClaudeStartError(str(e), tip_lines=tip) from e
    except WorktreePathExistsError as e:
        raise ClaudeStartError(
            str(e),
            tip_lines=("Remove the directory or use a different session name.",),
        ) from e
    except InvalidBranchNameError as e:
        raise ForgeOpError(str(e)) from e
    except (StateCorruptedError, StateUnreadableError):
        raise  # corrupt index/manifest -> top-level reset handler
    except ForgeSessionError as e:
        raise ForgeOpError(str(e)) from e
    except FileNotFoundError as e:
        raise ForgeOpError(str(e)) from e


def _apply_memory_activation(manifest: SessionState) -> SessionState:
    """Row 2: enable ``intent.memory.auto_update`` and return the re-read manifest."""
    from forge.session.models import MemoryIntent, MemoryWriterConfig
    from forge.session.store import SessionStore as _MemStore

    forge_root = manifest.forge_root or str(Path.cwd())

    def _set_memory(m: SessionState) -> None:
        if m.intent.memory is None:
            m.intent.memory = MemoryIntent(auto_update=MemoryWriterConfig(enabled=True))
        elif m.intent.memory.auto_update is None:
            m.intent.memory.auto_update = MemoryWriterConfig(enabled=True)
        else:
            m.intent.memory.auto_update.enabled = True

    return _MemStore(forge_root, manifest.name).update(timeout_s=5.0, mutate=_set_memory)


def _apply_subprocess_proxy(manifest: SessionState, subprocess_proxy: str) -> SessionState:
    """Row 3: persist ``intent.subprocess_proxy`` and return the re-read manifest."""
    manifest.intent.subprocess_proxy = subprocess_proxy
    forge_root = manifest.forge_root or str(Path.cwd())
    from forge.session.store import SessionStore as _SPStore

    _SPStore(forge_root, manifest.name).update(
        timeout_s=5.0,
        mutate=lambda m: setattr(m.intent, "subprocess_proxy", subprocess_proxy),
    )
    return _SPStore(forge_root, manifest.name).read()


def _apply_supervisor_wiring(
    manifest: SessionState,
    wiring: SupervisorWiring,
    *,
    proxy_id: str | None,
    template: str | None,
    direct: bool,
) -> SessionState:
    """Row 4: apply supervisor routing + lane and return the re-read manifest."""
    from forge.policy.semantic.supervisor import (
        SUPERVISOR_CONSUMER,
        apply_checker_options,
        apply_supervisor_and_lane,
        apply_supervisor_routing,
    )
    from forge.session.consumer_lanes import lane_record_for_runtime
    from forge.session.models import SupervisorConfig

    forge_root = manifest.forge_root or (manifest.worktree.path if manifest.worktree else str(Path.cwd()))
    sup_config = SupervisorConfig(
        resume_id=wiring.target,
        forge_root=wiring.source_state.forge_root or forge_root,
    )
    apply_supervisor_routing(
        sup_config,
        wiring.source_state,
        supervisor_proxy=wiring.supervisor_proxy,
        supervisor_direct=wiring.supervisor_direct,
        current_proxy_id=proxy_id,
        current_template=template,
        current_direct=direct,
    )
    # Launch-time --cascade only flips the flag; the runtime hook escalates to the
    # frontier when no plan exists (see plan_check._needs_review).
    if wiring.cascade:
        sup_config.cascade = True
    apply_checker_options(
        sup_config,
        checker_model=wiring.checker_model,
        checker_provider=wiring.checker_provider,
        checker_effort=wiring.checker_effort,
    )
    if wiring.supervisor_effort is not None:
        sup_config.supervisor_effort = wiring.supervisor_effort
    lane = (
        lane_record_for_runtime(SUPERVISOR_CONSUMER, wiring.supervisor_runtime) if wiring.supervisor_runtime else None
    )
    store = SessionStore(forge_root, manifest.name)
    store.update(timeout_s=5.0, mutate=lambda m: apply_supervisor_and_lane(m, sup_config, lane))
    return store.read()


def _run_incognito_cleanup(
    manager: SessionManager,
    manifest: SessionState,
    presenter: ClaudeIncognitoCleanupPresenter,
) -> None:
    """Delete the incognito session on exit; wraps ONLY the launch (never create)."""
    presenter.on_incognito_cleanup_start()
    try:
        manager.delete_session(
            manifest.name,
            delete_transcripts=True,
            force=True,
            forge_root=manifest.forge_root,
        )
        presenter.on_incognito_cleanup_ok()
    except ForgeSessionError as e:
        presenter.on_incognito_cleanup_warning(str(e))


def _update_manifest_best_effort(
    store: SessionStore,
    *,
    mutate: Callable[[SessionState], None],
    label: str,
) -> None:
    """Best-effort manifest write that must never block interactive launch."""
    if not store.exists():
        logger.debug("%s: session manifest missing; skipping", label)
        return
    try:
        store.update(timeout_s=5.0, mutate=mutate)
    except Exception:
        logger.debug("%s: manifest update failed", label, exc_info=True)


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
    fork_session: bool | None,
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
        fork_session=bool(fork_session),
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

    _update_manifest_best_effort(
        store,
        mutate=lambda m: setattr(m.confirmed, "is_sandboxed", True),
        label="sidecar sandbox confirmation",
    )

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
        _update_manifest_best_effort(
            store,
            mutate=lambda m: setattr(m.confirmed, "is_sandboxed", False),
            label="sidecar sandbox rollback",
        )
        raise ForgeOpError(str(e)) from e
    except Exception:
        _update_manifest_best_effort(
            store,
            mutate=lambda m: setattr(m.confirmed, "is_sandboxed", False),
            label="sidecar sandbox rollback",
        )
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
    fork_session: bool | None,
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
    _update_manifest_best_effort(
        store,
        mutate=lambda m: setattr(m.confirmed, "is_sandboxed", False),
        label="host sandbox confirmation",
    )

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

    invoke_kwargs: dict[str, Any] = {
        "session_id": session_id,
        "resume_id": resume_id,
        "name": name,
        "model": None,
        "system_prompt_file": system_prompt_file,
        "env_vars": env_vars,
        "unset_env_vars": unset_env_vars,
        "extra_args": extra_args,
        "cwd": str(launch_root),
    }
    if fork_session is not None:
        invoke_kwargs["fork_session"] = fork_session

    exit_code = active_runner(
        session_name=manifest.name,
        worktree_path=worktree_path,
        launch_mode=LAUNCH_MODE_HOST,
        forge_root=manifest.forge_root,
        claude_session_id=session_id,
        runner=lambda: invoke(**invoke_kwargs),
    )
    if exit_code == 0 and fork_session is False:
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

"""Mutation and launch-plan preparation for ``forge session fork``.

The read-only preflight owns deterministic refusals. This module consumes that
plan, creates the child, prepares its artifacts, compensates every hard
pre-launch failure, and returns caller-rendered events plus an optional
``ForkLaunchPlan``. It deliberately does not import Click or render output.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, TypeAlias

from forge.core.state import FileLockTimeoutError
from forge.install.project_registry import ProjectRegistryStore
from forge.install.tracking import TrackingStore
from forge.session import (
    SessionManager,
    SessionState,
    SessionStore,
)
from forge.session.context_limit import _resolve_context_limit
from forge.session.exceptions import (
    InvalidSessionNameError,
    ManifestCorruptedError,
    ManifestValidationError,
    SessionFileNotFoundError,
)
from forge.session.launch import (
    _combine_prompt_files,
    _get_runtime_base_url,
    _resolve_worktree_extension_root,
    get_launch_preferences,
    resolve_manifest_prompt_file,
)
from forge.session.prev_sessions import child_path

from .claude_session import (
    ClaudeLaunchPreferences,
    ClaudeSessionStateContext,
    ForkLaunchPlan,
    SupervisorWiring,
    apply_resume_routing_override_to_state,
    apply_supervisor_wiring,
    get_effective_proxy_for_resume,
    persist_resume_routing_override,
    resolve_claude_session_state_context,
)
from .session import ForgeOpError
from .session_fork_preflight import ForkPreflightPlan
from .session_model_routing import (
    ResolvedModelRoute,
    apply_model_route_transition,
    plan_model_route_transition,
)

logger = logging.getLogger(__name__)

ForkNoticeLevel = Literal["status", "tip", "warning"]
ForkExtensionStatus = Literal["skipped_parent", "skipped_conflict", "installed", "failed"]


class ForkRuntimeRouting(Protocol):
    """Realized routing shape accepted from the CLI runtime resolver."""

    @property
    def template(self) -> str | None: ...

    @property
    def base_url(self) -> str | None: ...

    @property
    def proxy_id(self) -> str | None: ...


class RewindArtifacts(Protocol):
    """Artifact result required from the shared rewind preparer."""

    @property
    def resume_id(self) -> str: ...

    @property
    def context_path(self) -> Path | None: ...

    @property
    def warnings(self) -> Sequence[str]: ...

    @property
    def rewind_relocated_session_id(self) -> str | None: ...

    @property
    def resume_transcript_ready(self) -> bool: ...


class TransferContextFactory(Protocol):
    """Pure artifact callback used by transfer-mode fork preparation."""

    def __call__(
        self,
        *,
        manager: SessionManager,
        manifest: SessionState,
        parent_state: SessionState | None = None,
        strategy: str = "structured",
        inline_plan: bool = False,
    ) -> tuple[Path | None, list[str]]: ...


class RewindArtifactFactory(Protocol):
    """Pure artifact callback used by rewind-mode fork preparation."""

    def __call__(
        self,
        *,
        manifest: SessionState,
        parent_name: str,
        parent_state: SessionState,
        parent_uuid: str,
        drop_last: int,
    ) -> RewindArtifacts: ...


@dataclass(frozen=True)
class ForkExecutionNotice:
    """Caller-rendered status, warning, or tip emitted during preparation."""

    level: ForkNoticeLevel
    message: str
    continuation: str | None = None
    commands: tuple[str, ...] = ()


@dataclass(frozen=True)
class ForkModelOverridePersistenceWarning:
    """Structured warning for a non-fatal persisted-model write failure."""

    session_name: str
    error: str
    continuation: str


@dataclass(frozen=True)
class ForkCreated:
    """Caller-rendered summary for a successfully reserved fork child."""

    parent_name: str
    session_name: str
    effective_template: str | None
    effective_url: str | None
    worktree_path: Path | None
    worktree_branch: str | None
    supervisor_target: str | None
    incognito: bool


@dataclass(frozen=True)
class ForkContextPrepared:
    """Caller-rendered path for a transfer or rewind launch context."""

    path: Path
    display_relative_to: Path | None


@dataclass(frozen=True)
class ForkExtensionPrepared:
    """Caller-rendered result of best-effort worktree extension preparation."""

    status: ForkExtensionStatus
    profile: str | None = None
    module_count: int | None = None
    error: str | None = None


ForkExecutionEvent: TypeAlias = (
    ForkExecutionNotice
    | ForkModelOverridePersistenceWarning
    | ForkCreated
    | ForkContextPrepared
    | ForkExtensionPrepared
)


class ForkExecutionError(ForgeOpError):
    """Hard pre-launch failure after a typed plan has been accepted."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "preparation_failed",
        tip: str | None = None,
        events: tuple[ForkExecutionEvent, ...] = (),
    ) -> None:
        self.code = code
        self.tip = tip
        self.events = events
        super().__init__(message)


@dataclass(frozen=True)
class ForkExecutionResult:
    """Prepared child state, render events, and optional runtime handoff."""

    parent: SessionState
    manifest: SessionState
    events: tuple[ForkExecutionEvent, ...]
    launch_plan: ForkLaunchPlan | None
    show_resume_tip: bool


@dataclass
class _ForkCompensation:
    """Owned artifacts that rollback may safely remove."""

    delete_transcripts: bool = False
    created_transfer_snapshot: Path | None = None


def execute_session_fork(
    plan: ForkPreflightPlan,
    *,
    manager: SessionManager,
    routing: ForkRuntimeRouting | None,
    supervisor_proxy: str | None,
    transfer_context_factory: TransferContextFactory,
    rewind_artifact_factory: RewindArtifactFactory,
    model_route_selection: ResolvedModelRoute | None = None,
) -> ForkExecutionResult:
    """Create and prepare one fork from a validated read-only plan.

    ``routing`` and ``supervisor_proxy`` are already runtime-realized by the
    adapter. Every hard failure after ``fork_session`` compensates the created
    child before a typed error escapes. Best-effort persistence and extension
    preparation remain non-fatal and surface caller-rendered events.
    """
    request = plan.request
    create_worktree = request.create_worktree or request.branch is not None
    into_resolved = str(plan.target.checkout_root) if plan.target.is_into else None
    into_branch = plan.target.branch if plan.target.is_into else None
    fork_warnings: list[str] = []

    parent, manifest = manager.fork_session(
        parent_name=request.parent_name,
        fork_name=plan.fork_name,
        direct=request.direct,
        is_incognito=request.is_incognito,
        create_worktree=create_worktree,
        branch=into_branch if into_resolved else request.branch,
        into_path=into_resolved,
        forge_root=request.forge_root,
        force=request.force,
        memory_flag=({"on": True, "off": False}.get(request.memory_flag) if request.memory_flag else None),
        resume_mode=plan.manager_resume_mode,
        warnings_sink=fork_warnings,
        authority=request.authority,
        authority_explicit=request.authority_explicit,
    )

    events: list[ForkExecutionEvent] = [
        ForkExecutionNotice(
            "warning" if warning.startswith("[warn]") else "status",
            warning.removeprefix("[warn]"),
        )
        for warning in fork_warnings
    ]
    compensation = _ForkCompensation()

    try:
        result = _prepare_created_fork(
            plan=plan,
            manager=manager,
            parent=parent,
            manifest=manifest,
            routing=routing,
            supervisor_proxy=supervisor_proxy,
            transfer_context_factory=transfer_context_factory,
            rewind_artifact_factory=rewind_artifact_factory,
            model_route_selection=model_route_selection,
            events=events,
            compensation=compensation,
        )
        return result
    except ForkExecutionError as error:
        raise _rollback_created_fork(
            manager=manager,
            manifest=manifest,
            error=error,
            events=events,
            compensation=compensation,
        ) from error
    except Exception as error:
        wrapped = ForkExecutionError(
            f"Could not prepare fork '{manifest.name}' for launch: {error}",
            tip="Retry after resolving the preparation error.",
        )
        raise _rollback_created_fork(
            manager=manager,
            manifest=manifest,
            error=wrapped,
            events=events,
            compensation=compensation,
        ) from error


def _prepare_created_fork(
    *,
    plan: ForkPreflightPlan,
    manager: SessionManager,
    parent: SessionState,
    manifest: SessionState,
    routing: ForkRuntimeRouting | None,
    supervisor_proxy: str | None,
    transfer_context_factory: TransferContextFactory,
    rewind_artifact_factory: RewindArtifactFactory,
    model_route_selection: ResolvedModelRoute | None,
    events: list[ForkExecutionEvent],
    compensation: _ForkCompensation,
) -> ForkExecutionResult:
    request = plan.request
    operation_cwd = request.cwd
    state_context = resolve_claude_session_state_context(manifest, cwd=operation_cwd)

    if model_route_selection is not None:
        transition = plan_model_route_transition(model_route_selection)
        store = state_context.store

        def _apply_selection(state: SessionState) -> None:
            state.intent = apply_model_route_transition(state.intent, transition)
            # A fork owns a new child manifest; inherited parent confirmation is
            # not evidence for that child and must be cleared with its new intent.
            state.confirmed.started_with_proxy = None

        manifest = store.update(timeout_s=5.0, mutate=_apply_selection)
        state_context = resolve_claude_session_state_context(manifest, cwd=operation_cwd)
    else:
        persist_resume_routing_override(
            forge_root=state_context.forge_root,
            session_name=manifest.name,
            routing=routing,
            direct=request.direct,
        )
        apply_resume_routing_override_to_state(state=manifest, routing=routing, direct=request.direct)

    if request.supervise_target:
        manifest = apply_supervisor_wiring(
            state_context,
            SupervisorWiring(
                target=request.parent_name,
                source_state=parent,
                supervisor_proxy=supervisor_proxy,
                supervisor_direct=request.supervisor_direct,
                cascade=request.cascade_flag,
                checker_model=request.checker_model,
                checker_provider=request.checker_provider,
                checker_effort=request.checker_effort,
                supervisor_effort=request.supervisor_effort,
                supervisor_runtime=request.supervisor_runtime,
            ),
            proxy_id=routing.proxy_id if routing else None,
            template=routing.template if routing else None,
            direct=request.direct,
        )
        state_context = resolve_claude_session_state_context(manifest, cwd=operation_cwd)

    if routing is not None:
        effective_template = routing.template
        effective_url = routing.base_url
        effective_proxy_id = routing.proxy_id
    else:
        effective_template, effective_url, effective_proxy_id = get_effective_proxy_for_resume(manifest)
    context_limit = (
        model_route_selection.context_limit
        if model_route_selection is not None and model_route_selection.context_limit is not None
        else _resolve_context_limit(effective_proxy_id or effective_template)
    )

    is_worktree = bool(manifest.worktree and manifest.worktree.is_worktree)
    events.append(
        ForkCreated(
            parent_name=request.parent_name,
            session_name=manifest.name,
            effective_template=effective_template,
            effective_url=effective_url,
            worktree_path=(Path(manifest.worktree.path) if is_worktree and manifest.worktree else None),
            worktree_branch=(manifest.worktree.branch if is_worktree and manifest.worktree else None),
            supervisor_target=request.parent_name if request.supervise_target else None,
            incognito=request.is_incognito,
        )
    )

    parent_session_id = plan.parent_session_id or parent.confirmed.claude_session_id
    use_sidecar, mounts, image = get_launch_preferences(manifest)
    if model_route_selection is None:
        _apply_direct_model_override(
            manifest=manifest,
            direct_model=plan.normalized_direct_model,
            forge_root=state_context.forge_root,
            use_sidecar=use_sidecar,
            events=events,
        )

    rewind_active = plan.rewind_requested and request.drop_last is not None and request.drop_last > 0
    native_relocate = is_worktree and plan.manager_resume_mode == "native-relocate" and not rewind_active
    same_dir_transfer = not is_worktree and plan.manager_resume_mode == "transfer"
    if rewind_active and use_sidecar:
        raise ForkExecutionError(
            "--strategy rewind is not supported with sidecar mode.",
            code="rewind_sidecar",
            tip=("Rewind writes to the host ~/.claude store; run in host mode (e.g. --no-proxy) or use transfer mode."),
        )
    uses_fresh_transfer = ((is_worktree and not native_relocate) or same_dir_transfer) and not rewind_active

    launch_prompt_file: Path | None = None
    launch_session_id: str | None = None
    launch_resume_id: str | None = parent_session_id
    launch_fork_session: bool | None = True
    launch_register_fork = False
    if plan.rewind_requested and request.drop_last == 0:
        events.append(
            ForkExecutionNotice(
                "status",
                "--drop-last 0 uses plain native-relocate; no rewind context generated.",
            )
        )

    if native_relocate:
        if parent_session_id is None:
            raise ForkExecutionError("Parent session has no UUID", code="parent_uuid_missing")
        _prepare_native_relocation(
            parent_name=request.parent_name,
            parent=parent,
            manifest=manifest,
            parent_session_id=parent_session_id,
            state_context=state_context,
            events=events,
        )
        compensation.delete_transcripts = True
    elif rewind_active:
        if parent_session_id is None or request.drop_last is None:
            raise ForkExecutionError("Parent session has no UUID", code="parent_uuid_missing")
        artifacts = rewind_artifact_factory(
            manifest=manifest,
            parent_name=request.parent_name,
            parent_state=parent,
            parent_uuid=parent_session_id,
            drop_last=request.drop_last,
        )
        if artifacts.context_path is not None:
            events.append(ForkContextPrepared(artifacts.context_path, None))
        events.extend(ForkExecutionNotice("warning", warning) for warning in artifacts.warnings)
        if not artifacts.resume_transcript_ready:
            raise ForkExecutionError(
                "Rewind fallback could not prepare a resumable transcript in the fork worktree.",
                code="rewind_unready",
                tip="Use the default transfer fork, or retry after fixing Claude transcript store access.",
            )
        # Every ready path has established a resumable transcript in the child
        # namespace: either a fresh rewind UUID or the full parent-UUID fallback.
        # The manifest tracks the relevant id and manager cleanup protects copies
        # still referenced by another session.
        compensation.delete_transcripts = True
        prompt_files: list[Path] = []
        if artifacts.context_path is not None:
            prompt_files.append(artifacts.context_path)
        configured_prompt = resolve_manifest_prompt_file(manifest)
        if configured_prompt is not None:
            prompt_files.append(configured_prompt)
        combined = _combine_prompt_files(
            worktree_path=state_context.worktree_path,
            session_name=manifest.name,
            prompt_files=prompt_files,
        )
        launch_prompt_file = Path(combined) if combined is not None else None
        launch_resume_id = artifacts.resume_id
        launch_fork_session = True
    elif uses_fresh_transfer:
        prompt_base_dir = state_context.worktree_path if is_worktree else state_context.forge_root
        if is_worktree and request.resume_mode is None:
            events.append(
                ForkExecutionNotice(
                    "tip",
                    "Worktree fork uses transfer context by default.",
                    continuation="Use --resume-mode native-relocate for byte-faithful Claude resume.",
                )
            )
        expected_snapshot = (
            child_path(state_context.forge_root, manifest.parent_session, manifest.name)
            if manifest.parent_session is not None
            else None
        )
        snapshot_existed = expected_snapshot is not None and expected_snapshot.exists()
        try:
            context_path, warnings = transfer_context_factory(
                manager=manager,
                manifest=manifest,
                parent_state=parent,
                strategy=request.strategy,
                inline_plan=request.inline_plan,
            )
        finally:
            # The child name is already reserved by fork_session, so an absent-to-file
            # transition at this exact path belongs to this preparation attempt. Record it
            # even when the factory writes and then raises; pre-existing snapshots remain
            # outside compensation because ensure_child deliberately preserves them.
            if expected_snapshot is not None and not snapshot_existed and expected_snapshot.is_file():
                compensation.created_transfer_snapshot = expected_snapshot
        prompt_files = []
        if context_path is not None:
            prompt_files.append(context_path)
        configured_prompt = resolve_manifest_prompt_file(manifest)
        if configured_prompt is not None:
            prompt_files.append(configured_prompt)
        combined = _combine_prompt_files(
            worktree_path=prompt_base_dir,
            session_name=manifest.name,
            prompt_files=prompt_files,
        )
        launch_prompt_file = Path(combined) if combined is not None else None
        if launch_prompt_file is not None:
            events.append(ForkContextPrepared(launch_prompt_file, prompt_base_dir))
        events.extend(ForkExecutionNotice("warning", warning) for warning in warnings)
        try:
            manifest = _persist_fork_transfer_derivation(
                manifest=manifest,
                strategy=request.strategy,
                context_path=context_path,
            )
        except Exception:
            logger.warning("Failed to persist fork derivation transfer details", exc_info=True)
        state_context = resolve_claude_session_state_context(manifest, cwd=operation_cwd)

        fork_uuid = str(uuid.uuid4())
        _preseed_transfer_uuid_best_effort(manager=manager, context=state_context, session_id=fork_uuid)
        launch_session_id = fork_uuid
        launch_resume_id = None
        launch_fork_session = False if use_sidecar else None
        launch_register_fork = True

    extension_event = _prepare_worktree_extensions(
        manifest=manifest,
        parent=parent,
        into_target=plan.target.is_into,
        force_extensions=request.extensions,
    )
    if extension_event is not None:
        events.append(extension_event)
    if not is_worktree and request.extensions is True:
        events.append(ForkExecutionNotice("tip", "--extensions only applies with --worktree."))

    if request.no_launch:
        events.append(ForkExecutionNotice("status", "Fork created (--no-launch: Claude not started)"))
        return ForkExecutionResult(
            parent=parent,
            manifest=manifest,
            events=tuple(events),
            launch_plan=None,
            show_resume_tip=is_worktree or same_dir_transfer,
        )

    runtime_base_url = _get_runtime_base_url(use_sidecar=use_sidecar, effective_url=effective_url)
    launch_plan = ForkLaunchPlan(
        manifest=manifest,
        session_id=launch_session_id,
        resume_id=launch_resume_id,
        fork_session=launch_fork_session,
        register_fork=launch_register_fork,
        prompt_file=launch_prompt_file,
        context_limit=context_limit,
        launch_preferences=ClaudeLaunchPreferences(use_sidecar=use_sidecar, mounts=mounts, image=image),
        effective_template=effective_template,
        runtime_base_url=runtime_base_url,
        proxy_id=effective_proxy_id,
        incognito=request.is_incognito,
        render_post_exit=(not request.is_incognito or use_sidecar),
        model_route_selection=model_route_selection,
        render_model_route=request.direct_model is not None,
    )
    return ForkExecutionResult(
        parent=parent,
        manifest=manifest,
        events=tuple(events),
        launch_plan=launch_plan,
        show_resume_tip=False,
    )


def _prepare_native_relocation(
    *,
    parent_name: str,
    parent: SessionState,
    manifest: SessionState,
    parent_session_id: str,
    state_context: ClaudeSessionStateContext,
    events: list[ForkExecutionEvent],
) -> None:
    from forge.session.claude import (
        RelocateConflictError,
        RelocateSameDirError,
        relocate_transcript,
    )
    from forge.session.claude.paths import resolve_claude_project_root

    fork_cwd = resolve_claude_project_root(manifest)
    parent_cwd = parent.confirmed.claude_project_root or resolve_claude_project_root(parent)
    try:
        relocate_transcript(
            session_id=parent_session_id,
            source_project_root=parent_cwd,
            dest_project_root=fork_cwd,
        )
    except (OSError, RelocateSameDirError) as error:
        if isinstance(error, RelocateSameDirError):
            message = (
                "--resume-mode native-relocate requires a different CWD than the parent; "
                "the fork resolves to the parent's own Claude project dir."
            )
            tip = "Fork into a fresh --worktree, or use the default transfer mode."
        elif isinstance(error, RelocateConflictError):
            message = f"The destination worktree already holds a different transcript for parent '{parent_name}'."
            tip = "Fork into a fresh worktree, or use the default transfer mode."
        else:
            message = f"Could not relocate the parent transcript for native resume: {error}"
            tip = "Use the default transfer mode, or fork into a fresh worktree."
        raise ForkExecutionError(message, code="native_relocate", tip=tip) from error

    events.append(
        ForkExecutionNotice(
            "warning",
            "Native-relocate preserves Claude history across CWDs, but historical tool paths may still point at "
            "the parent checkout -- path rewriting is not enabled.",
        )
    )

    # The hook will reconcile this best-effort seed if the store is busy.
    try:
        state_context.store.update(
            timeout_s=5.0,
            mutate=lambda state: setattr(state.confirmed, "claude_project_root", fork_cwd),
        )
    except Exception:
        logger.debug(
            "native-relocate claude_project_root pre-seed failed (hook will reconcile)",
            exc_info=True,
        )


def _apply_direct_model_override(
    *,
    manifest: SessionState,
    direct_model: str | None,
    forge_root: Path,
    use_sidecar: bool,
    events: list[ForkExecutionEvent],
) -> None:
    if direct_model is None:
        return
    if use_sidecar:
        raise ForkExecutionError("--model cannot be combined with sidecar fork", code="model_sidecar")

    from forge.session.models import LaunchIntent

    if manifest.intent.launch is None:
        manifest.intent.launch = LaunchIntent()
    manifest.intent.launch.direct_model = direct_model
    store = SessionStore(str(forge_root), manifest.name)

    def _mutate(state: SessionState) -> None:
        if state.intent.launch is None:
            state.intent.launch = LaunchIntent()
        state.intent.launch.direct_model = direct_model

    try:
        store.update(timeout_s=5.0, mutate=_mutate)
    except FileLockTimeoutError as error:
        logger.warning("Failed to persist direct model override to manifest", exc_info=True)
        events.append(
            ForkModelOverridePersistenceWarning(
                session_name=manifest.name,
                error=str(error),
                continuation=(
                    "If this command launches Claude, it will use the requested model for this run, but future "
                    "resumes may use the previous stored model. Retry after current Forge state updates finish."
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
    ) as error:
        logger.warning("Failed to persist direct model override to manifest", exc_info=True)
        events.append(
            ForkModelOverridePersistenceWarning(
                session_name=manifest.name,
                error=str(error),
                continuation=(
                    "If this command launches Claude, it will use the requested model for this run, but future "
                    "resumes may use the previous stored model. Check the session manifest before relying on this pin."
                ),
            )
        )


def _persist_fork_transfer_derivation(
    *,
    manifest: SessionState,
    strategy: str,
    context_path: Path | None,
) -> SessionState:
    worktree_path = Path(manifest.worktree.path) if manifest.worktree else Path.cwd()
    forge_root = Path(manifest.forge_root) if manifest.forge_root else worktree_path
    context_file: str | None = None
    if context_path is not None:
        try:
            context_file = str(context_path.relative_to(forge_root))
        except ValueError:
            context_file = str(context_path)

    def _mutate(state: SessionState) -> None:
        if state.confirmed.derivation is None:
            from forge.session.models import Derivation

            state.confirmed.derivation = Derivation(parent_session=state.parent_session or "")
        state.confirmed.derivation.resume_mode = "transfer"
        state.confirmed.derivation.strategy = strategy
        state.confirmed.derivation.context_file = context_file

    return SessionStore(str(forge_root), manifest.name).update(timeout_s=5.0, mutate=_mutate)


def _preseed_transfer_uuid_best_effort(
    *,
    manager: SessionManager,
    context: ClaudeSessionStateContext,
    session_id: str,
) -> None:
    from forge.session.claude.paths import resolve_claude_project_root

    try:
        store = context.store
        manifest = store.read()
        project_root = resolve_claude_project_root(manifest)

        def _mutate(state: SessionState) -> None:
            state.confirmed.claude_session_id = session_id
            state.confirmed.claude_project_root = project_root

        store.update(timeout_s=5.0, mutate=_mutate)
        manager.index_store.sync_uuid_from_state(manifest.name, store.read())
    except Exception:
        logger.debug("Pre-seed UUID write failed (hook will reconcile)", exc_info=True)


def _detect_parent_extensions(parent_project_root: Path) -> tuple[str, str] | None:
    from forge.install.hooks import has_forge_hooks

    try:
        store = TrackingStore()
        local_install = store.get_installation("local", str(parent_project_root))
        if local_install is not None:
            return local_install.profile, local_install.mode
        user_install = store.get_installation("user")
        if user_install is not None:
            return user_install.profile, user_install.mode
    except Exception:
        logger.debug(
            "Tracking store lookup failed, falling through to hook detection",
            exc_info=True,
        )

    try:
        if has_forge_hooks(parent_project_root):
            return "standard", "copy"
    except Exception:
        logger.debug("Hook detection failed", exc_info=True)
    return None


def _prepare_worktree_extensions(
    *,
    manifest: SessionState,
    parent: SessionState,
    into_target: bool,
    force_extensions: bool | None,
) -> ForkExtensionPrepared | None:
    is_worktree = bool(manifest.worktree and manifest.worktree.is_worktree)
    if not is_worktree:
        return None
    extension_root = _resolve_worktree_extension_root(manifest)
    if extension_root is None:
        return None

    try:
        ProjectRegistryStore().enroll(extension_root, "worktree")
    except Exception:
        logger.debug("Worktree registry enrollment failed", exc_info=True)

    if into_target:
        try:
            if TrackingStore().get_installation("local", str(extension_root)) is not None:
                logger.debug("Skipping auto-install: target worktree has existing local install")
                return None
        except Exception:
            pass

    if force_extensions is False:
        return None

    parent_root = Path(parent.forge_root or (parent.worktree.path if parent.worktree else str(Path.cwd())))
    try:
        if force_extensions is True:
            profile, mode = "standard", "copy"
        else:
            detected = _detect_parent_extensions(parent_root)
            if detected is None:
                return ForkExtensionPrepared("skipped_parent")
            profile, mode = detected

        from forge.install.installer import Installer
        from forge.install.models import InstallMode, InstallProfile, InstallScope

        installer = Installer(scope=InstallScope.LOCAL, project_root=extension_root)
        install_plan = installer.init(profile=InstallProfile(profile), mode=InstallMode(mode))
        if install_plan.has_conflicts:
            return ForkExtensionPrepared("skipped_conflict")
        return ForkExtensionPrepared("installed", profile=profile, module_count=len(install_plan.modules))
    except Exception as error:
        logger.debug("Extension auto-install failed", exc_info=True)
        return ForkExtensionPrepared("failed", error=str(error))


def _rollback_created_fork(
    *,
    manager: SessionManager,
    manifest: SessionState,
    error: ForkExecutionError,
    events: list[ForkExecutionEvent],
    compensation: _ForkCompensation,
) -> ForkExecutionError:
    try:
        manager.delete_session(
            manifest.name,
            delete_worktree=True,
            delete_branch=True,
            delete_transcripts=compensation.delete_transcripts,
            force=True,
            forge_root=manifest.forge_root,
        )
    except Exception as cleanup_error:
        logger.debug("fork preparation rollback delete failed", exc_info=True)
        failure = str(cleanup_error) or type(cleanup_error).__name__
        keep_transcripts = "" if compensation.delete_transcripts else " --keep-transcripts"
        command = f"forge session delete {manifest.name} --yes --force{keep_transcripts}"
        tip = error.tip or "Retry after resolving the preparation error."
        snapshot_recovery = ""
        if compensation.created_transfer_snapshot is not None:
            snapshot_recovery = (
                f" After deleting the session, remove '{compensation.created_transfer_snapshot}' before retrying."
            )
        return ForkExecutionError(
            f"{error} Cleanup also failed for created session '{manifest.name}': {failure}.",
            code=error.code,
            tip=f"Run '{command}' after resolving the cleanup error.{snapshot_recovery} {tip}",
            events=tuple(events),
        )

    if compensation.created_transfer_snapshot is not None:
        try:
            compensation.created_transfer_snapshot.unlink(missing_ok=True)
        except OSError as cleanup_error:
            failure = str(cleanup_error) or type(cleanup_error).__name__
            tip = error.tip or "Retry after resolving the preparation error."
            return ForkExecutionError(
                f"{error} Session cleanup succeeded, but created transfer snapshot "
                f"'{compensation.created_transfer_snapshot}' could not be removed: {failure}.",
                code=error.code,
                tip=f"Remove '{compensation.created_transfer_snapshot}' before retrying. {tip}",
                events=tuple(events),
            )
    return ForkExecutionError(str(error), code=error.code, tip=error.tip, events=tuple(events))

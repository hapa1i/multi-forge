"""Read-only command-core planning for ``forge session fork``.

The Click adapter owns rendering, exits, proxy startup, and execution. This
module resolves deterministic preconditions into an immutable plan before any
child manifest, index row, Git ref, worktree, transfer artifact, or runtime is
created. The mutation layer repeats race-sensitive checks until order 32 moves
execution behind the plan as one transaction boundary.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from dacite import DaciteError

from forge.core.models.direct_model import DirectModelPin, resolve_direct_model_pin
from forge.core.naming import generate_unique_name
from forge.core.paths import display_path
from forge.install.project_compat import (
    ProjectCompatibilityError,
    enforce_project_compatibility,
    enforce_project_compatibility_toml,
)
from forge.policy.semantic.supervisor import (
    supervisor_option_error,
    validate_checker_model,
)
from forge.session import (
    LAUNCH_MODE_SIDECAR,
    SessionManager,
    SessionState,
    SessionStore,
)
from forge.session.active import ActiveSessionStore
from forge.session.artifacts import latest_transcript_artifact_path
from forge.session.claude.paths import (
    find_project_root,
    get_transcript_path,
    resolve_claude_project_root,
)
from forge.session.context_limit import (
    _get_context_limit_for_proxy,
    _get_context_limit_for_template,
    _resolve_context_limit,
)
from forge.session.exceptions import (
    CannotForkIncognitoError,
    ForgeSessionError,
    GitNotFoundError,
    GitWorktreeError,
    ManifestCorruptedError,
    ManifestValidationError,
    SessionExistsError,
    SessionNotFoundError,
)
from forge.session.git import get_main_repo_root
from forge.session.identity import session_name_from_key
from forge.session.model_pin import (
    _validate_direct_model_pin_for_routing,
    _validate_template_model_pin,
)
from forge.session.models import SessionIndexEntry
from forge.session.transfer import (
    estimate_transcript_tokens,
    resolve_transfer_transcript_source,
)
from forge.session.validation import validate_name
from forge.session.worktree import (
    preflight_create_worktree,
    read_file_at_revision,
    resolve_commit,
)

from .context import find_forge_root
from .session import ForgeOpError

logger = logging.getLogger(__name__)

EffectiveResumeMode = Literal["native", "transfer", "native-relocate"]
NoticeLevel = Literal["status", "tip", "warning"]


class ForkPreflightError(ForgeOpError):
    """Typed user-facing refusal raised before fork mutation."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_request",
        tip: str | None = None,
        commands: tuple[str, ...] = (),
        detail: str | None = None,
    ) -> None:
        self.code = code
        self.tip = tip
        self.commands = commands
        self.detail = detail
        super().__init__(message)


@dataclass(frozen=True)
class ForkPreflightNotice:
    """A caller-rendered, non-fatal preflight notice."""

    level: NoticeLevel
    message: str


@dataclass(frozen=True)
class ForkRoutingPreview:
    """Read-only routing facts used by model and budget checks."""

    requested_proxy: str | None
    template: str | None
    base_url: str | None
    proxy_id: str | None
    context_limit: int


@dataclass(frozen=True)
class ForkTargetPlan:
    """Resolved fork target without a reservation or Git mutation."""

    checkout_root: Path
    forge_root: Path
    branch: str | None
    is_into: bool
    replace_stale_state: bool
    replacement_start_point: str | None = None


@dataclass(frozen=True)
class ForkPreflightRequest:
    """All CLI-owned fork inputs needed for read-only planning."""

    parent_name: str
    cwd: Path
    forge_root: str | None
    fork_name: str | None = None
    proxy_name: str | None = None
    direct: bool = False
    direct_model: str | None = None
    is_incognito: bool = False
    create_worktree: bool = False
    branch: str | None = None
    no_launch: bool = False
    extensions: bool | None = None
    strategy: str = "structured"
    drop_last: int | None = None
    inline_plan: bool = False
    into_path: str | None = None
    resume_mode: str | None = None
    supervise_target: bool = False
    supervisor_proxy: str | None = None
    supervisor_direct: bool = False
    cascade_flag: bool = False
    checker_model: str | None = None
    checker_provider: str | None = None
    checker_effort: str | None = None
    supervisor_effort: str | None = None
    supervisor_runtime: str | None = None
    force: bool = False
    memory_flag: str | None = None
    strategy_explicit: bool = False
    drop_last_explicit: bool = False
    inline_plan_explicit: bool = False


@dataclass(frozen=True)
class ForkPreflightPlan:
    """Immutable result of every deterministic pre-mutation fork check."""

    request: ForkPreflightRequest
    parent: SessionState
    parent_entry: SessionIndexEntry
    fork_name: str
    target: ForkTargetPlan
    routing: ForkRoutingPreview
    direct_model_pin: DirectModelPin | None
    normalized_direct_model: str | None
    manager_resume_mode: str | None
    resume_mode: EffectiveResumeMode
    rewind_requested: bool
    transfer_depth: int
    parent_session_id: str | None
    transcript_token_estimate: int | None
    notices: tuple[ForkPreflightNotice, ...]


@dataclass(frozen=True)
class _IntoTarget:
    checkout_root: Path
    branch: str | None
    common_dir: Path


def plan_session_fork(
    request: ForkPreflightRequest,
    *,
    manager: SessionManager | None = None,
    context_limit_resolver: Callable[[str | None], int] = _resolve_context_limit,
    notices_sink: list[ForkPreflightNotice] | None = None,
) -> ForkPreflightPlan:
    """Resolve a fork without durable/runtime writes.

    ``notices_sink`` receives notices as they are resolved so an adapter can
    retain earlier context when a later precondition fails.
    """
    manager = manager or SessionManager()
    notices = notices_sink if notices_sink is not None else []

    if request.direct and request.proxy_name:
        raise ForkPreflightError("--no-proxy and --proxy are mutually exclusive")

    supervisor_error = supervisor_option_error(
        supervise_target=request.supervise_target,
        supervisor_proxy=request.supervisor_proxy,
        supervisor_direct=request.supervisor_direct,
        cascade_flag=request.cascade_flag,
        checker_model=request.checker_model,
        checker_provider=request.checker_provider,
        checker_effort=request.checker_effort,
        supervisor_effort=request.supervisor_effort,
        supervisor_runtime=request.supervisor_runtime,
    )
    if supervisor_error:
        raise ForkPreflightError(supervisor_error)
    try:
        validate_checker_model(request.checker_model)
    except ValueError as e:
        raise ForkPreflightError(str(e)) from e

    direct_model_pin: DirectModelPin | None = None
    normalized_direct_model: str | None = None
    if request.direct_model:
        try:
            direct_model_pin = resolve_direct_model_pin(request.direct_model)
            normalized_direct_model = direct_model_pin.env_model
        except ValueError as e:
            raise ForkPreflightError(str(e)) from e

    create_worktree = request.create_worktree or request.branch is not None
    if request.into_path is not None and create_worktree:
        option = "--branch" if request.branch else "--worktree"
        raise ForkPreflightError(f"--into and {option} are mutually exclusive")

    into = _resolve_into_target(request.into_path) if request.into_path is not None else None
    if into is None:
        _validate_command_cwd(request.cwd, create_worktree=create_worktree)

    is_cross_dir = create_worktree or into is not None
    manager_resume_mode, effective_resume_mode, rewind_requested = _resolve_strategy(
        request,
        is_cross_dir=is_cross_dir,
        notices=notices,
    )

    parent, parent_entry = _load_parent_read_only(manager, request)
    parent_worktree = _parent_worktree(parent, parent_entry, request.cwd)

    parent_launch = parent.intent.launch
    if parent_launch is not None and parent_launch.runtime == "codex":
        raise ForkPreflightError(
            f"Session '{request.parent_name}' is a Codex session; 'forge session fork' is Claude-only.",
            code="codex_parent",
            tip="Continue the Codex thread, or branch a new Codex session from it:",
            commands=(
                f"forge session resume {request.parent_name} --task <next step>",
                f"forge session start <name> --runtime codex --resume-from {request.parent_name} --task <task>",
            ),
        )

    from forge.session.launchability import require_session_worktree

    require_session_worktree(request.parent_name, parent_worktree, action="fork")
    _validate_into_repo(into, parent_worktree)

    parent_relative = parent_entry.relative_path or "."
    fork_name = _resolve_fork_name(request.fork_name, manager, parent_entry)
    target_identity = _target_identity(
        parent=parent,
        parent_entry=parent_entry,
        parent_worktree=parent_worktree,
        parent_relative=parent_relative,
        fork_name=fork_name,
        into=into,
        create_worktree=create_worktree,
        branch=request.branch,
    )

    if into is not None:
        enforce_project_compatibility(target_identity.forge_root)

    _validate_native_relocation(
        request,
        parent=parent,
        target_checkout=target_identity.checkout_root,
        is_into=into is not None,
        is_cross_dir=is_cross_dir,
        rewind_requested=rewind_requested,
        manager_resume_mode=manager_resume_mode,
        notices=notices,
    )

    routing = _preview_routing(request, parent, context_limit_resolver=context_limit_resolver)
    _validate_model_pin(
        request,
        parent=parent,
        pin=direct_model_pin,
        routing=routing,
    )

    transcript_token_estimate = _validate_budget(
        request,
        manager=manager,
        parent=parent,
        is_cross_dir=is_cross_dir,
        effective_resume_mode=effective_resume_mode,
        context_limit=routing.context_limit,
        notices=notices,
    )

    parent_session_id: str | None = None
    if not request.no_launch and effective_resume_mode != "transfer":
        parent_session_id = parent.confirmed.claude_session_id
        if not parent_session_id:
            raise ForkPreflightError(
                "Parent session has no UUID",
                code="parent_uuid_missing",
                detail="The parent session may not have been started yet.",
            )

    # These manager-owned checks historically ran after routing/supervisor
    # startup. Keep their relative error order while moving them ahead of both.
    if parent.is_incognito:
        raise CannotForkIncognitoError(request.parent_name)
    latest_transcript_artifact_path(parent)

    target = _preflight_target(
        manager=manager,
        request=request,
        parent=parent,
        parent_entry=parent_entry,
        parent_worktree=parent_worktree,
        parent_relative=parent_relative,
        fork_name=fork_name,
        into=into,
        create_worktree=create_worktree,
    )
    _validate_supervisor_proxy_reference(request.supervisor_proxy)

    return ForkPreflightPlan(
        request=request,
        parent=parent,
        parent_entry=parent_entry,
        fork_name=fork_name,
        target=target,
        routing=routing,
        direct_model_pin=direct_model_pin,
        normalized_direct_model=normalized_direct_model,
        manager_resume_mode=manager_resume_mode,
        resume_mode=effective_resume_mode,
        rewind_requested=rewind_requested,
        transfer_depth=1,
        parent_session_id=parent_session_id,
        transcript_token_estimate=transcript_token_estimate,
        notices=tuple(notices),
    )


def validate_session_fork_routing(
    plan: ForkPreflightPlan,
    *,
    proxy_id: str | None,
    base_url: str | None,
    context_limit: int | None,
) -> None:
    """Revalidate route-dependent facts after the CLI realizes a proxy."""
    request = plan.request
    if plan.direct_model_pin is not None and not request.direct:
        error = _validate_direct_model_pin_for_routing(
            pin=plan.direct_model_pin,
            proxy_id=proxy_id,
            base_url=base_url,
            surface="fork",
        )
        if error:
            raise ForkPreflightError(error)

    if (
        plan.transcript_token_estimate is not None
        and context_limit is not None
        and plan.transcript_token_estimate > context_limit
        and not request.force
    ):
        raise ForkPreflightError(
            f"Parent transcript ({plan.transcript_token_estimate:,} tokens) exceeds context limit "
            f"({context_limit:,}).",
            code="budget_exceeded",
            tip="Use --strategy structured or --strategy ai-curated instead.",
        )


def _validate_command_cwd(cwd: Path, *, create_worktree: bool) -> None:
    """UI-free equivalent of the fork command's repository-root guards."""
    cwd = cwd.resolve()
    forge_root = find_forge_root(cwd)

    # Same-directory forks retain require_repo_root's established allowance
    # for an enabled Forge root that is not itself inside Git.
    if not create_worktree and forge_root == cwd:
        _enforce_command_project_compatibility(cwd)
        return

    try:
        repo_root = find_project_root(str(cwd)).resolve()
    except FileNotFoundError as e:
        raise ForkPreflightError("Not in a git repository", code="cwd") from e

    if create_worktree:
        try:
            main_root = get_main_repo_root(repo_root).resolve()
        except (GitWorktreeError, GitNotFoundError):
            main_root = repo_root
        if repo_root != main_root:
            raise ForkPreflightError(
                "Cannot create worktrees from inside a child worktree. "
                f"Run from the main repository root ({display_path(main_root)})",
                code="cwd",
                tip="Run from:",
                commands=(f"cd {display_path(main_root)}",),
            )

        if forge_root == cwd:
            _enforce_command_project_compatibility(cwd)
            return

    if cwd != repo_root:
        # require_main_repo_root always points back to the main repository;
        # require_repo_root may point to an enclosing nested Forge root.
        hint = repo_root if create_worktree else forge_root or repo_root
        raise ForkPreflightError(
            f"Must run from the repository root ({display_path(repo_root)}), not a subdirectory",
            code="cwd",
            tip="Run from:",
            commands=(f"cd {display_path(hint)}",),
        )

    _enforce_command_project_compatibility(repo_root)


def _enforce_command_project_compatibility(project_root: Path) -> None:
    """Translate the project guardrail into a typed CLI-neutral refusal."""

    try:
        enforce_project_compatibility(project_root)
    except ProjectCompatibilityError as e:
        raise ForkPreflightError(
            f"Project compatibility refused ({e.state}) at {display_path(e.path)}: {e.reason}",
            code="project_compatibility",
            tip=e.recovery,
        ) from e


def _resolve_into_target(into_path: str) -> _IntoTarget:
    try:
        checkout = Path(
            subprocess.run(
                ["git", "-C", into_path, "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        ).resolve()
    except subprocess.CalledProcessError as e:
        raise ForkPreflightError(
            f"'{display_path(into_path)}' is not inside a git repository",
            code="into_not_repo",
        ) from e

    try:
        common_raw = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as e:
        raise ForkPreflightError("Failed to resolve git repository for --into target", code="into_repo") from e

    common_dir = (checkout / common_raw).resolve()
    main_root = common_dir.parent if common_dir.name == ".git" else common_dir
    if checkout == main_root:
        raise ForkPreflightError(
            "--into targets existing worktrees, not the main checkout. Use a same-directory fork instead.",
            code="into_main_checkout",
        )

    try:
        branch = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        branch = None

    return _IntoTarget(checkout_root=checkout, branch=branch, common_dir=common_dir)


def _load_parent_read_only(
    manager: SessionManager,
    request: ForkPreflightRequest,
) -> tuple[SessionState, SessionIndexEntry]:
    """Load the authoritative parent without index self-healing writes."""
    entry = manager.index_store.peek_session(request.parent_name, forge_root=request.forge_root)
    if isinstance(entry, SessionIndexEntry):
        return SessionStore(entry.root, request.parent_name).read(), entry
    if isinstance(manager, SessionManager):
        raise SessionNotFoundError(request.parent_name)

    # Test doubles and older embedders may not expose the read-only store seam.
    # The production IndexStore always takes the branch above.
    parent = manager.get_session(request.parent_name, forge_root=request.forge_root)
    fallback = manager.index_store.get_session(request.parent_name, forge_root=request.forge_root)
    if isinstance(fallback, SessionIndexEntry):
        return parent, fallback
    synthetic = _synthetic_parent_entry(parent, request.cwd)
    relative_path = getattr(fallback, "relative_path", None)
    if isinstance(relative_path, str) and relative_path:
        synthetic = replace(synthetic, relative_path=relative_path)
    return parent, synthetic


def _synthetic_parent_entry(parent: SessionState, cwd: Path) -> SessionIndexEntry:
    worktree = Path(parent.worktree.path) if parent.worktree is not None else cwd
    forge_root = Path(parent.forge_root) if parent.forge_root else worktree
    try:
        relative = str(forge_root.relative_to(worktree)) or "."
    except ValueError:
        relative = "."
    try:
        project_root = get_main_repo_root(worktree)
    except (ForgeSessionError, OSError):
        project_root = worktree
    return SessionIndexEntry(
        worktree_path=str(worktree),
        project_root=str(project_root),
        last_accessed_at=parent.last_accessed_at,
        is_fork=parent.is_fork,
        is_incognito=parent.is_incognito,
        parent_session=parent.parent_session,
        forge_root=str(forge_root),
        checkout_root=str(worktree),
        relative_path=relative,
    )


def _parent_worktree(parent: SessionState, entry: SessionIndexEntry, cwd: Path) -> Path:
    if parent.worktree is not None:
        return Path(parent.worktree.path)
    if entry.worktree_path:
        return Path(entry.worktree_path)
    return cwd


def _validate_into_repo(into: _IntoTarget | None, parent_worktree: Path) -> None:
    if into is None:
        return
    try:
        parent_common_raw = subprocess.run(
            ["git", "-C", str(parent_worktree), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return
    parent_common = (parent_worktree / parent_common_raw).resolve()
    if into.common_dir != parent_common:
        raise ForkPreflightError(
            "--into target is not part of the same repository as the parent session",
            code="into_cross_repo",
        )


def _target_identity(
    *,
    parent: SessionState,
    parent_entry: SessionIndexEntry,
    parent_worktree: Path,
    parent_relative: str,
    fork_name: str | None,
    into: _IntoTarget | None,
    create_worktree: bool,
    branch: str | None,
) -> ForkTargetPlan:
    provisional_name = fork_name or "pending-fork"
    if into is not None:
        return ForkTargetPlan(
            checkout_root=into.checkout_root,
            forge_root=into.checkout_root / parent_relative,
            branch=into.branch,
            is_into=True,
            replace_stale_state=False,
        )
    if create_worktree:
        from forge.session.worktree import resolve_worktree_path, sanitize_branch_name

        try:
            repo_root = get_main_repo_root(parent_worktree)
        except (ForgeSessionError, OSError):
            repo_root = parent_worktree
        checkout = resolve_worktree_path(repo_root, provisional_name)
        return ForkTargetPlan(
            checkout_root=checkout,
            forge_root=checkout / parent_relative,
            branch=branch or sanitize_branch_name(provisional_name),
            is_into=False,
            replace_stale_state=False,
        )
    parent_root = Path(parent_entry.forge_root or parent_entry.worktree_path)
    return ForkTargetPlan(
        checkout_root=parent_worktree,
        forge_root=parent_root,
        branch=parent.worktree.branch if parent.worktree is not None else None,
        is_into=False,
        replace_stale_state=False,
    )


def _resolve_strategy(
    request: ForkPreflightRequest,
    *,
    is_cross_dir: bool,
    notices: list[ForkPreflightNotice],
) -> tuple[str | None, EffectiveResumeMode, bool]:
    resume_mode = request.resume_mode
    rewind_requested = request.strategy == "rewind"
    if request.drop_last_explicit and not rewind_requested:
        raise ForkPreflightError("--drop-last requires --strategy rewind")
    if rewind_requested:
        if request.drop_last is None:
            raise ForkPreflightError("--strategy rewind requires --drop-last N")
        if request.drop_last < 0:
            raise ForkPreflightError("--drop-last must be non-negative")
        if request.inline_plan_explicit:
            raise ForkPreflightError("--inline-plan applies only to transfer forks, not --strategy rewind")
        if resume_mode == "transfer":
            raise ForkPreflightError("--strategy rewind cannot be combined with --resume-mode transfer")
        if not is_cross_dir:
            raise ForkPreflightError(
                "--strategy rewind on fork requires --worktree or --into.",
                tip="Use 'forge session resume <name> --fresh --strategy rewind --drop-last N' "
                "for a same-directory child.",
            )
        resume_mode = "native-relocate"

    if (
        not is_cross_dir
        and resume_mode is None
        and not rewind_requested
        and (request.strategy_explicit or request.inline_plan_explicit)
    ):
        resume_mode = "transfer"
        notices.append(
            ForkPreflightNotice(
                "status",
                "Same-directory fork switched to transfer mode " "(--strategy/--inline-plan implies a transfer fork).",
            )
        )

    if resume_mode == "native-relocate" and is_cross_dir:
        effective: EffectiveResumeMode = "native-relocate"
    elif is_cross_dir or resume_mode == "transfer":
        effective = "transfer"
    else:
        effective = "native"
    return resume_mode, effective, rewind_requested


def _validate_native_relocation(
    request: ForkPreflightRequest,
    *,
    parent: SessionState,
    target_checkout: Path,
    is_into: bool,
    is_cross_dir: bool,
    rewind_requested: bool,
    manager_resume_mode: str | None,
    notices: list[ForkPreflightNotice],
) -> None:
    if manager_resume_mode == "native-relocate" and is_cross_dir:
        if request.no_launch:
            raise ForkPreflightError(
                "--resume-mode native-relocate cannot be combined with --no-launch.",
                tip="Native-relocate relocates and resumes at launch; omit --no-launch.",
            )
        launch = parent.intent.launch
        parent_is_sidecar = parent.confirmed.is_sandboxed or (launch is not None and launch.mode == LAUNCH_MODE_SIDECAR)
        if not request.direct and parent_is_sidecar:
            raise ForkPreflightError(
                "--resume-mode native-relocate is not supported with sidecar mode.",
                tip="Relocation writes to the host ~/.claude store; run in host mode (e.g. --no-proxy) "
                "or use the default transfer mode.",
            )
        parent_uuid = parent.confirmed.claude_session_id
        if parent_uuid is None:
            raise ForkPreflightError(
                f"Parent session '{request.parent_name}' has no Claude transcript to relocate.",
                tip="Start the parent session so it has a conversation to fork, or use the default transfer mode.",
            )
        parent_cwd = parent.confirmed.claude_project_root or resolve_claude_project_root(parent)
        source_transcript = get_transcript_path(parent_cwd, parent_uuid)
        if not source_transcript.is_file():
            raise ForkPreflightError(
                f"Parent session '{request.parent_name}' has no Claude transcript to relocate.",
                tip="Start the parent session so it has a conversation to fork, or use the default transfer mode.",
            )
        destination_transcript = get_transcript_path(str(target_checkout), parent_uuid)
        if source_transcript == destination_transcript:
            target_label = "the --into target" if is_into else "the fork"
            raise ForkPreflightError(
                "--resume-mode native-relocate requires a different CWD than the parent; "
                f"{target_label} resolves to the parent's own Claude project dir.",
                tip="Fork into a fresh --worktree, or use the default transfer mode.",
            )
        if (not rewind_requested or request.drop_last == 0) and destination_transcript.is_file():
            try:
                destination_matches = destination_transcript.read_bytes() == source_transcript.read_bytes()
            except OSError as e:
                raise ForkPreflightError(
                    f"Could not inspect the native-relocate transcript target: {e}",
                    tip="Fix access to the Claude transcript store, or use the default transfer mode.",
                ) from e
            if not destination_matches:
                raise ForkPreflightError(
                    f"The destination worktree already holds a different transcript for parent "
                    f"'{request.parent_name}'.",
                    tip="Fork into a fresh worktree, or use the default transfer mode.",
                )
        if not rewind_requested and (request.strategy_explicit or request.inline_plan_explicit):
            notices.append(
                ForkPreflightNotice(
                    "tip",
                    "--strategy/--inline-plan apply only to transfer forks; ignored with "
                    "--resume-mode native-relocate.",
                )
            )
    elif manager_resume_mode == "native-relocate":
        notices.append(
            ForkPreflightNotice(
                "tip",
                "--resume-mode native-relocate only applies to --worktree/--into forks; "
                "same-directory forks use native resume or --resume-mode transfer.",
            )
        )


def _preview_routing(
    request: ForkPreflightRequest,
    parent: SessionState,
    *,
    context_limit_resolver: Callable[[str | None], int],
) -> ForkRoutingPreview:
    if request.direct:
        return ForkRoutingPreview(None, None, None, None, context_limit_resolver(None))

    if request.proxy_name:
        from forge.proxy.proxies import (
            ProxyRegistryStore,
            ProxyResolutionError,
            resolve_proxy,
        )

        try:
            entry = resolve_proxy(ProxyRegistryStore().read(), request.proxy_name)
        except ProxyResolutionError as e:
            from forge.config.loader import template_exists

            try:
                template_exists(request.proxy_name)
            except ValueError as template_error:
                raise ForkPreflightError(str(template_error)) from e
            return ForkRoutingPreview(
                request.proxy_name,
                request.proxy_name,
                None,
                None,
                _get_context_limit_for_template(request.proxy_name),
            )
        return ForkRoutingPreview(
            request.proxy_name,
            entry.template,
            entry.base_url,
            entry.proxy_id,
            _get_context_limit_for_proxy(entry.proxy_id),
        )

    from .claude_session import get_effective_proxy_for_resume

    template, base_url, proxy_id = get_effective_proxy_for_resume(parent)
    return ForkRoutingPreview(
        None,
        template,
        base_url,
        proxy_id,
        context_limit_resolver(proxy_id or template),
    )


def _validate_model_pin(
    request: ForkPreflightRequest,
    *,
    parent: SessionState,
    pin: DirectModelPin | None,
    routing: ForkRoutingPreview,
) -> None:
    if pin is None or request.direct:
        return
    launch = parent.intent.launch
    inherited_sidecar = parent.confirmed.is_sandboxed or (launch is not None and launch.mode == LAUNCH_MODE_SIDECAR)
    if inherited_sidecar:
        raise ForkPreflightError("--model cannot be combined with sidecar fork")
    if routing.proxy_id is None and routing.base_url is None:
        if routing.template is None:
            return
        from forge.config.loader import template_exists

        # A real prospective template can be validated before it is started.
        # Unknown names are left to the established CLI resolver so its exact
        # not-found guidance and test-double seams stay unchanged.
        if not template_exists(routing.template):
            return
        error = _validate_template_model_pin(routing.template, pin)
        if error:
            raise ForkPreflightError(error)
        return
    error = _validate_direct_model_pin_for_routing(
        pin=pin,
        proxy_id=routing.proxy_id,
        base_url=routing.base_url,
        surface="fork",
    )
    if error:
        raise ForkPreflightError(error)


def _validate_supervisor_proxy_reference(supervisor_proxy: str | None) -> None:
    """Reject deterministic supervisor routing failures before any proxy starts.

    Error text mirrors ``ensure_supervisor_proxy``; order 32 removes this split
    when supervisor realization moves behind the command-core plan.
    """
    if supervisor_proxy is None:
        return

    from forge.config.loader import load_config, template_exists
    from forge.proxy.proxies import (
        AmbiguousProxyError,
        ProxyNotFoundError,
        ProxyRegistryStore,
        resolve_proxy,
    )

    try:
        resolve_proxy(ProxyRegistryStore().read(), supervisor_proxy)
        return
    except AmbiguousProxyError as e:
        raise ForkPreflightError(str(e)) from e
    except ProxyNotFoundError as e:
        try:
            exists = template_exists(supervisor_proxy)
        except ValueError as template_error:
            raise ForkPreflightError(str(template_error)) from template_error
        if not exists:
            raise ForkPreflightError(
                f"Supervisor proxy '{supervisor_proxy}' is not running and no template named "
                f"'{supervisor_proxy}' exists. Run 'forge proxy template list' to see templates."
            ) from e

    try:
        load_config(template=supervisor_proxy)
    except ValueError as e:
        raise ForkPreflightError(
            f"Supervisor proxy '{supervisor_proxy}': failed to start from template: "
            f"Invalid template '{supervisor_proxy}': {e}"
        ) from e


def _validate_budget(
    request: ForkPreflightRequest,
    *,
    manager: SessionManager,
    parent: SessionState,
    is_cross_dir: bool,
    effective_resume_mode: EffectiveResumeMode,
    context_limit: int,
    notices: list[ForkPreflightNotice],
) -> int | None:
    if not (
        (is_cross_dir or effective_resume_mode == "transfer") and request.strategy == "full" and not request.direct
    ):
        return None
    if parent.forge_root:
        artifact_root = Path(parent.forge_root)
    else:
        resolved_root = manager.resolve_project_root(_parent_cwd(parent))
        artifact_root = Path(resolved_root) if isinstance(resolved_root, (str, Path)) else Path(_parent_cwd(parent))
    transcript_path, _artifact_path = resolve_transfer_transcript_source(parent, artifact_root)
    if transcript_path is None or not transcript_path.is_file():
        return None
    token_estimate = estimate_transcript_tokens(transcript_path)
    if token_estimate > context_limit:
        if request.force:
            notices.append(
                ForkPreflightNotice(
                    "warning",
                    f"Parent transcript ({token_estimate:,} tokens) exceeds context limit ({context_limit:,}). "
                    "Proceeding anyway (--force).",
                )
            )
        else:
            raise ForkPreflightError(
                f"Parent transcript ({token_estimate:,} tokens) exceeds context limit ({context_limit:,}).",
                code="budget_exceeded",
                tip="Use --strategy structured or --strategy ai-curated instead.",
            )
    return token_estimate


def _parent_cwd(parent: SessionState) -> str:
    return parent.worktree.path if parent.worktree is not None else str(Path.cwd())


def _resolve_fork_name(
    requested: str | None,
    manager: SessionManager,
    parent_entry: SessionIndexEntry,
) -> str:
    if requested is not None:
        validate_name(requested)
        return requested

    existing: set[str] = set()
    index = manager.index_store.read()
    sessions = index.sessions if isinstance(index.sessions, dict) else {}
    for key, entry in sessions.items():
        if not isinstance(entry, SessionIndexEntry) or entry.forge_root != parent_entry.root:
            continue
        name = session_name_from_key(key)
        if SessionStore(entry.root, name).exists():
            existing.add(name)
    return generate_unique_name(existing)


def _preflight_target(
    *,
    manager: SessionManager,
    request: ForkPreflightRequest,
    parent: SessionState,
    parent_entry: SessionIndexEntry,
    parent_worktree: Path,
    parent_relative: str,
    fork_name: str,
    into: _IntoTarget | None,
    create_worktree: bool,
) -> ForkTargetPlan:
    if not isinstance(manager, SessionManager):
        # Legacy CLI seam tests replace the manager wholesale and assert only
        # adapter wiring. Real command execution and command-core tests always
        # use the concrete manager and take the full target path below.
        return _target_identity(
            parent=parent,
            parent_entry=parent_entry,
            parent_worktree=parent_worktree,
            parent_relative=parent_relative,
            fork_name=fork_name,
            into=into,
            create_worktree=create_worktree,
            branch=request.branch,
        )

    if into is not None:
        checkout = into.checkout_root
        target_root = checkout / parent_relative
        if not (target_root / ".forge").is_dir():
            raise ForgeSessionError(
                f"No Forge project at {target_root}. Run 'forge extension enable' in {target_root} first, "
                "or use --worktree to create a new checkout with auto-enable."
            )
        target_branch = into.branch
        is_into = True
        replacement_start_point = None
    elif create_worktree:
        from forge.session.worktree import resolve_worktree_path, sanitize_branch_name

        checkout = resolve_worktree_path(get_main_repo_root(parent_worktree), fork_name)
        target_root = checkout / parent_relative
        target_branch = request.branch or sanitize_branch_name(fork_name)
        is_into = False
        replacement_start_point = resolve_commit(get_main_repo_root(parent_worktree))
    else:
        checkout = parent_worktree
        target_root = Path(parent_entry.root)
        target_branch = parent.worktree.branch if parent.worktree is not None else None
        is_into = False
        replacement_start_point = None

    target_store = SessionStore(str(target_root), fork_name)
    target_entry = manager.index_store.peek_session(fork_name, forge_root=str(target_root))
    if not isinstance(target_entry, SessionIndexEntry):
        target_entry = None
    target_state: SessionState | None = None
    if target_store.exists():
        try:
            target_state = target_store.read()
        except (ManifestCorruptedError, ManifestValidationError):
            target_state = None

    conflict = target_store.exists() or target_entry is not None
    replace_stale = False
    if conflict:
        if not request.force:
            raise SessionExistsError(fork_name)
        replace_stale = _can_force_replace(
            fork_name=fork_name,
            parent_name=request.parent_name,
            target_forge_root=target_root,
            existing_state=target_state,
            expected_worktree_path=checkout,
            expected_branch=target_branch or fork_name,
            expected_is_worktree=create_worktree or is_into,
            expected_owns_worktree=create_worktree,
        )
        if not replace_stale:
            raise SessionExistsError(fork_name)

    if create_worktree:
        repo_root = get_main_repo_root(parent_worktree)
        worktree_plan = preflight_create_worktree(
            fork_name,
            request.branch,
            repo_root,
            force=request.force,
            replace_owned_stale_state=replace_stale,
        )
        checkout = worktree_plan.worktree_path
        target_root = checkout / parent_relative
        target_branch = worktree_plan.branch
        if replacement_start_point is None:
            raise RuntimeError("worktree preflight is missing its resolved start point")
        prospective_pin = read_file_at_revision(
            Path(parent_relative) / ".forge" / "project.toml",
            revision=replacement_start_point,
            cwd=repo_root,
        )
        if prospective_pin is not None:
            enforce_project_compatibility_toml(
                prospective_pin,
                path=target_root / ".forge" / "project.toml",
            )
        if replace_stale:
            enforce_project_compatibility(target_root)

    return ForkTargetPlan(
        checkout_root=checkout,
        forge_root=target_root,
        branch=target_branch,
        is_into=is_into,
        replace_stale_state=replace_stale,
        replacement_start_point=replacement_start_point,
    )


def _can_force_replace(
    *,
    fork_name: str,
    parent_name: str,
    target_forge_root: Path,
    existing_state: SessionState | None,
    expected_worktree_path: Path,
    expected_branch: str,
    expected_is_worktree: bool,
    expected_owns_worktree: bool,
) -> bool:
    if existing_state is None or not existing_state.is_fork or existing_state.parent_session != parent_name:
        return False
    if (
        existing_state.forge_root is not None
        and Path(existing_state.forge_root).resolve() != target_forge_root.resolve()
    ):
        return False
    worktree = existing_state.worktree
    if worktree is None or Path(worktree.path).resolve() != expected_worktree_path.resolve():
        return False
    if worktree.branch != expected_branch or worktree.is_worktree != expected_is_worktree:
        return False
    if expected_is_worktree and getattr(worktree, "owns_worktree", True) != expected_owns_worktree:
        return False
    try:
        return ActiveSessionStore().peek_session(fork_name, forge_root=str(target_forge_root)) is None
    except (OSError, ValueError, DaciteError) as e:
        # The manager's mutation-time check retains the runtime registry's
        # established self-healing read. Defer repairable unreadable state to
        # that check so this read-only pass neither rewrites active.json nor
        # turns its corruption into a permanent force-replacement refusal.
        logger.debug("Deferring unreadable active state for fork target %r: %s", fork_name, e)
        return True
    except Exception as e:
        logger.debug("Unable to verify active state for fork target %r: %s", fork_name, e)
        return False

"""Launch transaction for marked artifact-authority sessions."""

from __future__ import annotations

import logging
import os
import shlex
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from forge.core.reactive.env import RunIdentity
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.core.state import FileLockTimeoutError
from forge.install.hook_dispatcher import (
    diagnose_hook_dispatcher,
    render_dispatcher_command,
)
from forge.install.hooks import find_forge_hook_registrations, forge_hook_handler
from forge.session.active import ActiveSessionStore
from forge.session.authority import (
    AUTHORITY_HOOK_TIMEOUT_SECONDS,
    append_authority_event,
    authority_config_sha256,
    authority_hook_contract_sha256,
    authority_session_lock,
    build_authority_marker,
    new_authority_event,
)
from forge.session.config import LAUNCH_MODE_SIDECAR
from forge.session.models import AuthorityIntent, SessionState, session_runtime
from forge.session.store import SessionStore

from .session import ForgeOpError

logger = logging.getLogger(__name__)

AUTHORITY_LAUNCH_LOCK_TIMEOUT_S = 1.0


@dataclass
class AuthorityLaunchAttempt:
    """One marked launch's immutable evidence plus its eventual exit result."""

    state: SessionState
    store: SessionStore
    root: RunIdentity
    operation: str
    launch_mode: str
    config_sha256: str
    hook_registration_sha256: str | None
    marker: str | None
    exit_code: int | None = None
    pre_invocation_aborted: bool = False

    @property
    def marked(self) -> bool:
        return self.state.intent.authority is not None

    def complete(self, exit_code: int) -> None:
        """Record the child result for the transaction's required terminal event."""
        self.exit_code = exit_code

    def abort_before_child(self, *, reason_code: str) -> None:
        """Append M1 compensation and suppress the normal terminal event."""
        self.pre_invocation_aborted = True
        append_launch_aborted(
            store=self.store,
            state=self.state,
            root=self.root,
            operation=self.operation,
            config_sha256=self.config_sha256,
            hook_sha256=self.hook_registration_sha256,
            reason_code=reason_code,
        )


class AuthoritySeamPreflightError(ForgeOpError):
    """A launch-seam refusal with a stable journal reason code."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@contextmanager
def authority_launch_transaction(
    *,
    store: SessionStore,
    root: RunIdentity,
    operation: str,
    launch_mode: str,
    worktree_path: Path,
    claude_session_id: str | None = None,
    codex_preflight: CodexPreflight | None = None,
    active_store: ActiveSessionStore | None = None,
) -> Iterator[AuthorityLaunchAttempt | None]:
    """Serialize authority posture and preflight and journal a marked launch.

    An unmarked child retains the existing launcher behavior while holding the
    per-session authority lock for its complete lifetime. That prevents authority
    from being assigned after the launch has committed to an unmarked environment,
    without making ordinary launches depend on the global active registry. For a
    marked child, preflight, active registration, and ``run_started`` commit under
    the same lock; the lock is then released before the child runs.
    """
    if root.run_id != root.root_run_id or root.parent_run_id is not None:
        raise ForgeOpError("authority launches require one fresh root run identity")

    active = active_store or ActiveSessionStore()
    lock_stack = ExitStack()
    try:
        lock_stack.enter_context(
            authority_session_lock(
                store.session_dir,
                timeout_s=AUTHORITY_LAUNCH_LOCK_TIMEOUT_S,
            )
        )
    except FileLockTimeoutError as exc:
        try:
            existing = active.get_session(store.session_name, forge_root=str(store.forge_root))
        except Exception:
            existing = None
            logger.debug(
                "Could not inspect active state after authority launch-lock contention for '%s'",
                store.session_name,
                exc_info=True,
            )
        if existing is not None:
            raise ForgeOpError(f"session '{store.session_name}' is already active") from exc
        raise ForgeOpError(
            f"session '{store.session_name}' has another launch or authority change in progress; retry after it completes"
        ) from exc
    except OSError as exc:
        raise ForgeOpError(
            f"could not coordinate launch for session '{store.session_name}': "
            f"the authority lock could not be opened ({exc})"
        ) from exc

    with lock_stack:
        try:
            if not store.exists():
                raise ForgeOpError(f"cannot launch session: manifest is missing for '{store.session_name}'")
            state = store.read()
            attempt = (
                _begin_marked_authority_launch(
                    store=store,
                    state=state,
                    root=root,
                    operation=operation,
                    launch_mode=launch_mode,
                    worktree_path=worktree_path,
                    claude_session_id=claude_session_id,
                    codex_preflight=codex_preflight,
                    active_store=active,
                )
                if state.intent.authority is not None
                else None
            )
        except ForgeOpError:
            raise
        except Exception as exc:
            raise ForgeOpError(f"authority launch preflight failed: {exc}") from exc

        if attempt is None:
            # Keep the lock across the legacy launcher. An external set/clear
            # must not change the posture after this unmarked decision.
            yield None
            return

    caught: BaseException | None = None
    try:
        yield attempt
    except BaseException as exc:
        caught = exc
        raise
    finally:
        terminal_error: Exception | None = None
        if not attempt.pre_invocation_aborted:
            try:
                _append_run_ended(attempt, caught)
            except Exception as exc:  # required journal failure must be surfaced
                terminal_error = exc
        clear_error: Exception | None = None
        try:
            active.clear_session(attempt.state.name, forge_root=str(store.forge_root))
        except Exception as exc:
            clear_error = exc
            logger.debug(
                "Failed to clear marked active session '%s'",
                attempt.state.name,
                exc_info=True,
            )
        if clear_error is not None and attempt.pre_invocation_aborted:
            if caught is not None:
                raise ForgeOpError(f"{caught}; active-state cleanup also failed: {clear_error}") from caught
            raise ForgeOpError(
                f"pre-invocation launch abort could not clear active state: {clear_error}"
            ) from clear_error
        if terminal_error is not None:
            if caught is None:
                outcome = "unknown" if attempt.exit_code is None else str(attempt.exit_code)
                raise ForgeOpError(
                    f"child exit outcome was {outcome}, but the required authority run_ended append failed: "
                    f"{terminal_error}"
                ) from terminal_error
            raise ForgeOpError(
                f"launcher failed ({type(caught).__name__}) and the required authority run_ended append also failed: "
                f"{terminal_error}"
            ) from caught


def _begin_marked_authority_launch(
    *,
    store: SessionStore,
    state: SessionState,
    root: RunIdentity,
    operation: str,
    launch_mode: str,
    worktree_path: Path,
    claude_session_id: str | None,
    codex_preflight: CodexPreflight | None,
    active_store: ActiveSessionStore,
) -> AuthorityLaunchAttempt:
    authority = state.intent.authority
    if authority is None:
        raise ForgeOpError("marked authority launch requires an authority intent")

    runtime = session_runtime(state)
    config_digest = authority_config_sha256(authority, runtime)
    try:
        hook_digest = _preflight_authority_seam(
            authority,
            runtime=runtime,
            launch_mode=launch_mode,
            worktree_path=worktree_path,
            codex_preflight=codex_preflight,
        )
    except AuthoritySeamPreflightError as exc:
        _append_failed_preflight(
            store=store,
            state=state,
            root=root,
            operation=operation,
            config_sha256=config_digest,
            reason_code=exc.reason_code,
        )
        raise
    except Exception as exc:
        _append_failed_preflight(
            store=store,
            state=state,
            root=root,
            operation=operation,
            config_sha256=config_digest,
            reason_code="authority_preflight_error",
        )
        if isinstance(exc, ForgeOpError):
            raise
        raise ForgeOpError(f"authority seam preflight failed: {exc}") from exc

    marker = None
    if authority.role == "advisory":
        if hook_digest is None:
            _append_failed_preflight(
                store=store,
                state=state,
                root=root,
                operation=operation,
                config_sha256=config_digest,
                reason_code="authority_preflight_error",
            )
            raise ForgeOpError("advisory authority preflight returned no hook digest")
        try:
            marker = build_authority_marker(state, root.run_id, hook_digest)
        except Exception as exc:
            _append_failed_preflight(
                store=store,
                state=state,
                root=root,
                operation=operation,
                config_sha256=config_digest,
                reason_code="authority_marker_invalid",
            )
            raise ForgeOpError(f"could not construct the advisory authority marker: {exc}") from exc

    preflight = new_authority_event(
        state,
        event_type="launch_preflight",
        run_id=root.run_id,
        origin_surface="launcher",
        operation=operation,
        outcome="success",
        config_sha256=config_digest,
        hook_registration_sha256=hook_digest,
    )
    append_authority_event(str(store.forge_root), preflight)

    if active_store.get_session(state.name, forge_root=str(store.forge_root)) is not None:
        _best_effort_launch_aborted(
            store,
            state,
            root,
            operation,
            config_digest,
            hook_digest,
            "session_already_active",
        )
        raise ForgeOpError(f"session '{state.name}' is already active")

    try:
        active_store.upsert_session(
            state.name,
            worktree_path=str(worktree_path),
            launch_mode=launch_mode,
            claude_session_id=claude_session_id,
            container_name=(f"forge-{state.name}" if launch_mode == LAUNCH_MODE_SIDECAR else None),
            forge_root=str(store.forge_root),
            authority_run_id=root.run_id,
            authority_config_sha256=config_digest,
            authority_hook_registration_sha256=hook_digest,
        )
    except Exception as exc:
        _best_effort_launch_aborted(
            store,
            state,
            root,
            operation,
            config_digest,
            hook_digest,
            "active_registration_failed",
        )
        raise ForgeOpError(f"could not register the marked launch as active: {exc}") from exc

    try:
        started = new_authority_event(
            state,
            event_type="run_started",
            run_id=root.run_id,
            origin_surface="launcher",
            operation=operation,
            outcome="success",
            config_sha256=config_digest,
            hook_registration_sha256=hook_digest,
        )
        append_authority_event(str(store.forge_root), started)
    except Exception:
        try:
            active_store.clear_session(state.name, forge_root=str(store.forge_root))
        finally:
            _best_effort_launch_aborted(
                store,
                state,
                root,
                operation,
                config_digest,
                hook_digest,
                "run_started_append_failed",
            )
        raise

    return AuthorityLaunchAttempt(
        state=state,
        store=store,
        root=root,
        operation=operation,
        launch_mode=launch_mode,
        config_sha256=config_digest,
        hook_registration_sha256=hook_digest,
        marker=marker,
    )


def _preflight_authority_seam(
    authority: AuthorityIntent,
    *,
    runtime: str,
    launch_mode: str,
    worktree_path: Path,
    codex_preflight: CodexPreflight | None,
) -> str | None:
    if authority.role == "producer":
        return None
    if runtime == "claude_code":
        if launch_mode == LAUNCH_MODE_SIDECAR:
            raise AuthoritySeamPreflightError(
                "advisory authority is unsupported for Claude sidecar launches in v1; "
                "use a host launch or clear authority",
                reason_code="advisory_sidecar_unsupported",
            )
        expected_command = render_dispatcher_command("authority-check")
        registrations = find_forge_hook_registrations(worktree_path, "PreToolUse", "authority-check")
        exact = [
            row
            for row in registrations
            if row.matcher is None and row.command == expected_command and row.timeout == AUTHORITY_HOOK_TIMEOUT_SECONDS
        ]
        if len(registrations) != 1 or len(exact) != 1:
            has_project_registration = any(row.scope in {"local", "project"} for row in registrations)
            recovery = (
                f"run 'forge extension cleanup-project --root {shlex.quote(str(worktree_path))}', then "
                "'forge extension sync --scope user'"
                if has_project_registration
                else "run 'forge extension sync --scope user'"
            )
            raise AuthoritySeamPreflightError(
                "advisory authority requires exactly one catch-all Claude authority-check registration "
                f"with a {AUTHORITY_HOOK_TIMEOUT_SECONDS}s timeout; {recovery}",
                reason_code="claude_registration_invalid",
            )
        diagnosis = diagnose_hook_dispatcher()
        dispatcher = Path(diagnosis.path)
        if diagnosis.status != "current" or not dispatcher.is_file() or not os.access(dispatcher, os.X_OK):
            raise AuthoritySeamPreflightError(
                "advisory authority requires the current executable Forge hook dispatcher; "
                "run 'forge extension sync --scope user'",
                reason_code="claude_dispatcher_invalid",
            )
        return authority_hook_contract_sha256(runtime)

    if runtime == "codex":
        from forge.core.ops.codex_enrollment import verify_codex_enrollment
        from forge.install.codex_hooks import (
            get_builtin_codex_entries,
            get_codex_config_path,
            inspect_codex_hook_registration,
        )
        from forge.install.models import InstallScope

        expected_policy = next(
            entry for entry in get_builtin_codex_entries() if forge_hook_handler(entry.command) == "codex-policy-check"
        )
        registration = inspect_codex_hook_registration(
            get_codex_config_path(InstallScope.USER),
            expected_policy,
        )
        if not registration.exactly_one:
            detail = registration.error or (
                f"found {registration.registration_count} logical registration(s), "
                f"{registration.exact_count} byte-exact"
            )
            raise AuthoritySeamPreflightError(
                "advisory authority requires exactly one catch-all Codex codex-policy-check registration "
                f"with the installed command bytes and timeout ({detail}); "
                "run 'forge extension sync --scope user'",
                reason_code="codex_policy_registration_invalid",
            )

        verification = verify_codex_enrollment(preflight=codex_preflight)
        if not (
            verification.ready
            and verification.registered
            and verification.attempted
            and verification.codex_succeeded
            and verification.enrolled is True
        ):
            raise AuthoritySeamPreflightError(
                "advisory authority requires empirically verified Codex hook enrollment for this launch attempt: "
                f"{verification.reason} Run 'forge runtime preflight codex --verify-enrollment' after fixing trust.",
                reason_code="codex_enrollment_unverified",
            )
        return authority_hook_contract_sha256(runtime)
    raise AuthoritySeamPreflightError(
        f"artifact authority does not support runtime {runtime!r}",
        reason_code="authority_runtime_unsupported",
    )


def _append_failed_preflight(
    *,
    store: SessionStore,
    state: SessionState,
    root: RunIdentity,
    operation: str,
    config_sha256: str,
    reason_code: str,
) -> None:
    event = new_authority_event(
        state,
        event_type="launch_preflight",
        run_id=root.run_id,
        origin_surface="launcher",
        operation=operation,
        outcome="error",
        reason_code=reason_code,
        config_sha256=config_sha256,
    )
    append_authority_event(str(store.forge_root), event)
    _best_effort_launch_aborted(
        store,
        state,
        root,
        operation,
        config_sha256,
        None,
        reason_code,
    )


def _append_run_ended(attempt: AuthorityLaunchAttempt, caught: BaseException | None) -> None:
    if caught is not None:
        if isinstance(caught, KeyboardInterrupt):
            outcome, reason = "cancelled", "launcher_cancelled"
        elif attempt.exit_code is not None:
            if attempt.exit_code == 130:
                outcome, reason = "cancelled", "child_cancelled"
            elif attempt.exit_code != 0:
                outcome, reason = "error", "child_exited_nonzero"
            else:
                outcome, reason = "error", "launcher_exception_after_child"
        elif isinstance(caught, OSError):
            outcome, reason = "error", "child_never_spawned"
        else:
            outcome, reason = "error", "launcher_exception"
    elif attempt.exit_code is None:
        outcome, reason = "error", "child_exit_unrecorded"
    elif attempt.exit_code == 0:
        outcome, reason = "success", None
    elif attempt.exit_code == 130:
        outcome, reason = "cancelled", "child_cancelled"
    else:
        outcome, reason = "error", "child_exited_nonzero"
    event = new_authority_event(
        attempt.state,
        event_type="run_ended",
        run_id=attempt.root.run_id,
        origin_surface="launcher",
        operation=attempt.operation,
        outcome=outcome,
        reason_code=reason,
        config_sha256=attempt.config_sha256,
        hook_registration_sha256=attempt.hook_registration_sha256,
    )
    append_authority_event(str(attempt.store.forge_root), event)


def _best_effort_launch_aborted(
    store: SessionStore,
    state: SessionState,
    root: RunIdentity,
    operation: str,
    config_sha256: str,
    hook_sha256: str | None,
    reason_code: str,
) -> None:
    try:
        append_launch_aborted(
            store=store,
            state=state,
            root=root,
            operation=operation,
            config_sha256=config_sha256,
            hook_sha256=hook_sha256,
            reason_code=reason_code,
        )
    except Exception:
        logger.debug(
            "Failed to append authority launch_aborted for '%s'",
            state.name,
            exc_info=True,
        )


def append_launch_aborted(
    *,
    store: SessionStore,
    state: SessionState,
    root: RunIdentity,
    operation: str,
    config_sha256: str,
    hook_sha256: str | None,
    reason_code: str,
) -> None:
    """Append required authority compensation for a launch that cannot invoke its child."""
    event = new_authority_event(
        state,
        event_type="launch_aborted",
        run_id=root.run_id,
        origin_surface="launcher",
        operation=operation,
        outcome="error",
        reason_code=reason_code,
        config_sha256=config_sha256,
        hook_registration_sha256=hook_sha256,
    )
    append_authority_event(str(store.forge_root), event)

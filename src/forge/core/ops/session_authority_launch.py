"""Launch transaction for marked artifact-authority sessions."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from forge.core.reactive.env import RunIdentity
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.install.hook_dispatcher import (
    diagnose_hook_dispatcher,
    render_dispatcher_command,
)
from forge.install.hooks import find_forge_hook_registrations
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

    @property
    def marked(self) -> bool:
        return self.state.intent.authority is not None

    def complete(self, exit_code: int) -> None:
        """Record the child result for the transaction's required terminal event."""
        self.exit_code = exit_code


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
    state_hint: SessionState | None = None,
) -> Iterator[AuthorityLaunchAttempt | None]:
    """Preflight and journal a marked launch while serializing activation.

    Unmarked sessions yield ``None`` and retain the existing launcher behavior. For
    marked sessions, preflight, active registration, and ``run_started`` commit while
    holding the same per-session lock used by the human mutation surface. The child
    runs after that lock is released; ``run_ended`` and active cleanup happen on every
    exit path.
    """
    if root.run_id != root.root_run_id or root.parent_run_id is not None:
        raise ForgeOpError("authority launches require one fresh root run identity")

    active = active_store or ActiveSessionStore()
    try:
        attempt = _begin_authority_launch(
            store=store,
            root=root,
            operation=operation,
            launch_mode=launch_mode,
            worktree_path=worktree_path,
            claude_session_id=claude_session_id,
            codex_preflight=codex_preflight,
            active_store=active,
            state_hint=state_hint,
        )
    except ForgeOpError:
        raise
    except Exception as exc:
        raise ForgeOpError(f"authority launch preflight failed: {exc}") from exc
    if attempt is None:
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
        try:
            _append_run_ended(attempt, caught)
        except Exception as exc:  # required journal failure must be surfaced
            terminal_error = exc
        finally:
            try:
                active.clear_session(attempt.state.name, forge_root=str(store.forge_root))
            except Exception:
                logger.debug(
                    "Failed to clear marked active session '%s'",
                    attempt.state.name,
                    exc_info=True,
                )
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


def _begin_authority_launch(
    *,
    store: SessionStore,
    root: RunIdentity,
    operation: str,
    launch_mode: str,
    worktree_path: Path,
    claude_session_id: str | None,
    codex_preflight: CodexPreflight | None,
    active_store: ActiveSessionStore,
    state_hint: SessionState | None,
) -> AuthorityLaunchAttempt | None:
    if not store.exists():
        if state_hint is not None and state_hint.intent.authority is None:
            # Injectable launcher tests historically supplied an unpersisted unmarked
            # state. Keep that no-authority path free of new state requirements.
            return None
        raise ForgeOpError(f"cannot launch marked session: manifest is missing for '{store.session_name}'")
    with authority_session_lock(store.session_dir):
        state = store.read()
        authority = state.intent.authority
        if authority is None:
            return None

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
        except ForgeOpError as exc:
            _append_failed_preflight(
                store=store,
                state=state,
                root=root,
                operation=operation,
                config_sha256=config_digest,
                reason_code=_preflight_reason_code(runtime, launch_mode, str(exc)),
            )
            raise

        marker = None
        if authority.role == "advisory":
            if hook_digest is None:
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
            raise ForgeOpError(
                "advisory authority is unsupported for Claude sidecar launches in v1; "
                "use a host launch or clear authority"
            )
        expected_command = render_dispatcher_command("authority-check")
        registrations = find_forge_hook_registrations(worktree_path, "PreToolUse", "authority-check")
        exact = [
            row
            for row in registrations
            if row.matcher is None and row.command == expected_command and row.timeout == AUTHORITY_HOOK_TIMEOUT_SECONDS
        ]
        if len(registrations) != 1 or len(exact) != 1:
            raise ForgeOpError(
                "advisory authority requires exactly one catch-all Claude authority-check registration "
                f"with a {AUTHORITY_HOOK_TIMEOUT_SECONDS}s timeout; run 'forge extension sync --scope user'"
            )
        diagnosis = diagnose_hook_dispatcher()
        dispatcher = Path(diagnosis.path)
        if diagnosis.status != "current" or not dispatcher.is_file() or not os.access(dispatcher, os.X_OK):
            raise ForgeOpError(
                "advisory authority requires the current executable Forge hook dispatcher; "
                "run 'forge extension sync --scope user'"
            )
        return authority_hook_contract_sha256(runtime)

    if runtime == "codex":
        from forge.core.ops.codex_enrollment import verify_codex_enrollment

        verification = verify_codex_enrollment(preflight=codex_preflight)
        if not (
            verification.ready
            and verification.registered
            and verification.attempted
            and verification.codex_succeeded
            and verification.enrolled is True
        ):
            raise ForgeOpError(
                "advisory authority requires empirically verified Codex hook enrollment for this launch attempt: "
                f"{verification.reason} Run 'forge runtime preflight codex --verify-enrollment' after fixing trust."
            )
        return authority_hook_contract_sha256(runtime)
    raise ForgeOpError(f"artifact authority does not support runtime {runtime!r}")


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
    except Exception:
        logger.debug(
            "Failed to append authority launch_aborted for '%s'",
            state.name,
            exc_info=True,
        )


def _preflight_reason_code(runtime: str, launch_mode: str, message: str) -> str:
    if runtime == "claude_code" and launch_mode == LAUNCH_MODE_SIDECAR:
        return "advisory_sidecar_unsupported"
    if runtime == "codex":
        return "codex_enrollment_unverified"
    if "registration" in message:
        return "claude_registration_invalid"
    return "claude_dispatcher_invalid"

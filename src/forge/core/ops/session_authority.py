"""Command-core operations for session artifact authority."""

from __future__ import annotations

import os
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator, Literal

from dacite import DaciteError

from forge.core.reactive.env import get_run_identity
from forge.core.state import FileLockTimeoutError
from forge.session.active import ActiveSessionStore
from forge.session.authority import (
    append_authority_event,
    authority_config_sha256,
    authority_coverage,
    authority_hook_contract_sha256,
    authority_session_lock,
    new_authority_event,
    read_authority_events,
)
from forge.session.models import AuthorityIntent, SessionState, session_runtime
from forge.session.store import SessionStore

from .context import ExecutionContext
from .session import ForgeOpError, ResolveSessionResult, resolve_session

AuthorityLaunchSupport = Literal["unsupported", "unverified", "verified", "not_running"]
AuthorityConfigurationHistory = Literal["supported", "unproven"]

AUTHORITY_LIMITATIONS = (
    "Enforcement covers managed runtime-tool requests only; it is not OS-level filesystem immutability.",
    "Runtime hook timeout, non-delivery, dispatcher failure, or discarded malformed output can fail open.",
    "The local journal is append-only by convention and is not tamper-proof.",
    "Authority does not attest authorship, semantic independence, admission, merge, or provider compliance.",
)
AUTHORITY_MUTATION_LOCK_TIMEOUT_S = 0.25


@dataclass(frozen=True)
class AuthorityMutationResult:
    session: str
    role: str | None
    tier: str | None


@dataclass(frozen=True)
class AuthorityReport:
    session: str
    role: str | None
    tier: str | None
    runtime: str
    active: bool
    launch_support: AuthorityLaunchSupport | None
    configuration_history: AuthorityConfigurationHistory | None
    configured_epoch: dict[str, Any] | None
    covered_tools: list[str]
    read_only_tools: list[str]
    control_tools: list[str]
    observed_denials: dict[str, Any]
    limitations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def set_session_authority(
    *,
    ctx: ExecutionContext,
    session_name: str,
    role: str,
    tier: str | None,
) -> AuthorityMutationResult:
    """Set authority on an externally controlled, inactive managed session."""
    try:
        requested = AuthorityIntent(role=role, tier=tier)
    except ValueError as exc:
        raise ForgeOpError(str(exc)) from exc
    resolved = resolve_session(ctx=ctx, session_name=session_name)
    _enforce_compatible(resolved.store)

    with _authority_mutation_lock(resolved.store, operation="set"):
        fresh = resolved.store.read()
        _refuse_if_in_agent_or_active(resolved.store, fresh, operation="set")
        previous = deepcopy(fresh.intent.authority)

        def apply(state: SessionState) -> None:
            state.intent.authority = deepcopy(requested)

        updated = resolved.store.update(timeout_s=5.0, mutate=apply)
        try:
            event = new_authority_event(
                updated,
                event_type="authority_configured",
                run_id=None,
                origin_surface="external_cli",
                operation="set",
                outcome="success",
            )
            append_authority_event(str(resolved.store.forge_root), event)
        except Exception as exc:
            _rollback_authority(resolved.store, previous, exc)

    return AuthorityMutationResult(session=updated.name, role=requested.role, tier=requested.tier)


def clear_session_authority(*, ctx: ExecutionContext, session_name: str) -> AuthorityMutationResult:
    """Remove the complete authority subtree from an externally controlled inactive session."""
    resolved = resolve_session(ctx=ctx, session_name=session_name)
    _enforce_compatible(resolved.store)

    with _authority_mutation_lock(resolved.store, operation="clear"):
        fresh = resolved.store.read()
        _refuse_if_in_agent_or_active(resolved.store, fresh, operation="clear")
        previous = deepcopy(fresh.intent.authority)

        def apply(state: SessionState) -> None:
            state.intent.authority = None

        updated = resolved.store.update(timeout_s=5.0, mutate=apply)
        try:
            event = new_authority_event(
                updated,
                event_type="authority_cleared",
                run_id=None,
                origin_surface="external_cli",
                operation="clear",
                outcome="success",
                authority=None,
            )
            append_authority_event(str(resolved.store.forge_root), event)
        except Exception as exc:
            _rollback_authority(resolved.store, previous, exc)

    return AuthorityMutationResult(session=updated.name, role=None, tier=None)


def refuse_generic_authority_mutation(
    *,
    resolved: ResolveSessionResult,
    operation: str,
) -> None:
    """Journal and reject a target-resolved generic override authority attempt."""
    state = resolved.store.read()
    reason_code = "generic_authority_override_refused"
    event = new_authority_event(
        state,
        event_type="mutation_refused",
        run_id=_current_root_run_id(),
        origin_surface="external_cli",
        operation=operation,
        outcome="refused",
        reason_code=reason_code,
    )
    try:
        append_authority_event(str(resolved.store.forge_root), event)
    except Exception as exc:
        raise ForgeOpError(f"authority mutation was refused, but its required journal write failed: {exc}") from exc
    raise ForgeOpError(
        "authority is managed by the session authority control plane, not overrides; "
        "use 'forge session authority set' or 'forge session authority clear'"
    )


def get_session_authority_report(*, ctx: ExecutionContext, session_name: str | None = None) -> AuthorityReport:
    """Derive a read-only authority posture from strict durable and live state."""
    resolved = resolve_session(ctx=ctx, session_name=session_name)
    state = resolved.state
    runtime = session_runtime(state)
    events = read_authority_events(str(resolved.store.forge_root), state.name)
    authority = state.intent.authority
    history, epoch = _configuration_history(authority, runtime, events)
    covered, read_only, control = authority_coverage(authority, runtime)

    active_store = ActiveSessionStore()
    try:
        active_entry = active_store.peek_session(state.name, forge_root=str(resolved.store.forge_root))
    except (OSError, ValueError, DaciteError, FileLockTimeoutError) as exc:
        raise ForgeOpError(
            f"could not inspect the active-session registry at {active_store.index_path} without modifying it; "
            "run 'forge session list' to repair runtime-only state, then retry"
        ) from exc
    active = active_entry is not None
    launch_support: AuthorityLaunchSupport | None = None
    if authority is not None and authority.role == "advisory":
        launch = state.intent.launch
        if runtime == "claude_code" and launch is not None and launch.mode == "sidecar":
            launch_support = "unsupported"
        elif not active:
            launch_support = "not_running"
        else:
            launch_support = "verified" if _active_preflight_matches(state, events, active_entry) else "unverified"

    denial_events = [event for event in events if event.event_type == "request_denied" and event.outcome == "denied"]
    limitations: list[str] = list(AUTHORITY_LIMITATIONS)
    if authority is not None and authority.role == "advisory" and authority.tier == "named_tools":
        limitations.append(
            "named_tools does not cover Bash, delegation, MCP, skill, unknown, or external-process surfaces."
        )

    return AuthorityReport(
        session=state.name,
        role=authority.role if authority is not None else None,
        tier=authority.tier if authority is not None else None,
        runtime=runtime,
        active=active,
        launch_support=launch_support,
        configuration_history=history,
        configured_epoch=epoch,
        covered_tools=covered,
        read_only_tools=read_only,
        control_tools=control,
        observed_denials={
            "count": len(denial_events),
            "first_at": denial_events[0].timestamp if denial_events else None,
            "last_at": denial_events[-1].timestamp if denial_events else None,
        },
        limitations=limitations,
    )


def _refuse_if_in_agent_or_active(store: SessionStore, state: SessionState, *, operation: str) -> None:
    reason_code: str | None = None
    if os.environ.get("FORGE_SESSION"):
        reason_code = "in_agent_authority_mutation"
    elif ActiveSessionStore().get_session(state.name, forge_root=str(store.forge_root)) is not None:
        reason_code = "active_session_authority_mutation"
    if reason_code is None:
        return

    event = new_authority_event(
        state,
        event_type="mutation_refused",
        run_id=_current_root_run_id(),
        origin_surface="external_cli",
        operation=operation,
        outcome="refused",
        reason_code=reason_code,
    )
    try:
        append_authority_event(str(store.forge_root), event)
    except Exception as exc:
        raise ForgeOpError(f"authority mutation was refused, but its required journal write failed: {exc}") from exc
    if reason_code == "in_agent_authority_mutation":
        raise ForgeOpError("authority can only be changed by a human outside a managed Forge session")
    raise ForgeOpError(f"session '{state.name}' is active; stop it before changing authority")


@contextmanager
def _authority_mutation_lock(store: SessionStore, *, operation: str) -> Iterator[None]:
    """Acquire the control lock quickly or record a live-launch refusal."""

    stack = ExitStack()
    try:
        stack.enter_context(
            authority_session_lock(
                store.session_dir,
                timeout_s=AUTHORITY_MUTATION_LOCK_TIMEOUT_S,
            )
        )
    except FileLockTimeoutError as exc:
        in_agent = bool(os.environ.get("FORGE_SESSION"))
        reason_code = "in_agent_authority_mutation" if in_agent else "active_session_authority_mutation"
        try:
            state = store.read()
            event = new_authority_event(
                state,
                event_type="mutation_refused",
                run_id=_current_root_run_id(),
                origin_surface="external_cli",
                operation=operation,
                outcome="refused",
                reason_code=reason_code,
            )
            append_authority_event(str(store.forge_root), event)
        except Exception as journal_error:
            raise ForgeOpError(
                "authority mutation was refused while the session was launching or active, "
                f"but its required journal write failed: {journal_error}"
            ) from exc
        if in_agent:
            raise ForgeOpError("authority can only be changed by a human outside a managed Forge session") from exc
        raise ForgeOpError(
            f"session '{store.session_name}' is launching or active; stop it before changing authority"
        ) from exc
    except OSError as exc:
        raise ForgeOpError(
            f"could not change authority for session '{store.session_name}': "
            f"the authority lock could not be opened ({exc})"
        ) from exc
    with stack:
        yield


def _rollback_authority(store: SessionStore, previous: AuthorityIntent | None, cause: Exception) -> None:
    try:
        store.update(
            timeout_s=5.0,
            mutate=lambda state: setattr(state.intent, "authority", deepcopy(previous)),
        )
    except Exception as rollback_error:
        raise ForgeOpError(
            f"required authority journal write failed ({cause}); manifest rollback also failed ({rollback_error})"
        ) from cause
    raise ForgeOpError(f"required authority journal write failed; the manifest was rolled back: {cause}") from cause


def _configuration_history(
    current: AuthorityIntent | None,
    runtime: str,
    events: list[Any],
) -> tuple[AuthorityConfigurationHistory | None, dict[str, Any] | None]:
    historical: tuple[str, str | None, str | None] | None = None
    epoch: dict[str, Any] | None = None
    saw_history_event = False
    for event in events:
        if event.event_type in {"authority_configured", "authority_inherited"} and event.outcome == "success":
            saw_history_event = True
            historical = (
                event.payload["role"],
                event.payload["tier"],
                event.payload["effective_config_sha256"],
            )
            epoch = {
                "started_at": event.timestamp,
                "ended_at": None,
            }
        elif event.event_type == "authority_cleared" and event.outcome == "success":
            saw_history_event = True
            if historical is not None and epoch is not None:
                epoch["ended_at"] = event.timestamp
            historical = None

    if current is None:
        if not saw_history_event:
            return None, None
        return ("supported", epoch) if historical is None else ("unproven", epoch)
    expected = (current.role, current.tier, authority_config_sha256(current, runtime))
    return ("supported", epoch) if historical == expected else ("unproven", epoch)


def _active_preflight_matches(state: SessionState, events: list[Any], active_entry: Any) -> bool:
    authority = state.intent.authority
    if authority is None:
        return False
    run_id = active_entry.authority_run_id
    config_digest = authority_config_sha256(authority, session_runtime(state))
    hook_digest = active_entry.authority_hook_registration_sha256
    if (
        run_id is None
        or active_entry.authority_config_sha256 != config_digest
        or hook_digest is None
        or hook_digest != authority_hook_contract_sha256(session_runtime(state))
    ):
        return False
    preflight = any(
        event.event_type == "launch_preflight"
        and event.outcome == "success"
        and event.run_id == run_id
        and event.payload["effective_config_sha256"] == config_digest
        and event.payload["hook_registration_sha256"] == hook_digest
        for event in events
    )
    started = any(
        event.event_type == "run_started" and event.outcome == "success" and event.run_id == run_id for event in events
    )
    return preflight and started


def _current_root_run_id() -> str | None:
    identity = get_run_identity()
    return identity.root_run_id if identity is not None else None


def _enforce_compatible(store: SessionStore) -> None:
    from forge.install.project_compat import (
        ProjectCompatibilityError,
        enforce_project_compatibility,
    )

    try:
        enforce_project_compatibility(Path(store.forge_root))
    except ProjectCompatibilityError as exc:
        raise ForgeOpError(str(exc)) from exc

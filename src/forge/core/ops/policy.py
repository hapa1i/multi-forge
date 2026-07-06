"""Shared policy operations for supervisor lifecycle mutations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import forge.policy.semantic.supervisor as supervisor_semantic
from forge.core.lanes import Consumer, LaneError
from forge.policy.semantic.supervisor import SUPERVISOR_CONSUMER
from forge.policy.supervisor_lane_degrade import clear_supervisor_degrade
from forge.session import SessionStore
from forge.session.consumer_lanes import (
    clear_consumer_lane,
    confirmed_lane,
    lane_record_for,
    lane_record_for_runtime,
    set_intent_lane,
)
from forge.session.effective import compute_effective_intent
from forge.session.models import LaneRecord, SessionState, SupervisorConfig


class PolicyOpError(RuntimeError):
    """Raised when a policy operation cannot complete."""


class SupervisorInputError(PolicyOpError):
    def __init__(self, message: str, *, tip: str | None = None) -> None:
        super().__init__(message)
        self.tip = tip


class SupervisorTargetError(PolicyOpError):
    """Raised when the supervisor target cannot be resolved."""


class SupervisorProxyError(PolicyOpError):
    """Raised when explicit supervisor proxy routing cannot be resolved."""


class SupervisorLaneSelectionError(PolicyOpError):
    """Raised when a requested supervisor lane cannot be resolved."""


class SupervisorLaneFrozenError(PolicyOpError):
    """Raised when a requested lane conflicts with a frozen binding."""

    def __init__(self, frozen: LaneRecord) -> None:
        super().__init__("supervisor lane already frozen")
        self.frozen = frozen


class SupervisorNotConfiguredError(PolicyOpError):
    """Raised when a configured supervisor is required but absent."""


class SupervisorPlanFileNotFoundError(PolicyOpError):
    """Raised when an explicit supervisor plan path does not exist."""


class SupervisorPlanUnavailableError(PolicyOpError):
    def __init__(self, message: str, *, tip: str | None = None, direct_reason: str | None = None) -> None:
        super().__init__(message)
        self.tip = tip
        self.direct_reason = direct_reason or message


@dataclass(frozen=True)
class SupervisorSetResult:
    config: SupervisorConfig
    lane_record: LaneRecord | None
    routing_display: str | None
    routing_explicit: bool
    started_proxy_id: str | None
    started_proxy_template: str | None
    cascade_source_desc: str | None


@dataclass(frozen=True)
class SupervisorReloadResult:
    plan_path: str
    source_desc: str


@dataclass(frozen=True)
class SupervisorCascadeResult:
    enabled: bool
    config: SupervisorConfig
    source_desc: str | None


def supervisor_set(
    *,
    store: SessionStore,
    manifest: SessionState,
    target: str,
    policy_forge_root: str | None,
    supervisor_proxy: str | None = None,
    supervisor_direct: bool = False,
    timeout_seconds: int | None = None,
    cascade_flag: bool | None = None,
    checker_model: str | None = None,
    checker_provider: str | None = None,
    checker_effort: str | None = None,
    supervisor_effort: str | None = None,
    runtime: str | None = None,
    backend: str | None = None,
    lock_timeout_s: float = 5.0,
    confirmed_lane_func: Callable[[SessionState, Consumer], LaneRecord | None] = confirmed_lane,
) -> SupervisorSetResult:
    validate_supervisor_set_input(
        supervisor_proxy=supervisor_proxy,
        supervisor_direct=supervisor_direct,
        cascade_flag=cascade_flag,
        checker_model=checker_model,
    )
    checker_option_supplied = bool(checker_model or checker_provider or checker_effort)

    lane_record = _resolve_requested_lane(runtime=runtime, backend=backend)
    if lane_record is not None:
        frozen = confirmed_lane_func(manifest, SUPERVISOR_CONSUMER)
        if frozen is not None and frozen != lane_record:
            raise SupervisorLaneFrozenError(frozen)

    try:
        source_state = supervisor_semantic.validate_supervisor_target(target, forge_root=policy_forge_root)
    except ValueError as e:
        raise SupervisorTargetError(str(e)) from e

    started_proxy_id: str | None = None
    started_proxy_template: str | None = None
    if supervisor_proxy:
        try:
            resolved_proxy_id, started = supervisor_semantic.ensure_supervisor_proxy(supervisor_proxy)
        except ValueError as e:
            raise SupervisorProxyError(str(e)) from e
        if started:
            started_proxy_id = resolved_proxy_id
            started_proxy_template = supervisor_proxy
        supervisor_proxy = resolved_proxy_id

    current_template = manifest.intent.proxy.template if manifest.intent.proxy else None
    current_proxy_id = None
    if manifest.intent.proxy and hasattr(manifest.intent.proxy, "proxy_id"):
        current_proxy_id = manifest.intent.proxy.proxy_id  # type: ignore[union-attr]
    current_direct = not bool(manifest.intent.proxy)

    sup_config = SupervisorConfig(resume_id=target, forge_root=source_state.forge_root or policy_forge_root)
    if timeout_seconds is not None:
        sup_config.timeout_seconds = timeout_seconds
    if supervisor_effort is not None:
        sup_config.supervisor_effort = supervisor_effort

    routing_display = supervisor_semantic.apply_supervisor_routing(
        sup_config,
        source_state,
        supervisor_proxy=supervisor_proxy,
        supervisor_direct=supervisor_direct,
        current_proxy_id=current_proxy_id,
        current_template=current_template,
        current_direct=current_direct,
    )

    cascade_source_desc: str | None = None
    if cascade_flag:
        sup_config.cascade = True
        supervisor_semantic.apply_checker_options(
            sup_config,
            checker_model=checker_model,
            checker_provider=checker_provider,
            checker_effort=checker_effort,
        )
        plan_path, cascade_source_desc = _resolve_cascade_plan_for_set(sup_config, manifest)
        sup_config.plan_override_path = plan_path
    elif checker_option_supplied:
        supervisor_semantic.apply_checker_options(
            sup_config,
            checker_model=checker_model,
            checker_provider=checker_provider,
            checker_effort=checker_effort,
        )

    def _apply(m: SessionState) -> None:
        if lane_record is not None:
            frozen = confirmed_lane_func(m, SUPERVISOR_CONSUMER)
            if frozen is not None and frozen != lane_record:
                raise SupervisorLaneFrozenError(frozen)
        supervisor_semantic.apply_supervisor_to_intent(m, sup_config)
        if lane_record is not None:
            set_intent_lane(m, SUPERVISOR_CONSUMER, lane_record)
            clear_supervisor_degrade(m)

    store.update(timeout_s=lock_timeout_s, mutate=_apply)
    return SupervisorSetResult(
        config=sup_config,
        lane_record=lane_record,
        routing_display=routing_display,
        routing_explicit=bool(supervisor_proxy or supervisor_direct),
        started_proxy_id=started_proxy_id,
        started_proxy_template=started_proxy_template,
        cascade_source_desc=cascade_source_desc,
    )


def validate_supervisor_set_input(
    *,
    supervisor_proxy: str | None = None,
    supervisor_direct: bool = False,
    cascade_flag: bool | None = None,
    checker_model: str | None = None,
) -> None:
    if supervisor_proxy and supervisor_direct:
        raise SupervisorInputError("--supervisor-proxy and --no-supervisor-proxy are mutually exclusive")
    if cascade_flag is False:
        raise SupervisorInputError("--no-cascade is redundant on set (cascade defaults to off)")

    _validate_checker_model(checker_model)


def supervisor_off(*, store: SessionStore, manifest: SessionState, lock_timeout_s: float = 5.0) -> None:
    if not _has_supervisor_with_target(manifest):
        raise SupervisorNotConfiguredError("No supervisor configured.")

    def _suspend(m: SessionState) -> None:
        if m.intent.policy and m.intent.policy.supervisor:
            m.intent.policy.supervisor.suspended = True

    store.update(timeout_s=lock_timeout_s, mutate=_suspend)


def supervisor_on(*, store: SessionStore, manifest: SessionState, lock_timeout_s: float = 5.0) -> None:
    if not _has_supervisor_with_target(manifest):
        raise SupervisorNotConfiguredError("No supervisor configured.")

    def _resume(m: SessionState) -> None:
        if m.intent.policy and m.intent.policy.supervisor:
            m.intent.policy.supervisor.suspended = False

    store.update(timeout_s=lock_timeout_s, mutate=_resume)


def supervisor_remove(*, store: SessionStore, manifest: SessionState, lock_timeout_s: float = 5.0) -> None:
    if not (manifest.intent.policy and manifest.intent.policy.supervisor):
        raise SupervisorNotConfiguredError("No supervisor configured.")

    def _remove(m: SessionState) -> None:
        if m.intent.policy and m.intent.policy.supervisor:
            m.intent.policy.supervisor = None
        clear_consumer_lane(m, SUPERVISOR_CONSUMER)
        clear_supervisor_degrade(m)

    store.update(timeout_s=lock_timeout_s, mutate=_remove)


def supervisor_reload(
    *,
    store: SessionStore,
    manifest: SessionState,
    cwd: Path,
    reload_path: str | None,
    lock_timeout_s: float = 5.0,
) -> SupervisorReloadResult:
    effective = compute_effective_intent(manifest)
    if not effective.policy or not effective.policy.supervisor or not effective.policy.supervisor.resume_id:
        raise SupervisorNotConfiguredError("No supervisor configured.")

    if reload_path:
        resolved = Path(reload_path)
        if not resolved.is_absolute():
            resolved = (cwd / resolved).resolve()
        if not resolved.is_file():
            raise SupervisorPlanFileNotFoundError(f"Plan file not found: {resolved}")
        plan_path = str(resolved)
        source_desc = str(resolved)
    else:
        result = supervisor_semantic.resolve_supervisor_reload_plan_path(effective.policy.supervisor, manifest)
        if result is None:
            raise SupervisorPlanUnavailableError("No approved plan found for supervisor target or related sessions.")
        plan_path = result.path
        source_desc = _source_desc(result.source, result.session_name)

    def _set_plan(m: SessionState) -> None:
        if m.intent.policy and m.intent.policy.supervisor:
            m.intent.policy.supervisor.plan_override_path = plan_path

    store.update(timeout_s=lock_timeout_s, mutate=_set_plan)
    return SupervisorReloadResult(plan_path=plan_path, source_desc=source_desc)


def supervisor_cascade(
    *,
    store: SessionStore,
    manifest: SessionState,
    state: str,
    checker_model: str | None = None,
    checker_provider: str | None = None,
    checker_effort: str | None = None,
    lock_timeout_s: float = 5.0,
) -> SupervisorCascadeResult:
    validate_supervisor_cascade_input(
        state=state,
        checker_model=checker_model,
        checker_provider=checker_provider,
        checker_effort=checker_effort,
    )
    cascade_on = state == "on"

    sup = manifest.intent.policy.supervisor if manifest.intent.policy else None
    if not (sup and sup.resume_id):
        raise SupervisorNotConfiguredError("No supervisor configured.")

    if not cascade_on:

        def _disable_cascade(m: SessionState) -> None:
            if m.intent.policy and m.intent.policy.supervisor:
                m.intent.policy.supervisor.cascade = False

        store.update(timeout_s=lock_timeout_s, mutate=_disable_cascade)
        return SupervisorCascadeResult(enabled=False, config=sup, source_desc=None)

    plan_path: str | None = sup.plan_override_path
    source_desc: str | None = None
    if not plan_path:
        effective = compute_effective_intent(manifest)
        sup_effective = effective.policy.supervisor if effective.policy else None
        if sup_effective is None:
            raise _cascade_plan_unavailable()
        result = supervisor_semantic.resolve_supervisor_reload_plan_path(sup_effective, manifest)
        if result is None:
            raise _cascade_plan_unavailable()
        plan_path = result.path
        source_desc = _source_desc(result.source, result.session_name)

    def _enable_cascade(m: SessionState) -> None:
        if m.intent.policy and m.intent.policy.supervisor:
            m.intent.policy.supervisor.cascade = True
            supervisor_semantic.apply_checker_options(
                m.intent.policy.supervisor,
                checker_model=checker_model,
                checker_provider=checker_provider,
                checker_effort=checker_effort,
            )
            if not m.intent.policy.supervisor.plan_override_path:
                m.intent.policy.supervisor.plan_override_path = plan_path

    store.update(timeout_s=lock_timeout_s, mutate=_enable_cascade)

    preview = replace(sup, plan_override_path=sup.plan_override_path or plan_path, cascade=True)
    supervisor_semantic.apply_checker_options(
        preview,
        checker_model=checker_model,
        checker_provider=checker_provider,
        checker_effort=checker_effort,
    )
    return SupervisorCascadeResult(enabled=True, config=preview, source_desc=source_desc)


def validate_supervisor_cascade_input(
    *,
    state: str,
    checker_model: str | None = None,
    checker_provider: str | None = None,
    checker_effort: str | None = None,
) -> None:
    cascade_on = state == "on"
    if not cascade_on and (checker_model or checker_provider or checker_effort):
        raise SupervisorInputError("Checker options only apply when enabling cascade (state 'on')")

    _validate_checker_model(checker_model)


def _validate_checker_model(checker_model: str | None) -> None:
    try:
        supervisor_semantic.validate_checker_model(checker_model)
    except ValueError as e:
        raise SupervisorInputError(str(e), tip="Example: google/gemini-3.5-flash") from e


def _resolve_requested_lane(*, runtime: str | None, backend: str | None) -> LaneRecord | None:
    if runtime is None and backend is None:
        return None
    try:
        if backend is not None:
            return lane_record_for(SUPERVISOR_CONSUMER, runtime=runtime, backend=backend)
        if runtime is not None:
            return lane_record_for_runtime(SUPERVISOR_CONSUMER, runtime)
    except LaneError as e:
        raise SupervisorLaneSelectionError(str(e)) from e
    return None


def _resolve_cascade_plan_for_set(sup_config: SupervisorConfig, manifest: SessionState) -> tuple[str, str]:
    result = supervisor_semantic.resolve_supervisor_reload_plan_path(sup_config, manifest)
    if result is None:
        raise _cascade_plan_unavailable()
    return result.path, _source_desc(result.source, result.session_name)


def _cascade_plan_unavailable() -> SupervisorPlanUnavailableError:
    message = "No approved plan snapshot found for the cascade's tier-1 checker."
    return SupervisorPlanUnavailableError(
        message,
        tip=(
            "Approve a plan (ExitPlanMode) in the planning session, or run "
            "'forge policy supervisor reload --from <path>' to set one explicitly, then retry."
        ),
        direct_reason=(
            "No approved plan snapshot found for the cascade's tier-1 checker. "
            "Approve a plan (ExitPlanMode), or use '%policy supervisor reload <path>' "
            "to set one explicitly, then retry."
        ),
    )


def _source_desc(source: str, session_name: str) -> str:
    source_map = {
        "self": "current session",
        "fork": f"review fork '{session_name}'",
        "target": "supervisor target",
    }
    return source_map.get(source, source)


def _has_supervisor_with_target(manifest: SessionState) -> bool:
    return bool(
        manifest.intent.policy and manifest.intent.policy.supervisor and manifest.intent.policy.supervisor.resume_id
    )

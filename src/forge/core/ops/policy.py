"""Shared policy activation rules and supervisor lifecycle operations."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast, get_args

import forge.policy.semantic.supervisor as supervisor_semantic
from forge.core.lanes import Consumer
from forge.policy.deterministic.registry import BUNDLES
from forge.policy.semantic.identity import snapshot_supervisor_options
from forge.policy.semantic.supervisor import SUPERVISOR_CONSUMER
from forge.policy.supervisor_lane_degrade import clear_supervisor_degrade
from forge.policy.types import FailMode
from forge.session import SessionStore
from forge.session.consumer_lanes import (
    clear_consumer_lane,
    confirmed_lane,
    set_intent_lane,
)
from forge.session.effective import compute_effective_intent
from forge.session.models import LaneRecord, SessionState, SupervisorConfig

POLICY_BUNDLE_NAMES: tuple[str, ...] = tuple(BUNDLES)
POLICY_FAIL_MODES: tuple[str, ...] = get_args(FailMode)


class PolicyOpError(RuntimeError):
    """Raised when a policy operation cannot complete."""


class PolicyActivationInputError(PolicyOpError):
    """Raised when policy activation or deactivation inputs are invalid."""


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
class PolicyActivationValues:
    """Validated values for one surface-owned policy write.

    The builder freshly allocates ``bundle_config`` for each result. Current callers hand that dict by reference to one
    surface writer, so callers must treat it as immutable after construction; ``frozen=True`` is not a recursive freeze.
    """

    enabled: bool
    bundles: tuple[str, ...] = ()
    fail_mode: FailMode = "open"
    bundle_config: dict[str, dict[str, object]] = field(default_factory=dict)


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


def build_policy_activation(
    *,
    enabled: bool,
    bundles: Sequence[str] = (),
    fail_mode: str = "open",
    permissive: bool = False,
) -> PolicyActivationValues:
    """Validate and construct the values written by a policy activation surface."""
    bundle_names = tuple(bundles)

    if not enabled:
        if bundle_names or fail_mode != "open" or permissive:
            raise PolicyActivationInputError("policy deactivation cannot include activation options")
        return PolicyActivationValues(enabled=False)

    if not bundle_names:
        raise PolicyActivationInputError("at least one policy bundle is required")

    unknown = tuple(dict.fromkeys(bundle for bundle in bundle_names if bundle not in POLICY_BUNDLE_NAMES))
    if unknown:
        raise PolicyActivationInputError(f"unknown policy bundle: {', '.join(unknown)}")
    if fail_mode not in POLICY_FAIL_MODES:
        raise PolicyActivationInputError(f"fail mode must be one of {', '.join(POLICY_FAIL_MODES)}, got {fail_mode!r}")

    bundle_config: dict[str, dict[str, object]] = {}
    if permissive and "tdd" in bundle_names:
        bundle_config["tdd"] = {"strict": False}

    return PolicyActivationValues(
        enabled=True,
        bundles=bundle_names,
        fail_mode=cast(FailMode, fail_mode),
        bundle_config=bundle_config,
    )


def supervisor_set(
    *,
    store: SessionStore,
    manifest: SessionState,
    target: str | None,
    policy_forge_root: str | None,
    plan: str | Path | None = None,
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
    model: str | None = None,
    auth_mode: str = "inherit",
    lock_timeout_s: float = 5.0,
    confirmed_lane_func: Callable[[SessionState, Consumer], LaneRecord | None] = confirmed_lane,
) -> SupervisorSetResult:
    validate_supervisor_set_input(
        supervisor_proxy=supervisor_proxy,
        supervisor_direct=supervisor_direct,
        cascade_flag=cascade_flag,
        checker_model=checker_model,
    )
    if timeout_seconds is not None:
        from forge.policy.semantic.deadline import validate_timeout

        try:
            validate_timeout(timeout_seconds)
        except ValueError as exc:
            raise SupervisorInputError(str(exc)) from exc
    checker_option_supplied = bool(checker_model or checker_provider or checker_effort)

    if not target and plan is None:
        raise SupervisorInputError("Provide a planning target or --plan <file>.")
    plan_path = _validated_plan_path(plan) if plan is not None else None
    if plan_path and _is_sidecar(manifest):
        raise SupervisorInputError("Plan-file supervision is not supported in sidecars. Use a host executor.")

    from forge.policy.semantic.identity import select_supervisor_lane, validate_reviewer
    from forge.session.consumer_lanes import read_bound_lane

    if auth_mode == "subscription-only":
        if supervisor_proxy:
            raise SupervisorInputError("Subscription-only supervision cannot use a proxy.")
        supervisor_direct = True
        backend = backend or "claude-max"
    previous_lane = read_bound_lane(manifest, SUPERVISOR_CONSUMER)
    try:
        lane_record = (
            select_supervisor_lane(
                runtime=runtime or (previous_lane.runtime_id if previous_lane else None),
                backend=backend or (previous_lane.backend_id if previous_lane and not runtime else None),
                model=model,
            )
            if runtime or backend or model or not target
            else None
        )
        selected_lane = lane_record or previous_lane or select_supervisor_lane()
        selected_model = selected_lane.model if model or not target else None
        preview = SupervisorConfig(
            resume_id=target,
            plan_override_path=plan_path,
            supervisor_model=selected_model,
            auth_mode=auth_mode,
            supervisor_effort=supervisor_effort,
            proxy=supervisor_proxy,
            direct=supervisor_direct,
            cascade=bool(cascade_flag),
        )
        validate_reviewer(preview, selected_lane)
    except ValueError as exc:
        raise SupervisorInputError(str(exc)) from exc
    if auth_mode == "subscription-only" and _is_sidecar(manifest):
        raise SupervisorInputError("Subscription-only supervision requires a host executor.")

    def check_frozen(state: SessionState) -> None:
        frozen = confirmed_lane_func(state, SUPERVISOR_CONSUMER)
        if frozen is None:
            return
        old = snapshot_supervisor_options(state)
        changed_options = old is not None and (
            old.auth_mode != auth_mode
            or old.supervisor_model != selected_model
            or old.supervisor_effort != supervisor_effort
        )
        if (lane_record is not None and frozen != lane_record) or changed_options:
            raise SupervisorLaneFrozenError(frozen)

    check_frozen(manifest)

    try:
        source_state = (
            supervisor_semantic.validate_supervisor_target(target, forge_root=policy_forge_root) if target else manifest
        )
    except ValueError as e:
        raise SupervisorTargetError(str(e)) from e

    started_proxy_id: str | None = None
    started_proxy_template: str | None = None

    current_template = manifest.intent.proxy.template if manifest.intent.proxy else None
    current_launch = manifest.confirmed.launch
    current_proxy_id = current_launch.proxy_id if current_launch else None
    current_direct = not bool(manifest.intent.proxy)

    sup_config = SupervisorConfig(
        resume_id=target,
        forge_root=source_state.forge_root or policy_forge_root,
        plan_override_path=plan_path,
        auth_mode=auth_mode,
        supervisor_model=selected_model,
    )
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
        runtime=selected_lane.runtime_id,
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
        if not plan_path:
            plan_path, cascade_source_desc = _resolve_cascade_plan_for_set(sup_config, manifest)
            sup_config.plan_override_path = plan_path
    elif checker_option_supplied:
        supervisor_semantic.apply_checker_options(
            sup_config,
            checker_model=checker_model,
            checker_provider=checker_provider,
            checker_effort=checker_effort,
        )

    try:
        validate_reviewer(sup_config, selected_lane)
        from forge.policy.semantic.identity import validate_sidecar_supervisor

        validate_sidecar_supervisor(sup_config, sidecar=_is_sidecar(manifest))
        if not _is_sidecar(manifest):
            from forge.core.reactive.reviewer_runtime import (
                preflight_supervisor_runtime,
            )

            preflight_supervisor_runtime(
                sup_config, selected_lane, cwd=manifest.worktree.path if manifest.worktree else None
            )
        else:
            from forge.runtime_config import get_runtime_config
            from forge.session.launch import get_launch_preferences
            from forge.sidecar.docker import require_sidecar_contract

            image = get_launch_preferences(manifest)[2] or get_runtime_config().sidecar_image
            require_sidecar_contract(image, schema_version=3 if selected_model else 2, reviewer=True)
    except ValueError as exc:
        raise SupervisorInputError(str(exc)) from exc

    if supervisor_proxy:
        try:
            resolved_proxy_id, started = supervisor_semantic.ensure_supervisor_proxy(supervisor_proxy)
        except ValueError as e:
            raise SupervisorProxyError(str(e)) from e
        if started:
            started_proxy_id = resolved_proxy_id
            started_proxy_template = supervisor_proxy
        supervisor_proxy = resolved_proxy_id

        sup_config.proxy = supervisor_proxy
        routing_display = supervisor_proxy

    def _apply(m: SessionState) -> None:
        check_frozen(m)
        validate_sidecar_supervisor(sup_config, sidecar=_is_sidecar(m))
        replacements = tuple(
            name
            for name, value in (
                ("timeout_seconds", timeout_seconds),
                ("checker_model", checker_model),
                ("checker_provider", checker_provider),
                ("checker_effort", checker_effort),
            )
            if value is not None
        )
        supervisor_semantic.apply_supervisor_to_intent(m, sup_config, replace_overrides=replacements)
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
    if not _has_configured_supervisor(manifest):
        raise SupervisorNotConfiguredError("No supervisor configured.")

    def _suspend(m: SessionState) -> None:
        from forge.session.overrides import delete_override

        delete_override(m.overrides, "policy.supervisor.suspended")
        if m.intent.policy and m.intent.policy.supervisor:
            m.intent.policy.supervisor.suspended = True

    store.update(timeout_s=lock_timeout_s, mutate=_suspend)


def supervisor_on(*, store: SessionStore, manifest: SessionState, lock_timeout_s: float = 5.0) -> None:
    if not _has_configured_supervisor(manifest):
        raise SupervisorNotConfiguredError("No supervisor configured.")

    def _resume(m: SessionState) -> None:
        from forge.session.overrides import delete_override

        delete_override(m.overrides, "policy.supervisor.suspended")
        if m.intent.policy and m.intent.policy.supervisor:
            m.intent.policy.supervisor.suspended = False

    store.update(timeout_s=lock_timeout_s, mutate=_resume)


def supervisor_remove(*, store: SessionStore, manifest: SessionState, lock_timeout_s: float = 5.0) -> None:
    if not (manifest.intent.policy and manifest.intent.policy.supervisor):
        raise SupervisorNotConfiguredError("No supervisor configured.")

    def _remove(m: SessionState) -> None:
        from forge.session.overrides import delete_override

        delete_override(m.overrides, "policy.supervisor")
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
    if not effective.policy or not effective.policy.supervisor or not effective.policy.supervisor.configured:
        raise SupervisorNotConfiguredError("No supervisor configured.")

    if reload_path:
        resolved = Path(reload_path)
        if not resolved.is_absolute():
            resolved = (cwd / resolved).resolve()
        plan_path = _validated_plan_path(resolved)
        source_desc = str(resolved)
    elif not effective.policy.supervisor.resume_id:
        plan_path = _validated_plan_path(effective.policy.supervisor.plan_override_path or "")
        source_desc = plan_path
    else:
        result = supervisor_semantic.resolve_supervisor_reload_plan_path(effective.policy.supervisor, manifest)
        if result is None:
            raise SupervisorPlanUnavailableError("No approved plan found for supervisor target or related sessions.")
        plan_path = result.path
        source_desc = _source_desc(result.source, result.session_name)

    if _is_sidecar(manifest):
        raise SupervisorInputError("Plan-file supervision requires a host executor.")

    def _set_plan(m: SessionState) -> None:
        if _is_sidecar(m):
            raise SupervisorInputError("Plan-file supervision requires a host executor.")
        from forge.session.overrides import delete_override

        delete_override(m.overrides, "policy.supervisor.plan_override_path")
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
    if cascade_on and _is_sidecar(manifest):
        raise SupervisorInputError("Plan-file supervision requires a host executor.")

    sup = manifest.intent.policy.supervisor if manifest.intent.policy else None
    if not (sup and sup.configured):
        raise SupervisorNotConfiguredError("No supervisor configured.")
    if cascade_on and sup.auth_mode == "subscription-only":
        raise SupervisorInputError("Subscription-only supervision cannot enable the paid API checker.")

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
        if _is_sidecar(m):
            raise SupervisorInputError("Plan-file supervision requires a host executor.")
        if m.intent.policy and m.intent.policy.supervisor:
            if m.intent.policy.supervisor.auth_mode == "subscription-only":
                raise SupervisorInputError("Subscription-only supervision cannot enable the paid API checker.")
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
        raise SupervisorInputError(str(e), tip="Example: google/gemini-3.8-flash") from e


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


def _has_configured_supervisor(manifest: SessionState) -> bool:
    return bool(
        manifest.intent.policy and manifest.intent.policy.supervisor and manifest.intent.policy.supervisor.configured
    )


def _validated_plan_path(path: str | Path) -> str:
    resolved = Path(path).expanduser().absolute()
    if not resolved.is_file():
        raise SupervisorPlanFileNotFoundError(f"Plan file not found or not a regular file: {resolved}")
    try:
        content = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SupervisorInputError(f"Cannot read plan file {resolved}: {exc}") from exc
    if not content.strip():
        raise SupervisorInputError(f"Plan file is empty: {resolved}")
    return str(resolved)


def _is_sidecar(manifest: SessionState) -> bool:
    from forge.session.launch import is_sidecar_session

    return is_sidecar_session(manifest)

"""Supervisor-owned model choices; shared consumer lane formats stay unchanged."""

from __future__ import annotations

import json
from dataclasses import asdict

import dacite

from forge.core.effort import CODEX_EFFORT_LEVELS, validate_claude_effort
from forge.core.lanes import Consumer, Lane, resolve_lane
from forge.core.models.catalog import (
    get_model_spec,
    load_model_catalog,
    resolve_model_id,
)
from forge.session.models import (
    LaneRecord,
    SessionIntent,
    SessionState,
    SupervisorConfig,
)

CLAUDE_MODELS = (
    "opus",
    "sonnet",
    "haiku",
    *(model for model in load_model_catalog().models if model.startswith("claude-")),
)
CODEX_MODELS = ("gpt-5-codex", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol", "gpt-6-astra")

SUPERVISOR_CONSUMER = Consumer(
    id="supervisor",
    capability_floor="tool_agent",
    default_lane=Lane("claude_code", "anthropic-direct", "opus"),
    allowed_lanes=(
        Lane("codex", "chatgpt", "gpt-5-codex"),
        Lane("claude_code", "claude-max", "opus"),
        *(
            Lane("claude_code", backend, model)
            for backend in ("anthropic-direct", "claude-max")
            for model in CLAUDE_MODELS
            if model != "opus"
        ),
        *(Lane("codex", "chatgpt", model) for model in CODEX_MODELS if model != "gpt-5-codex"),
    ),
)


def select_supervisor_lane(
    *,
    runtime: str | None = None,
    backend: str | None = None,
    model: str | None = None,
) -> LaneRecord:
    """Select supervisor defaults explicitly instead of making backend matches ambiguous."""
    runtime = runtime or ("codex" if backend == "chatgpt" else "claude_code")
    backend = backend or ("chatgpt" if runtime == "codex" else "anthropic-direct")
    model = model or ("gpt-5-codex" if runtime == "codex" else "opus")
    if model not in (*CLAUDE_MODELS, *CODEX_MODELS):
        model = resolve_model_id(model)
    lane = resolve_lane(SUPERVISOR_CONSUMER, override=Lane(runtime, backend, model))
    return LaneRecord(lane.runtime_id, lane.backend_id, lane.model)


def validate_reviewer(config: SupervisorConfig, lane: LaneRecord) -> None:
    """Validate authored or decoded configuration before any model/proxy dispatch."""
    if config.review_trigger == "stop" and (config.cascade or config.shadow_sample_rate):
        raise ValueError("Stop supervision cannot use cascade or shadow sampling.")
    if config.supervisor_model is not None and config.supervisor_model != lane.model:
        raise ValueError("Supervisor model differs from its bound lane. Remove and reconfigure the supervisor.")
    if config.native_source:
        if (
            lane.runtime_id != "codex"
            or config.resume_id
            or config.cascade
            or config.shadow_sample_rate
            or not config.fork_session
        ):
            raise ValueError("Native sources require an isolated Codex reviewer without resume, cascade or shadow")
        if config.auth_mode not in {"subscription-only", "api"}:
            raise ValueError("Native Codex sources require explicit subscription-only or api auth")
        if config.supervisor_model not in {"gpt-6.1-sol", "gpt-6-sol"} or config.supervisor_effort != "low":
            raise ValueError("Native supervision currently requires gpt-6.1-sol or gpt-6-sol with low effort")
        if config.review_trigger == "stop" and not config.plan_override_path:
            raise ValueError("Native Stop supervision requires an explicit approved plan file")
    effort = config.supervisor_effort
    if lane.runtime_id == "codex":
        if config.proxy or config.base_url:
            raise ValueError("Codex supervision cannot use a Claude supervisor proxy.")
        if effort is not None and effort not in CODEX_EFFORT_LEVELS:
            raise ValueError("Unsupported Codex supervisor effort.")
        if config.supervisor_model and effort:
            supported = get_model_spec(config.supervisor_model).litellm_reasoning_efforts
            if supported is not None and effort not in supported:
                raise ValueError(f"{config.supervisor_model} does not support effort {effort!r}.")
    else:
        validate_claude_effort(effort)
        if (config.proxy or config.base_url) and config.supervisor_model not in (None, "opus", "sonnet", "haiku"):
            raise ValueError("Proxied supervisors select opus, sonnet, or haiku; the proxy owns their model mapping.")
    if config.native_source:
        return  # The native route is enforced in the dedicated fork child.
    if config.auth_mode == "subscription-only":
        if lane.runtime_id != "claude_code" or lane.backend_id != "claude-max" or not config.direct:
            raise ValueError("Subscription-only supervision requires direct Claude on backend claude-max.")
        if config.proxy or config.base_url or config.cascade:
            raise ValueError("Subscription-only supervision cannot use proxies or the paid API checker.")
    elif config.auth_mode != "inherit":
        raise ValueError("Supervisor auth_mode must be inherit or subscription-only.")


def validate_sidecar_supervisor(config: SupervisorConfig | None, *, sidecar: bool) -> None:
    if sidecar and config and config.native_source:
        raise ValueError("Native Codex supervision requires a host executor")
    if sidecar and config and config.review_trigger == "stop":
        raise ValueError(
            "Stop supervision requires a host Codex executor. Select pre-tool-use before changing runtime."
        )
    if sidecar and config and (config.plan_override_path or config.auth_mode == "subscription-only"):
        raise ValueError(
            "Plan-file and subscription-only supervision require a host executor. Remove supervision or launch on the host."
        )


def validate_stop_executor(config: SupervisorConfig | None, *, runtime: str, sidecar: bool = False) -> None:
    """Refuse unsupported Stop intent before creating or launching a child."""
    if config and config.review_trigger == "stop" and (runtime != "codex" or sidecar):
        raise ValueError(
            "Stop supervision requires a host Codex executor. Select pre-tool-use before changing runtime."
        )


def reviewer_cache_identity(config: SupervisorConfig, lane: LaneRecord | None) -> str:
    """A cache entry proves only the exact source and dispatch identity that produced it."""
    return json.dumps(
        {
            "lane": asdict(lane) if lane else None,
            "target": config.resume_id,
            "native_source": asdict(config.native_source) if config.native_source else None,
            "root": config.forge_root,
            "model": config.supervisor_model,
            "effort": config.supervisor_effort,
            "auth": config.auth_mode,
            "direct": config.direct,
            "proxy": config.proxy,
            "base_url": config.base_url,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def snapshot_supervisor_options(state: SessionState) -> SupervisorConfig | None:
    """Read the old review identity without decoding unrelated, possibly invalid overrides."""
    from forge.session.effective import apply_overrides

    policy = apply_overrides(asdict(state.intent), state.overrides).get("policy")
    raw = policy.get("supervisor") if isinstance(policy, dict) else None
    return dacite.from_dict(SupervisorConfig, raw, config=dacite.Config(strict=True)) if raw else None


def validate_supervisor_transition(state: SessionState, old: SupervisorConfig | None, effective: SessionIntent) -> None:
    """Validate effective configuration under the session lock, without runtime I/O.

    Reviewer readiness belongs to setup/launch and each review, not unrelated
    overrides or recovery operations such as disabling policy.
    """
    from forge.policy.semantic.deadline import validate_timeout
    from forge.session.consumer_lanes import confirmed_lane, read_bound_lane

    sup = effective.policy.supervisor if effective.policy else None
    if (sup.native_source if sup else None) != (old.native_source if old else None):
        raise ValueError("Native source identity requires remove/reconfigure with supervisor set.")
    if sup and sup.configured:
        validate_timeout(sup.timeout_seconds, trigger=sup.review_trigger)
        validate_reviewer(sup, read_bound_lane(state, SUPERVISOR_CONSUMER) or select_supervisor_lane())
        sidecar = effective.launch.mode == "sidecar" if effective.launch else bool(state.confirmed.is_sandboxed)
        validate_sidecar_supervisor(sup, sidecar=sidecar)
        from forge.session.models import session_runtime

        validate_stop_executor(sup, runtime=session_runtime(state), sidecar=sidecar)
    if confirmed_lane(state, SUPERVISOR_CONSUMER) is not None:

        def identity(value: SupervisorConfig | None):
            return (
                (value.auth_mode, value.supervisor_model, value.supervisor_effort, value.native_source)
                if value
                else None
            )

        if identity(sup) != identity(old):
            raise ValueError("Frozen supervisor identity requires remove/reconfigure.")


def validate_inherited_claude_trigger(parent: SessionState, *, preserve_overrides: bool = False) -> None:
    """Guard policy-inheriting Claude derivation before transfer or publication."""
    sup = snapshot_supervisor_options(parent)
    if sup:
        validate_stop_executor(sup, runtime="claude")
    # Derivation copies intent without overrides. Validate both the parent's
    # effective identity and the exact native configuration the child inherits.
    # Relaunch preserves overrides but not the parent's frozen lane binding.
    from forge.session.consumer_lanes import intent_lane, read_bound_lane
    from forge.session.effective import apply_overrides

    effective_policy = apply_overrides(asdict(parent.intent), parent.overrides).get("policy")
    effective_enabled = bool(effective_policy and effective_policy.get("enabled"))
    inherited = sup if preserve_overrides else parent.intent.policy.supervisor if parent.intent.policy else None
    inherited_enabled = (
        effective_enabled if preserve_overrides else bool(parent.intent.policy and parent.intent.policy.enabled)
    )
    for candidate, lane, enabled in (
        (sup, read_bound_lane(parent, SUPERVISOR_CONSUMER), effective_enabled),
        (inherited, intent_lane(parent, SUPERVISOR_CONSUMER), inherited_enabled),
    ):
        if candidate and candidate.native_source:
            validate_reviewer(candidate, lane or select_supervisor_lane())
            if enabled and candidate.active:
                from forge.policy.semantic.native_codex import preflight_native

                preflight_native(candidate)

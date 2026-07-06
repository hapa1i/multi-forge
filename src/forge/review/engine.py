"""Multi-model review engine with parallel fan-out.

Spawns N ``claude -p`` subprocesses in parallel via ThreadPoolExecutor,
one per model backend. Each subprocess runs in its own process group
(``start_new_session=True``) so that cleanup via ``os.killpg`` can
terminate orphaned children if the parent is interrupted.

Routing is pre-resolved: the engine receives a ``WorkerRoutingPlan``
and passes each worker its ``RoutingResult``. No per-worker registry
lookups during fan-out.
"""

from __future__ import annotations

import logging
import os
import shutil

from forge.core.auth.capabilities import CREDENTIALS, format_missing_credential_error
from forge.core.auth.template_secrets import resolve_env_or_credential
from forge.core.invoker import (
    Attribution,
    ClaudeHeadlessInvoker,
    HeadlessRequest,
    HeadlessResult,
)
from forge.core.models.direct_model import direct_model_env
from forge.core.reactive.env import (
    FORGE_COMMAND_VAR,
    build_claude_env,
    can_use_bare,
    should_spawn_subprocesses,
)
from forge.core.reactive.routing import RoutingResult
from forge.review.routing import (
    WorkerRoutingPlan,
    resolve_invocation_routing,
    resolve_model_flag,
)

from .models import (
    DEFAULT_MODELS,
    ModelSpec,
    MultiReviewOutput,
    ReviewResult,
)

_log = logging.getLogger(__name__)


def preflight_check(
    specs: list[ModelSpec],
    routing_plan: WorkerRoutingPlan | None = None,
) -> list[str]:
    """Validate routing before spawning workers.

    When a routing_plan is provided, validates each result has a route.
    Otherwise falls back to check_model_availability().

    Returns a list of error strings (empty means all OK).
    """
    errors: list[str] = []

    if should_spawn_subprocesses() and shutil.which("claude") is None:
        errors.append(
            "claude CLI not found in PATH. `forge workflow` workers run through local `claude -p`, "
            "even for proxy-routed models; install Claude Code or expose `claude` on PATH in the "
            "environment running `forge workflow`."
        )

    if routing_plan is not None:
        for spec, result in zip(specs, routing_plan.routes):
            if result.route is None:
                reason = result.warning or "No compatible route found"
                errors.append(f"{spec.name}: {reason}")
                continue

            credential_error = _credential_preflight_error(spec, result)
            if credential_error:
                errors.append(credential_error)
        return errors

    from .models import check_model_availability

    availabilities = check_model_availability(specs)
    for avail in availabilities:
        if avail.status == "ready":
            continue
        if avail.spec.preferred_proxy:
            hint = f" Run 'forge proxy create {avail.spec.preferred_proxy}' to set it up."
        else:
            hint = " Run 'forge auth login -c anthropic-api' or use --models to select only proxy-backed models."
        errors.append(f"{avail.spec.name}: {avail.reason}.{hint}")
    return errors


def _credential_preflight_error(spec: ModelSpec, result: RoutingResult) -> str | None:
    """Return an actionable missing-credential error for direct workflow routes."""
    route = result.route
    if route is None or route.provider != "direct":
        return None

    credential = CREDENTIALS.get(route.credential)
    if credential is None:
        return None

    missing_vars = [
        env_var.name
        for env_var in credential.env_vars
        if env_var.required and not resolve_env_or_credential(env_var.name)
    ]
    if not missing_vars:
        return None

    return format_missing_credential_error(
        credential,
        missing_vars=missing_vars,
        context=f"Workflow model '{spec.name}'",
    )


def run_multi_review(
    prompt: str,
    *,
    models: list[ModelSpec] | None = None,
    routing_plan: WorkerRoutingPlan | None = None,
    timeout_seconds: int = 600,
    cwd: str | None = None,
    resume_id: str | None = None,
    attribution: Attribution | None = None,
    reasoning_effort: str | None = None,
) -> MultiReviewOutput:
    """Fan out a review prompt to multiple models in parallel.

    Routing and per-worker request shaping happen here (review domain); the spawn
    lifecycle (process groups, signal cleanup, ordered fan-out, timeouts) is
    delegated to ``ClaudeHeadlessInvoker.run_parallel`` so it is shared with future
    runtimes (Phase 5). When ``attribution`` is set, the invoker emits a per-worker
    UsageEvent for each spawned worker.

    Args:
        prompt: The review prompt to send to each model.
        models: Model specs to use. Defaults to DEFAULT_MODELS values.
        routing_plan: Pre-resolved routing for all workers. When None,
            resolves routing once at the top before fan-out.
        timeout_seconds: Per-model timeout in seconds.
        cwd: Working directory for each subprocess.
        resume_id: If set, adds ``--resume <id>`` to each subprocess.
        attribution: Verb context (command/workflow/session) for per-worker usage
            events. None (default) skips per-worker emission.
        reasoning_effort: ``claude --effort`` level applied to every worker's
            ``claude -p`` argv. None (default) omits the flag (tier default).

    Returns:
        MultiReviewOutput with per-model results in input order.
        Returns empty results if FORGE_DEPTH limit reached.
    """
    if not should_spawn_subprocesses():
        _log.debug("Skipping ensemble review at FORGE_DEPTH limit")
        return MultiReviewOutput(prompt=prompt)

    specs = models if models is not None else list(DEFAULT_MODELS.values())

    if not specs:
        return MultiReviewOutput(prompt=prompt)

    # Resolve routing once if not provided by caller
    if routing_plan is None:
        try:
            routing_plan = resolve_invocation_routing(specs)
        except Exception as e:
            _log.warning("Routing resolution failed: %s", e)
            return MultiReviewOutput(
                prompt=prompt,
                results=[
                    ReviewResult(
                        model_name=s.effective_worker_id,
                        stdout="",
                        stderr="",
                        success=False,
                        duration_seconds=0.0,
                        error=str(e),
                    )
                    for s in specs
                ],
            )

    # Shape each worker into a request (routing -> env + argv + prompt). A worker
    # whose route fails to resolve becomes a failed ReviewResult here, without
    # spawning. Only the spawnable requests go to the invoker.
    prepared = [
        _prepare_worker(
            spec,
            routing_plan.routes[idx],
            prompt=prompt,
            cwd=cwd,
            resume_id=resume_id,
            timeout_seconds=timeout_seconds,
            attribution=attribution,
            reasoning_effort=reasoning_effort,
        )
        for idx, spec in enumerate(specs)
    ]

    results: dict[int, ReviewResult] = {}
    spawnable: list[tuple[int, HeadlessRequest]] = []
    for idx, item in enumerate(prepared):
        if isinstance(item, HeadlessRequest):
            spawnable.append((idx, item))
        else:
            results[idx] = item

    if spawnable:
        outcomes = ClaudeHeadlessInvoker().run_parallel([req for _, req in spawnable])
        for (idx, req), outcome in zip(spawnable, outcomes):
            results[idx] = _to_review_result(req, outcome)

    # Return in deterministic input order
    ordered = [results[idx] for idx in range(len(specs)) if idx in results]
    return MultiReviewOutput(prompt=prompt, results=ordered)


def _prepare_worker(
    spec: ModelSpec,
    routing_result: RoutingResult,
    *,
    prompt: str,
    cwd: str | None,
    resume_id: str | None,
    timeout_seconds: int,
    attribution: Attribution | None,
    reasoning_effort: str | None = None,
) -> ReviewResult | HeadlessRequest:
    """Shape one worker into a HeadlessRequest, or a failed ReviewResult.

    Returns a ReviewResult (no spawn) when the route doesn't resolve or the
    direct-model env can't be built; otherwise a HeadlessRequest carrying the
    built ``claude -p`` argv + env (with run-tree identity stamped) + the
    per-worker prompt.
    """
    if spec.prompt is None:
        worker_prompt = prompt
    elif spec.prompt_mode == "prefix":
        worker_prompt = f"{spec.prompt}\n\n{prompt}" if prompt else spec.prompt
    else:
        worker_prompt = spec.prompt

    # Review fan-out is per-prompt with no session name in scope, so X-Forge-Session
    # falls back to forge_run_<hash>; only the command role is stamped here.
    extra_env: dict[str, str] = {FORGE_COMMAND_VAR: "review"}
    if not os.environ.get("ANTHROPIC_API_KEY"):
        ak = resolve_env_or_credential("ANTHROPIC_API_KEY")
        if ak:
            extra_env["ANTHROPIC_API_KEY"] = ak

    route = routing_result.route
    if route is None:
        return ReviewResult(
            model_name=spec.effective_worker_id,
            stdout="",
            stderr="",
            success=False,
            duration_seconds=0.0,
            error=f"No route resolved for '{spec.name}'",
        )

    if route.provider == "direct":
        try:
            extra_env.update(direct_model_env(route.model_ref))
        except ValueError as e:
            return ReviewResult(
                model_name=spec.effective_worker_id,
                stdout="",
                stderr="",
                success=False,
                duration_seconds=0.0,
                error=str(e),
            )
        env = build_claude_env(direct=True, extra_vars=extra_env or None)
    else:
        env = build_claude_env(base_url=routing_result.base_url, extra_vars=extra_env or None)

    cmd = ["claude", "-p"]
    if can_use_bare(env):
        cmd.append("--bare")
    if resume_id:
        cmd.extend(["--resume", resume_id])
    model_flag = resolve_model_flag(route)
    if model_flag:
        cmd.extend(["--model", model_flag])
    if reasoning_effort:
        cmd.extend(["--effort", reasoning_effort])

    return HeadlessRequest(
        argv=cmd,
        prompt=worker_prompt,
        env=env,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        label=spec.effective_worker_id,
        # Record what actually ran (the resolved route), not the friendly catalog id:
        # a proxied worker's `route.model_ref` is the provider-prefixed model that
        # executed, with its provider + proxy. (`spec.model_id` stays recoverable via `label`.)
        model=route.model_ref,
        provider=route.provider,
        proxy_id=routing_result.proxy_id,
        # base_url drives Phase 5 cost precedence (None = direct -> runtime self-report
        # may count; set = proxied -> the verb aggregate holds the cost). output_format
        # defaults to "json" so the invoker injects --output-format (guarded); we never
        # append it to `cmd` here, so the capability guard covers the review fan-out too.
        base_url=routing_result.base_url,
        attribution=attribution,
    )


def _to_review_result(request: HeadlessRequest, outcome: HeadlessResult) -> ReviewResult:
    """Map a HeadlessResult back to a ReviewResult.

    Preserves the engine's original status conventions: strip stdout on success,
    ``stderr.strip() or "Exit code N"`` on non-zero exit, the ``Timeout after Ns``
    string with the configured timeout as the recorded duration.
    """
    identity = {
        "run_id": outcome.run_id,
        "parent_run_id": outcome.parent_run_id,
        "root_run_id": outcome.root_run_id,
    }
    model_name = request.label or ""

    if outcome.timed_out:
        return ReviewResult(
            model_name=model_name,
            stdout="",
            stderr="",
            success=False,
            duration_seconds=float(request.timeout_seconds),
            error=f"Timeout after {request.timeout_seconds}s",
            **identity,
        )
    if outcome.error is not None:
        return ReviewResult(
            model_name=model_name,
            stdout="",
            stderr="",
            success=False,
            duration_seconds=outcome.duration_seconds,
            error=outcome.error,
            **identity,
        )
    if outcome.returncode != 0:
        return ReviewResult(
            model_name=model_name,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            success=False,
            duration_seconds=outcome.duration_seconds,
            error=outcome.stderr.strip() or f"Exit code {outcome.returncode}",
            **identity,
        )
    return ReviewResult(
        model_name=model_name,
        stdout=outcome.stdout.strip(),
        stderr=outcome.stderr,
        success=True,
        duration_seconds=outcome.duration_seconds,
        **identity,
    )

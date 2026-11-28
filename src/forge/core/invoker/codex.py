"""Codex headless invoker (Phase 5b).

Concrete :class:`HeadlessInvoker` for ``codex exec --json``, sharing the hardened
subprocess lifecycle in :class:`_HeadlessLifecycleBase`. Codex differs from Claude in
three ways the hooks capture:

- **argv**: the caller builds the full ``codex exec --json --sandbox ...`` argv
  (:func:`prepare_codex_request`). Managed executors select and identify their
  launcher just before spawn; worker/reviewer jobs retain the caller's argv.
- **result**: the output is a JSONL *event stream*, reduced by
  :func:`parse_codex_jsonl_stream`, not a single envelope.
- **emit**: a ``codex_exec`` usage event with JSONL tokens. On managed Responses
  routes the proxy records charges for its individual creates.

Codex never enters the format-retry branch: it inherits the base
``_is_recoverable_format_rejection`` (always ``False``), so ``_on_format_rejection`` is
unreachable for it.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import replace
from functools import partial
from typing import Literal
from urllib.parse import urlsplit

from forge.core.invoker._lifecycle import (
    ParseHints,
    _HeadlessLifecycleBase,
    _Identity,
    _record_worker_upstream,
    _status,
)
from forge.core.invoker.codex_fork import CodexContinuationRequest
from forge.core.invoker.codex_stream import parse_codex_jsonl_stream
from forge.core.invoker.types import Attribution, HeadlessRequest, HeadlessResult
from forge.core.reactive.env import (
    FORGE_AUTHORITY_MARKER_VAR,
    FORGE_DEPTH_VAR,
    FORGE_PARENT_RUN_ID_VAR,
    FORGE_PROXY_WIRE_SHAPE_VAR,
    FORGE_ROOT_RUN_ID_VAR,
    FORGE_RUN_ID_VAR,
    FORGE_SUBPROCESS_BASE_URL_VAR,
    FORGE_SUBPROCESS_PROXY_ID_VAR,
    FORGE_SUBPROCESS_PROXY_VAR,
    FORGE_SUBPROCESS_TEMPLATE_VAR,
    get_forge_depth,
    get_run_identity,
    stamp_run_identity,
)
from forge.core.runtime.codex_feedback import (
    CODEX_EXECUTOR_IDENTITY_VAR,
    prepare_executor_launch,
)
from forge.core.runtime.codex_preflight import (
    CodexPreflight,
    codex_api_key_for_subprocess,
)
from forge.core.runtime.codex_proxy_launch import (
    CODEX_PROXY_TOKEN_VAR,
    CodexProxyLaunch,
)
from forge.core.runtime.codex_resume_usage import (
    NativeUsageUnavailable,
    capture_native_resume,
)
from forge.core.runtime.codex_usage import CodexUsageBaseline, continued_usage_delta
from forge.core.runtime.registry import get_runtime
from forge.core.worker_controls import CODEX_WORKER_PROFILE

CodexSandbox = Literal["read-only", "workspace-write", "danger-full-access"]

# Inherited env a direct Codex child must NOT keep: Claude/proxy routing (Codex ignores it,
# and the run is direct) and any auth that could contradict the preflight's resolved posture
# (a stale inherited CODEX_API_KEY would override a codex_store/ChatGPT login). Stripped, then
# only the preflight-resolved auth is re-established.
_CODEX_CHILD_STRIP_VARS = (
    CODEX_EXECUTOR_IDENTITY_VAR,
    CODEX_PROXY_TOKEN_VAR,
    "CODEX_API_KEY",
    "CODEX_ACCESS_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_CUSTOM_HEADERS",
    FORGE_SUBPROCESS_PROXY_VAR,
    FORGE_SUBPROCESS_BASE_URL_VAR,
    FORGE_SUBPROCESS_PROXY_ID_VAR,
    FORGE_SUBPROCESS_TEMPLATE_VAR,
)


# These hook variables are captured under _temporary_run_env, scoped to the child session.
_MANAGED_IDENTITY_VARS = (
    "FORGE_SESSION",
    "FORGE_FORGE_ROOT",
    "FORGE_SESSION_INSTANCE",
    FORGE_RUN_ID_VAR,
    FORGE_ROOT_RUN_ID_VAR,
    FORGE_PARENT_RUN_ID_VAR,
    FORGE_AUTHORITY_MARKER_VAR,
)


def _build_codex_proxy_env() -> dict[str, str]:
    """Give the client a synthetic bearer and leave upstream auth with the proxy."""
    env = os.environ.copy()
    for var in (
        *_CODEX_CHILD_STRIP_VARS,
        *_MANAGED_IDENTITY_VARS,
        "FORGE_FORK_NAME",
        "FORGE_PARENT_SESSION",
        FORGE_PROXY_WIRE_SHAPE_VAR,
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_ORGANIZATION",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT",
        "OPENAI_BASE_URL",
    ):
        env.pop(var, None)
    env[FORGE_DEPTH_VAR] = str(get_forge_depth(env) + 1)
    env[CODEX_PROXY_TOKEN_VAR] = "forge-loopback"
    return env


class CodexHeadlessInvoker(_HeadlessLifecycleBase):
    """Runs ``codex exec --json`` jobs. Implements the :class:`HeadlessInvoker` protocol."""

    def _prepare_argv(self, request: HeadlessRequest) -> tuple[list[str], ParseHints]:
        # Worker/reviewer jobs are not managed executors. Do not spend a reviewer's
        # whole-hook deadline on an executor feature probe.
        if request.attribution and request.attribution.command in {
            "codex-bridge",
            "codex-resume",
            "codex-enroll-verify",
        }:
            argv = prepare_executor_launch(request.argv, request.env, cwd=request.cwd)
        else:
            request.env.pop(CODEX_EXECUTOR_IDENTITY_VAR, None)
            argv = request.argv
        return argv, ParseHints(is_jsonl_stream=True)

    def _build_result(
        self,
        request: HeadlessRequest,
        *,
        stdout: str,
        stderr: str,
        returncode: int,
        duration_seconds: float,
        ident: _Identity,
        hints: ParseHints,
    ) -> HeadlessResult:
        stream = parse_codex_jsonl_stream(stdout, strict_usage=isinstance(request, CodexContinuationRequest))
        # Codex reports a failed turn in the JSONL stream, usually with EMPTY stderr; surface
        # the provider reason on stderr so a caller inspecting it sees why the turn failed.
        # Fall back to a generic line when the stream carried no (or an empty) error message,
        # so a failed turn never renders as a blank "Codex turn failed." with no detail.
        effective_stderr = stderr
        if not effective_stderr and stream.is_error:
            effective_stderr = stream.error_message or "Codex turn failed (no provider error message)."
        terminal = dict(
            input_tokens=stream.input_tokens, output_tokens=stream.output_tokens, cached_tokens=stream.cached_tokens
        )
        continuation = request if isinstance(request, CodexContinuationRequest) else None
        native = continuation.native_resume if continuation else None
        evidence: CodexUsageBaseline | NativeUsageUnavailable | None = (
            continuation.usage_baseline if continuation else None
        )
        if native is not None:
            if isinstance(native, NativeUsageUnavailable):
                evidence = native
            elif returncode == 0 and stream.single_completed_turn:
                evidence = native.verified_baseline(stream.thread_id, terminal)
            else:
                evidence = NativeUsageUnavailable("Codex did not report exactly one completed turn")
        baseline = evidence if isinstance(evidence, CodexUsageBaseline) else None
        usage = continued_usage_delta(baseline, terminal) if continuation else terminal
        usage_warning = None
        if native is not None and returncode == 0 and not stream.is_error and usage["input_tokens"] is None:
            reason = (
                evidence.reason if isinstance(evidence, NativeUsageUnavailable) else "invalid per-launch token delta"
            )
            usage_warning = f"Token usage is unknown for this resume ({reason})."
        return HeadlessResult(
            label=request.label,
            stdout=stream.final_text,
            stderr=effective_stderr,
            returncode=returncode,
            duration_seconds=duration_seconds,
            cost_micro_usd=None,  # The native JSONL stream reports tokens only.
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            cached_tokens=usage["cached_tokens"],
            terminal_usage=terminal if continuation else None,
            inherited_usage=baseline.as_dict() if baseline else None,
            usage_warning=usage_warning,
            # Parsed iff the stream yielded recognizable terminal events; a failed turn
            # (is_error) still parsed. An empty/garbage stream -> False, stdout "".
            envelope_parsed=bool(stream.final_text) or stream.input_tokens is not None or stream.is_error,
            runtime_is_error=stream.is_error,
            runtime_session_id=stream.thread_id,
            codex_turn_completed=stream.turn_completed,
            **ident,
        )

    def _emit(self, request: HeadlessRequest, result: HeadlessResult) -> None:
        _emit_codex(request, result)

    def _missing_binary_error(self) -> str:
        return "codex CLI not found in PATH"


def sanitize_codex_child_env(
    preflight: CodexPreflight, *, proxy_launch: CodexProxyLaunch | None = None
) -> dict[str, str]:
    """Prepare the child environment for a preflighted Codex route.

    Native children receive the resolved API key or enterprise token when their login needs one.
    Codex-store logins read their own auth. Proxy children use the synthetic loopback bearer.
    Both advance the Forge depth guard; managed launchers stamp the session and run identity.
    """
    if (preflight.auth_method == "proxy_token") != (proxy_launch is not None):
        raise ValueError("Codex preflight authentication and selected launch route disagree.")
    if proxy_launch is not None:
        env = _build_codex_proxy_env()
        # Codex honors ambient HTTP proxies. Keep this listener's headers and thread history on loopback.
        host = urlsplit(proxy_launch.base_url).hostname
        if host is None:
            raise ValueError("Codex proxy launch requires a loopback host.")
        bypass = ",".join(filter(None, (env.get("no_proxy"), env.get("NO_PROXY"), host)))
        env["no_proxy"] = env["NO_PROXY"] = bypass
        return env
    env = os.environ.copy()
    for var in _CODEX_CHILD_STRIP_VARS:
        env.pop(var, None)
    env[FORGE_DEPTH_VAR] = str(get_forge_depth(env) + 1)
    if preflight.auth_source in ("env", "credential_file"):
        if preflight.auth_method == "enterprise_token":
            # auth_source=env via CODEX_ACCESS_TOKEN (no API key): restore the exact token
            # (codex_api_key_for_subprocess resolves CODEX_API_KEY, which is absent here).
            token = os.environ.get("CODEX_ACCESS_TOKEN")
            if token:
                env["CODEX_ACCESS_TOKEN"] = token
        else:
            # api_key from Forge env/credential-file resolution (respects auth_ignore_env).
            key = codex_api_key_for_subprocess()
            if key:
                env["CODEX_API_KEY"] = key
    return env


def prepare_codex_request(
    *,
    prompt: str,
    preflight: CodexPreflight,
    attribution: Attribution | None,
    model: str | None = None,
    cwd: str | None = None,
    sandbox: CodexSandbox = "workspace-write",
    timeout_seconds: int = 600,
    label: str | None = None,
    resume_thread_id: str | None = None,
    resume_rollout_path: str | None = None,
    extra_args: Sequence[str] = (),
    worker: bool = False,
    proxy_launch: CodexProxyLaunch | None = None,
) -> HeadlessRequest:
    """Shape one ``codex exec --json`` job into a :class:`HeadlessRequest`.

    The caller runs :func:`assert_codex_ready` ONCE and passes the frozen ``preflight``
    in, so the ~20s ``codex doctor`` probe is not repeated per worker in a fan-out.

    ``resume_thread_id`` continues an existing Codex thread via the ``resume``
    subcommand. Options go BEFORE the subcommand (probe stage 60 form A:
    ``codex exec --json --sandbox X resume <thread_id>``); the prompt still arrives on
    stdin (probe stage 61 verified the stdin-prompt + resume combination).
    ``extra_args`` (a managed launch's ``--effort`` and ``--`` tail) join the options
    before that subcommand.
    Explicit ``worker=True`` applies native delegation/memory restrictions after
    those overrides. Managed root callers keep their normal configuration.

    The managed proxy path restores the session identity established by the caller and
    passes that launch's run IDs to Responses ingress. A direct child derives its own
    run under the caller's root.
    """
    env = sanitize_codex_child_env(preflight, proxy_launch=proxy_launch)
    argv = list(get_runtime("codex").headless_cmd)
    if proxy_launch is not None:
        # The routing commitment records this root. Use the same identity for ingress
        # and the worker's JSONL event so its exact cost joins to the event-backed row.
        run = get_run_identity()
        if run is None:
            raise ValueError("Managed Codex proxy launch requires an active Forge run.")
        env.update({key: os.environ[key] for key in _MANAGED_IDENTITY_VARS if key in os.environ})
        argv[1:1] = proxy_launch.provider_args(run, extra_args, env=env, cwd=cwd or os.getcwd())
    else:
        stamp_run_identity(env, derive=True)
    argv += ["--json", "--sandbox", sandbox]
    if model and proxy_launch is None:
        argv += ["-m", model]
    argv += extra_args

    if worker:
        CODEX_WORKER_PROFILE.apply(argv, env)
    if resume_thread_id:
        argv += ["resume", resume_thread_id]

    request = (
        partial(
            CodexContinuationRequest,
            usage_baseline=proxy_launch.usage_baseline if proxy_launch else None,
            native_resume=None if proxy_launch else capture_native_resume(resume_thread_id, resume_rollout_path),
        )
        if resume_thread_id
        else HeadlessRequest
    )
    return request(
        argv=argv,
        prompt=prompt,
        env=env,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        label=label,
        model=proxy_launch.dispatched_model if proxy_launch else model,
        provider=proxy_launch.provider if proxy_launch else "openai",
        proxy_id=proxy_launch.proxy_id if proxy_launch else None,
        output_format=None,  # Codex --json is already in argv.
        base_url=proxy_launch.base_url if proxy_launch else None,
        # Stamp the runtime + resolved billing posture onto the attribution so the emitted
        # event's billing_mode always matches the preflight that gated this spawn.
        attribution=(
            replace(attribution, runtime="codex", billing_mode=preflight.billing_mode)
            if attribution is not None
            else None
        ),
    )


def _emit_codex(request: HeadlessRequest, result: HeadlessResult) -> None:
    """Emit a per-run UsageEvent for a ``codex exec`` job that carries attribution.

    Opt-in (no attribution -> no event); no identity or a cancelled job -> nothing to
    attribute. Mirrors ``_emit_worker`` but routes through :func:`emit_codex_usage`
    (route ``codex_exec``, tokens-only, no cost).
    """
    attribution = request.attribution
    if attribution is None or not result.run_id or result.cancelled:
        return
    from forge.core.usage import emit_codex_usage

    status = _status(result)
    emit_codex_usage(
        run_id=result.run_id,
        parent_run_id=result.parent_run_id,
        root_run_id=result.root_run_id,
        command=attribution.command,
        workflow=attribution.workflow,
        session=attribution.session,
        runtime=attribution.runtime,
        model=request.model,
        provider=request.provider,
        proxy_id=request.proxy_id,
        billing_mode=attribution.billing_mode,
        status=status,
        latency_ms=round(result.duration_seconds * 1000, 1) if result.duration_seconds else None,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cached_tokens=result.cached_tokens,
    )
    _record_worker_upstream(attribution, result, status)

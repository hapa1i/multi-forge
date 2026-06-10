"""Codex headless invoker (Phase 5b).

Concrete :class:`HeadlessInvoker` for ``codex exec --json``, sharing the hardened
subprocess lifecycle in :class:`_HeadlessLifecycleBase`. Codex differs from Claude in
three ways the hooks capture:

- **argv**: the caller builds the full ``codex exec --json --sandbox ...`` argv
  (:func:`prepare_codex_request`); ``_prepare_argv`` passes it through unchanged (no
  capability-gated flag injection -- ``--json`` is native and always supported).
- **result**: the output is a JSONL *event stream*, reduced by
  :func:`parse_codex_jsonl_stream`, not a single envelope.
- **emit**: a ``runtime_native`` usage event (route ``codex_exec``) with tokens but no
  cost -- Codex runs DIRECT to OpenAI, so there is no proxy cost record to join.

Codex never enters the format-retry branch: it inherits the base
``_is_recoverable_format_rejection`` (always ``False``), so ``_on_format_rejection`` is
unreachable for it.
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Literal

from forge.core.invoker._lifecycle import (
    ParseHints,
    _HeadlessLifecycleBase,
    _Identity,
    _status,
)
from forge.core.invoker.codex_stream import parse_codex_jsonl_stream
from forge.core.invoker.types import Attribution, HeadlessRequest, HeadlessResult
from forge.core.reactive.env import (
    FORGE_DEPTH_VAR,
    FORGE_SUBPROCESS_BASE_URL_VAR,
    FORGE_SUBPROCESS_PROXY_ID_VAR,
    FORGE_SUBPROCESS_PROXY_VAR,
    FORGE_SUBPROCESS_TEMPLATE_VAR,
    get_forge_depth,
    stamp_run_identity,
)
from forge.core.runtime.codex_preflight import (
    CodexPreflight,
    codex_api_key_for_subprocess,
)
from forge.core.runtime.registry import get_runtime

CodexSandbox = Literal["read-only", "workspace-write", "danger-full-access"]

# Inherited env a direct Codex child must NOT keep: Claude/proxy routing (Codex ignores it,
# and the run is direct) and any auth that could contradict the preflight's resolved posture
# (a stale inherited CODEX_API_KEY would override a codex_store/ChatGPT login). Stripped, then
# only the preflight-resolved auth is re-established.
_CODEX_CHILD_STRIP_VARS = (
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


class CodexHeadlessInvoker(_HeadlessLifecycleBase):
    """Runs ``codex exec --json`` jobs. Implements the :class:`HeadlessInvoker` protocol."""

    def _prepare_argv(self, request: HeadlessRequest) -> tuple[list[str], ParseHints]:
        # The caller built the full argv (--json is already present). No capability gate.
        return request.argv, ParseHints(is_jsonl_stream=True)

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
        stream = parse_codex_jsonl_stream(stdout)
        # Codex reports a failed turn in the JSONL stream, usually with EMPTY stderr; surface
        # the provider reason on stderr so a caller inspecting it sees why the turn failed.
        effective_stderr = stderr
        if not effective_stderr and stream.is_error and stream.error_message:
            effective_stderr = stream.error_message
        return HeadlessResult(
            label=request.label,
            stdout=stream.final_text,
            stderr=effective_stderr,
            returncode=returncode,
            duration_seconds=duration_seconds,
            cost_micro_usd=None,  # native runtime: no $ figure (direct to OpenAI)
            input_tokens=stream.input_tokens,
            output_tokens=stream.output_tokens,
            cached_tokens=stream.cached_tokens,
            # Parsed iff the stream yielded recognizable terminal events; a failed turn
            # (is_error) still parsed. An empty/garbage stream -> False, stdout "".
            envelope_parsed=bool(stream.final_text) or stream.input_tokens is not None or stream.is_error,
            runtime_is_error=stream.is_error,
            runtime_session_id=stream.thread_id,
            **ident,
        )

    def _emit(self, request: HeadlessRequest, result: HeadlessResult) -> None:
        _emit_codex(request, result)

    def _missing_binary_error(self) -> str:
        return "codex CLI not found in PATH"


def prepare_codex_request(
    *,
    prompt: str,
    preflight: CodexPreflight,
    attribution: Attribution,
    model: str | None = None,
    cwd: str | None = None,
    sandbox: CodexSandbox = "workspace-write",
    timeout_seconds: int = 600,
    label: str | None = None,
    resume_thread_id: str | None = None,
) -> HeadlessRequest:
    """Shape one ``codex exec --json`` job into a :class:`HeadlessRequest`.

    The caller runs :func:`assert_codex_ready` ONCE and passes the frozen ``preflight``
    in, so the ~20s ``codex doctor`` probe is not repeated per worker in a fan-out.

    ``resume_thread_id`` continues an existing Codex thread via the ``resume``
    subcommand. Options go BEFORE the subcommand (probe stage 60 form A:
    ``codex exec --json --sandbox X resume <thread_id>``); the prompt still arrives on
    stdin (probe stage 61 verified the stdin-prompt + resume combination).

    Codex runs DIRECT to OpenAI: no Forge proxy, no ``ANTHROPIC_*`` env, ``base_url`` is
    ``None``. The child env is **sanitized** so it cannot contradict the preflight: all
    inherited Codex/Anthropic/proxy vars are stripped, then exactly the preflight-resolved
    auth is re-established -- ``CODEX_API_KEY`` for an api-key login the ``codex`` binary
    can't otherwise see (``env``/``credential_file``), the inherited ``CODEX_ACCESS_TOKEN``
    for an enterprise login, or **nothing** for ``codex_store`` (ChatGPT/enterprise reads
    its own store). ``cwd`` is expected to be a git worktree; callers that intentionally
    target a non-git directory must opt into Codex's own bypass themselves rather than
    Forge silently weakening the check. The run-tree triple is stamped so the run shares
    its parent's root.
    """
    argv = [*get_runtime("codex").headless_cmd, "--json", "--sandbox", sandbox]
    if model:
        argv += ["-m", model]
    if resume_thread_id:
        argv += ["resume", resume_thread_id]

    env = os.environ.copy()
    for var in _CODEX_CHILD_STRIP_VARS:
        env.pop(var, None)
    # Keep normal ambient context (including FORGE_SESSION for attribution), but advance
    # the recursion guard just like a Claude headless child: Codex can run shell commands
    # that invoke `forge`, even though it does not run Forge hooks.
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
    # auth_source == "codex_store": inject nothing -- codex reads its own ~/.codex auth.
    stamp_run_identity(env, derive=True)

    return HeadlessRequest(
        argv=argv,
        prompt=prompt,
        env=env,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        label=label,
        model=model,
        provider="openai",
        proxy_id=None,
        # Codex's --json is already in argv; the Claude format-injection path is never
        # reached (CodexHeadlessInvoker._prepare_argv passes argv through). base_url=None
        # because Codex is direct -- the cost-precedence "proxied" branch must not fire.
        output_format=None,
        base_url=None,
        # Stamp the runtime + resolved billing posture onto the attribution so the emitted
        # event's billing_mode always matches the preflight that gated this spawn.
        attribution=replace(attribution, runtime="codex", billing_mode=preflight.billing_mode),
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
        billing_mode=attribution.billing_mode,
        status=_status(result),
        latency_ms=round(result.duration_seconds * 1000, 1) if result.duration_seconds else None,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cached_tokens=result.cached_tokens,
    )

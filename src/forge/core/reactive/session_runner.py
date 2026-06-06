"""Claude subprocess management for headless (-p) mode.

Provides a unified interface for running ``claude -p`` as a subprocess
with structured result handling. Used by the semantic supervisor
(``claude -p --resume``) and the memory writer (``claude -p``).

For interactive sessions (stdin/stdout inherited), use
``forge.session.claude.invoke.invoke_claude()`` instead.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

from forge.core.reactive.env import (
    FORGE_PARENT_RUN_ID_VAR,
    FORGE_ROOT_RUN_ID_VAR,
    FORGE_RUN_ID_VAR,
    FORGE_SUBPROCESS_PROXY_VAR,
    build_claude_env,
    can_use_bare,
)
from forge.core.reactive.headless_json import (
    is_json_flag_rejection,
    mark_json_output_unsupported,
    prepare_json_argv,
    treat_is_error_as_failure,
)
from forge.core.reactive.structured_output import parse_headless_envelope

_log = logging.getLogger(__name__)


@dataclass
class SessionResult:
    """Result from a ``claude -p`` invocation.

    The runner never raises — all errors are captured in the ``error`` field.
    Callers inspect ``success`` and ``error`` to decide their own fail
    behavior (fail-open warnings for supervisor, return False for the memory writer).
    """

    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False
    error: str | None = None
    # Run-tree identity of this subprocess (minted by build_claude_env). Read by
    # the usage ledger (Phase 4c) to attribute the work to its run/session.
    run_id: str | None = None
    parent_run_id: str | None = None
    root_run_id: str | None = None
    # Runtime-self-reported cost/usage from --output-format json (Phase 5). Nullable:
    # cost is None when the route reported none. ``envelope_parsed`` and
    # ``cost_micro_usd is not None`` are INDEPENDENT (a parsed envelope may carry
    # tokens but no cost). ``runtime_is_error`` reflects the envelope's is_error
    # (already AND-gated by treat_is_error_as_failure) and steers the usage-ledger
    # status ONLY -- it deliberately does NOT change ``success`` (consumers branch
    # on returncode for fail-open control flow; see emit._session_status).
    cost_micro_usd: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    envelope_parsed: bool = False
    runtime_is_error: bool = False

    @property
    def success(self) -> bool:
        """True if the subprocess completed successfully (returncode-based; unchanged)."""
        return self.returncode == 0 and not self.timed_out and self.error is None


def run_claude_session(
    prompt: str,
    *,
    resume_id: str | None = None,
    fork_session: bool = False,
    model: str | None = None,
    bare: bool | None = None,
    base_url: str | None = None,
    direct: bool = False,
    timeout_seconds: int = 60,
    cwd: str | None = None,
    extra_env: dict[str, str] | None = None,
    unset_env_vars: list[str] | tuple[str, ...] | None = None,
    output_format: str | None = "json",
) -> SessionResult:
    """Run ``claude -p`` as a headless subprocess.

    Builds the command, environment, and runs ``subprocess.run`` with
    ``capture_output=True``. All exceptions are caught and reported
    via ``SessionResult.error``.

    Args:
        prompt: Text sent to claude via stdin.
        resume_id: If set, adds ``--resume <id>`` to continue a session.
        fork_session: If True and resume_id is set, adds ``--fork-session``
            to create an ephemeral fork instead of appending to the
            original conversation.
        model: Optional Claude model/tier passed via ``--model``.
        bare: If True, adds ``--bare`` to skip hooks/LSP/plugins.
            None (default) auto-detects: uses ``--bare`` only when
            ANTHROPIC_API_KEY is present (``--bare`` disables OAuth).
        base_url: Proxy URL (sets ANTHROPIC_BASE_URL in environment).
        timeout_seconds: Maximum seconds to wait for completion.
        cwd: Working directory for the subprocess.
        extra_env: Additional environment variables.
        unset_env_vars: Environment variables to remove from the child process
            after routing env has been built.
        output_format: When set (default ``"json"``) and the CLI supports it, adds
            ``--output-format <fmt>`` so the run self-reports cost/usage; the
            envelope is parsed and ``.result`` unwrapped back into ``stdout`` so
            text consumers are unchanged. ``None`` keeps plain text output.

    Returns:
        SessionResult with stdout/stderr/returncode or error details, plus
        runtime-self-reported cost/usage when an envelope was parsed.
    """
    env = build_claude_env(base_url=base_url, extra_vars=extra_env, direct=direct)
    for key in unset_env_vars or ():
        env.pop(key, None)

    # Read the run-tree identity build_claude_env stamped, and funnel every
    # return through _session_result so all outcomes (success AND error) carry
    # it — the usage ledger attributes failures by run_id too.
    run_id = env.get(FORGE_RUN_ID_VAR)
    parent_run_id = env.get(FORGE_PARENT_RUN_ID_VAR)
    root_run_id = env.get(FORGE_ROOT_RUN_ID_VAR)

    def _session_result(
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int = -1,
        timed_out: bool = False,
        error: str | None = None,
        cost_micro_usd: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cached_tokens: int | None = None,
        envelope_parsed: bool = False,
        runtime_is_error: bool = False,
    ) -> SessionResult:
        return SessionResult(
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            timed_out=timed_out,
            error=error,
            run_id=run_id,
            parent_run_id=parent_run_id,
            root_run_id=root_run_id,
            cost_micro_usd=cost_micro_usd,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            envelope_parsed=envelope_parsed,
            runtime_is_error=runtime_is_error,
        )

    use_bare = bare if bare is not None else can_use_bare(env)
    cmd = ["claude", "-p"]
    if use_bare:
        cmd.append("--bare")
    if resume_id:
        cmd.extend(["--resume", resume_id])
        if fork_session:
            cmd.append("--fork-session")
    if model:
        cmd.extend(["--model", model])

    # Guard: fail if subprocess proxy was configured but didn't resolve.
    # Prevents silent fallback to direct mode (which would burn subscription quota).
    subprocess_proxy = env.get(FORGE_SUBPROCESS_PROXY_VAR)
    if subprocess_proxy and not base_url and not direct and not env.get("ANTHROPIC_BASE_URL"):
        msg = (
            f"Subprocess proxy '{subprocess_proxy}' not available. "
            f"Start it with: forge proxy start {subprocess_proxy}"
        )
        _log.warning(msg)
        return _session_result(error=msg)

    # Guard: fail with actionable error if --bare was requested but no API key.
    # Without this, the subprocess would fail with a cryptic Claude CLI error.
    # Only fires when bare mode was explicitly requested (bare=True) — when
    # bare=None and no key exists, can_use_bare() returns False and Claude
    # falls through to OAuth (which may be intentional).
    if bare and not env.get("ANTHROPIC_BASE_URL") and not env.get("ANTHROPIC_API_KEY"):
        try:
            from forge.core.auth.capabilities import (
                CREDENTIALS,
                format_missing_credential_error,
            )
            from forge.runtime_config import get_runtime_config

            env_ignored = get_runtime_config().auth_ignore_env
            cred = CREDENTIALS.get("anthropic-api")
            if cred:
                msg = format_missing_credential_error(
                    cred,
                    missing_vars=["ANTHROPIC_API_KEY"],
                    context="Forge subprocess (claude -p)",
                    extra_hint="Or use --subprocess-proxy to route through an existing proxy.",
                    env_ignored=env_ignored,
                )
                _log.warning(msg)
                return _session_result(error=msg)
        except Exception as e:
            _log.debug("Could not format missing Anthropic subprocess credential error: %s", e)

    # Capability-gated JSON request (shared with the invoker via headless_json):
    # the base cmd carries no --output-format token; this is the single injection point.
    run_cmd, json_requested = prepare_json_argv(cmd, output_format)

    try:
        _log.debug(
            "Running claude session: cmd=%s, resume=%s, cwd=%s",
            run_cmd,
            resume_id and resume_id[:16],
            cwd,
        )

        result = subprocess.run(
            run_cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=cwd,
            env=env,
        )

        # Retry-once backstop: the version gate allowed the flag but this CLI still
        # rejected it. Latch unsupported (siblings skip it) and re-run without it.
        if json_requested and is_json_flag_rejection(result.returncode, result.stderr):
            mark_json_output_unsupported()
            _log.debug("claude rejected --output-format; retrying without it")
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=cwd,
                env=env,
            )
            json_requested = False

        if result.returncode != 0:
            _log.warning("claude -p returned non-zero exit code: %d", result.returncode)

        if json_requested:
            envelope = parse_headless_envelope(result.stdout)
            if envelope.parsed:
                # Unwrap .result into stdout so text consumers are unchanged; lift
                # the runtime's self-reported cost/usage onto the result.
                return _session_result(
                    stdout=envelope.result_text,
                    stderr=result.stderr,
                    returncode=result.returncode,
                    cost_micro_usd=envelope.cost_micro_usd,
                    input_tokens=envelope.input_tokens,
                    output_tokens=envelope.output_tokens,
                    cached_tokens=envelope.cached_tokens,
                    envelope_parsed=True,
                    runtime_is_error=envelope.is_error and treat_is_error_as_failure(),
                )

        # No JSON (not requested, or non-envelope output): raw stdout, today's behavior.
        return _session_result(
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )

    except subprocess.TimeoutExpired:
        _log.warning("claude -p timed out after %ds", timeout_seconds)
        return _session_result(
            timed_out=True,
            error=f"Timed out after {timeout_seconds}s",
        )

    except FileNotFoundError:
        _log.error("claude CLI not found in PATH")
        return _session_result(error="claude CLI not found in PATH")

    except Exception as e:
        _log.warning("claude -p failed: %s", e)
        return _session_result(error=str(e))

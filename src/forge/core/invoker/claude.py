"""Claude headless invoker (Phase 4d; lifecycle shared since 5b).

Concrete :class:`HeadlessInvoker` for ``claude -p``. The subprocess lifecycle
(process groups, SIGTERM->SIGKILL cleanup, ordered fan-out, timeouts, cancellation
races) lives in :class:`_HeadlessLifecycleBase`; this module supplies the Claude
specifics via the template hooks:

- argv: capability-gated ``--output-format json`` injection (``prepare_json_argv``);
- result: ``parse_headless_envelope`` -- unwrap ``.result`` and lift self-reported
  cost/usage;
- format retry: on a ``--output-format`` rejection, mark the capability unsupported
  and re-run the unflagged argv;
- emit: a per-job ``UsageEvent`` when the request carries :class:`Attribution`.
"""

from __future__ import annotations

from typing import cast

from forge.core.invoker._lifecycle import (
    ParseHints,
    _HeadlessLifecycleBase,
    _Identity,
    _status,
)
from forge.core.invoker.types import HeadlessRequest, HeadlessResult
from forge.core.reactive.headless_json import (
    is_json_flag_rejection,
    mark_json_output_unsupported,
    prepare_json_argv,
    treat_is_error_as_failure,
)
from forge.core.reactive.structured_output import parse_headless_envelope


def _result_from_outcome(
    request: HeadlessRequest,
    *,
    stdout: str,
    stderr: str,
    returncode: int,
    duration_seconds: float,
    ident: _Identity,
    json_requested: bool,
) -> HeadlessResult:
    """Build a HeadlessResult from a completed ``claude -p`` run.

    When JSON was requested and a valid envelope is found, unwrap ``.result`` into
    ``stdout`` (text consumers unchanged) and lift the runtime's self-reported
    cost/usage onto the result. Non-envelope output keeps raw ``stdout``.
    """
    envelope = parse_headless_envelope(stdout) if json_requested else None
    if envelope is not None and envelope.parsed:
        return HeadlessResult(
            label=request.label,
            stdout=envelope.result_text,
            stderr=stderr,
            returncode=returncode,
            duration_seconds=duration_seconds,
            cost_micro_usd=envelope.cost_micro_usd,
            input_tokens=envelope.input_tokens,
            output_tokens=envelope.output_tokens,
            cached_tokens=envelope.cached_tokens,
            envelope_parsed=True,
            runtime_is_error=envelope.is_error and treat_is_error_as_failure(),
            **ident,
        )
    return HeadlessResult(
        label=request.label,
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
        duration_seconds=duration_seconds,
        **ident,
    )


class ClaudeHeadlessInvoker(_HeadlessLifecycleBase):
    """Runs ``claude -p`` jobs. Implements the :class:`HeadlessInvoker` protocol."""

    def _prepare_argv(self, request: HeadlessRequest) -> tuple[list[str], ParseHints]:
        # Capability-gated JSON request, per call (so each self-heals if a rejection
        # races the shared latch). Shared with run_claude_session via headless_json.
        run_argv, json_requested = prepare_json_argv(request.argv, request.output_format)
        return run_argv, ParseHints(json_requested=json_requested)

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
        return _result_from_outcome(
            request,
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            duration_seconds=duration_seconds,
            ident=ident,
            json_requested=hints.json_requested,
        )

    def _emit(self, request: HeadlessRequest, result: HeadlessResult) -> None:
        _emit_worker(request, result)

    def _is_recoverable_format_rejection(self, returncode: int, stderr: str, hints: ParseHints) -> bool:
        return hints.json_requested and is_json_flag_rejection(returncode, stderr)

    def _on_format_rejection(self, request: HeadlessRequest) -> tuple[list[str], ParseHints]:
        mark_json_output_unsupported()
        # The request's argv is the unflagged form (the invoker added --output-format).
        return request.argv, ParseHints(json_requested=False)

    def _missing_binary_error(self) -> str:
        return "claude CLI not found in PATH"


def _emit_worker(request: HeadlessRequest, result: HeadlessResult) -> None:
    """Emit a per-worker UsageEvent when the request carries attribution.

    Opt-in (no attribution -> no event), so non-workflow callers of ``run_parallel``
    don't suddenly write to the ledger. No identity -> nothing to attribute. A
    cancelled job did no attributable work, so it is not recorded either.
    """
    attribution = request.attribution
    if attribution is None or not result.run_id or result.cancelled:
        return
    from forge.core.usage import emit_worker_usage

    status = _status(result)
    emit_worker_usage(
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
        status=status,
        latency_ms=round(result.duration_seconds * 1000, 1) if result.duration_seconds else None,
        # Phase 5 cost precedence: base_url decides whether the runtime self-report
        # counts (direct) or the verb aggregate holds it (proxied). See emit_worker_usage.
        base_url=request.base_url,
        cost_micro_usd=result.cost_micro_usd,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cached_tokens=result.cached_tokens,
        envelope_parsed=result.envelope_parsed,
    )
    from forge.core.telemetry.upstream import UpstreamStatus, record_upstream_operation

    record_upstream_operation(
        command=attribution.command,
        operation="workflow.worker",
        status=cast(UpstreamStatus, status),
        session=attribution.session,
        run_id=result.run_id,
        parent_run_id=result.parent_run_id,
        root_run_id=result.root_run_id,
        reason_code=_worker_reason_code(result),
        message=None if status == "success" else result.error or result.stderr[:200] or None,
        latency_ms=round(result.duration_seconds * 1000, 1) if result.duration_seconds else None,
    )


def _worker_reason_code(result: HeadlessResult) -> str | None:
    if result.timed_out:
        return "timeout"
    if result.error:
        return "subprocess_error"
    if result.runtime_is_error:
        return "runtime_reported_error"
    if result.returncode != 0:
        return f"exit_{result.returncode}"
    return None

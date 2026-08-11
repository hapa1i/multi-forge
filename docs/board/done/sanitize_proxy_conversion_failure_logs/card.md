# Sanitize proxy conversion-failure logs

**Epic**: [`epic_proxy_conversion_failure_handling`](../../doing/epic_proxy_conversion_failure_handling/card.md).

**Lane**: `done/` -- shipped in PR #161 (`8088ceae`).

**Finding**: D053 (Wave 6 MEDIUM).

## Goal

Keep provider response-conversion failures visible in ordinary proxy logs without rendering provider-controlled
exception text or tracebacks.

## Evidence

Rechecked on merged `main` at `de02b09b`. A non-streaming response with a provider-controlled invalid `id` produced a
Pydantic `ValidationError`; its `input_value` canary appeared in the ordinary ERROR message and traceback. A streaming
generator that raised a canary-bearing `ValueError` produced the same plaintext/traceback leak while the client-facing
SSE error remained generic.

## Expected Behavior

The [§A.11 no-plaintext posture](../../../design_appendix.md#a11-intercept-audit-and-request-logging-configuration-7x)
permits fixed context, request IDs, safe exception classes, and lifecycle flags in ordinary logs. Provider response
values and exception rendering that can embed them belong only in an explicitly sanctioned raw-content plane.

## Scope

- Replace exception rendering and formatted tracebacks in the non-streaming and streaming response-conversion catch-alls
  and the nested streaming error-delivery guard with parameterized, metadata-only ERROR records.
- Retain a safe exception class so operators can distinguish validation, type, and other conversion failures.
- Preserve the non-streaming fallback response shape and exception-derived assistant text until O007 changes that
  external contract.
- Preserve streaming error-event/message-stop bytes, lifecycle flags and summary, `on_complete` behavior, and the opt-in
  bounded `stream_chunks` plane.

## Acceptance Criteria

| Test                   | Fixture                                             | Assertion                                                                | Test File                                                             |
| ---------------------- | --------------------------------------------------- | ------------------------------------------------------------------------ | --------------------------------------------------------------------- |
| Non-streaming hygiene  | canary-bearing Pydantic response validation failure | ERROR names `ValidationError`; no canary or traceback reaches logs       | `tests/regression/test_bug_d053_provider_conversion_log_plaintext.py` |
| Non-streaming control  | the same invalid provider response                  | existing fallback response remains unchanged for this member             | same regression                                                       |
| Streaming hygiene      | generator raises canary-bearing `ValueError`        | ERROR names `ValueError`; no canary or traceback reaches logs            | same regression                                                       |
| Streaming wire control | the same failed stream                              | generic error event, message-stop, lifecycle, and callback remain intact | existing converter lifecycle/log-hygiene coverage                     |
| Delivery hygiene       | consumer throws at the static error-event yield     | ERROR names `RuntimeError`; no rendered exception reaches logs           | same regression                                                       |
| Raw opt-in control     | `stream_chunks=true` with a bounded provider chunk  | explicitly requested capped chunk diagnostics remain available           | `tests/src/proxy/test_converters_log_hygiene.py`                      |

## Compatibility and Exclusions

This member changes ordinary log text only. It does not change converter return values, HTTP/SSE behavior, accounting,
provider traces, request diagnostics, audit records, or config. O007 owns the later non-streaming failure-status change;
O041 task ownership and O045 provider-call failure traces remain separate.

## Implementation Outcome

- Replaced both response-conversion catch-all records and the nested streaming error-delivery record with parameterized
  ERROR messages containing fixed context, the request ID, and the exception class only. None renders an exception or
  captures a traceback.
- Used `exception_type` for concrete Python classes on the streaming records, leaving the lifecycle summary's existing
  `error_type=internal_error` as the distinct metrics classification. The non-streaming record keeps the established
  `error_type=<class>` convention because it has no lifecycle-key collision.
- Removed the now-unused traceback dependency while preserving the non-streaming fallback object and its
  exception-derived assistant text for O007's separate client/accounting change.
- Kept the streaming generic error and message-stop bytes, `internal_error` lifecycle classification, completion
  callback payload, and explicit bounded `stream_chunks` diagnostics unchanged. No architecture, config, ownership, or
  documented external contract changed, so the existing normative guidance remains current.

## Verification

The two admitted regressions failed on merged base `cf77c175` after their behavior-preservation controls, with the old
records capturing canaries and tracebacks. A follow-up guard also failed while the nested error-delivery record still
rendered its injected transport exception. All three pass after the log-only corrections. The focused converter,
log-hygiene, lifecycle, and adjacent O037/O038/O042 slice passes 96 tests. The full unit suite passes 8,954 tests with
one skip and 122 deselections, the full regression suite passes 719 tests, and the hermetic translated-proxy Docker
slice passes all three cases after an image rebuild. The first pre-commit pass let mdformat normalize the moved board
tables after every code and secret-scanning hook passed; clean reruns, board links, stale-lane checks, and diff checks
pass. The member shipped in PR #161 (`8088ceae`), unblocking O007 on its own execution branch.

# Sanitize proxy conversion-failure logs

**Epic**: [`epic_proxy_conversion_failure_handling`](../epic_proxy_conversion_failure_handling/card.md).

**Lane**: `todo/` -- accepted and parked; activate only after the admission record is reviewed and merged.

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
  with parameterized, metadata-only ERROR records.
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
| Raw opt-in control     | `stream_chunks=true` with a bounded provider chunk  | explicitly requested capped chunk diagnostics remain available           | `tests/src/proxy/test_converters_log_hygiene.py`                      |

## Compatibility and Exclusions

This member changes ordinary log text only. It does not change converter return values, HTTP/SSE behavior, accounting,
provider traces, request diagnostics, audit records, or config. O007 owns the later non-streaming failure-status change;
O041 task ownership and O045 provider-call failure traces remain separate.

## Verification

Retain a marked D053 regression, run focused converter/log-hygiene and lifecycle tests, the full regression suite, a
targeted translated-proxy Docker case, and `make pre-commit`.

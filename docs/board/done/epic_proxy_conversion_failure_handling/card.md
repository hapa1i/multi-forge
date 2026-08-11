# Epic: Proxy conversion failure handling

**Parent epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md).

**Lane**: `done/` -- D053 shipped in PR #161 (`8088ceae`) and O007 shipped in PR #162 (`31a0832f`); both retained
regression boundaries are verified.

## Goal

Keep provider response-conversion failures observable and confidential: ordinary logs carry safe failure metadata, and
non-streaming failures reach clients and telemetry as failures rather than successful assistant turns.

## Design Authority

- [`docs/developer/coding_standards.md` §5](../../../developer/coding_standards.md#system-boundaries-external-data)
  requires critical external-data failures to fail with a clear error and best-effort paths to degrade visibly and
  safely.
- [`docs/design.md` §7.x](../../../design.md#7x-optional-always-on-proxy-audit-and-control) and
  [`docs/design_appendix.md` §A.11](../../../design_appendix.md#a11-intercept-audit-and-request-logging-configuration-7x)
  reserve ordinary proxy logs for metadata and keep provider/caller plaintext in explicit bounded planes.
- [`docs/end-user/proxy.md`](../../../end-user/proxy.md#proxy-metrics) defines failed-request and failure-type
  accounting as operator-visible proxy truth.
- [`review_combined.md`](../../review_combined.md) supplies O007 and D053.

## Reproduction Record

O007 and D053 were rechecked on merged `main` at `de02b09b`. One disposable pytest module passed four broken-behavior
characterizations and was removed after evidence capture.

| Finding | Fixture                                                   | Observed result                                                                    |
| ------- | --------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| O007    | provider response whose `id` fails Pydantic validation    | converter returned an `end_turn` assistant error containing provider data          |
| O007    | the same response through the translated non-stream route | route returned HTTP 200; cost/metrics recorded `failed=false` and no error type    |
| D053    | non-streaming validation failure with a provider canary   | ordinary ERROR output rendered the canary and a full traceback                     |
| D053    | streaming generator raising a canary-bearing `ValueError` | client got the generic error event, but ordinary ERROR rendered canary + traceback |

The streaming client event is already generic and is a preservation control for D053. O007 is limited to the
non-streaming translated path; streaming conversion has its own in-band error-event contract.

## Members and Sequence

| Order | Finding | Member                                                                                                | Review boundary                                  |
| ----- | ------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| 1     | D053    | [`sanitize_proxy_conversion_failure_logs`](../../done/sanitize_proxy_conversion_failure_logs/card.md) | ordinary non-streaming/streaming ERROR metadata  |
| 2     | O007    | [`fail_non_streaming_response_conversion`](../fail_non_streaming_response_conversion/card.md)         | client status and cost/metrics failure semantics |

D053 shipped first as a log-only correction at both converter catch-alls and established a safe diagnostic boundary
before O007 changed the non-streaming exception flow. O007 remained a separate member because replacing a successful
assistant response with an HTTP failure changes the external wire and accounting contract.

## Shared Constraints

- Never render provider exception messages, validation `input_value` snippets, or tracebacks in ordinary logs. Safe
  exception classes and fixed failure metadata remain available for triage.
- D053 changes diagnostics only: preserve non-streaming fallback output until O007 ships, streaming error-event bytes,
  lifecycle flags, completion callbacks, and the explicit bounded `stream_chunks` plane.
- O007 returns a stable provider-data-free server error for non-streaming conversion failures and records the request as
  failed without discarding provider-reported usage/cost evidence.
- Apply O007 consistently to the initial request and the authentication-retry success path. Preserve successful
  conversion, `ToolCallError`, passthrough, and streaming behavior.
- Provider-call failure trace coverage (O045) and converter task lifetime (O041) remain separate findings.
- Each member retains a marked fail-first regression and runs focused converter/server tests, targeted translated-proxy
  Docker integration, the full regression suite, and pre-commit before closeout.

## Closeout

Both members shipped independently, the review ledger records their dispositions, and retained regressions cover safe
conversion-failure logs plus truthful non-streaming client/accounting outcomes. Other MEDIUM rows remain with the parent
maintenance epic.

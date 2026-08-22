# Trace failed provider attempts

**Epic**: [`epic_wave8_residual_maintenance`](../epic_wave8_residual_maintenance/card.md).

**Lane**: `done/` -- shipped in PR #216 (`634ff40e`).

**Finding**: O045 (MEDIUM).

## Goal

Emit provider-trace lifecycle evidence for an upstream call that fails before a usable response while preserving the
rule that pre-dispatch validation/conversion failures are not fabricated as provider attempts.

## Verified Evidence

The main Messages handler's broad provider-call failure arm records failed downstream cost and metrics but no provider
trace. Responses passthrough does the same for non-streaming transport failure, streaming open failure, and a non-200
stream response. Successful, terminal-response, and established-stream paths already record a trace using the same
downstream event identity.

Current seams: `src/forge/proxy/server.py` around the generic completion exception and
`src/forge/proxy/responses_passthrough.py` around request/open/non-200 handling. Authority:
[`design_telemetry.md` provider trace](../../../design_telemetry.md) and the existing `ProviderTraceRecord` lifecycle.

## Acceptance Criteria

- Record exactly one trace for each billable provider attempt that fails before a normal response lifecycle completes.
- Reuse the request's `downstream_event_id` so trace and cost evidence merge into one attempt.
- Represent pre-stream/open failures honestly (`stream_started=false`, no chunk/usage evidence); retain observed status,
  header-cost, and stream facts when available.
- Keep invalid request, local conversion, routing, and other pre-dispatch failures trace-free.
- Preserve capability gating, sanitized client errors, cost/metrics failure accounting, response status/body, and
  best-effort trace writes.

## Verification

Add regressions for Messages provider failure plus Responses non-stream, stream-open, and non-200 failures, with a
negative pre-dispatch control. Run focused proxy/trace tests, full unit and regression suites, targeted Docker proxy and
telemetry integration, and `make pre-commit`.

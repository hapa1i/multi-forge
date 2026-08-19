# Trace failed provider attempts checklist

Current focus: O045 implementation and verification are complete; publish it without broadening pre-dispatch telemetry.

## Phase 1 -- Characterize and activate

- [x] Activate only order 1 from pushed closeout `7a2ad4c1` on `agent/trace-failed-provider-attempts`.
- [x] Recheck the translated Messages generic failure path: failed cost and metrics share `downstream_event_id`, but no
  provider lifecycle record is written.
- [x] Recheck Responses generation transport failure, streaming-open failure, and non-200 streaming response: each
  records failed accounting while omitting the provider trace.
- [x] Confirm Responses context exists only for billable generation requests and translated Messages conversion errors
  remain pre-dispatch HTTP 400 failures.
- [x] Add a marked regression: the four trace assertions failed and the conversion-error negative control passed on the
  execution base; a context-construction negative control added during boundary review also passes after correction.

## Phase 2 -- Implement

- [x] Record the translated Messages failure only after a provider call starts and before a usable response returns;
  preserve the existing auth-retry success record and avoid duplicate post-response traces.
- [x] Record Responses non-stream transport and streaming-open failures with no observed stream/chunk/usage facts.
- [x] Record the Responses non-200 streaming response once, marking the received response as stream-started while
  preserving its status/body and any reported header cost.
- [x] Reuse the request's exact `downstream_event_id`, provider capability gate, correlation fields, and best-effort
  write.
- [x] Keep invalid requests, local conversion, routing, client construction, and non-generation relay failures
  trace-free.
- [x] Synchronize the normative provider-trace lifecycle wording without changing public schemas or CLI JSON.

## Phase 3 -- Verify and publish

| Boundary                       | Fixture                                        | Assertion                                            | Tier       |
| ------------------------------ | ---------------------------------------------- | ---------------------------------------------------- | ---------- |
| Messages call failure          | translated non-stream request; client raises   | one unavailable non-stream trace joins failed cost   | regression |
| Responses request failure      | generation request; HTTP request raises        | one trace with no stream, chunks, usage, or cost     | regression |
| Responses open failure         | streaming generation; context entry raises     | one streaming trace with `stream_started=false`      | regression |
| Responses context construction | stream context creation raises before entry    | response behavior unchanged and zero traces          | regression |
| Responses non-200              | opened stream with status/body and cost header | status/body unchanged; trace starts and retains cost | regression |
| Pre-dispatch control           | translated request conversion rejects          | HTTP 400 and zero provider traces                    | regression |

- [x] Run focused Responses transport/provider-trace and O045/auth-retry coverage (108 passed), plus CLI trace read
  coverage (10 passed).
- [x] Run `make test-unit` (9,309 passed, 1 skipped), `make test-regression` (936 passed), and targeted Docker
  proxy/telemetry integration (6 passed).
- [x] Run `make pre-commit`; verify `design.md` at 29,990 Opus-5 tokens, `design_appendix.md` at 29,979, `change_log.md`
  at 24,162, all 965 board links, and staged diff hygiene.
- [x] Commit, push, and open an independent draft PR.
- [ ] After merge, close order 1 before activating order 2.

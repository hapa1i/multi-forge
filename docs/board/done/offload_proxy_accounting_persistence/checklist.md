# Offload proxy accounting persistence checklist

Current focus: implementation and behavior proof are complete; finish the publish gates without activating order 3.

## Phase 1 -- Characterize and activate

- [x] Close order 1 on pushed `main` (`e3def8c3`) before activating this member.
- [x] Create `agent/offload-proxy-accounting-persistence` from that exact closeout and move only order 2 to `doing/`.
- [x] Recheck the live completion path: `_calc_and_log_cost` synchronously appends downstream JSONL, and
  `CostTracker.record` can synchronously atomic-write and `fsync` cap state.
- [x] Confirm in-memory cap decisions are event-loop-owned while durable cap persistence can consume an immutable
  snapshot in completion order.
- [x] Add fail-first deterministic coverage: all three event-loop heartbeat assertions failed on `e3def8c3`; ordered
  cost/trace records, immutable cap snapshots, shutdown drain, failure warnings, and restart reconstruction now pass.

## Phase 2 -- Implement

- [x] Add one proxy-owned serial persistence boundary that submits blocking cost, trace, and cap writes to one worker
  thread.
- [x] Keep cost provenance, response headers, metrics, and in-memory cap totals available before durable writes finish.
- [x] Snapshot cap state before submission so the worker never reads or mutates the event-loop-owned tracker.
- [x] Drain queued accounting during FastAPI lifespan shutdown; warn without failing requests or shutdown when a write
  fails.
- [x] Keep a queued cap snapshot dirty until its completion succeeds; retry a failed drained snapshot directly and
  off-loop during shutdown.
- [x] Preserve canonical detached builders outside the running proxy and all downstream/cap schemas and restart reads;
  remove the now-test-only `log_request_cost` production wrapper.
- [x] Record the explicit boundary around opt-in passthrough response-body audit and unbounded, non-dropping queueing;
  do not invent an implicit drop/backpressure policy.
- [x] Synchronize accounting ownership in `docs/design.md` and the former consolidated design appendix without
  broadening public schemas.

## Phase 3 -- Verify and publish

| Boundary               | Fixture                                       | Assertion                                               | Tier       |
| ---------------------- | --------------------------------------------- | ------------------------------------------------------- | ---------- |
| downstream append      | first append blocks in worker                 | heartbeat and later completion remain responsive        | unit       |
| completion ordering    | two queued request records                    | durable worker observes submission order                | unit       |
| cap checkpoint         | atomic write blocks after snapshot            | totals update immediately; persisted object cannot race | unit       |
| controlled shutdown    | queued append remains blocked during teardown | lifespan waits, then drains after release               | unit       |
| persistence failure    | append or cap writer raises                   | warn; cap state remains dirty and retries               | regression |
| restart reconstruction | offloaded records and cap state on disk       | fresh tracker reconstructs the same spend               | regression |

- [x] Run focused proxy/accounting and adjacent trace regressions (828 passed), then the review-remediation selection
  (203 passed).
- [x] Run `make test-unit` (9,312 passed, 1 skipped), `make test-regression` (942 passed), targeted Docker
  proxy/telemetry/cap integration (7 passed, 1 workflow test deliberately deselected), and `make pre-commit`.
- [x] Verify documentation size (`design.md` 29,986; appendix 29,976 Opus-5 tokens), all 967 local board links, branch
  diff hygiene, and an independent source/diff review boundary.
- [x] Commit, push, and open independent draft PR #217.
- [x] After PR #217 merged as `6b2e0129`, close order 2 before activating order 3.

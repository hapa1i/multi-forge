# Share instance-safe proxy transport test fakes checklist

Current focus: order 9 is active from `549fb0e3`; orders 10--35 remain parked.

## Activation and evidence

- [x] Create `refactor/share-proxy-transport-test-fakes` from the pushed order-8 closeout.
- [x] Move only order 9 to `doing/` and repoint its board links.
- [x] Recheck both fake families and correct the stale leakage claim: mutable class state and duplication remain, while
  pytest already restores monkeypatched factories after failures.
- [x] Characterize the distinct Anthropic and Responses defaults, request methods, headers, read failures, stream
  failures, and context-manager teardown assertions.

## Implementation

- [x] Add one reusable instance-owned response, stream, request-capture, and async-client test scaffold.
- [x] Expose the scaffold through a shared proxy fixture and keep transport-specific defaults in their owning suites.
- [x] Migrate both suites without changing production code, wire shapes, usage merging, or provider-trace behavior.
- [x] Add direct isolation coverage proving two configured fake transports cannot share response, stream, request, or
  teardown state.

## Verification and closeout

- [x] Run both complete proxy transport files in both orders (126 passed), the shared-fake contract tests (two passed),
  and the passthrough/failure-lifecycle regression slices (14 passed).
- [x] Run full unit (9,117 passed, one expected skip), regression (906 passed), pre-commit, Markdown, 340-file/870-link
  board-integrity, lane-graph, and diff checks.
- [x] Record the verified outcome without activating order 10.
- [x] Open a draft PR without activating order 10.
- [ ] After merge, add the change-log entry, move this card to `done/`, and leave order 10 parked pending explicit
  selection.

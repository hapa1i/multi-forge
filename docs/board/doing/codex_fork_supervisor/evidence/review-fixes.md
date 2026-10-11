# B5 review fixes

PR #265 review identified executor admission, lease contention, policy recovery and CLI defects after the original
installed product controls. The user approved retaining one independently obtained reviewer login and queueing reviews
within their existing deadlines on 2026-10-12. True concurrent subscription inference remains outside this contract.

## Corrected behavior

- Executor ancestry reads bounded headers, allowing body appends and histories beyond the copied-source limit. Separate
  TUI executors use the same hook/journal turn provenance as other executors. The source copied into the reviewer keeps
  its measured origin, format, byte/token and one-generation limits; a TUI planning source remains unsupported.
- Subscription attempts wait for the shared store until their review deadline. Readiness does not acquire the lease,
  status distinguishes busy from unready, and login/logout report contention without starting another native process.
  Watchdog/anchor descriptor ownership and independent-login refresh ownership are unchanged.
- Policy set/reset performs structural validation without runtime I/O under the session lock. Active on/reload checks
  readiness before locking and refuses a concurrent configuration change. Disabled policy skips launch readiness.
- Configured home aliases are resolved before safe descriptor traversal. Symlinked native files and owned reviewer
  subdirectories remain refused. CLI lifecycle errors are diagnostics, direct-command help is one JSON reply, and both
  in-session status views identify the native source.

## Validation boundary

Regression coverage exercises each reported failure. Integration coverage uses the production invoker/watchdog with an
explicit local stub, including two sessions sharing a login and a large TUI executor at Stop. No native inference or
additional API calls are authorized or performed for these fixes. Earlier [product captures](product.md) apply to
`1b0f01cf`; they do not establish native compatibility of these later paths.

`make test-unit` passed 10,770 tests (117 integration cases deselected). The targeted integration runner passed 16
tests, with the same 11 legacy native cases explicitly deselected to preserve the closed budget. Deterministic policy
CLI file and diff inputs both passed against the changed source selector.

`make build` produced a wheel installed into a clean Python 3.13 environment with independently resolved dependencies.
The [offline wheel report](review-fixes-wheel.json) records matching hashes for all 386 installed Forge Python files,
home aliases, a large TUI executor with a separate source, busy readiness, lease expiry, copied inputs, terminal help
and status, and direct-command JSON help. Its synthetic credential file was removed; it ran zero native/API starts.

The first aggregate regression run passed 1,583 tests and failed four fixture cases. Two older admission tests omitted
`policy.enabled=true`, and two new missing-source cases passed a Path instead of a manifest string. Those fixtures were
corrected, and all 17 tests in the affected files passed on rerun. The final complete `make test-regression` run passed
all 1,587 tests. PR #265 carries CI results for its exact head; merge and shipped-tree verification remain outstanding.

# Deprecate the supervisor verdict compatibility wrapper checklist

Current focus: order 19 implementation on `refactor/deprecate-supervisor-verdict-wrapper`; orders 20--35 remain parked.

## Activation and evidence

- [x] Close order 18 on pushed `main` at `2745e5ed` after PR #197 merged as `86a83a1d` with all five checks passing.
- [x] Branch from that exact closeout and move only order 19 to `doing/`.
- [x] Recheck every production, test, export, resource, extension, documentation, and string patch-target reference to
  `parse_supervisor_verdict`.
- [x] Correct the card's return contract: the compatibility wrapper returns `SupervisorVerdict`, not the
  `(SupervisorVerdict, parsed)` tuple owned by `parse_supervisor_verdict_with_status`.
- [x] Confirm the warning class, call-site attribution, retained export, and later-release removal gate against DG4 and
  the coding standards.

## Implementation

- [x] Keep `parse_supervisor_verdict` importable with identical verdict/fallback semantics for this release window.
- [x] Emit one actionable `FutureWarning` naming `parse_supervisor_verdict_with_status`, attributed to the caller.
- [x] Keep `parse_supervisor_verdict_with_status` warning-free for production callers.
- [x] Move internal behavior and regression tests to the status-bearing parser, retaining one focused wrapper contract.
- [x] Document the active deprecation in the wrapper's developer-facing docstring and the board change log.

## Acceptance controls

| Surface              | Fixture                         | Assertion                                                                  |
| -------------------- | ------------------------------- | -------------------------------------------------------------------------- |
| Compatibility import | package and defining module     | Legacy wrapper remains importable                                          |
| Return behavior      | valid and malformed responses   | Wrapper returns the same `SupervisorVerdict` as the status-bearing parser  |
| Warning              | one legacy-wrapper invocation   | One visible `FutureWarning` names the replacement and points at the caller |
| Replacement          | warning-as-error filter         | Status-bearing production API stays silent                                 |
| Internal consumers   | repository-wide executable scan | Only the focused compatibility test calls the deprecated wrapper directly  |
| Supervisor behavior  | parser and supervisor tests     | Parse status, fail-open verdicts, cache identity, and decisions are intact |

## Verification and closeout

- [x] Run focused verdict, semantic-supervisor, and named regression tests (198 passed); run all semantic-policy tests
  (272 passed).
- [x] Run a fresh-process consumer-module smoke that shows the `FutureWarning` at the external call site.
- [x] Run `make test-unit` (9,207 passed, one skipped, 122 deselected), `make test-regression` (913 passed), and
  `make pre-commit`.
- [x] Run diff, design-size, board-link, and Wave 7 lane-count checks without a Forge workflow.
- [ ] Open a PR for order 19 and close it after merge before selecting order 20.

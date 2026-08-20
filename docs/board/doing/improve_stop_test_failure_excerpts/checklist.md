# Improve Stop test-suite failure excerpts checklist

Current focus: active in Wave 8 Batch 1 on `agent/wave8-batch-1`; characterize mixed pytest output before changing
diagnostic selection.

## Phase 1 -- Pin the diagnostic failure

- [x] Recheck current `main`: failure reporting selects `stderr or stdout`, then bounds the start of that stream, so
  warning-only stderr can hide a useful stdout failure summary.
- [ ] Add a mixed-stream regression with a long pytest header, a late failing-test identifier on stdout, and unrelated
  stderr noise.
- [ ] Pin redaction-before-selection, a 200-character maximum, and byte-identical displayed/persisted error content.

## Phase 2 -- Implement

- [ ] Select the most useful bounded failed-test context across both streams without exposing secrets or unbounded text.
- [ ] Preserve the fixed `uv run pytest` argv, no-shell execution, incomplete classification, retry limits, timeout
  behavior, and fail-open infrastructure posture.

## Phase 3 -- Verify and publish

- [ ] Run focused Stop-verification unit/regression tests and `make pre-commit`.
- [ ] Record exact verification evidence and commit this card without mixing another Batch 1 implementation.

## Acceptance tests

| Boundary          | Fixture                                                    | Assertion                                                                    | Tier            |
| ----------------- | ---------------------------------------------------------- | ---------------------------------------------------------------------------- | --------------- |
| Mixed streams     | long stdout ending in failing node ID; warning-only stderr | diagnostic retains the failing node ID and de-prioritizes noise              | regression      |
| Secret boundary   | secret spans the would-be excerpt boundary                 | redaction occurs first; neither persisted nor displayed text leaks it        | regression      |
| Shared diagnostic | one failed fixed-suite run                                 | displayed and persisted excerpt content match and are at most 200 characters | unit/regression |
| Runtime contract  | pass, timeout, launch error, and max-iteration controls    | existing allow/block/fail-open behavior and fixed argv remain unchanged      | unit            |

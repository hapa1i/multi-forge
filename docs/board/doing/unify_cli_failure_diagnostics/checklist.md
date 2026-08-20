# Unify CLI failure diagnostics checklist

Current focus: prove each admitted non-zero human diagnostic is split across stdout/stderr before changing its output
owner.

## Phase 1 -- Characterize and activate

- [x] Activate only Wave 8 order 5 from pushed closeout `2da22c2a` on `agent/unify-cli-failure-diagnostics`; keep orders
  6--19 parked.
- [x] Recheck the cited workflow, extension, and policy paths and exclude successful output, continuing warnings,
  prompts, and JSON payloads.
- [x] Add fail-first stream assertions: the three representative output guards failed on `2da22c2a`, and a follow-up
  auto-detected sync-conflict probe retained one stdout line.

## Phase 2 -- Implement

- [x] Route every admitted diagnostic header, detail, and recovery line to stderr without changing its text or exit
  code.
- [x] Preserve successful output, continuing warnings, prompts, and public JSON shapes; a successful auto-detected sync
  control keeps its existing stdout contract.
- [x] Confirm the existing CLI style guide already owns the normative stream rule and synchronize retained board
  evidence without adding duplicate end-user semantics.

## Phase 3 -- Verify and publish

| Boundary           | Fixture                                      | Assertion                                          | Tier        |
| ------------------ | -------------------------------------------- | -------------------------------------------------- | ----------- |
| Workflow preflight | missing worker prerequisite                  | stdout empty; full human diagnostic on stderr      | unit/Docker |
| Extension failure  | version/compatibility or lifecycle rejection | stdout empty; details and recovery remain together | unit/Docker |
| Policy failure     | invalid supervisor input                     | stdout empty; error and tip remain together        | unit        |
| Excluded behavior  | success, warning, prompt, and JSON paths     | existing stream and payload contracts remain       | unit        |

- [x] Run focused CLI/output tests and the touched workflow, extension, and policy suites (239 passed).
- [x] Run `make test-unit` (9,322 passed, one skip), `make test-regression` (959 passed), six targeted Docker
  workflow-worker/extension checks, and the clean-wheel runtime smoke.
- [x] Run final staged `make pre-commit`; verify design/appendix size (59,979 Opus-5 tokens), all 972 board links,
  stale-lane references, and diff hygiene.
- [x] Commit, push, and open independent draft PR #220; close order 5 after merge before activating order 6.

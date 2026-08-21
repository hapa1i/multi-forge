# Explain or remove type suppressions checklist

Current focus: closed in Wave 8 Batch 5 PR #230 (`7e5ea8c4`).

## Phase 1 -- Reverification and guard

- [x] Recheck every production `# type: ignore` on the Batch 5 base and confirm 13 lack a reason comment.
- [x] Add a fail-first source guard that reports each production suppression without a non-empty same-line reason.

## Phase 2 -- Suppression cleanup

- [x] Replace suppressions with explicit narrowing, `cast`, or corrected annotations where the runtime invariant is
  already expressible to the checker.
- [x] Pair every unavoidable production suppression with its concrete runtime invariant without changing behavior.

## Phase 3 -- Verification

- [x] Run the source guard and focused tests for every production module changed by narrowing or annotation cleanup.
- [x] Run the configured mypy and pyright checks directly because this checkout exposes no `make type-check` target.
- [x] Contribute to the integrated unit, regression, pre-commit, board/link, and diff gates.
- [x] Record the final suppression disposition and focused verification evidence without closing the card before merge.

## Acceptance evidence

| Boundary             | Fixture                                 | Assertion                                                   |
| -------------------- | --------------------------------------- | ----------------------------------------------------------- |
| Source guard         | every Python file under `src/forge`     | each `type: ignore` has a non-empty same-line reason        |
| Checker-safe cleanup | each of the 13 unexplained suppressions | suppression is removed or its runtime invariant is stated   |
| Runtime preservation | focused tests for touched modules       | narrowing and annotations do not change observable behavior |

Fail-first evidence: the new conformance guard failed with exactly 13 production paths on `e6064920` before source
cleanup. The implementation removed all 13 unexplained suppressions through typed casts, explicit value narrowing,
direct model construction, complete helper signatures, and concrete return/parameter annotations. It also removed the
adjacent already-explained installer source-path suppression; the 11 remaining production suppressions all retain their
specific same-line reasons.

Focused evidence: both conformance guards passed; mypy reported no issues across 349 source files; pyright reported zero
errors or warnings; and 446 focused proxy, policy, status-line, installer, session-repair, usage-summary, and
conformance tests passed. `make type-check` itself is unavailable because the repository Makefile defines no such
target.

Integrated evidence: the combined head passed 9,332 unit tests with 124 deselected, 1,059 regression tests, and three
targeted integration boundaries covering cross-runtime install/disable/sync, containerized session repair, and
subprocess OpenAI routing with reasoning/verbosity forwarding. `make pre-commit` passed every hook.

PR review evidence: `TierOverride` does not itself narrow the two string fields, but the immediately constructed
`ModelHyperparameters` validates both core literals. A direct invalid-value probe confirmed rejection for reasoning and
verbosity, 60 focused type/hyperparameter tests passed, and the casts now name that boundary without changing behavior.

## Phase 4 -- Closeout

- [x] Confirm PR #230 merged as `7e5ea8c4` with all five GitHub checks passing.
- [x] Move the card to `done/` with its epic and review-ledger links synchronized.

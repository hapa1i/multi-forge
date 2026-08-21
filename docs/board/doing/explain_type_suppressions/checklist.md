# Explain or remove type suppressions checklist

Current focus: active as Wave 8 Batch 5 order 18 on `agent/wave8-batch-5`, based on pushed `main` at `1e0e664c`. This
card owns production suppression cleanup and the conformance guard; the Batch 5 integrator owns shared board evidence.

## Phase 1 -- Reverification and guard

- [x] Recheck every production `# type: ignore` on the Batch 5 base and confirm 13 lack a reason comment.
- [ ] Add a fail-first source guard that reports each production suppression without a non-empty same-line reason.

## Phase 2 -- Suppression cleanup

- [ ] Replace suppressions with explicit narrowing, `cast`, or corrected annotations where the runtime invariant is
  already expressible to the checker.
- [ ] Pair every unavoidable production suppression with its concrete runtime invariant without changing behavior.

## Phase 3 -- Verification

- [ ] Run the source guard and focused tests for every production module changed by narrowing or annotation cleanup.
- [ ] Run `make type-check`, then contribute to the integrated unit, regression, pre-commit, board/link, and diff gates.
- [ ] Record the final suppression disposition and verification evidence without closing the card before merge.

## Acceptance evidence

| Boundary             | Fixture                                 | Assertion                                                   |
| -------------------- | --------------------------------------- | ----------------------------------------------------------- |
| Source guard         | every Python file under `src/forge`     | each `type: ignore` has a non-empty same-line reason        |
| Checker-safe cleanup | each of the 13 unexplained suppressions | suppression is removed or its runtime invariant is stated   |
| Runtime preservation | focused tests for touched modules       | narrowing and annotations do not change observable behavior |

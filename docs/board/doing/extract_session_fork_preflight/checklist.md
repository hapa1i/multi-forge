# Extract session-fork preflight checklist

Current focus: implementation and verification complete; publish the independent order-31 PR without activating order
32\.

- [x] Create `refactor/extract-session-fork-preflight` from pushed `main` at `54188e61`.
- [x] Reverify O068 against the callback, manager, routing, supervisor, worktree, and target-occupancy seams.
- [x] Confirm order 32 remains the owner of child creation, relocation, rollback, artifact generation, and launch.
- [x] Add fail-first characterization that snapshots the index, manifests, worktrees, branches, transfer artifacts, and
  runtime-start seams across rejected preconditions.
- [x] Introduce typed command-core request/plan/failure values with no Click, rendering, exit, durable-write, or
  runtime-start dependency.
- [x] Resolve parent/launchability, target/occupancy, strategy/depth/budget, relocation, routing/model, and supervisor
  inputs before calling the existing mutation phase.
- [x] Keep notices, tips, cross-project hints, exact stderr, and exit behavior in the Click adapter.
- [x] Update command-core ownership documentation without absorbing order 32's execution seam.
- [x] Run focused fork/session/routing units and regressions.
- [x] Run targeted Docker fork lifecycle and project-identity integration.
- [x] Run `make test-unit`, `make test-regression`, `make pre-commit`, design token checks, and board integrity.
- [x] Record verification and closeout evidence before PR publication.

## Acceptance coverage

| Boundary                     | Proof                                                                                                                                                 |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Input and supervisor options | Invalid direct/proxy, supervisor, checker, model, target-mode, drop-last, rewind, and relocation combinations preserve the durable/Git snapshot.      |
| Parent state                 | Codex, incognito, missing-worktree, missing UUID/transcript, malformed artifact, and stale-index paths fail before child reservation or index repair. |
| Routing and budget           | Prospective template/model incompatibility and over-budget full transfer fail before proxy startup or child creation.                                 |
| Target state                 | Existing session and worktree/branch conflicts are read-only planned and revalidated by the existing manager mutation layer.                          |
| Adapter boundary             | Click alone renders notices/errors and a rejected request calls neither target-proxy nor supervisor-proxy startup.                                    |

## Verification record

- Baseline: 88 focused fork/rewind/target tests passed before implementation.
- Final: 304 focused tests; 9,291 unit tests passed, one skipped, and 122 deselected; all 923 regressions passed.
- Docker: seven targeted fork lifecycle/project-identity tests passed, with 29 deselected.
- Quality: full pre-commit and diff checks pass. Initial staged passes formatted the two new Python files and exposed
  test-helper and parent-conversation type narrowing gaps; both were corrected before the clean rerun.
- Documentation: Claude Opus 5 counts are 29,979 for `design.md` and 29,966 for `design_appendix.md`; all 894 local
  links across 367 board documents resolve; Wave 7 remains 30 done, one doing, and four todo.
- No Forge workflow command was used.

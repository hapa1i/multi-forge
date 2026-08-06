# Repair sidecar shadow-drain routing checklist

Current focus: complete -- D039 shipped in PR #132 (`dc963a7c`) and Wave 2 is closed.

## Activation and reproduction

- [x] Start `fix/repair-sidecar-shadow-drain-routing` from merged `main` at `3e090ef5`.
- [x] Record transcript-artifact merge PR #131 and clear the sidecar activation gate in both coordinating epics.
- [x] Move this member from `todo/` to `doing/` and repoint inbound board links.
- [x] Retain a marked D039 regression that fails because sidecar candidate discovery probes the host-only Forge root.
- [x] Verify the container-visible probe root and host-resolvable marker roots at the real Stop enqueue seam.

## Implementation

- [x] Separate candidate discovery from deferred marker payload path translation without changing either schema.
- [x] Preserve ordinary host-mode routing, rate-zero/no-candidate inertness, marker idempotence, and fail-open
  diagnostics.
- [x] Synchronize `docs/design.md` and `docs/design_workflows.md` with the implemented root ownership.

## Acceptance tests

| Test                  | Fixture                                                         | Assertion                                                                       | Test file                                                        |
| --------------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| D039 sidecar routing  | mounted candidate plus distinct container and host roots        | exactly one marker carries host-resolvable worktree and Forge-root paths        | `tests/regression/test_bug_d039_sidecar_shadow_drain_routing.py` |
| Host routing          | ordinary host mode with one pending candidate                   | existing project/Forge roots are probed and enqueued unchanged                  | focused hook/shadow unit tests                                   |
| Inert routing         | rate zero or no pending candidate                               | no shadow marker is enqueued                                                    | focused hook/shadow unit tests                                   |
| Sidecar hook boundary | real sidecar Stop hook followed by host-visible marker handling | mounted candidate is detected and the host can resolve the deferred marker data | `tests/integration/sidecar/test_sidecar_hook_inject.py`          |

## Verification and closeout

- [x] Run the focused hook, shadow, workqueue, and D039 regression suites (120 passed).
- [x] Run `./scripts/test-integration.sh tests/integration/sidecar/test_sidecar_hook_inject.py` (4 passed).
- [x] Run `make test-regression` (659 passed) and `make test-unit` (8,734 passed, 1 pre-existing platform skip, 118
  deselected).
- [x] Run final `make pre-commit` after recording closeout evidence.
- [x] Record the implementation outcome in the review ledger, card, and change log.
- [x] After review and merge, move the member and Wave 2 epic to `done/` and fix inbound links.
- [x] Review and merge this member before sequencing Wave 3 (PR #132, `dc963a7c`).

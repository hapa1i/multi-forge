# Epic coordination checklist: Session Authority and Provenance

Coordination only -- shared-contract drift control, member sequencing, link maintenance, and aggregate closeout. It does
not replace either member's execution checklist. The normative contract is [card.md](card.md).

## Current focus

The epic closed on 2026-08-23 after both members shipped independently. M1
[Artifact Authority Mode](../artifact_authority_mode/card.md) shipped via PR #234 (merge `a1c54a05`); its
[execution checklist](../artifact_authority_mode/checklist.md) retains the member evidence. M2
[Session Route Provenance and Marking](../session_route_provenance/card.md) shipped via PR #240 (merge `2a53397c`); its
[execution checklist](../session_route_provenance/checklist.md) retains the ratified contract, fixture-grounded matrix,
review corrections, and final evidence. No epic batch was used.

## Activation bookkeeping

- [x] C1-C5 accepted as the shared contract before member execution; the epic card records the active lane and member.
- [x] Per-card branch `feat/artifact-authority-mode` created from `main` at `80d23f39`; no unrelated feature branch was
  reused.
- [x] At initial epic activation, epic and M1 moved `proposed/ -> doing/` with `git mv`; M2 remained in `proposed/`.
- [x] Epic forward links, M1/M2 back links, and the adjacent model-first proposal link were repointed for the lane move.
- [x] M1 received its own fixture-grounded execution checklist; implementation and commits remained paused through
  checklist review.
- [x] User ratified M1 decisions D1-D5 on 2026-08-21; the checklist records the adopt exclusion, empirical Codex probe
  cost, spawn-boundary reason codes, and artifact containing-tree matrix.
- [x] No implementation or commit began during ratification; execution remains at the user-requested review boundary.
- [x] After M1 closeout, M2 was accepted for detailed planning on its own branch, moved to `doing/`, and received a
  decision-grounded checklist; the user ratified the reviewed checklist before source implementation.

Activation and ratification verification (2026-08-21): all affected local Markdown links resolve, `git diff --check`
passes, and `make pre-commit-md` passes.

M2 planning activation verification (2026-08-22): all affected local Markdown links resolve, `git diff --check` passes,
and `make pre-commit-md` passes. No source implementation or test suite was run before the M2 review gate.

## Shared-contract drift watch

These close only with member evidence; M1 must implement the neutral seam without presenting M2 as shipped.

- [x] **C1 -- envelope:** one schema-v1 implementation owns `sevt_` ids, RFC 3339 UTC timestamps, required fields, and
  the frozen origin/operation/outcome enums; malformed or newer records fail reads.
- [x] **C2 -- run identity:** each interactive attempt mints one existing root `RunIdentity` before preflight and reuses
  it for every M1 event and marker; `run_id == root_run_id` at the interactive root.
- [x] **C3 -- journals:** one authority-neutral helper owns contained paths, a dedicated lock, validation, and complete
  required JSONL appends; M1 uses only `authority/events.jsonl`.
- [x] **C4 -- evidence language:** reads preserve the exact `supported | unproven | null | unavailable` meanings and do
  not upgrade missing local evidence into a negative claim.
- [x] **C5 -- presentation:** M1 ships only `session authority show`; it adds no status-line segment and no combined
  authority/marking badge.
- [x] M1 tests leave an explicit neutral-helper contract for M2, including enum and schema drift guards.
- [x] **M2 composition -- C3 clarification and abort presentation:** ratify that a landed authority abort supersedes
  same-run start evidence in the M1 reader even when active clear fails; simultaneous abort/clear failure retains the
  epic's explicit evidence limitation.

M1 evidence (2026-08-21): `forge.session.events` owns the neutral schema/path/lock/read/write seam; all authority events
reuse it while creating only `authority/events.jsonl`. One launch transaction supplies the root run identity and an
explicit future routing/projection insertion boundary. Strict absence/history reporting and status-line exclusion are
pinned by focused, full-unit, regression, and Docker acceptance tests; exact results live in the M1 checklist. PR #234
merged as `a1c54a05`, and the member's lane/link closeout completed on 2026-08-22.

M2 final evidence (2026-08-23): routing reuses the shared envelope, lock/path helper, root run identity, and marked
launch transaction while remaining independently readable for unmarked sessions. Failure-injection tests pin
same-payload compensation, abort precedence, active-state cleanup, and child suppression; integration tests compose
authority, routing, proxy, sidecar, and both runtime launch boundaries. The final head passed 289 focused tests, 9,740
unit tests with 117 deselected, 1,067 regressions, the composed managed-launch lifecycle, one malformed-config Docker
case, and three real-runtime Docker cases (two Claude and one Codex), plus the wheel and full pre-commit gates. PR #240
merged as `2a53397c` with all five GitHub checks passing.

## Member sequence

- [x] **M1 -- Artifact Authority Mode (done):** checklist reviewed, implemented, verified, docs synchronized, merged via
  PR #234, and closed from `doing/` to `done/` with inbound links repointed.
- [x] **M2 -- Session Route Provenance and Marking (done):** reviewed, implemented, verified, documented, merged via PR
  #240, and closed from `doing/` to `done/` with inbound links repointed.
- [x] Review and ratify M2 D1-D8 before source implementation.
- [x] Implement, verify, document, and close M2 independently; do not fork the shared helper or vocabulary.

## Aggregate acceptance

- [x] One launch with both members active reuses one root run id across both journals and the route projection.
- [x] Each member still works alone; authority never depends on route/marking availability and routing never authorizes
  mutation.
- [x] Later-journal or projection failure attempts same-run compensation in every touched journal; a landed authority
  abort reports `launch_support=aborted` even when active clear fails, while simultaneous abort/clear failure is
  diagnosed and never permits child invocation.
- [x] Malformed journal handling, forced-child advisory inheritance, and separate absence/live-state rendering pass the
  epic acceptance matrix.
- [x] Session deletion and cleanup make no selective journal purge regardless of `--keep-transcripts`: both directories
  survive with their containing Forge artifact tree and disappear together only when an owning-worktree delete removes
  that tree.

## Closeout

- [x] Every live member is `done/` or has an explicit terminal outcome; no proposed member is counted as shipped.
- [x] `docs/design.md`, the relevant session/runtime/telemetry design docs, `docs/cli_reference.md`, and end-user guides
  describe only shipped behavior and preserve the no-attestation boundary.
- [x] Aggregate unit, regression, integration, pre-commit, and relative-link checks pass on the final integrated head.
- [x] Add the epic closeout to `docs/board/change_log.md`; promote only human-approved durable lessons to
  `docs/board/impl_notes.md`.
- [x] Move the epic `doing/ -> done/` after all shipped-member evidence is merged and repoint every inbound board link.

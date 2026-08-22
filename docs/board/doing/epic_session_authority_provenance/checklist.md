# Epic coordination checklist: Session Authority and Provenance

Coordination only -- shared-contract drift control, member sequencing, link maintenance, and aggregate closeout. It does
not replace either member's execution checklist. The normative contract is [card.md](card.md).

## Current focus

The epic was activated on 2026-08-21 with C1-C5 accepted and frozen. M1
[Artifact Authority Mode](../../done/artifact_authority_mode/card.md) shipped via PR #234 (merge `a1c54a05`) and closed
to `done/` on 2026-08-22; its [execution checklist](../../done/artifact_authority_mode/checklist.md) retains the member
evidence. M2 [Session Route Provenance and Marking](../../proposed/session_route_provenance/card.md) remains proposed
and is the epic's next reassessment decision. No epic batch is authorized.

## Activation bookkeeping

- [x] C1-C5 accepted as the shared contract before member execution; the epic card records the active lane and member.
- [x] Per-card branch `feat/artifact-authority-mode` created from `main` at `80d23f39`; no unrelated feature branch was
  reused.
- [x] Epic and M1 moved `proposed/ -> doing/` with `git mv`; M2 remains in `proposed/`.
- [x] Epic forward links, M1/M2 back links, and the adjacent model-first proposal link were repointed for the lane move.
- [x] M1 received its own fixture-grounded execution checklist; implementation and commits remained paused through
  checklist review.
- [x] User ratified M1 decisions D1-D5 on 2026-08-21; the checklist records the adopt exclusion, empirical Codex probe
  cost, spawn-boundary reason codes, and artifact containing-tree matrix.
- [x] No implementation or commit began during ratification; execution remains at the user-requested review boundary.

Activation and ratification verification (2026-08-21): all affected local Markdown links resolve, `git diff --check`
passes, and `make pre-commit-md` passes.

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

M1 evidence (2026-08-21): `forge.session.events` owns the neutral schema/path/lock/read/write seam; all authority events
reuse it while creating only `authority/events.jsonl`. One launch transaction supplies the root run identity and an
explicit future routing/projection insertion boundary. Strict absence/history reporting and status-line exclusion are
pinned by focused, full-unit, regression, and Docker acceptance tests; exact results live in the M1 checklist. PR #234
merged as `a1c54a05`, and the member's lane/link closeout completed on 2026-08-22.

## Member sequence

- [x] **M1 -- Artifact Authority Mode (done):** checklist reviewed, implemented, verified, docs synchronized, merged via
  PR #234, and closed from `doing/` to `done/` with inbound links repointed.
- [ ] Reassess M2 only after M1 closeout. If accepted, create a separate member branch/checklist and require reuse of
  M1's shared journal/run-correlation tests; do not fork the helper or vocabulary.
- [ ] If M2 is not accepted, keep the epic active only while a concrete coordination task remains; otherwise move it to
  the appropriate terminal lane with the member outcome recorded.

## Aggregate acceptance (deferred until both members ship)

- [ ] One launch with both members active reuses one root run id across both journals and the route projection.
- [ ] Each member still works alone; authority never depends on route/marking availability and routing never authorizes
  mutation.
- [ ] Later-journal or projection failure produces same-run compensating abort events in journals already touched and
  never reads as a started run.
- [ ] Malformed journal handling, forced-child advisory inheritance, and separate absence/live-state rendering pass the
  epic acceptance matrix.
- [ ] Session deletion and cleanup make no selective journal purge regardless of `--keep-transcripts`: both directories
  survive with their containing Forge artifact tree and disappear together only when an owning-worktree delete removes
  that tree.

## Closeout

- [ ] Every live member is `done/` or has an explicit terminal outcome; no proposed member is counted as shipped.
- [ ] `docs/design.md`, `docs/design_workflows.md`, relevant workflow/CLI docs, and end-user guides describe only
  shipped behavior and preserve the no-attestation boundary.
- [ ] Aggregate unit, regression, integration, pre-commit, and relative-link checks pass on the final integrated head.
- [ ] Add the epic closeout to `docs/board/change_log.md`; promote only human-approved durable lessons to
  `docs/board/impl_notes.md`.
- [ ] Move the epic `doing/ -> done/` after all shipped-member evidence is merged and repoint every inbound board link.

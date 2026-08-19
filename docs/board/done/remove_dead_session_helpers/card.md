# Remove verified dead session helpers

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4).

**Lane**: `done/` -- shipped in PR #197 (`86a83a1d`) on 2026-08-17.

**Finding**: O092's `collect_shadow_entries.session_filter`, `_print_session_tip`, and
`_generate_relaunch_name.parent_name` subsets.

## Goal

Remove individually verified, internal-only session parameters/behavior that no production caller can exercise.

## Evidence and Authority

Reverified on `f2fcc688`: every production shadow collector call passes `None` through the canonical function or its
private CLI wrapper; the only non-`None` consumer is the direct-only filtered-behavior test. `_print_session_tip` is a
definition-only private no-op and its `SessionState` import has no other consumer. `_generate_relaunch_name` has one
production caller and one test patch target; its body derives uniqueness only from the `forge_root`-filtered session
set. Repository-wide source, test, resource, extension, documentation, export, string-target, and history searches found
no additional compatibility consumer. DG4 and
[`docs/developer/coding_standards.md` "Internal surface"](../../../developer/coding_standards.md#internal-surface-module-to-module-private-apis)
govern the deletion.

## Acceptance Criteria

- Recheck source, resource, extension, docs, and export callers for each exact symbol immediately before removal.
- Remove direct-only filtered/no-op/unused-argument tests while retaining live shadow collection and project-scoped
  relaunch collision coverage.
- Run shadow-curation, session manager/resume, and related regression tests plus targeted session integration coverage.

## Exclusions

Do not remove active session selection, change shadow ordering, or base relaunch uniqueness on the parent name.

Review also confirmed a related O092-tail candidate that remains outside this member: `collect_shadow_entries` builds
`entries` only in the passport scan, so `seen_keys` always starts empty and every emitted entry has
`session="(project)"`. Upstream key deduplication therefore makes `_review_curate`'s same-shadow session-name merge
unreachable today. This evidence is recorded for separate follow-up admission; the branch does not change that behavior.

## Outcome

Shadow discovery no longer carries an unreachable session filter through either the session-layer collector or its
private CLI wrapper; the live passport scan, scope, root collection, and deduplication path are unchanged. The
definition-only session-tip no-op and its sole import are gone. Relaunch name generation now requires the
project-scoping `forge_root`, rejecting accidental unscoped calls while the parent still supplies lineage and child
state exactly as before.

The direct-only filtered shadow test was removed. A new control proves relaunch collision inputs contain only names from
the selected Forge root, and the live launch characterization pins the keyword-only `forge_root` handoff.

Verification passed 552 focused tests, 9,205 unit tests (one skip, 122 deselected), 913 regressions, 23 targeted Docker
session-lifecycle tests, full pre-commit, and board/design checks. PR #197 merged as `86a83a1d` with all five GitHub
checks passing. No Forge workflow command was used.

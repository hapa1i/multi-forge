# Decide compatibility requirements for cleanup deletions

**Epic**: [`epic_repo_maintenance_round`](../epic_repo_maintenance_round/card.md) (DG4).

**Lane**: `todo/` -- accepted decision work, parked until an execution branch becomes active.

## Problem

The review identifies deletion-class candidates in O047–O052, O092–O093, and O096: modules with no production importers,
unraised exception paths, inert configuration, legacy public methods, dead retry branches, test-only callers, and
unreachable branches.

Zero production callers do not establish that deletion is compatible. Tests may pin a supported import, serialized
config may be user-authored, extension consumers may live outside this repository, and several claims are partial or
explicitly unverified. A bulk sweep would mix safe local cleanup with public-surface and migration decisions.

## Decision Required

Define the compatibility evidence required before deleting:

- a module or public symbol;
- an exception type and its handling path;
- a serialized config field;
- a public store/registry method;
- a legacy environment shim; or
- a test-only helper or unreachable branch.

For every candidate, record `keep`, `deprecate`, `delete`, `replace`, or `verify further`, with external-consumer risk,
test disposition, documentation impact, and migration requirements. O092 must be split into individually verified
symbols; O093's no-op claim and every explicitly unverified candidate remain ineligible until confirmed.

## Evidence

- Review: [`review_combined.md` DG4](../../review_combined.md#decision-gates).
- Candidate rows: O047–O052, O092–O093, and O096 in the review's code and maintenance table.
- Board rule: independently shippable changes remain member cards; deletion is not one mechanical operation merely
  because the findings share a type label.

## Acceptance Criteria

- A compatibility rubric covers imports, durable config, public APIs, tests, extensions, and migration.
- Every listed row has an evidence-backed disposition; compound rows are split by symbol or behavior.
- Unverified candidates are explicitly excluded or promoted only after confirmation.
- Accepted removals become narrowly scoped implementation cards with characterization and regression expectations.
- No production deletion is bundled into this decision card.

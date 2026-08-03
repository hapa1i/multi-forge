# Decide authority for sessions with a missing worktree

**Epic**: [`epic_repo_maintenance_round`](../epic_repo_maintenance_round/card.md) (DG2; D009).

**Lane**: `todo/` -- accepted decision work, parked until an execution branch becomes active.

## Problem

Session readers disagree when a manifest survives but its recorded worktree does not:

- `list_sessions` prunes the index row when the worktree is missing;
- `get_session` keeps the row alive when the store root and manifest survive; and
- `session repair` reports `missing-worktree` without re-indexing it because the list predicate would prune the row
  again.

The result can be invisible manifest-owned names and bindings with no supported recovery. The behavior is known in the
orphan-repair design and change log, so changing one predicate without choosing authority would only move the drift.

## Decision Required

Define:

- whether the manifest, index row, or worktree is authoritative for session liveness;
- the canonical predicate shared by list, get, binding scans, delete, repair, and clean;
- whether a missing-worktree session is recoverable, terminal, or report-only;
- which command owns safe repair or removal; and
- how ordinary, root-level worktree, moved-checkout, and nested-project sessions differ.

## Evidence

- Review: [`review_combined.md` DG2 and D009](../../review_combined.md#decision-gates).
- Reader predicates: `src/forge/session/index.py:198,271` at the review baseline.
- Repair contract: `docs/design.md` §3.2.
- Shipped repair context: `docs/board/change_log.md`, “Session orphan manifest repair.”

## Acceptance Criteria

- Normative session design names one liveness authority and predicate per session shape.
- List/get/repair/delete/clean and binding-scan responsibilities are enumerated.
- Recovery and refusal behavior is specified for every missing-worktree classification.
- D009 receives one or more implementation cards with race/failure fixtures and regression coverage.
- No code change is bundled into this decision card.

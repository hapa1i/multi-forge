# Decide authority for sessions with a missing worktree

**Epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md) (DG2; D009).

**Lane**: `done/` -- approved on 2026-08-04; implementation shipped in PR #137 (`cce6e8c6`) through
[`retain_missing_worktree_sessions`](../../done/retain_missing_worktree_sessions/card.md).

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

## Decision

**Status:** approved on 2026-08-04. The decision separates durable existence, discovery, and launchability instead of
forcing one path to answer all three questions.

1. A valid manifest is the durable reservation for a session name, provenance, and conversation bindings.
2. The global index is the publication and discovery cache. It may be repaired from a valid manifest and may prune a row
   only when the corresponding manifest is absent.
3. The recorded worktree is a launch prerequisite, not a liveness prerequisite. A valid manifest with no worktree is a
   live, degraded session.

This matches the transaction contract already present in `IndexStore.create_session_txn`: the manifest is what reserves
a name, while a row without a manifest is safe residue. The current `list_sessions` worktree predicate is the outlier.

### Canonical operation behavior

| Operation                                     | Missing worktree with valid manifest                                                                                                                                                 |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `list` / workspace reads                      | Retain and show the session with `launchability=missing_worktree`; do not self-prune it.                                                                                             |
| `get` / `show`                                | Return/read the session and expose the degraded status. Reads that do not require a checkout remain available.                                                                       |
| resume, fork, launch, worktree-local mutation | Refuse before mutation with the recorded path and recovery/removal guidance.                                                                                                         |
| binding scans and name-collision checks       | Count the manifest's name and Claude/Codex bindings as occupied; preserve fail-closed reads.                                                                                         |
| `session repair`                              | Re-index a valid orphan as degraded after the existing collision, unchanged-bytes, and binding checks. It does not invent or recreate a worktree.                                    |
| `session delete`                              | Own explicit removal of the manifest/index reservation and optional external artifacts. An already absent worktree is not an error. Existing ownership and force checks still apply. |
| `forge clean`                                 | Report the degraded session but do not auto-delete a valid manifest merely because its worktree is absent. Corrupt residue remains under clean's existing fail-closed rules.         |

An index row whose manifest is absent remains prunable. A corrupt, unreadable, schema-newer, or identity-conflicting
manifest is not promoted to “live and healthy”: readers fail closed or report its existing repair/clean classification.

### Session shapes

| Shape                                                                           | Decision                                                                                                    |
| ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Ordinary checkout moved intact                                                  | Repair from the manifest at its discovered location and correct recorded checkout/worktree paths, as today. |
| Linked/root-level worktree session whose manifest survives under the Forge root | Publish or retain it as degraded when the linked worktree path is gone.                                     |
| `--into` or another non-owned/shared checkout                                   | Treat worktree absence as degraded; repair never claims ownership or recreates the checkout.                |
| Nested project whose manifest lived inside the deleted worktree                 | There is no surviving manifest, so no durable session remains to publish. A stale row is prunable.          |
| Root/main session whose checkout and co-located manifest both disappeared       | Same as the nested case: no surviving manifest, so the row is residue.                                      |

The degraded state should be derived from the manifest and filesystem at read time rather than persisted as a second
truth. JSON read surfaces expose a stable launchability value; human output gives an actionable path. A worktree that
reappears at the same validated path becomes launchable without a state migration.

## Finding Disposition

| Finding | Disposition | Downstream work                                                                                                                                          |
| ------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D009    | Implement   | Align list/get/repair around manifest liveness, expose derived launchability, retain bindings, and make checkout-dependent operations refuse actionably. |

Proposed implementation member: `retain_missing_worktree_sessions`. It must include row-without-manifest and
manifest-without-worktree races, root-level and nested-project fixtures, ordinary moved-checkout repair, binding
uniqueness, delete/clean ownership, JSON/human output, and targeted session integration coverage.

## Acceptance Criteria

- Normative session design names one liveness authority and predicate per session shape.
- List/get/repair/delete/clean and binding-scan responsibilities are enumerated.
- Recovery and refusal behavior is specified for every missing-worktree classification.
- D009 receives one or more implementation cards with race/failure fixtures and regression coverage.
- No code change is bundled into this decision card.

## Closeout

The target contract and operation matrix are approved. The implementation member now aligns the list/get predicates,
repair, clean, launch refusal, and normative/end-user documentation with this decision; it remains in `doing/` until
independent review and merge. Decision verification: `make pre-commit-md` and `git diff --check`.

# Preserve supervisor edit identity checklist

Current focus: implementation and verification are complete; the active epic owns review and merge before Wave 1 closes.

## Evidence and Regression

- [x] Verify PR #126 merged and the D002–D004/O028 review gate is satisfied.
- [x] Recheck the Claude and Codex adapter shapes against merged `main`.
- [x] Recheck frontier, plan-check, and shadow cache-key consumers against merged `main`.
- [x] Add `tests/regression/test_bug_d005_supervisor_edit_identity.py` with the D005 root cause.
- [x] Record the expected pre-fix failures for Claude removed text, Codex delete-only hunks, and post-truncation tails
  (`9 failed`).

## Implementation

- [x] Define one runtime-neutral canonical action identity with unambiguous field boundaries.
- [x] Hash the complete action before adapter prompt truncation; persist only the digest in normalized context/cache
  keys.
- [x] Include Claude matched and replacement fragments in the frontier prompt without changing deterministic inputs.
- [x] Use Codex/on-demand raw diffs and Write content in the relevant canonical representation.
- [x] Apply the same identity to supervisor, plan-check, and deterministic shadow sampling.
- [x] Preserve plan, route, budget, effort, target-metadata, TTL, and clean-allow-only cache dimensions.
- [x] Keep D026 shadow configuration reconstruction and whole-file delete behavior out of scope.

## Acceptance Matrix

| Runtime/path              | Distinguishing input                     | Expected prompt                   | Expected identity/cache result             |
| ------------------------- | ---------------------------------------- | --------------------------------- | ------------------------------------------ |
| Claude Edit               | Different `old_string`, same replacement | Matched and replacement fragments | Distinct supervisor and plan-check entries |
| Codex Update File         | Different delete-only raw hunks          | Bounded raw diff                  | Distinct supervisor and plan-check entries |
| Claude/Codex long actions | Difference only after 5,000 characters   | Existing bounded presentation     | Distinct pre-truncation identities         |
| Identical action          | Byte-identical canonical fields          | Same bounded presentation         | Clean allow remains a cache hit            |

## Verification and Closeout

- [x] Run focused Claude/Codex adapters, supervisor, plan-check, and shadow tests (`304 passed`).
- [x] Run `make test-regression` (`641 passed`).
- [x] Run `make test-unit` (`8,709 passed, 1 skipped, 118 deselected`).
- [x] Run `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py` (`21 passed`).
- [x] Run `make pre-commit`.
- [x] Update `docs/design_workflows.md`; no end-user Day 1 path changes.
- [x] Record the outcome in the review ledger and `docs/board/change_log.md`.
- [x] Move the member to `done/`, repoint inbound links, and record final verification.

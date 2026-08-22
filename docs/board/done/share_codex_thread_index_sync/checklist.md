# Share Codex thread-to-index synchronization checklist

Current focus: complete -- order 23 shipped in PR #202 (`d1abccc7`); orders 24--35 remain parked.

## Activation and evidence

- [x] Close order 22 on pushed `main` at `a3dadb18`, create the execution branch from that exact commit, and move only
  this member to `doing/`.
- [x] Re-run source, caller, import, and test searches for both `_sync_codex_thread_to_index` copies and
  `IndexStore.update_codex_thread`.
- [x] Characterize no-thread, already-bound, missing-row, collision, and manifest-deletion behavior before extraction.
- [x] Record the focused Codex op/adoption/index baseline before implementation (201 passed).

## Implementation

- [x] Extract one UI-free Codex thread-to-index writer with the existing best-effort contract.
- [x] Route interactive start/resume and headless start/resume through the shared writer.
- [x] Preserve manifest publication ordering, index-lock ownership, adoption collision guards, and runtime thread IDs.
- [x] Add direct shared-writer contracts and retain deleted-identity caller guards at the launch boundaries.

## Verification and closeout

- [x] Run focused Codex op, adoption, identity, and index-store tests (205 passed).
- [x] Run the full unit suite (9,220 passed, one skipped, 122 deselected) and regression suite (915 passed).
- [x] Confirm Codex 0.147.0 readiness, then run the real start/resume integration with index assertions (one passed).
- [x] Run full pre-commit and `git diff --check`; confirm `design.md` (29,972) and the former consolidated design
  appendix (29,990) stay below 30,000 tokens; and audit 357 board documents, 882 local links, zero missing links, and
  Wave 7's 22 done / one doing / 12 todo lanes without a Forge workflow.
- [x] Open PR #202, merge it as `d1abccc7` after all five checks pass, and close order 23 without activating order 24.

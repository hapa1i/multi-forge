# Stop and artifact correctness checklist

Current focus: complete -- all Wave 2 members shipped and the coordination record is closed.

- [x] Create the Wave 2 execution branch and move this epic to `doing/`.
- [x] Activate only `align_stop_verification_contract` and create its execution checklist.
- [x] Recheck D006/U002/U003 against merged `main` before implementation (`5813994c`; six regression failures).
- [x] Review and merge the verification member before activating transcript-artifact work (PR #130, 2026-08-05).
- [x] Create the transcript-artifact execution branch, move its card to `doing/`, and create its checklist.
- [x] Recheck D007/D024 on merged `main` at `fee562ab` before implementation (six regression failures).
- [x] Review and merge the transcript-artifact member before activating sidecar routing work (PR #131, `3e090ef5`).
- [x] Create the D039 execution branch, move its card to `doing/`, and create its checklist.
- [x] Recheck D039 against merged `main` at `3e090ef5` before implementation (`queued_shadow=false` regression).
- [x] Implement and verify D039 without broadening shadow candidate or marker schemas.
- [x] Review and merge D039 before closing Wave 2 (PR #132, `dc963a7c`).
- [x] Close Wave 2 only after all three members ship and the ledger/design records are synchronized.

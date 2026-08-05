# Stop and artifact correctness checklist

Current focus: review and merge `preserve_transcript_artifact_identity`; sidecar routing remains parked.

- [x] Create the Wave 2 execution branch and move this epic to `doing/`.
- [x] Activate only `align_stop_verification_contract` and create its execution checklist.
- [x] Recheck D006/U002/U003 against merged `main` before implementation (`5813994c`; six regression failures).
- [x] Review and merge the verification member before activating transcript-artifact work (PR #130, 2026-08-05).
- [x] Create the transcript-artifact execution branch, move its card to `doing/`, and create its checklist.
- [x] Recheck D007/D024 on merged `main` at `fee562ab` before implementation (six regression failures).
- [ ] Review and merge the transcript-artifact member before activating sidecar routing work.
- [ ] Close Wave 2 only after all three members ship and the ledger/design records are synchronized.

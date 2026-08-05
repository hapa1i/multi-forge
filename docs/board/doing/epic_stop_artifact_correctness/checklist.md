# Stop and artifact correctness checklist

Current focus: review and merge completed `align_stop_verification_contract`; later members remain parked in sequence.

- [x] Create the Wave 2 execution branch and move this epic to `doing/`.
- [x] Activate only `align_stop_verification_contract` and create its execution checklist.
- [x] Recheck D006/U002/U003 against merged `main` before implementation (`5813994c`; six regression failures).
- [ ] Review and merge the verification member before activating transcript-artifact work.
- [ ] Review and merge the transcript-artifact member before activating sidecar routing work.
- [ ] Close Wave 2 only after all three members ship and the ledger/design records are synchronized.

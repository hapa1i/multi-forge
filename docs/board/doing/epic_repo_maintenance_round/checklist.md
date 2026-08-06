# Repository maintenance round checklist

Current focus: independently review and merge D009 without starting O003 or D021.

- [x] Create the execution branch and move the epic and decision cards to `doing/`.
- [x] Create checklists for the active epic and member cards.
- [x] Verify every decision against implementation and normative documentation.
- [x] Draft DG1–DG4 and record finding-level dispositions.
- [x] Identify downstream implementation cards without starting implementation.
- [x] Run documentation and board-consistency checks.
- [x] Obtain human approval of the decision set (2026-08-04).
- [x] Create accepted implementation members and close the four decision cards.
- [x] Convert Wave 1 policy/supervision findings into independently shippable member cards.
- [x] Recheck and reproduce Wave 1 D001–D005 and the related O028 parser subset.
- [x] Sequence Wave 1 members without starting parked `todo/` work implicitly.
- [x] Close Wave 1 only after all members ship and its ledger/design links are current.
- [x] Recheck and reproduce Wave 2 D006–D007 against merged `main` before implementation starts.
- [x] Characterize Wave 2 D024 and D039 at their affected read/path seams.
- [x] Sequence Wave 2 into three parked members under `epic_stop_artifact_correctness`.
- [x] Implement and verify the D005 plus-prefix corrective member.
- [x] Review and merge the D005 corrective member before starting Wave 2 implementation (PR #129, 2026-08-05).
- [x] Implement and verify the D006/U002/U003 Stop-verification member.
- [x] Review and merge the Stop-verification member before activating transcript-artifact work (PR #130, 2026-08-05).
- [x] Activate `preserve_transcript_artifact_identity` on its execution branch.
- [x] Implement and verify the D007/D024 transcript-artifact member without activating sidecar routing.
- [x] Review and merge the D007/D024 transcript-artifact member (PR #131, `3e090ef5`).
- [x] Activate `repair_sidecar_shadow_drain_routing` on its execution branch.
- [x] Implement and verify D039 without broadening the shadow candidate or marker schemas.
- [x] Review and merge D039, then close the Wave 2 child epic (PR #132, `dc963a7c`).
- [x] Recheck and reproduce Wave 3 D008–D011, D021–D022, O003, and O006 on merged `main` (8 executable characterizations
  passed on `dc963a7c`).
- [x] Sequence Wave 3 under `epic_session_durable_state_safety` without activating a parked member.
- [x] Run Wave 3 admission Markdown, relative-link, stale-lane, and diff checks.
- [x] Review and merge the Wave 3 admission record before activating D011 (PR #133, `eef7cee0`).
- [x] Activate `preserve_unreadable_json_state_classification` from merged `main` on its own execution branch.
- [x] Implement and verify D011 without activating O006 or D021.
- [x] Review D011 and record its GC-documentation amendment and separate D046 follow-up (2026-08-06).
- [x] Merge D011 before activating O006 (PR #134, `6be815bf`).
- [x] Activate O006 from merged `main` and retain its baseline `AttributeError` regression failure.
- [x] Implement and behaviorally verify O006 without changing D009 liveness or D011 read classification.
- [x] Review O006 and record its separate D047 status-line raw-reader follow-up (2026-08-06).
- [x] Merge O006 before activating D008 (PR #135, `00692356`).
- [x] Activate D008 from merged `main` and create its execution checklist.
- [x] Implement and behaviorally verify D008 without activating D009 or D021.
- [x] Review D008 and record its separate D048 relaunch-inheritance policy follow-up (2026-08-06).
- [x] Merge D008 before activating D009 (PR #136, `8ebdb644`).
- [x] Activate D009 from merged `main` and create its execution checklist.
- [x] Implement and behaviorally verify D009 without activating O003 or D021.
- [ ] Independently review and merge D009 before activating O003.
- [ ] Recheck and reproduce later-wave CRITICAL/HIGH findings before their implementation members start.
- [ ] Sequence later-wave accepted members as each wave reaches its entry conditions.

The epic remains in `doing/` after the decision cards close; later execution waves remain outstanding.

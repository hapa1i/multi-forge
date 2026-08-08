# Repository maintenance round checklist

Current focus: independently review and merge D019 as the final Wave 4 member.

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
- [x] Independently review and merge D009 before activating O003 (PR #137, `cce6e8c6`).
- [x] Activate O003 from merged `main` and create its execution checklist.
- [x] Implement and behaviorally verify O003 without activating D021.
- [x] Review O003, repair the stale CLI integration-fixture import, and record the separate D049 receipt-shell race.
- [x] Merge O003 before activating D021 (PR #138, `4a601dc2`).
- [x] Activate D021 from merged `main` at `de8adaac` and retain its byte-rewrite regression failure.
- [x] Implement and behaviorally verify D021 while preserving PR #139's rotating-window semantics.
- [x] Merge D021 before activating D022 (PR #140, `ecc79aa2`).
- [x] Activate D022 from merged `main` at `ecc79aa2` and create its execution checklist.
- [x] Retain D022's silent structured-fallback regression and implement canonical transfer-strategy validation.
- [x] Review and merge D022 before activating D010 (PR #141, `d2ed2349`).
- [x] Activate D010 from merged `main` at `d2ed2349` and create its execution checklist.
- [x] Retain D010's linked-worktree guard regression and implement root-guard parity.
- [x] Review and merge D010, then close the Wave 3 child epic (PR #142, `2461e3fa`).
- [x] Recheck and reproduce Wave 4 D012--D014 and D019 on merged `main` (four broken-behavior characterizations passed;
  a fifth corrected D012's stale tracked-baseline claim).
- [x] Sequence Wave 4 into three parked members under `epic_installer_transaction_safety` without activating installer
  implementation.
- [x] Run Wave 4 admission Markdown, relative-link, stale-lane, change-log size, and diff checks.
- [x] Review and merge the Wave 4 admission record before activating D013/D014 (PR #143, `afde43bf`).
- [x] Activate D013/D014 from merged `main` at `afde43bf` and create its execution checklists.
- [x] Retain D013/D014 regressions and implement exact Codex config rollback across read-back and tracking failures.
- [x] Independently review D013/D014 (2026-08-08; no design violations).
- [x] Merge D013/D014 before activating D012 (PR #144, `37a03209`).
- [x] Activate D012 from merged `main` and create its execution checklist.
- [x] Retain D012's baseline-rotation regression and implement immutable baseline ownership across both disable paths.
- [x] Verify D012 with focused, Docker, clean-wheel, regression, and pre-commit coverage.
- [x] Independently review D012 and resolve its LOW tracked-baseline deletion race.
- [x] Merge D012 before activating D019 (PR #145, `f069226f`).
- [x] Activate D019 from merged `main` at `f069226f` and create its execution checklist.
- [x] Retain D019's unconditional scalar/env deletion regression and implement value-aware legacy removal.
- [ ] Verify and independently review D019, then close the Wave 4 child epic after merge.
- [ ] Recheck and reproduce later-wave CRITICAL/HIGH findings before their implementation members start.
- [ ] Sequence later-wave accepted members as each wave reaches its entry conditions.

The epic remains in `doing/` after the decision cards close; later execution waves remain outstanding.

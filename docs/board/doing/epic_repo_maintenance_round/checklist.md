# Repository maintenance round checklist

Current focus: Wave 5 is closed; Wave 6 has shipped its first 8 findings across 4 members and has no active member.

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
- [x] Independently review D019 with no findings and merge it (PR #146, `3f3a3c6d`).
- [x] Close the Wave 4 child epic after synchronizing its three shipped members and inbound links.
- [x] Recheck the seven remaining Wave 5 HIGH findings on merged `main` (7 disposable broken-behavior characterizations
  passed on `3f3a3c6d`; O003 was already shipped in Wave 3).
- [x] Sequence Wave 5 into seven parked members under `epic_cli_proxy_runtime_correctness` without activating
  implementation.
- [x] Run Wave 5 admission Markdown, relative-link, stale-lane, change-log size, and diff checks.
- [x] Review and merge the Wave 5 admission record before activating D015 (PR #147, `92b981a5`).
- [x] Start `fix/unify-downstream-retention`, move the Wave 5 child epic and D015 to `doing/`, create their checklists,
  and repoint inbound links.
- [x] Implement, independently review, and merge D015 before activating O002 (PR #148, `8b997e6a`).
- [x] Activate O002 from merged `main`, close D015, and create the O002 execution checklist.
- [x] Implement, independently review, and merge O002 before activating D016 (PR #149, `c20b8d10`).
- [x] Activate D016 from merged `main`, close O002, and create the D016 execution checklist.
- [x] Implement, independently review, and merge D016 before activating D017 (PR #150, `61580fdb`).
- [x] Activate D017 from merged `main`, close D016, and create the D017 execution checklist.
- [x] Independently review D017; add its missing corrupt `--scope all` control, correct the CLI helper docs, and admit
  D051/D052 separately (2026-08-09).
- [x] Merge D017 before activating O001 (PR #151, `efbefce9`).
- [x] Activate O001 from merged `main`, close D017, and create the O001 execution checklist.
- [x] Implement, independently review, and merge O001 before activating O004 (PR #152, `983e4470`).
- [x] Activate O004 from merged `main`, close O001, and create the O004 execution checklist.
- [x] Implement, independently review, and merge O004 before activating D018 (PR #153, `8f030ef4`).
- [x] Activate D018 from merged `main`, close O004, and create the D018 execution checklist.
- [x] Implement, independently review, and merge D018; close its seven-member child epic (PR #154, `c4f14037`).
- [x] Recheck D035, D036, O037, O038, and O042 on merged `main` at `c9c4bc2e` (six disposable broken-behavior
  characterizations passed; one also confirmed the current `0600` shard mode, and the module was removed).
- [x] Correct D035's stale no-pruner subclaim and record its current `0600` shard mitigation while retaining the
  reproduced plaintext, per-record bound, and `0700` directory-hardening scope.
- [x] Sequence the five findings as three parked members under `epic_proxy_diagnostic_data_hygiene` without activating
  implementation.
- [x] Review and merge the bounded proxy-hygiene admission record before activating O037/O038/O042 (PR #156,
  `46e6a309`).
- [x] Start `fix/remove-proxy-converter-plaintext-logs`, activate the child epic and O037/O038/O042 from merged `main`,
  and create their execution checklists.
- [x] Keep provider-side response-conversion exception rendering outside O037/O038/O042 and admit it separately as D053
  after runtime reproduction (2026-08-10).
- [x] Implement, review, and merge O037/O038/O042 before activating D035 (PR #157, `a2fb0638`).
- [x] Start `fix/make-tool-events-metadata-only`, close O037/O038/O042, activate D035, and create its checklist.
- [x] Implement, review, and merge D035 before activating D036 (PR #158, `ce7eb1ec`).
- [x] Start `fix/validate-proxy-request-ids`, close D035, activate D036, and create its checklist.
- [x] Independently review and merge D036, then close the proxy-diagnostic hygiene child epic (PR #159, `de02b09b`).
- [x] Recheck O007 and D053 on merged `main` at `de02b09b` (four disposable broken-behavior characterizations passed,
  and the module was removed).
- [x] Sequence O007/D053 as two parked members under `epic_proxy_conversion_failure_handling` without activating
  implementation.
- [x] Review and merge the bounded O007/D053 admission record before activating D053 (PR #160, `cf77c175`).
- [x] Start `fix/sanitize-proxy-conversion-failure-logs`, activate the child epic and D053 from merged `main`, and
  create their execution checklists.
- [x] Retain D053's non-streaming and streaming fail-first regressions while preserving existing client behavior.
- [x] Implement and verify metadata-only conversion-failure ERROR records without activating O007.
- [x] Independently review and merge D053 before activating O007 (PR #161, `8088ceae`).
- [x] Start `fix/fail-non-streaming-response-conversion`, close D053, activate O007, and create its execution checklist.
- [x] Retain O007's initial and authentication-retry false-success regressions on merged `main`.
- [x] Implement and verify truthful non-streaming conversion-failure client/accounting behavior.
- [x] Independently review and merge O007, then close the proxy-conversion child epic (PR #162, `31a0832f`).
- [x] Compact the oldest change-log tail before recording the next MEDIUM admission, preserving dates, goals, decisions,
  verification, and deferred items (July 10--17 compacted; approximately 20.6k tokens / 1.35k lines remain).
- [x] Close the open-ended Wave 5 admission boundary on `246aaff1`: recheck 36 CLI/proxy/runtime candidate rows, reject
  D033/O020 with two passing behavior controls, and park the 34 live rows under `epic_wave6_correctness_maintenance`
  without activating implementation.
- [x] Activate the Wave 6 epic and D020 on `agent/d020-inherited-forge-headers`; keep the other 11 members parked.
- [x] Ship D020 independently before activating the next ordered Wave 6 member (PR #164, `26ab5f29`).
- [x] Ship D023/D028/O022 independently before activating the next ordered Wave 6 member (PR #165, `b3150184`).
- [x] Ship D027/O012 independently before activating the next ordered Wave 6 member (PR #166, `5b50acc8`).
- [x] Activate only O014/O026 from merged `main` at `4774f69e` on `agent/close-proxy-failure-lifecycles`.
- [x] Ship O014/O026 independently before activating the next ordered Wave 6 member (PR #167, `33e3db7f`).
- [ ] Activate only D029/O025 from merged `main`, then retain its fail-first execution-base reproduction before
  production changes.
- [ ] Recheck the remaining Wave 6 MEDIUM/LOW findings and Wave 7 structural findings against their entry conditions
  before activating any additional implementation cards.

The epic remains in `doing/` after the decision cards close; later execution waves remain outstanding.

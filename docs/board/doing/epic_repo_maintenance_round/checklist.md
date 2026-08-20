# Repository maintenance round checklist

Current focus: reject unknown workflow-policy keys in active Wave 8 order 7; orders 8--19 remain parked.

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
- [x] Activate only D029/O025 from merged `main` at `7c76a099` on `agent/complete-proxy-instance-config-wiring`.
- [x] Ship D029/O025 independently before activating the next ordered Wave 6 member (PR #168, `9b18edc3`).
- [x] Record PR #169 (`ece999d4`) as bounded post-merge O012 and retention-status hardening without changing the Wave 6
  finding count.
- [x] Activate only D030/O008/O015/O035 from merged `main` at `7f705aad` on `agent/restore-proxy-request-semantics`.
- [x] Ship D030/O008/O015/O035 independently in PR #170 (`acae1b9e`) before activating the next Wave 6 member.
- [x] Verify and admit D054/D055 as a new Wave 6 proxy-boundary member on merged `main` at `22071fcd`.
- [x] Activate only D054/D055 on `agent/harden-proxy-boundary-failures`; keep the six parked members gated.
- [x] Ship D054/D055 independently in PR #171 (`5cd268c1`) before activating another Wave 6 member.
- [x] Activate only O013/O034 from merged `main` at `f6df4a40`; keep the remaining five Wave 6 members parked.
- [x] Ship O013/O034 independently in PR #172 (`366c216a`) before activating another Wave 6 member.
- [x] Activate only D031 from merged `main` at `7280d177`; keep the remaining four Wave 6 members parked.
- [x] Ship D031 independently in PR #173 (`a55ab218`) before activating another Wave 6 member.
- [x] Activate only D032/D041/O005/O031--O033 from merged `main` at `13ecef87`; keep the remaining three Wave 6 members
  parked.
- [x] Ship D032/D041/O005/O031--O033 independently in PR #174 (`095fcd90`) before activating another Wave 6 member.
- [x] Close PR #174 bookkeeping and activate only D034/D037/D038/O027 on `agent/harden-command-state-boundaries` from
  merged production code at `095fcd90`.
- [x] Implement and verify D034/D037/D038/O027 without activating either remaining Wave 6 member.
- [x] Ship D034/D037/D038/O027 independently in PR #175 (`967d9cae`) before activating another Wave 6 member.
- [x] Close PR #175 bookkeeping and activate only O011/O017/O021/O023/O029/O030 on
  `agent/preserve-session-launch-preconditions` from merged production code at `967d9cae`.
- [x] Implement and verify O011/O017/O021/O023/O029/O030 without activating O036.
- [x] Review and merge O011/O017/O021/O023/O029/O030 independently in PR #176 (`88ac88c5`) before activating O036.
- [x] Close PR #176 bookkeeping and activate only O036 on `agent/harden-walkthrough-sandbox-provenance` from merged
  production code at `88ac88c5`.
- [x] Implement and verify O036 from its retained fail-first artifact without activating another maintenance member.
- [x] Review and merge O036 independently in PR #177 (`3026b14a`).
- [x] Close O036 and the bounded Wave 6 correctness-maintenance epic at 36/36 findings across 13/13 members.
- [x] Record human workflow preflight stream splitting as D056, outside the active member and behind its own entry gate.
- [x] Recheck the Wave 7 structural/deletion candidates on merged `main` at `5777192a`; reject O062/O063/O093 as
  written, promote only verified O067/O095 subsets, and keep all unverified symbols excluded.
- [x] Park the ordered implementation members under `epic_wave7_refactor_and_deletion`, split the DG4 umbrellas and
  large fork/installer/status-line seams, and retire three superseded/invalidated cards without activating work.
- [x] Recheck D040, D042--D052, D056, O045--O046, O072, O074--O091, O097, and omitted O100 on merged `main` at
  `bad273ef`; admit 23 verified rows as 19 parked Wave 8 members, leave D040 proposed, reject O078/O079 as bugs, record
  already-resolved rows, and narrow O080/O085/O097 to supported scope without activating implementation.
- [x] Prepare the Wave 8 admission, member graph, ledger dispositions, and verification record directly on `main`
  without activating implementation.
- [x] Reproduce order 32's retained transfer snapshot and stale same-name retry, then activate only the bounded
  `correct_fork_transfer_snapshot_rollback` correction from the pushed Wave 8 admission base.
- [x] Merge and close the fork snapshot correction in PR #215 (`7736d0d0`) before activating Wave 8 order 1.
- [x] Branch from pushed correction closeout `7a2ad4c1` and activate only Wave 8 order 1
  `trace_failed_provider_attempts`; keep the other 18 members parked.
- [x] Ship Wave 8 order 1 in PR #216 (`634ff40e`) and close it before activating order 2.
- [x] Branch from pushed order-1 closeout `e3def8c3` and activate only Wave 8 order 2
  `offload_proxy_accounting_persistence`; keep orders 3--19 parked.
- [x] Ship Wave 8 order 2 in PR #217 (`6b2e0129`) and close it before activating order 3.
- [x] Branch from pushed order-2 closeout `cddfe5c3` and activate only Wave 8 order 3
  `strip_openai_account_response_headers`; keep orders 4--19 parked.
- [x] Ship Wave 8 order 3 in PR #218 (`4cd859cb`) and close it before activating order 4.
- [x] Branch from pushed order-3 closeout `3f50012c` and activate only Wave 8 order 4
  `harden_worktree_config_copy_safety`; keep orders 5--19 parked.
- [x] Ship Wave 8 order 4 in PR #219 (`43a3b29c`) and close it before activating order 5.
- [x] Branch from pushed order-4 closeout `2da22c2a` and activate only Wave 8 order 5 `unify_cli_failure_diagnostics`;
  keep orders 6--19 parked.
- [x] Ship Wave 8 order 5 in PR #220 (`61be7d80`) and close it before activating order 6.
- [x] Branch from pushed order-5 closeout `3c0a3002` and activate only Wave 8 order 6 `eliminate_runtime_test_skips`;
  keep orders 7--19 parked.
- [x] Ship Wave 8 order 6 in PR #221 (`9d6deb7f`) and close it before activating order 7.
- [x] Commit the Wave 7 admission on `main` (`095d8eeb`), branch from that exact commit, and activate only order 1
  `decouple_lane_runtime_vocabulary`; keep the other 33 members parked.
- [x] Ship O043 independently and close its member before activating Wave 7 order 2.
- [x] Branch from O043's pushed closeout (`2a08f009`) and activate only `share_policy_activation_rules`.
- [x] Ship O044 independently and close its member before activating Wave 7 order 3.
- [x] Branch from O044's pushed closeout (`ef9c27c1`) and activate only `centralize_time_parsing_and_periods`.
- [x] Ship O060/O061/O094 independently and close its member before activating Wave 7 order 4.
- [x] Branch from order-3's pushed closeout (`9817cad3`) and activate only `unify_git_root_discovery`.
- [x] Ship O066/O092 independently and close its member before activating Wave 7 order 5.
- [x] Branch from order-4's pushed closeout (`56d32945`) and activate only `centralize_install_path_authority`.
- [x] Ship O065/O069 independently and close its member before activating Wave 7 order 6.
- [x] Branch from order-5's pushed closeout (`62055bab`) and activate only `centralize_cli_metric_formatting`.
- [x] Ship O064 independently in PR #183 (`cd3e50e8`) and close its member before activating Wave 7 order 7.
- [x] Branch from order-6's pushed closeout (`4f167379`) and activate only `remove_verified_internal_residue`, the
  explicitly admitted O098/O092 subset; keep orders 8--35 parked.
- [x] Ship the O098/O092 subset independently in PR #184 (`95488c10`) and close its member before selecting order 8.
- [x] Keep Wave 7 order 8 parked and activate `correct_post_merge_review_findings` for the five verified defects from
  the review of PRs #170--#180.
- [x] Implement the walkthrough, proxy, timezone, rollback, and shadow-guidance corrections with focused, full,
  integration, package, and documentation coverage.
- [x] Merge the corrective member in PR #185 (`8ccbf387`) and close its board record without activating Wave 7 order 8.
- [x] Branch from the corrective closeout (`5bd69ef5`) and activate only order 8 `remove_stale_dependencies`.
- [x] Ship the verified O071 `python-dotenv` subset independently in PR #186 (`19dcf9cb`) and close its member before
  selecting Wave 7 order 9.
- [x] Branch from the order-8 closeout (`549fb0e3`) and activate only order 9 `share_proxy_transport_test_fakes`.
- [x] Complete O099's fake-family consolidation with instance-owned state and focused, full, pre-commit, and board
  verification; keep Wave 7 order 10 parked until order 9 ships.
- [x] Ship O099's fake-family subset independently in PR #187 (`be321ad2`) and close its member before activating Wave 7
  order 10.
- [x] Branch from the order-9 closeout (`3260a6fa`) and activate only order 10 `lock_walkthrough_state_parity`.
- [x] Lock the walkthrough/QA state-script bodies, test both installed copies, and complete bundled-skill package and
  runtime verification; keep Wave 7 order 11 parked until order 10 ships.
- [x] Ship order 10 independently in PR #188 (`b8e4b32c`) and close its member without activating Wave 7 order 11.
- [x] Branch from the order-10 closeout (`459887fa`) and activate only `correct_empty_tz_period_bounds` for the verified
  empty-`TZ` regression.
- [x] Restore explicit empty-`TZ` UTC semantics with deterministic focused, full, integration, and board verification;
  ship PR #189 (`f0afc0c4`) and keep Wave 7 order 11 parked through the closeout.
- [x] Close PR #189 on `main` at `cc03a4e6`, branch from that exact commit, and activate only order 11
  `remove_obsolete_proxy_abstractions`.
- [x] Remove only the reverified proxy types, handlers, and diagnostics after moving useful metrics coverage to a
  reachable failure; complete the order-11 verification while keeping orders 12--35 parked.
- [x] Ship order 11 independently in PR #190 (`ca2f289b`) and close its member without activating order 12.
- [x] Close PR #190 on `main` at `c99be7a3`, branch from that exact commit, and activate only order 12
  `migrate_inert_config_fields`.
- [x] Ship the first-release accept-and-warn transition for the three O049 config fields in PR #191 (`e0be9a60`) while
  keeping orders 13--35 parked.
- [x] Close PR #191 on `main` at `9a334b18`, branch from that exact commit, and activate only order 13
  `migrate_memory_intent_generated_file`.
- [x] Ship the tolerant durable-manifest migration for O049's `MemoryIntent.generated_file` in PR #192 (`b7a8ad9e`)
  while keeping orders 14--35 parked.
- [x] Close PR #192 on `main` at `74b364d2`, branch from that exact commit, and activate only order 14
  `replace_unsafe_index_test_fixtures` after reverifying 180 executable calls across 48 test files.
- [x] Migrate unsafe index test setup through coherent shared builders in PR #193 (`56dfc27b`) while keeping orders
  15--35 parked.
- [x] Close PR #193 on `main` at `0e8e1cbb`, branch from that exact commit, and activate only order 15
  `retire_unsafe_index_mutators` after reverifying the residual direct contracts and stale references.
- [x] Delete only the unsafe public index mutators and their direct contracts while keeping orders 16--35 parked.
- [x] Ship order 15 independently in PR #194 (`ae7519fc`) and close its member without activating order 16.
- [x] Close PR #194 on `main` at `358b39d6`, branch from that exact commit, and activate only order 16
  `replace_legacy_tier_inference` after reverifying the request-tier, cache, and auth-retry paths.
- [x] Replace O051's nonexistent environment inference with explicit or named-default tier provenance while keeping
  orders 17--35 parked.
- [x] Ship order 16 independently in PR #195 (`aca65c7f`) and close its member without activating order 17.
- [x] Close PR #195 on `main` at `2ec0f92d`, branch from that exact commit, and activate only order 17
  `remove_dead_session_context_retry` after reverifying its error and fallback paths.
- [x] Delete only O052's duplicate index retry while keeping orders 18--35 parked.
- [x] Ship order 17 independently in PR #196 (`bc4f3a0c`) and close its member without activating order 18.
- [x] Close PR #196 on `main` at `f2fcc688`, branch from that exact commit, and activate only order 18
  `remove_dead_session_helpers` after reverifying its three bounded internal surfaces.
- [x] Remove only O092's three verified internal session residues while keeping orders 19--35 parked.
- [x] Ship order 18 independently in PR #197 (`86a83a1d`) and close its member without activating order 19.
- [x] Close PR #197 on `main` at `2745e5ed`, branch from that exact commit, and activate only order 19
  `deprecate_supervisor_verdict_wrapper` after correcting its return-type acceptance wording.
- [x] Retain O092's supervisor verdict wrapper for its warning release, emit one caller-attributed deprecation, migrate
  internal consumers, and complete the order-19 verification while keeping orders 20--35 parked.
- [x] Ship order 19 independently in PR #198 (`7fd701b5`) and close its member without activating order 20.
- [x] Close PR #198 on `main` at `93957659`, branch from that exact commit, and activate only order 20
  `wire_transcript_reindex_guard` after correcting its metadata-fingerprint contract.
- [x] Wire O092's metadata guard and complete order-20 verification while keeping orders 21--35 parked.
- [x] Ship order 20 independently in PR #199 (`7b3ac2df`) and close its member without activating order 21.
- [x] Close order 20 on pushed `main` at `5664258b`, branch from that exact commit, and activate only order 21
  `retire_test_only_settings_helpers` after reverifying its three bounded internal surfaces.
- [x] Remove only the three verified settings-helper residues while keeping orders 22--35 parked.
- [x] Complete order 21's focused, full, regression, Docker installer, clean-wheel, pre-commit, design-size, and
  board-integrity gates without a Forge workflow.
- [x] Ship order 21 independently in PR #200 (`63ae0f74`) and close its member without activating order 22.
- [x] Close order 21 on pushed `main` at `78678e18`, branch from that exact commit, and activate only order 22
  `simplify_count_tokens_mode_selector` after reverifying its public selector contract.
- [x] Wire both token-count flags to one named mode while keeping orders 23--35 parked.
- [x] Complete order 22's focused, full, regression, token-smoke, pre-commit, design-size, and board-integrity gates
  without a Forge workflow.
- [x] Ship order 22 independently in PR #201 (`b350b4d5`) and close its member without activating order 23.
- [x] Close order 22 on pushed `main` at `a3dadb18`, branch from that exact commit, and activate only order 23
  `share_codex_thread_index_sync`.
- [x] Extract one adoption-safe Codex thread-to-index writer while keeping orders 24--35 parked.
- [x] Complete order 23's focused, full, regression, targeted Codex integration, pre-commit, design-size, and
  board-integrity gates without a Forge workflow.
- [x] Ship order 23 independently in PR #202 (`d1abccc7`) and close its member without activating order 24.
- [x] Close order 23 on pushed `main` at `6e4038db`, branch from that exact commit, and activate only order 24
  `unify_resume_routing_reference`.
- [x] Route transfer, native, and rewind resume context-limit lookup through one routing-reference helper while keeping
  orders 25--35 parked.
- [x] Complete order 24's focused, full, regression, targeted session integration, pre-commit, design-size, and
  board-integrity gates without a Forge workflow.
- [x] Ship order 24 independently in PR #203 (`0d041b83`) and close its member without activating order 25.
- [x] Close order 24 on pushed `main` at `5eb39d15`, branch from that exact commit, and activate only order 25
  `reuse_claude_usage_measurement`.
- [x] Route the workflow verb aggregate through the shared Claude measurement resolver while keeping orders 26--35
  parked.
- [x] Complete order 25's focused, full, regression, targeted telemetry/cost integration, pre-commit, design-size, and
  board-integrity gates without a Forge workflow.
- [x] Ship order 25 independently in PR #204 (`356ea665`) and close its member without activating order 26.
- [x] Close order 25 on pushed `main` at `83394417`, branch from that exact commit, and activate only order 26
  `centralize_telemetry_jsonl_reads`.
- [x] Share the telemetry JSONL read scaffold while keeping orders 27--35 parked.
- [x] Complete order 26's focused, full, regression, targeted telemetry integration, pre-commit, design-size, and
  board-integrity gates without a Forge workflow.
- [x] Ship order 26 independently in PR #205 (`5c36f25f`) and close its member without activating order 27.
- [x] Close order 26 on pushed `main` at `8787f7e7`, branch from that exact commit, and activate only order 27
  `share_review_worker_preparation` after reverifying the shared preparation and CLI parser seams.
- [x] Share the review worker preparation/parser scaffold while keeping orders 28--35 parked.
- [x] Complete order 27's focused, full, regression, targeted workflow-worker integration, pre-commit, design-size, and
  board-integrity gates without a Forge workflow.
- [x] Ship order 27 independently in PR #206 (`242ded2d`) and close its member without activating order 28.
- [x] Challenge and reproduce order 20's post-merge fingerprint race, close
  [`correct_search_index_fingerprint_race`](../../done/correct_search_index_fingerprint_race/card.md) directly on
  `main`, and preserve the Wave 7 finding/member counts before activating order 28.
- [x] Activate `refactor/unify-claude-session-state-context` from corrected `main` at `52c36e2a` and reverify O058's
  launch/resume/fork plus post-create mutation seams.
- [x] Unify Claude manifest-to-store/worktree derivation while keeping orders 29--35 parked.
- [x] Complete order 28's focused, full, regression, targeted session integration, pre-commit, design-size, and
  board-integrity gates without a Forge workflow.
- [x] Ship order 28 independently in PR #207 (`32c6917b`) and close it without activating order 29.
- [x] Close order 28 on pushed `main` at `7c925880`, branch from that exact commit, and activate only order 29
  `share_transfer_rewind_rendering` after reverifying its shared renderer seam.
- [x] Share only transfer/rewind text, list, and cited-item rendering while keeping orders 30--35 parked.
- [x] Complete order 29's focused, full, regression, targeted rewind integration, pre-commit, design-size, and
  board-integrity gates without a Forge workflow.
- [x] Ship order 29 independently in PR #208 (`ea5b9103`) and close it without activating order 30.
- [x] Close order 29 on pushed `main` at `1d02b0cb`, branch from that exact commit, and activate only order 30
  `share_passthrough_sse_framing` after reverifying its common framing and protocol-specific merge seams.
- [x] Share only incremental SSE data-line framing while keeping orders 31--35 parked.
- [x] Complete order 30's focused, full, regression, targeted streaming integration, pre-commit, design-size, and
  board-integrity gates without a Forge workflow.
- [x] Ship order 30 independently in PR #209 (`a1efd5d7`) and close it without activating order 31.
- [x] Close order 30 on pushed `main` at `54188e61`, branch from that exact commit, and activate only order 31
  `extract_session_fork_preflight` after reverifying the callback, manager, routing, and mutation boundaries.
- [x] Extract and verify order 31's typed read-only preflight while keeping order 32 parked; publication remains on the
  active member.
- [x] Ship order 31 independently in PR #210 (`85c050e2`) and close it without activating order 32.
- [x] Close order 31 on pushed `main` at `1897b547`, branch from that exact commit, and activate only order 32
  `extract_session_fork_execution` after the preflight merge.
- [x] Extract and verify order 32's typed execution/compensation boundary while keeping order 33 parked; publication
  remains on the active member.
- [x] Ship order 32 independently in PR #211 (`e4a62d1b`) and close it without activating order 33.
- [x] Close order 32 on pushed `main` at `b72fab14`, branch from that exact commit, and activate only order 33
  `decompose_extension_install_transaction` after reverifying the phase and test-root seams.
- [x] Decompose and verify order 33's installer apply transaction while keeping orders 34--35 parked.
- [x] Ship order 33 independently in PR #212 (`f1afb30c`) and close it without activating order 34.
- [x] Close order 33 on pushed `main` at `43130c3d`, branch from that exact commit, and activate only order 34
  `extract_statusline_sources` after reverifying the source/import boundary.
- [x] Extract and verify Wave 7 order 34's status-line source/import boundary without activating order 35.
- [x] Ship Wave 7 order 34 independently in PR #213 (`e761d0d1`) and close it without activating order 35.
- [x] Close Wave 7 order 34 on pushed `main` at `7ea1d1de`, branch from that exact commit, and activate only order 35
  `extract_statusline_rendering` after reverifying the render/cache boundary.
- [x] Extract and verify Wave 7 order 35's status-line rendering and cache boundary; publication remains on the active
  member.
- [x] Ship Wave 7 order 35 independently in PR #214 (`4c9dee34`) and close its member.
- [x] Close the bounded Wave 7 epic after synchronizing all 35 members, the review ledger, and terminal verification.

The epic remains in `doing/` after the decision cards close; later execution waves remain outstanding.

- [x] Activate only the bounded `correct_wave8_merged_regressions` follow-up from pushed order-6 closeout `113b5670`.
- [x] Ship and close the corrective follow-up in PR #222 (`02e0ced9`) before advancing Wave 8 sequencing.
- [x] Create `agent/reject-unknown-workflow-policy-keys` from pushed corrective closeout `071cfd92` and activate only
  Wave 8 order 7.
- [ ] Ship Wave 8 order 7 independently in PR #223 and close it before activating order 8.

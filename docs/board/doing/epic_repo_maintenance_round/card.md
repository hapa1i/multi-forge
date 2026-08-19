# Epic: Repository maintenance round

**Epic** -- coordinating card for the cleanup, bug-fix, refactor, and maintenance findings below. Lane: `doing/` --
Waves 1--5 and the bounded Wave 6 correctness-maintenance admission are closed. Wave 5 contains 13 shipped findings; its
closeout audit rejected stale claims D033/O020 and handed 34 still-live correctness rows to Wave 6. Follow-up
verification added D054/D055, and all 36 findings shipped across 13 members in PRs #164--#168 and #170--#177. PR #169
added bounded O012 and retention-status hardening without changing that finding count. Wave 7 is closed at 32 verified
findings across 35 implementation members, all shipped independently in PRs #178--#184, #186--#188, and #190--#214. The
bounded [`correct_search_index_fingerprint_race`](../../done/correct_search_index_fingerprint_race/card.md) correction
closed order 20's post-merge snapshot race directly on `main` after PR #206 and before order 28. The bounded
[`correct_empty_tz_period_bounds`](../../done/correct_empty_tz_period_bounds/card.md) correction shipped in PR #189
before order 11; the earlier
[`correct_post_merge_review_findings`](../../done/correct_post_merge_review_findings/card.md) member shipped five
verified post-merge corrections in PR #185. The user admitted O098 and the verified cap-state subset of O092 as one
bounded, non-overlapping sequencing exception. The bounded
[`correct_fork_transfer_snapshot_rollback`](../../done/correct_fork_transfer_snapshot_rollback/card.md) correction
shipped in PR #215 before Wave 8. The residual gate on merged `main` at `bad273ef` accepted 23 still-live correctness,
security, performance, test-policy, output, and documentation rows as 19 parked members under
[`epic_wave8_residual_maintenance`](../epic_wave8_residual_maintenance/card.md); order 1 shipped in PR #216, order 2 is
active, and the remaining 17 members remain parked.

## Goal

Turn the whole-repository review into independently shippable, verified work without losing provenance, mixing
unresolved design choices into implementation, or destabilizing the healthy invariants the review identified.

The evidence source is [`review_combined.md`](../../review_combined.md), reviewed at commit
`0a03786fc9b333e9890a64bf80436bb09d8606cf`. It began with 144 severity-ranked rows and three unranked design-drift
notes; DG1 admitted U002/U003, and follow-up reviews admitted D045--D056, for a current total of 158 ranked findings
plus unranked U001. The report remains the evidence ledger; this epic owns member coordination, sequencing, and final
disposition.

## Admission Contract

A finding enters implementation only when it has:

- a stable finding ID and verified scope;
- expected behavior grounded in a named authority;
- a reproduction or failing/characterization test appropriate to its risk;
- observable acceptance criteria and a required test tier;
- compatibility and migration implications recorded; and
- every linked decision gate resolved.

Rows marked `(unverified)` are not executable. Dead-code and deletion findings require individual compatibility
characterization; zero production callers alone do not authorize removal. Behavior correction and refactoring should
remain independently reviewable even when one member card coordinates both.

## Initial Members: Decision Gates

| Gate | Card                                                                                    | Findings                   | Unblocks                         |
| ---- | --------------------------------------------------------------------------------------- | -------------------------- | -------------------------------- |
| DG1  | [`stop_verification_contract`](../../done/stop_verification_contract/card.md)           | D006, U002–U003            | Stop/artifact correctness        |
| DG2  | [`missing_worktree_authority`](../../done/missing_worktree_authority/card.md)           | D009                       | Session and durable-state safety |
| DG3  | [`downstream_retention_ownership`](../../done/downstream_retention_ownership/card.md)   | D015                       | Proxy/telemetry retention fixes  |
| DG4  | [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) | O047–O052, O092–O093, O096 | Refactor and deletion work       |

These decisions are separate cards because they govern different authorities, state owners, tests, and downstream waves.
The epic coordinates their completion; it does not collapse them into one implementation unit.

## Approved Decision Set

All four decisions were approved on 2026-08-04. They intentionally contain no production changes.

| Gate | Approved resolution                                                                                                                                                                      |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| DG1  | Keep `completion_promise` and fixed `test_suite`; make the latter the sole opt-in latency exception; delete the documented `custom_command`; validate `block`, `warn`, and `allow`.      |
| DG2  | A valid manifest reserves durable identity; the index publishes it; worktree presence determines launchability only. Missing-worktree sessions remain visible and recoverable/deletable. |
| DG3  | Give the shared downstream directory one global `telemetry.downstream` policy and one pruner; migrate agreeing legacy settings and disable pruning on conflict.                          |
| DG4  | Adopt evidence-based deletion rules; migrate serialized fields; replace unsafe APIs; reject O093 deletion, wire `needs_reindex`, and retain and wire the explicit `--local` selector.    |

Approval creates accepted implementation work; it does not start later waves or authorize merging unrelated cleanup.
Normative design documents move with shipped behavior, not ahead of it.

## Accepted Implementation Members

Wave 1 closed through [`epic_policy_supervision_correctness`](../../done/epic_policy_supervision_correctness/card.md). A
post-close D005 parser defect was corrected by
[`preserve_codex_plus_prefixed_write_identity`](../../done/preserve_codex_plus_prefixed_write_identity/card.md) and
merged in PR #129 (`5813994c`). Wave 2 closed through
[`epic_stop_artifact_correctness`](../../done/epic_stop_artifact_correctness/card.md) after its members shipped in PRs
#130–#132. Wave 3 closed through
[`epic_session_durable_state_safety`](../../done/epic_session_durable_state_safety/card.md) after all eight members
shipped in PRs #134--#138 and #140--#142. Wave 4 closed under
[`epic_installer_transaction_safety`](../../done/epic_installer_transaction_safety/card.md) after its three members
shipped in PRs #144--#146. The bounded Wave 5 HIGH set closed under
[`epic_cli_proxy_runtime_correctness`](../../done/epic_cli_proxy_runtime_correctness/card.md) after all seven members
shipped independently in PRs #148--#154. The first bounded Wave 5 MEDIUM set is sequenced as three members under
[`epic_proxy_diagnostic_data_hygiene`](../../done/epic_proxy_diagnostic_data_hygiene/card.md) and shipped independently
in PRs #157--#159. The next bounded MEDIUM set closed under
[`epic_proxy_conversion_failure_handling`](../../done/epic_proxy_conversion_failure_handling/card.md) after D053 and
O007 shipped independently in PRs #161--#162. The Wave 5 closeout screen on `246aaff1` rejected D033/O020 and accepted
34 live rows into [`epic_wave6_correctness_maintenance`](../../done/epic_wave6_correctness_maintenance/card.md).
Follow-up verification expanded that bounded admission with D054/D055, and all 36 findings shipped across 13 independent
members in PRs #164--#168 and #170--#177. D056 is recorded separately and awaits its own execution gate.

A post-Wave 6 screen on merged `main` at `5777192a` admitted the verified refactor/deletion set under
[`epic_wave7_refactor_and_deletion`](../../done/epic_wave7_refactor_and_deletion/card.md). The child epic split the old
DG4 umbrellas and the fork/installer/status-line structural rows into 35 ordered review boundaries, rejected O062/O063
and O093 as written, and promoted only the verified O067/O095 subsets. All 32 findings shipped across 35 members;
correctness/test-policy/output/docs rows outside that admission remain gated.

The post-Wave 7 residual gate rechecked those excluded rows on `bad273ef`, admitted only the 23 evidence-backed scopes
under [`epic_wave8_residual_maintenance`](../epic_wave8_residual_maintenance/card.md), and initially parked every
member. Order 1 activated from pushed closeout `7a2ad4c1`. D040 remains a proposed inheritance decision; D043/O075 and
D045--D052 are already resolved; O078/O079 are rejected as bugs; and O080/O085/O097 are narrowed to their supported
behavior. O100 was also admitted after the old Wave 7 exclusion list was found to have omitted it.

For that pair, D053 (Wave 6) deliberately sequenced before O007 (Wave 5); the child epic owns this exception to wave
order.

| Wave | Findings            | Member                                                                                                              |
| ---- | ------------------- | ------------------------------------------------------------------------------------------------------------------- |
| 1    | D001                | [`preserve_policy_intent_on_enable`](../../done/preserve_policy_intent_on_enable/card.md)                           |
| 1    | D002–D004, O028     | [`harden_supervisor_verdict_boundary`](../../done/harden_supervisor_verdict_boundary/card.md)                       |
| 1    | D005                | [`preserve_supervisor_edit_identity`](../../done/preserve_supervisor_edit_identity/card.md)                         |
| 1C   | D005                | [`preserve_codex_plus_prefixed_write_identity`](../../done/preserve_codex_plus_prefixed_write_identity/card.md)     |
| 2    | D006, U002–U003     | [`align_stop_verification_contract`](../../done/align_stop_verification_contract/card.md)                           |
| 2    | D007, D024          | [`preserve_transcript_artifact_identity`](../../done/preserve_transcript_artifact_identity/card.md)                 |
| 2    | D039                | [`repair_sidecar_shadow_drain_routing`](../../done/repair_sidecar_shadow_drain_routing/card.md)                     |
| 3    | D011                | [`preserve_unreadable_json_state_classification`](../../done/preserve_unreadable_json_state_classification/card.md) |
| 3    | O006                | [`reject_non_object_manifest_confirmed`](../../done/reject_non_object_manifest_confirmed/card.md)                   |
| 3    | D008                | [`enforce_launch_runtime_override_immutability`](../../done/enforce_launch_runtime_override_immutability/card.md)   |
| 3    | D009                | [`retain_missing_worktree_sessions`](../../done/retain_missing_worktree_sessions/card.md)                           |
| 3    | O003                | [`preserve_headless_codex_concurrent_delete`](../../done/preserve_headless_codex_concurrent_delete/card.md)         |
| 3    | D021                | [`preserve_newer_workqueue_markers`](../../done/preserve_newer_workqueue_markers/card.md)                           |
| 3    | D022                | [`reject_unknown_resume_strategy`](../../done/reject_unknown_resume_strategy/card.md)                               |
| 3    | D010                | [`align_incognito_worktree_guard`](../../done/align_incognito_worktree_guard/card.md)                               |
| 4    | D013–D014           | [`rollback_codex_install_transaction`](../../done/rollback_codex_install_transaction/card.md)                       |
| 4    | D012                | [`preserve_install_settings_baseline`](../../done/preserve_install_settings_baseline/card.md)                       |
| 4    | D019                | [`preserve_legacy_settings_user_edits`](../../done/preserve_legacy_settings_user_edits/card.md)                     |
| 5    | D015                | [`unify_downstream_retention`](../../done/unify_downstream_retention/card.md)                                       |
| 5    | O002                | [`preserve_proxy_ownership_on_stop_failure`](../../done/preserve_proxy_ownership_on_stop_failure/card.md)           |
| 5    | D016                | [`stabilize_proxy_create_smoke_json`](../../done/stabilize_proxy_create_smoke_json/card.md)                         |
| 5    | D017                | [`align_search_corruption_failures`](../../done/align_search_corruption_failures/card.md)                           |
| 5    | O001                | [`forward_litellm_user_agent`](../../done/forward_litellm_user_agent/card.md)                                       |
| 5    | O004                | [`relay_anthropic_response_headers`](../../done/relay_anthropic_response_headers/card.md)                           |
| 5    | D018                | [`make_statusline_sources_segment_lazy`](../../done/make_statusline_sources_segment_lazy/card.md)                   |
| 5M   | O037–O038, O042     | [`remove_proxy_converter_plaintext_logs`](../../done/remove_proxy_converter_plaintext_logs/card.md)                 |
| 5M   | D035                | [`make_tool_events_metadata_only`](../../done/make_tool_events_metadata_only/card.md)                               |
| 5M   | D036                | [`validate_proxy_request_ids`](../../done/validate_proxy_request_ids/card.md)                                       |
| 5M   | O007                | [`fail_non_streaming_response_conversion`](../../done/fail_non_streaming_response_conversion/card.md)               |
| 6    | D053                | [`sanitize_proxy_conversion_failure_logs`](../../done/sanitize_proxy_conversion_failure_logs/card.md)               |
| 6    | 36 correctness rows | [`epic_wave6_correctness_maintenance`](../../done/epic_wave6_correctness_maintenance/card.md)                       |
| 7    | 32 structural rows  | [`epic_wave7_refactor_and_deletion`](../../done/epic_wave7_refactor_and_deletion/card.md)                           |
| 8    | 23 residual rows    | [`epic_wave8_residual_maintenance`](../epic_wave8_residual_maintenance/card.md)                                     |

## Execution Waves

The canonical wave definitions and finding ranges live in
[`review_combined.md` § Backlog Conversion and Sequencing](../../review_combined.md#backlog-conversion-and-sequencing).
The ordering constraint is:

1. resolve DG1–DG4 and reproduce every CRITICAL/HIGH finding on its execution branch;
2. ship policy and supervision correctness;
3. ship Stop/artifact, session/state, installer, and CLI/proxy correctness in dependency order;
4. process bounded MED/LOW maintenance findings;
5. execute the parked Wave 7 sequence only after behavior and compatibility are characterized; and
6. close the rechecked Wave 8 residuals one member at a time without reopening rejected or decision-gated rows.

New member cards must name their finding IDs and wave. Create a child epic only when multiple independently shippable
members share a contract or sequencing decision that would otherwise drift.

## Drift Watch

Preserve these review-proven properties while members ship:

- row-first session creation and in-lock compensation;
- UI-free `core/ops` boundaries;
- strict proxy config-block wiring and exact-set guards;
- `_SAFE_KEYS` redaction and request-mutation tripwires;
- fail-closed binding scans and explicitly differentiated fail-open consumers;
- transcript parsing and cost-accounting provenance; and
- regression characterization before behavior-preserving refactors.

Every member that changes architecture, file/config ownership, CLI contracts, installer behavior, proxy/session
semantics, workflow prerequisites, or Day 1 behavior must update the normative design and end-user docs in the same
execution phase.

## Out of Scope

- Treating every review row as accepted implementation work without triage.
- Implementing unverified findings.
- A bulk dead-code deletion sweep.
- Replacing shipped architecture in design docs before the corresponding code ships.
- Using this epic as a substitute for member-card acceptance criteria and verification.

## Closeout

Move the epic to `done/` only when every live member is done, all accepted findings have a recorded disposition, the
combined review points to the shipped/retired outcomes, verification is recorded, and normative docs are synchronized. A
retired member does not count as shipped; record its rationale and successor on both the member and epic.

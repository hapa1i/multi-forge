# Whole-Repo Review: Execution Ledger

The complete backlog conversion, wave admission, and coordination record from the combined review.

[Combined review overview](../review_combined.md)

---

## Backlog Conversion and Sequencing

Do not create one card per existing table row mechanically. First split compound rows so each accepted card has one
observable behavior change. Keep characterization, behavior correction, and refactoring as separate assertions even when
one card coordinates them.

### Required finding-to-card fields

| Field             | Requirement                                                                                         |
| ----------------- | --------------------------------------------------------------------------------------------------- |
| Finding IDs       | Every card names the exact `D###`, `O###`, or `U###` scope; compound rows name the accepted subset  |
| Expected behavior | Cite the full authority path and section, not an unqualified `§N`                                   |
| Evidence          | Record source inspection plus a minimal reproduction or existing failing test                       |
| Acceptance        | State observable output/state and the required unit, regression, integration, or clean-install test |
| Compatibility     | Identify durable-state, public import, config, CLI JSON, and extension-package implications         |
| Dependencies      | Link any decision gate, epic, prerequisite fix, or design-doc update                                |
| Exclusions        | Preserve adjacent intentional divergence and healthy invariants named in this review                |

### Proposed execution waves

| Wave                                    | Scope                                                                               | Entry condition                                                                 |
| --------------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| 0 — decisions and reproduction          | DG1–DG4; recheck all CRITICAL/HIGH findings on the execution branch                 | Normative contract chosen; reproduction or failing test recorded                |
| 1 — policy and supervision correctness  | D001–D005 plus related parser behavior such as the unknown-verdict subset           | Policy-state preservation and fail-open/citation acceptance criteria agreed     |
| 2 — Stop and artifact correctness       | D006–D007, D024, D039, U002–U003                                                    | DG1 resolved; verification and artifact contracts defined                       |
| 3 — session and durable-state safety    | D008–D011, D021–D022, O003, and O006                                                | State authority, fault outcomes, and recovery paths defined                     |
| 4 — installer transactions              | D012–D014, D019                                                                     | Fault points and rollback ownership enumerated; integration fixtures identified |
| 5 — CLI, proxy, and runtime correctness | D015–D018, O001, O002, O004; D035, D036, O037, O038, O042, O007                     | Closed: all 13 admitted findings shipped and the admission cutoff is recorded   |
| 6 — bounded maintenance fixes           | D045–D053 plus remaining verified MED/LOW bugs, performance issues, and docs drift  | Each row split to one behavior and assigned a test tier                         |
| 7 — refactor and deletion               | Verified duplication, dead code, inert config, and structural findings              | Behavior characterized; DG4 resolved; unverified symbols excluded               |
| 8 — verified residual maintenance       | Rechecked correctness, security, performance, test-policy, output, and docs residue | Closed Wave 7; each residual accepted, rejected, resolved, or decision-gated    |

### Wave 3 admission record

All five HIGH and three MEDIUM Wave 3 rows were rechecked on merged `main` at `dc963a7c`. One disposable pytest module
passed eight assertions of the documented broken behavior and was removed after the evidence was recorded. No
implementation member was activated during admission.

| Order | Findings | Reproduced boundary                                                                  | Accepted member                                                                                                  |
| ----- | -------- | ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| 1     | D011     | generic `read_json` maps read `OSError` to corruption                                | [`preserve_unreadable_json_state_classification`](../done/preserve_unreadable_json_state_classification/card.md) |
| 2     | O006     | explicit-null `confirmed` leaks raw `AttributeError`                                 | [`reject_non_object_manifest_confirmed`](../done/reject_non_object_manifest_confirmed/card.md)                   |
| 3     | D008     | parent `launch` override creates raw/effective runtime disagreement                  | [`enforce_launch_runtime_override_immutability`](../done/enforce_launch_runtime_override_immutability/card.md)   |
| 4     | D009     | list deletes a row that get accepts through its valid manifest                       | [`retain_missing_worktree_sessions`](../done/retain_missing_worktree_sessions/card.md)                           |
| 5     | O003     | headless Codex post-turn update raises and leaves a lock-only directory after delete | [`preserve_headless_codex_concurrent_delete`](../done/preserve_headless_codex_concurrent_delete/card.md)         |
| 6     | D021     | five drains rewrite and move a newer-schema marker to `failed/`                      | [`preserve_newer_workqueue_markers`](../done/preserve_newer_workqueue_markers/card.md)                           |
| 7     | D022     | unknown strategy runs structured but persists the unknown literal                    | [`reject_unknown_resume_strategy`](../done/reject_unknown_resume_strategy/card.md)                               |
| 8     | D010     | incognito worktree creation calls the weaker repository guard                        | [`align_incognito_worktree_guard`](../done/align_incognito_worktree_guard/card.md)                               |

The first five members retain HIGH-severity priority. D011 goes first because its generic exception contract affects the
later workqueue member. O006 pins strict manifest classification before D009 changes manifest/index liveness, and D009
precedes O003 so the concurrent-delete fix can preserve the approved live-versus-absent authority model. The MEDIUM
members follow as separate review boundaries; D021 depends explicitly on D011.

### Wave 4 admission record

All three HIGH and one MEDIUM Wave 4 findings were rechecked on merged `main` at `2461e3fa`. One disposable pytest
module passed four assertions of the broken behavior and was removed after evidence capture. A fifth two-run
characterization corrected D012's stale claim that tracking retained the first backup: sync replaces the tracked path as
well as creating the newer Forge-bearing backup. No implementation member was activated during admission.

| Order | Findings  | Reproduced boundary                                                                | Accepted member                                                                              |
| ----- | --------- | ---------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| 1     | D013–D014 | post-Codex read-back or tracking failure leaves untracked files/config state       | [`rollback_codex_install_transaction`](../done/rollback_codex_install_transaction/card.md)   |
| 2     | D012      | second settings run replaces the baseline; disable restores the Forge-bearing copy | [`preserve_install_settings_baseline`](../done/preserve_install_settings_baseline/card.md)   |
| 3     | D019      | legacy scalar/env removal deletes values changed after installation                | [`preserve_legacy_settings_user_edits`](../done/preserve_legacy_settings_user_edits/card.md) |

D013 and D014 share one rollback transaction: the same pre-mutation Codex snapshot must cover a post-write read-back
failure and the later manifest commit, so they form one member rather than two partial rollback implementations. It goes
first because a failed fresh enable otherwise leaves surfaces with no ownership row. D012 follows as the remaining
HIGH-severity baseline invariant; D019's bounded no-sidecar compatibility path ships last.

### Wave 5 admission record

The seven remaining HIGH Wave 5 findings were rechecked on merged `main` at `3f3a3c6d`. One disposable pytest module
passed seven assertions of the broken behavior and was removed after evidence capture. O003 is absent from this set
because its headless Codex concurrent-delete fix shipped in Wave 3. The current evidence supports every remaining HIGH
classification; no implementation member was activated during admission.

| Order | Finding | Reproduced boundary                                                          | Accepted member                                                                                        |
| ----- | ------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| 1     | D015    | two policies prune one downstream shard; the stricter second pass deletes it | [`unify_downstream_retention`](../done/unify_downstream_retention/card.md)                             |
| 2     | O002    | stop error exits 0; delete drops ownership and reports success               | [`preserve_proxy_ownership_on_stop_failure`](../done/preserve_proxy_ownership_on_stop_failure/card.md) |
| 3     | D016    | failed create smoke emits two JSON documents and exits 0                     | [`stabilize_proxy_create_smoke_json`](../done/stabilize_proxy_create_smoke_json/card.md)               |
| 4     | D017    | corrupt query/status disagree across human and JSON exit status              | [`align_search_corruption_failures`](../done/align_search_corruption_failures/card.md)                 |
| 5     | O001    | translated LiteLLM detector value cannot enter the User-Agent gate           | [`forward_litellm_user_agent`](../done/forward_litellm_user_agent/card.md)                             |
| 6     | O004    | Anthropic 429 loses upstream retry and rate-limit response headers           | [`relay_anthropic_response_headers`](../done/relay_anthropic_response_headers/card.md)                 |
| 7     | D018    | a path/branch-only status line still runs proxy and session discovery        | [`make_statusline_sources_segment_lazy`](../done/make_statusline_sources_segment_lazy/card.md)         |

D015 goes first because its duplicate startup passes can destroy shared telemetry under a policy the operator did not
choose, and DG3 already defines its config/migration contract. O002 follows because failed process teardown currently
discards or misreports ownership. D016 and D017 then align machine-readable failure semantics; O001 and O004 are
independent request/response metadata boundaries. D018 ships last so its segment dependency declaration can preserve the
default status line while eliminating unrelated hot-path I/O.

### Wave 5 MEDIUM proxy-hygiene admission record

D035, D036, O037, O038, and O042 were rechecked on merged `main` at `c9c4bc2e`. One disposable pytest module passed six
broken-behavior characterizations; one also confirmed the current `0600` shard mode. The module was removed after
evidence capture. The recheck narrowed D035: global log cleanup discovers the plane, but free-form full caller payloads,
missing directory hardening, and the ordinary client-failure WARNING remain. No implementation member was activated
during admission.

| Order | Findings         | Reproduced boundary                                                            | Accepted member                                                                                  |
| ----- | ---------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| 1     | O037, O038, O042 | converter logs request/schema/tool payloads and formats suppressed DEBUG dumps | [`remove_proxy_converter_plaintext_logs`](../done/remove_proxy_converter_plaintext_logs/card.md) |
| 2     | D035             | tool-event details and the client-failure WARNING retain caller plaintext      | [`make_tool_events_metadata_only`](../done/make_tool_events_metadata_only/card.md)               |
| 3     | D036             | invalid client request ID reaches state, logs, and response header verbatim    | [`validate_proxy_request_ids`](../done/validate_proxy_request_ids/card.md)                       |

The three members share a metadata-only diagnostic contract but remain independent review boundaries. Converter logging
goes first because the same payload dumps cause both the confidentiality and eager-formatting findings. D035 then makes
the structured tool-event schema and adjacent warning metadata-only while preserving the explicit `tool_failures` plane.
D036 follows separately because its compatibility contract preserves conventional client correlation tokens and mints a
Forge ID only for malformed or overlong input. Remaining MEDIUM rows are not admitted by this bounded record.

### Wave 5/6 MEDIUM proxy-conversion admission record

O007 and D053 were rechecked on merged `main` at `de02b09b`. One disposable pytest module passed four broken-behavior
characterizations and was removed after evidence capture. The recheck confirmed two independent boundaries at the same
converter seam: provider exception rendering reaches ordinary logs, while non-streaming conversion failure is returned
and accounted as success. No implementation member was activated during admission.

| Order | Finding | Reproduced boundary                                                                  | Accepted member                                                                                    |
| ----- | ------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------- |
| 1     | D053    | non-streaming and streaming conversion ERRORs render provider canaries and traceback | [`sanitize_proxy_conversion_failure_logs`](../done/sanitize_proxy_conversion_failure_logs/card.md) |
| 2     | O007    | invalid non-streaming response returns HTTP 200 and records `failed=false`           | [`fail_non_streaming_response_conversion`](../done/fail_non_streaming_response_conversion/card.md) |

D053 goes first as a log-only correction that establishes safe failure metadata without changing wire behavior. O007
then changes the non-streaming client/accounting contract on its own review boundary, retaining observed provider usage
while reporting a stable HTTP failure. Remaining MEDIUM rows are not admitted by this bounded record.

### Wave 5 closure audit and Wave 6 handoff

The remaining MEDIUM rows were never implicitly part of Wave 5: each bounded admission above excludes them, and the
canonical wave table assigns unadmitted verified MED/LOW bugs to Wave 6. To remove the open-ended phrase "accepted MED
correctness rows," the 36 unresolved rows whose descriptions still touched CLI, proxy, or launch/runtime correctness
were source-rechecked on `main` at `246aaff1`.

Two claims are rejected as stale or unsupported by current behavior:

| Finding | Closeout evidence                                                                                                                                                    | Disposition |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- |
| D033    | `%cancel-verification` catches effective-intent failure, verifies raw intent, and persists the bypass; a malformed unrelated override passes the retained guard test | rejected    |
| O020    | model-call rows start from every event-backed command and add downstream-only records; a mixed direct/proxy/downstream control retains and sums all three            | rejected    |

The controls live in `tests/regression/test_bug_d033_cancel_verification_escape_hatch.py` and
`tests/regression/test_bug_o020_model_pane_cost_union.py`. D033's claimed escape-hatch failure does not occur because
the caller catches the non-strict conversion error and falls back to raw intent. O020 must not be implemented from the
old row.

At admission, current source still contained the cited boundary for the other 34 rows. All were accepted as Wave 6 work.
Follow-up verification expanded the bounded admission with D054/D055. All 36 findings across 13 members have since
shipped independently; O036 closed the set in PR #177 (`3026b14a`):

| Findings                         | Wave 6 member                                                                                            |
| -------------------------------- | -------------------------------------------------------------------------------------------------------- |
| D020                             | [`strip_direct_child_forge_headers`](../done/strip_direct_child_forge_headers/card.md)                   |
| D023, D028, O022                 | [`align_transfer_preflight_and_cli_contract`](../done/align_transfer_preflight_and_cli_contract/card.md) |
| D027, O012                       | [`harden_detached_process_teardown`](../done/harden_detached_process_teardown/card.md)                   |
| O014, O026                       | [`close_proxy_failure_lifecycles`](../done/close_proxy_failure_lifecycles/card.md)                       |
| D029, O025                       | [`complete_proxy_instance_config_wiring`](../done/complete_proxy_instance_config_wiring/card.md)         |
| D030, O008, O015, O035           | [`restore_proxy_request_semantics`](../done/restore_proxy_request_semantics/card.md)                     |
| D054, D055                       | [`harden_proxy_boundary_failures`](../done/harden_proxy_boundary_failures/card.md)                       |
| O013, O034                       | [`align_policy_routing_context`](../done/align_policy_routing_context/card.md)                           |
| D031                             | [`exclude_interactive_usage_cost`](../done/exclude_interactive_usage_cost/card.md)                       |
| D032, D041, O005, O031--O033     | [`align_cli_failure_surfaces`](../done/align_cli_failure_surfaces/card.md)                               |
| D034, D037, D038, O027           | [`harden_command_state_boundaries`](../done/harden_command_state_boundaries/card.md)                     |
| O011, O017, O021, O023, O029--30 | [`preserve_session_launch_preconditions`](../done/preserve_session_launch_preconditions/card.md)         |
| O036                             | [`harden_walkthrough_sandbox_provenance`](../done/harden_walkthrough_sandbox_provenance/card.md)         |

Post-merge review on 2026-08-14 verified five follow-up defects in PRs #170, #172, #176, #177, and #180. They are new
edge cases in the shipped implementations rather than original findings left unresolved: filtered required/named tool
selection, positional shadow recovery guidance, rollback-deletion failure visibility, post-source walkthrough-root
reassignment, and non-IANA process `TZ` forms. The original finding counts and dispositions remain closed; the bounded
corrections shipped in PR #185 (`8ccbf387`) through
[`correct_post_merge_review_findings`](../done/correct_post_merge_review_findings/card.md).

This handoff closed Wave 5 at 13/13 admitted findings. Its bounded Wave 6 child epic is now closed at 36/36 findings
across 13/13 members. Neither admission claims D056 or policy-internal, durable-state-only, performance, docs,
duplication, dead-code, structural, or explicitly unverified rows outside its screen.

### Wave 7 refactor and deletion admission record

The structural/deletion candidates were rechecked after Wave 6 on merged `main` at `5777192a`. The screen covered
O043--O073 and O092--O099 as candidate rows, then checked the remaining live ledger for structurally misclassified work.
It initially admitted 31 verified finding rows as 34 parked implementation members under
[`epic_wave7_refactor_and_deletion`](../done/epic_wave7_refactor_and_deletion/card.md). No implementation branch or
member was activated. After order 6, a repository-wide residue audit verified O098 and the `caps.py` non-dict branch
from O092; the user admitted that bounded subset as one new member, bringing the current graph to 32 findings and 35
members.

The admission corrects the original report rather than treating it as a command:

| Finding scope | Admission result                                                                                                                                                                                                                          |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| O062          | Rejected. The current result types have different lifecycle/consumer contracts; a common base would add coupling.                                                                                                                         |
| O063          | Rejected. Only the tiny write/update shape matches; registry read, error, version, and stale-process semantics differ.                                                                                                                    |
| O067          | Verified and admitted. Incremental SSE framing is still identical; transport-owned merge behavior stays separate.                                                                                                                         |
| O093          | Rejected as deletion/simplification. Explicit-backend mapping is consumed and test-pinned; its completed investigation card is retired, not shipped.                                                                                      |
| O095          | Narrowed and admitted only for worker parsing and optional JSON metadata. Repeated Click option declarations remain local.                                                                                                                |
| O092          | Split by symbol/compatibility owner. The cap-state branch is admitted; the curation session-name merge is recorded but not admitted; converter and unnamed candidates remain excluded; warning windows still block same-release deletion. |
| O098          | Verified and admitted with the adjacent zero-caller session summary helper after import, patch-target, entry-point, documentation, resource, and history checks found no compatibility consumer.                                          |
| O068--O070    | Split at existing preflight/execution, install path/transaction, and status source/render seams; no card authorizes a monolithic rewrite.                                                                                                 |

Fresh-process import timing confirmed O043's heavyweight edge (about 317 ms cumulative for `forge.core.lanes` versus 20
ms for `forge.core.runtime_vocab`). Focused characterization passed 58 tests: 23 cover fresh-config and explicit-backend
model mapping plus split-chunk/garbage handling in both SSE accumulators, while 35 cover lane vocabulary and both review
worker parsers. No Forge workflow command or external model call was used.

The Wave 7 admission explicitly did **not** absorb remaining correctness work. D040, D042--D052, D056, O045--O046, O072,
O074--O091, and O097 retained separate verification/entry gates at that point; the later Wave 8 record below disposes
them. O099's transcript-selector subset was already closed by D007/D024. O098 and only the verified cap-state branch
moved through a bounded Wave 7 exception; converter/Gemini residue, release-gated deletions, and the unnamed tail remain
outside. Those exclusions made Wave 7 an executable refactor/deletion sequence rather than a synonym for “everything
left.”

Post-merge review on 2026-08-18 verified one correctness edge in order 20: incremental and bulk indexing could record a
newer live transcript fingerprint than the snapshot written to the search stores. This is not a new structural finding
or member-count change; the bounded
[`correct_search_index_fingerprint_race`](../done/correct_search_index_fingerprint_race/card.md) correction shipped
directly on `main` after PR #206 and before order 28.

### Wave 8 verified residual admission record

The correctness/security/performance/test-policy/output/documentation residue excluded from Wave 7 was rechecked on
merged `main` at `bad273ef0d1485d50f0fdb2db1842f6b9830c0e6`. The screen covered D040, D042--D052, D056, O045--O046,
O072, O074--O091, O097, and the omitted conformance row O100. It admitted 23 finding rows as 19 parked members under
[`epic_wave8_residual_maintenance`](../done/epic_wave8_residual_maintenance/card.md); no implementation branch or member
was activated by the admission itself. All 19 later shipped through PRs #216--#230.

The gate corrected stale and overbroad claims before admission:

| Scope      | Disposition                                                                                                                                                                          |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| D043, O075 | Resolved on current `main`; the nonexistent status component is gone and PR #158 made the client tool-failure warning metadata-only.                                                 |
| D045--D052 | Already shipped through their Wave 2/3/5 members; the old Wave 7 exclusion was historical, not live work.                                                                            |
| D040       | Real asymmetry, not executable: memory explicitly inherits effective activation, but generic override propagation across fork/resume/relaunch has no chosen contract. Kept proposed. |
| O078       | Rejected as a bug: shipped docs and tests define `config reset` as top-level-only. Dotted reset would be a feature.                                                                  |
| O079       | Rejected as a bug: status inventories the log root while clean intentionally acts only on recognized log files; no authority promises set equality.                                  |
| O080       | Narrowed to enabling actions (`on`, `cascade on`) that lack their required config; idempotent disabling/removal remains successful.                                                  |
| O085       | Narrowed to native-relocate deletion, the only path that performs two global manifest scans.                                                                                         |
| O097       | Narrowed to verified non-zero workflow/extension/policy failures split across stdout/stderr; cosmetic wording, successful paths, and public JSON-key changes remain excluded.        |
| O100       | Recounted at 13 current unexplained suppressions rather than the stale 14-site description.                                                                                          |

Rich JSON corruption for O086 was reproduced directly: a whitespace-rich JSON string beyond the fixed 200-column console
width was hard-wrapped and failed `json.loads`. O083's reported typo behavior was also source-checked at the original
`dacite.from_dict` call; contrary to the old annotation, that call is non-strict. The remaining admitted LOW rows have
direct single-boundary controls named on their cards. No Forge workflow or external model call was used.

| Order | Findings       | Accepted member                                                                                      |
| ----- | -------------- | ---------------------------------------------------------------------------------------------------- |
| 1     | O045           | [`trace_failed_provider_attempts`](../done/trace_failed_provider_attempts/card.md)                   |
| 2     | O046           | [`offload_proxy_accounting_persistence`](../done/offload_proxy_accounting_persistence/card.md)       |
| 3     | O074           | [`strip_openai_account_response_headers`](../done/strip_openai_account_response_headers/card.md)     |
| 4     | O089/O090      | [`harden_worktree_config_copy_safety`](../done/harden_worktree_config_copy_safety/card.md)           |
| 5     | D056/O097      | [`unify_cli_failure_diagnostics`](../done/unify_cli_failure_diagnostics/card.md)                     |
| 6     | O072           | [`eliminate_runtime_test_skips`](../done/eliminate_runtime_test_skips/card.md)                       |
| 7     | O083           | [`reject_unknown_workflow_policy_keys`](../done/reject_unknown_workflow_policy_keys/card.md)         |
| 8     | O087           | [`preserve_assistant_block_boundaries`](../done/preserve_assistant_block_boundaries/card.md)         |
| 9     | O088           | [`report_active_registry_cleanup_failures`](../done/report_active_registry_cleanup_failures/card.md) |
| 10    | O091           | [`serialize_llm_client_initialization`](../done/serialize_llm_client_initialization/card.md)         |
| 11    | O084           | [`fix_cost_breakdown_selectors`](../done/fix_cost_breakdown_selectors/card.md)                       |
| 12    | O086           | [`stabilize_proxy_metrics_json`](../done/stabilize_proxy_metrics_json/card.md)                       |
| 13    | O080           | [`align_supervisor_missing_config_exits`](../done/align_supervisor_missing_config_exits/card.md)     |
| 14    | O077           | [`reject_ambiguous_policy_check_input`](../done/reject_ambiguous_policy_check_input/card.md)         |
| 15    | O076           | [`validate_proxy_audit_limits`](../done/validate_proxy_audit_limits/card.md)                         |
| 16    | O081           | [`log_forge_info_probe_degradation`](../done/log_forge_info_probe_degradation/card.md)               |
| 17    | O085           | [`reuse_transcript_reference_scan`](../done/reuse_transcript_reference_scan/card.md)                 |
| 18    | O100           | [`explain_type_suppressions`](../done/explain_type_suppressions/card.md)                             |
| 19    | D042/D044/O082 | [`sync_residual_runtime_documentation`](../done/sync_residual_runtime_documentation/card.md)         |

The policy-check vocabulary follow-up joins Batch 3 without finding credit; the Stop-excerpt follow-up shipped in Batch
1 without credit. Members retain separate implementation, acceptance, and closeout boundaries within a shared review.
Provider tracing precedes accounting offload; both precede the cost view that reads their evidence.

### Coordination boundaries

The linked cards retain acceptance, verification, and closeout detail; this table is only the ownership index.

| Boundary                                                                                                                                                                                                                            | Status                                                                                               |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| [Policy/supervision](../done/epic_policy_supervision_correctness/card.md)                                                                                                                                                           | Closed; D001--D005, O028, and later O044 shipped.                                                    |
| [Stop/artifact](../done/epic_stop_artifact_correctness/card.md)                                                                                                                                                                     | Closed; DG1 and its verification/artifact work shipped.                                              |
| [Durable-state/session](../done/epic_session_durable_state_safety/card.md) and [installer](../done/epic_installer_transaction_safety/card.md)                                                                                       | Closed; Wave 3 shipped.                                                                              |
| [CLI/proxy/runtime](../done/epic_cli_proxy_runtime_correctness/card.md), [diagnostic hygiene](../done/epic_proxy_diagnostic_data_hygiene/card.md), and [conversion failure](../done/epic_proxy_conversion_failure_handling/card.md) | Closed; Wave 5 shipped.                                                                              |
| [Wave 6 correctness](../done/epic_wave6_correctness_maintenance/card.md)                                                                                                                                                            | Closed at 36 verified findings across 13 members; D033/O020 rejected.                                |
| [Wave 7 refactor/deletion](../done/epic_wave7_refactor_and_deletion/card.md)                                                                                                                                                        | Closed at 32 findings across 35 members; bounded post-merge corrections did not change those counts. |
| [Wave 8 residual maintenance](../done/epic_wave8_residual_maintenance/card.md)                                                                                                                                                      | Closed at 23 findings across 19 members after Batch 5 shipped in PR #230.                            |

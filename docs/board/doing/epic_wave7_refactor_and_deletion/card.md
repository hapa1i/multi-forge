# Epic: Wave 7 refactor and deletion

**Parent epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md).

**Lane**: `doing/` -- coordination is active on `refactor/decouple-lane-runtime-vocabulary`; only order 1 is active and
the other 33 members remain parked.

## Goal

Remove verified accidental complexity from the merged post-Wave 6 codebase without turning the review ledger into a bulk
cleanup mandate. Every member preserves current behavior unless its card names an approved compatibility transition, and
every deletion follows the [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md).

## Admission Record

The structural/deletion screen was repeated on merged `main` at `5777192a4f9bef64b042d57eb2bcd82432853250` after Wave 6
closed. It covered O043--O073 and O092--O099 as candidates, then checked the rest of the residual ledger for
misclassified structural work before separating non-Wave-7 categories. Thirty-one verified finding rows are represented
by 34 members: cards combine findings only at one shared seam, while O049, O050, O068, O069, O070, and O092 split at
independent compatibility or review boundaries.

Current-source checks changed the original ledger in five material ways:

- O062 is rejected: `SessionResult` and `HeadlessResult` now have different cancellation, duration, label, runtime-ID,
  and construction contracts, and the one real conversion is intentionally explicit.
- O063 is rejected: the two nine-line registry write/update cycles are similar, but their read/version/error and stale
  process semantics differ; a generic registry base would add coupling without removing a defect or invariant.
- O067 is promoted from unverified: both accumulators still contain the same tolerant SSE data-line framing loop while
  their `_merge` methods intentionally differ.
- O093's deletion premise is rejected. Explicit-backend requests consume `map_model_name`, and mapping/pass-through
  tests remain live; the investigation card is retired as a retained behavior, not counted as shipped work.
- O095 is narrowed to the verified worker-spec parser and optional JSON-metadata tails. Click option declarations stay
  local because visual duplication alone does not justify hiding command shape behind decorator machinery.

The lane import recheck measured approximately 317 ms cumulative import time versus 20 ms for `runtime_vocab` in fresh
Python processes, confirming O043's heavyweight edge. Focused characterization passed 58 tests: 23 cover
fresh-config/explicit-backend mapping and both split-chunk SSE accumulators, while 35 cover lane vocabulary and both
review worker parsers. No Forge workflow command was used for this admission.

## Members and Sequence

Only one member should be active at a time unless the parent explicitly records a non-overlapping exception. The opening
members establish or clean low-level boundaries; compatibility transitions precede deletion; structural decomposition
runs last so it lands on the smallest stable surface.

| Order | Findings         | Member                                                                                                  | Review boundary                                      |
| ----- | ---------------- | ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| 1     | O043             | [`decouple_lane_runtime_vocabulary`](../decouple_lane_runtime_vocabulary/card.md)                       | import-only runtime vocabulary                       |
| 2     | O044             | [`share_policy_activation_rules`](../../todo/share_policy_activation_rules/card.md)                     | shared validation, distinct state owners             |
| 3     | O060, O061, O094 | [`centralize_time_parsing_and_periods`](../../todo/centralize_time_parsing_and_periods/card.md)         | timestamp/period primitives with explicit styles     |
| 4     | O066, O092       | [`unify_git_root_discovery`](../../todo/unify_git_root_discovery/card.md)                               | optional vs strict git-root contracts                |
| 5     | O065, O069       | [`centralize_install_path_authority`](../../todo/centralize_install_path_authority/card.md)             | lower-layer path and ownership policy                |
| 6     | O064             | [`centralize_cli_metric_formatting`](../../todo/centralize_cli_metric_formatting/card.md)               | named token/currency presentation policies           |
| 7     | O071             | [`remove_stale_dependencies`](../../todo/remove_stale_dependencies/card.md)                             | package metadata and clean-wheel proof               |
| 8     | O099 subset      | [`share_proxy_transport_test_fakes`](../../todo/share_proxy_transport_test_fakes/card.md)               | instance-safe proxy transport fixtures               |
| 9     | O073             | [`lock_walkthrough_state_parity`](../../todo/lock_walkthrough_state_parity/card.md)                     | self-contained skill copies with drift guards        |
| 10    | O047, O048, O092 | [`remove_obsolete_proxy_abstractions`](../../todo/remove_obsolete_proxy_abstractions/card.md)           | unreachable proxy types and factory diagnostics      |
| 11    | O049 config      | [`migrate_inert_config_fields`](../../todo/migrate_inert_config_fields/card.md)                         | first-release config deprecation only                |
| 12    | O049 manifest    | [`migrate_memory_intent_generated_file`](../../todo/migrate_memory_intent_generated_file/card.md)       | tolerant durable-manifest migration                  |
| 13    | O050 fixtures    | [`replace_unsafe_index_test_fixtures`](../../todo/replace_unsafe_index_test_fixtures/card.md)           | transaction-safe test state construction             |
| 14    | O050 API         | [`retire_unsafe_index_mutators`](../../todo/retire_unsafe_index_mutators/card.md)                       | zero-caller unsafe public mutators                   |
| 15    | O051             | [`replace_legacy_tier_inference`](../../todo/replace_legacy_tier_inference/card.md)                     | explicit tier/cache/auth-retry provenance            |
| 16    | O052             | [`remove_dead_session_context_retry`](../../todo/remove_dead_session_context_retry/card.md)             | session-context error classification                 |
| 17    | O092 session     | [`remove_dead_session_helpers`](../../todo/remove_dead_session_helpers/card.md)                         | verified internal session-only zero-callers          |
| 18    | O092 policy      | [`deprecate_supervisor_verdict_wrapper`](../../todo/deprecate_supervisor_verdict_wrapper/card.md)       | one-release re-export deprecation                    |
| 19    | O092 search      | [`wire_transcript_reindex_guard`](../../todo/wire_transcript_reindex_guard/card.md)                     | unchanged-snapshot index avoidance                   |
| 20    | O092, O096       | [`retire_test_only_settings_helpers`](../../todo/retire_test_only_settings_helpers/card.md)             | live settings merge/rollback coverage                |
| 21    | O092 script      | [`simplify_count_tokens_mode_selector`](../../todo/simplify_count_tokens_mode_selector/card.md)         | explicit local/provider selector                     |
| 22    | O053             | [`share_codex_thread_index_sync`](../../todo/share_codex_thread_index_sync/card.md)                     | one adoption-safe durable index writer               |
| 23    | O054             | [`unify_resume_routing_reference`](../../todo/unify_resume_routing_reference/card.md)                   | proxy-ID/template resume reference                   |
| 24    | O055             | [`reuse_claude_usage_measurement`](../../todo/reuse_claude_usage_measurement/card.md)                   | one proxied usage precedence rule                    |
| 25    | O056             | [`centralize_telemetry_jsonl_reads`](../../todo/centralize_telemetry_jsonl_reads/card.md)               | tolerant per-plane JSONL read scaffold               |
| 26    | O057, O095       | [`share_review_worker_preparation`](../../todo/share_review_worker_preparation/card.md)                 | review resource/worker input preparation             |
| 27    | O058             | [`unify_claude_session_state_context`](../../todo/unify_claude_session_state_context/card.md)           | manifest-to-store/worktree derivation                |
| 28    | O059             | [`share_transfer_rewind_rendering`](../../todo/share_transfer_rewind_rendering/card.md)                 | shared rendering primitives, distinct envelopes      |
| 29    | O067             | [`share_passthrough_sse_framing`](../../todo/share_passthrough_sse_framing/card.md)                     | common SSE framing, transport-specific merge         |
| 30    | O068             | [`extract_session_fork_preflight`](../../todo/extract_session_fork_preflight/card.md)                   | UI-free pre-mutation validation                      |
| 31    | O068, O096       | [`extract_session_fork_execution`](../../todo/extract_session_fork_execution/card.md)                   | mutation/rollback plan and thin Click adapter        |
| 32    | O069             | [`decompose_extension_install_transaction`](../../todo/decompose_extension_install_transaction/card.md) | ordered install fault and rollback phases            |
| 33    | O070             | [`extract_statusline_sources`](../../todo/extract_statusline_sources/card.md)                           | source facts and import direction                    |
| 34    | O070, O092       | [`extract_statusline_rendering`](../../todo/extract_statusline_rendering/card.md)                       | pure render/layout tail and process-local cache exit |

## Dependencies and Activation Rules

- Order 12 follows the related config transition for coordination but remains an independent durable-state migration.
  Order 14 depends on order 13: safe fixture migration is a real compatibility phase, not a checklist step to collapse
  into public-API deletion.
- Order 25 uses the timestamp contract from order 3; order 32 uses the path authority from order 5; order 34 follows
  orders 6 and 33; fork execution follows fork preflight.
- Before moving a member to `doing/`, re-run its named source/caller checks on the execution base, retain or add the
  characterization listed on the card, create the member checklist, and record the branch/base in this epic.
- Config and re-export deprecations do not authorize deletion in the first release carrying their warning (planning
  baseline: version 0.9.4). A later release must open a new card after the promised compatibility window.
- Architecture/file-ownership changes update `docs/design.md` or `docs/design_appendix.md` only when the production
  change ships. Bundled-skill, dependency, and installer members require build/clean-install verification.

## Shared Constraints

- Preserve row-first session creation, lock-local compensation, binding uniqueness, and strict durable-state reads.
- Keep `core/ops` UI-free. Click rendering, prompts, and exits remain in `cli/` adapters.
- Preserve policy's distinct owners: terminal commands write intent; `%policy` commands write session overrides.
- Preserve provider request/wire shapes, model mapping, telemetry schemas, and per-plane newer-schema behavior.
- Preserve status-line exit-0/fail-open behavior and byte-level default rendering unless a member explicitly changes a
  documented presentation policy.
- Preserve installer preflight-before-mutation, ownership boundaries, tracked baselines, Codex rollback, and
  runtime-scoped disable behavior at every extraction step.
- Do not invent a common result base for O062, a generic registry base for O063, or an option-decorator abstraction for
  O095. Those rejected scopes re-enter only through a new evidence-backed proposal.

## Separately Gated and Excluded Work

- D040, D042--D052, D056, O045--O046, O072, O074--O091, O097, and O098 are correctness, security, performance,
  test-policy, output, or documentation work under separate Wave 6 entry gates as applicable; they are not prerequisites
  that Wave 7 may absorb silently.
- O092's defensive cap-state branch, converter `system_prompt`/Gemini candidates, and approximately 20 unnamed symbols
  remain unverified and excluded.
- O095's repeated Click option blocks remain local; O099's transcript-selector subset already shipped with D007/D024.
- O093 is retained and its former investigation card is a retired reference. No Wave 7 member may delete or bypass
  explicit-backend model mapping.

## Closeout

This epic closes only after all 34 live members ship or receive an explicit terminal disposition, the review ledger and
parent links are synchronized, design/end-user docs describe shipped ownership, and every required integration, package,
and board-integrity check is recorded. Retired cards are not shipped-member credit.

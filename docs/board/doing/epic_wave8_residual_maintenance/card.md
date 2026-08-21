# Epic: Wave 8 verified residual maintenance

**Parent epic**: [`epic_repo_maintenance_round`](../epic_repo_maintenance_round/card.md).

**Lane**: `doing/` -- orders 1--17 shipped in PRs #216--#228; Batch 5 orders 18--19 are under review in draft PR #230.
The corrective and external follow-ups retain their recorded PRs.

**Current execution**: Batch 5 is under review in draft PR #230 from `agent/wave8-batch-5`, based on pushed correction
closeout `1e0e664c`. Its fixed order is order 18 [`explain_type_suppressions`](../explain_type_suppressions/card.md),
then order 19 [`sync_residual_runtime_documentation`](../sync_residual_runtime_documentation/card.md); each retains its
own checklist and commit boundary. Combined verification and publication evidence are recorded in the epic checklist.

**Admission baseline**: merged `main` at `bad273ef0d1485d50f0fdb2db1842f6b9830c0e6` on 2026-08-19.

**Findings**: 23 verified rows across 19 independently shippable members: D042, D044, D056, O045, O046, O072, O074,
O076, O077, O080--O091 except the resolved/rejected O075/O078/O079 rows, plus the verified O097 subset and O100.

## Goal

Close the evidence-backed correctness, security, performance, test-policy, output, and documentation residue left
outside Wave 7 without treating the original review ledger as an implementation mandate.

## Admission Result

The residual gate rechecked current source, tests, shipped docs, board ownership, and the relevant compatibility rules.
It corrected the original report before creating members:

- D043 and O075 are already resolved on current `main`; D045--D052 already shipped through earlier Wave 6 members.
- D040 is real asymmetry but not executable yet: memory has an explicit effective-state inheritance contract while no
  authority says every live override should propagate to fork/resume children. Its decision remains in
  [`decide_derived_session_override_inheritance`](../../proposed/decide_derived_session_override_inheritance/card.md).
- O078 is rejected as a bug because `config reset` is explicitly documented as top-level-only; dotted reset is a new
  feature, not missing conformance.
- O079 is rejected as written: `logs show` inventories files under the log root while `logs clean` deliberately removes
  only recognized log extensions. No contract promises those sets are identical.
- O080 is admitted only for `supervisor on` and `cascade on`, which require an existing supervisor yet currently warn
  and exit zero. Idempotent `off`, `remove`, and `cascade off` behavior stays unchanged.
- O085 is narrowed to the native-relocate delete path, the only path that performs the second global manifest scan.
- O097 is admitted only for proven non-zero failure paths whose header, details, and recovery split across stdout and
  stderr. Cosmetic wording, raw successful paths, and public JSON-key changes remain excluded.
- O100 now covers 13 current suppressions without reasons, not the stale original count of 14.

The Rich JSON defect in O086 was reproduced in a fresh in-process control: a value containing spaces beyond column 200
was hard-wrapped and `json.loads` raised `JSONDecodeError`. The other admitted LOW rows are directly observable at
single source boundaries; each card names the fail-first regression required before correction. No Forge workflow or
external model call was used.

## Members and Sequence

The member order remains the finding-provenance sequence. Remaining execution uses the epic-authorized batches below,
with only one batch active at a time. Every card remains a separate implementation unit with its own checklist, commit
boundary, acceptance evidence, and closeout record.

| Order | Findings       | Member                                                                                                  | Review boundary                         |
| ----- | -------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| 1     | O045           | [`trace_failed_provider_attempts`](../../done/trace_failed_provider_attempts/card.md)                   | failed provider-attempt trace lifecycle |
| 2     | O046           | [`offload_proxy_accounting_persistence`](../../done/offload_proxy_accounting_persistence/card.md)       | event-loop vs durable accounting I/O    |
| 3     | O074           | [`strip_openai_account_response_headers`](../../done/strip_openai_account_response_headers/card.md)     | upstream account metadata relay         |
| 4     | O089, O090     | [`harden_worktree_config_copy_safety`](../../done/harden_worktree_config_copy_safety/card.md)           | per-file copy/cleanup ownership         |
| 5     | D056, O097     | [`unify_cli_failure_diagnostics`](../../done/unify_cli_failure_diagnostics/card.md)                     | one diagnostic, one stderr stream       |
| 6     | O072           | [`eliminate_runtime_test_skips`](../../done/eliminate_runtime_test_skips/card.md)                       | deterministic unit coverage             |
| 7     | O083           | [`reject_unknown_workflow_policy_keys`](../../done/reject_unknown_workflow_policy_keys/card.md)         | strict external config boundary         |
| 8     | O087           | [`preserve_assistant_block_boundaries`](../../done/preserve_assistant_block_boundaries/card.md)         | transcript promise-line reconstruction  |
| 9     | O088           | [`report_active_registry_cleanup_failures`](../../done/report_active_registry_cleanup_failures/card.md) | best-effort cleanup result truth        |
| 10    | O091           | [`serialize_llm_client_initialization`](../../done/serialize_llm_client_initialization/card.md)         | one lazy async client per adapter       |
| 11    | O084           | [`fix_cost_breakdown_selectors`](../../done/fix_cost_breakdown_selectors/card.md)                       | CLI selector and unique-run accounting  |
| 12    | O086           | [`stabilize_proxy_metrics_json`](../../done/stabilize_proxy_metrics_json/card.md)                       | byte-safe stable JSON                   |
| 13    | O080           | [`align_supervisor_missing_config_exits`](../../done/align_supervisor_missing_config_exits/card.md)     | required-state failure semantics        |
| 14    | O077           | [`reject_ambiguous_policy_check_input`](../../done/reject_ambiguous_policy_check_input/card.md)         | mutually exclusive input selectors      |
| 15    | O076           | [`validate_proxy_audit_limits`](../../done/validate_proxy_audit_limits/card.md)                         | positive bounded list limits            |
| 16    | O081           | [`log_forge_info_probe_degradation`](../../done/log_forge_info_probe_degradation/card.md)               | observable best-effort fallback         |
| 17    | O085           | [`reuse_transcript_reference_scan`](../../done/reuse_transcript_reference_scan/card.md)                 | native-relocate delete scan reuse       |
| 18    | O100           | [`explain_type_suppressions`](../explain_type_suppressions/card.md)                                     | typed suppression rationale             |
| 19    | D042/D044/O082 | [`sync_residual_runtime_documentation`](../sync_residual_runtime_documentation/card.md)                 | shipped docs and source commentary      |

## Batch Execution Plan

Execute these batches in order on one branch and PR per batch:

1. **Batch 1 -- independent correctness**: order 9
   [`report_active_registry_cleanup_failures`](../../done/report_active_registry_cleanup_failures/card.md), order 10
   [`serialize_llm_client_initialization`](../../done/serialize_llm_client_initialization/card.md), and the external
   accepted follow-up [`improve_stop_test_failure_excerpts`](../../done/improve_stop_test_failure_excerpts/card.md).
   These can be implemented in parallel because their GC, core LLM adapter, and Stop-verification write/test scopes are
   disjoint.
2. **Batch 2 -- proxy and telemetry read surfaces**: order 11
   [`fix_cost_breakdown_selectors`](../../done/fix_cost_breakdown_selectors/card.md) and order 12
   [`stabilize_proxy_metrics_json`](../../done/stabilize_proxy_metrics_json/card.md). Their code and focused-test scopes
   are parallel; the batch integrator owns shared `docs/cli_reference.md` and `docs/end-user/proxy.md` edits plus final
   CLI reconciliation.
3. **Batch 3 -- policy CLI**: order 13
   [`align_supervisor_missing_config_exits`](../../done/align_supervisor_missing_config_exits/card.md), order 14
   [`reject_ambiguous_policy_check_input`](../../done/reject_ambiguous_policy_check_input/card.md), and the external
   accepted follow-up [`align_policy_check_bundle_vocabulary`](../../done/align_policy_check_bundle_vocabulary/card.md).
   Review these together, but use one owner and implement them sequentially: the first two touch
   `src/forge/cli/policy.py`, while the last shares the terminal `policy check` declaration and also corrects direct
   parsing.
4. **Batch 4 -- isolated runtime fixes**: order 15
   [`validate_proxy_audit_limits`](../../done/validate_proxy_audit_limits/card.md), order 16
   [`log_forge_info_probe_degradation`](../../done/log_forge_info_probe_degradation/card.md), and order 17
   [`reuse_transcript_reference_scan`](../../done/reuse_transcript_reference_scan/card.md). These can be implemented in
   parallel across proxy audit, global info, and session-manager seams.
5. **Batch 5 -- final conformance**: order 18 [`explain_type_suppressions`](../explain_type_suppressions/card.md) and
   order 19 [`sync_residual_runtime_documentation`](../sync_residual_runtime_documentation/card.md). These can be
   implemented in parallel only after Batches 1--4 close, so the suppression sweep sees final production code and the
   documentation pass sees final CLI behavior.

The two external accepted follow-ups join their batches only for execution and review. They do not become Wave 8 finding
credit and do not change this epic's 23 findings or 19-member accounting.

## Dependencies and Activation

- Order 2 follows order 1 because both touch proxy completion accounting; trace lifecycle must be pinned before durable
  writes move off-loop. Order 11 follows order 2 because it reads the same downstream cost/run evidence.
- Order 4 requires targeted session/worktree Docker integration. Orders 1--3 require targeted proxy/telemetry
  integration. Order 5 requires workflow plus extension/installer integration for the touched paths.
- Before activating a batch, recheck every selected card's cited lines on current `main`, create the shared branch from
  the recorded base, move all selected cards to `doing/`, create their individual checklists, and record the active
  branch/base in this epic and its checklist.
- Keep card changes in distinct commits or contiguous commit series. The named batch integrator owns shared docs and
  board edits plus combined-head reconciliation; same-file cards remain sequential even though they share a review.
- Run each card's focused and risk-required verification, then run the applicable combined unit, regression, pre-commit,
  and board/link gates on the integrated branch head.
- Architecture, CLI JSON, config, proxy/session, or Day 1 changes update the applicable normative and end-user docs in
  the same member. Package-loaded or installer changes also run clean-wheel verification where the repository rules
  require it.

## External Batch Members and Gated Work

- [`align_policy_check_bundle_vocabulary`](../../done/align_policy_check_bundle_vocabulary/card.md) retains its bounded
  shared vocabulary residue as a standalone accepted follow-up. It joins Batch 3 without becoming review-row credit for
  this epic.
- [`improve_stop_test_failure_excerpts`](../../done/improve_stop_test_failure_excerpts/card.md) joined Batch 1 as an
  unrelated accepted follow-up without becoming Wave 8 finding credit.
- [`correct_daily_review_regressions`](../../done/correct_daily_review_regressions/card.md) is an independent
  post-Batch-4 correction for three reproduced merged edge cases; it is not a Batch 5 member and adds no Wave 8 finding
  credit.
- D040 remains proposed, and the rejected/resolved rows above are not executable members.
- This epic does not reopen Wave 7 deletion candidates, release-gated deprecations, or the unverified O092 tail.

## Shared Constraints

- Preserve request/response wire shapes, telemetry event IDs, reported-cost provenance, and provider capability gates
  unless a member explicitly names its public compatibility change.
- Keep `core/ops` UI-free; diagnostics and exits remain owned by CLI adapters.
- Preserve strict durable-state reads, fail-closed tracked-content boundaries, and best-effort continuation only when
  failures remain visible in the result or logs.
- Do not collapse implementation ownership within a batch: retain each card's checklist, commit boundary, acceptance
  evidence, and closeout record. Close one complete batch before activating the next.

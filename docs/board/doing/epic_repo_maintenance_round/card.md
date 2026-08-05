# Epic: Repository maintenance round

**Epic** -- coordinating card for the cleanup, bug-fix, refactor, and maintenance findings below. Lane: `doing/` -- Wave
1 policy/supervision coordination is active on `docs/policy-supervision-wave-1`; member implementation remains on
separate execution branches.

## Goal

Turn the whole-repository review into independently shippable, verified work without losing provenance, mixing
unresolved design choices into implementation, or destabilizing the healthy invariants the review identified.

The evidence source is [`review_combined.md`](../../review_combined.md), reviewed at commit
`0a03786fc9b333e9890a64bf80436bb09d8606cf`. It began with 144 severity-ranked rows and three unranked design-drift
notes; DG1 admitted U002/U003 for a current total of 146 ranked findings plus unranked U001. The report remains the
evidence ledger; this epic owns member coordination, sequencing, and final disposition.

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

Wave 1 is coordinated by [`epic_policy_supervision_correctness`](../epic_policy_supervision_correctness/card.md), which
owns the shared external data and edit-identity contracts without collapsing its implementation members.

| Wave | Findings        | Member                                                                                                |
| ---- | --------------- | ----------------------------------------------------------------------------------------------------- |
| 1    | D001            | [`preserve_policy_intent_on_enable`](../../done/preserve_policy_intent_on_enable/card.md)             |
| 1    | D002–D004, O028 | [`harden_supervisor_verdict_boundary`](../../done/harden_supervisor_verdict_boundary/card.md)         |
| 1    | D005            | [`preserve_supervisor_edit_identity`](../../done/preserve_supervisor_edit_identity/card.md)           |
| 2    | D006, U002–U003 | [`align_stop_verification_contract`](../../todo/align_stop_verification_contract/card.md)             |
| 3    | D009            | [`retain_missing_worktree_sessions`](../../todo/retain_missing_worktree_sessions/card.md)             |
| 5    | D015            | [`unify_downstream_retention`](../../todo/unify_downstream_retention/card.md)                         |
| 7    | O047–O048       | [`remove_obsolete_proxy_abstractions`](../../todo/remove_obsolete_proxy_abstractions/card.md)         |
| 7    | O049            | [`migrate_inert_config_fields`](../../todo/migrate_inert_config_fields/card.md)                       |
| 7    | O050            | [`retire_unsafe_index_mutators`](../../todo/retire_unsafe_index_mutators/card.md)                     |
| 7    | O051            | [`replace_legacy_tier_inference`](../../todo/replace_legacy_tier_inference/card.md)                   |
| 7    | O052            | [`remove_dead_session_context_retry`](../../todo/remove_dead_session_context_retry/card.md)           |
| 7    | O092            | [`wire_transcript_reindex_guard`](../../todo/wire_transcript_reindex_guard/card.md)                   |
| 7    | O092            | [`remove_verified_internal_zero_callers`](../../todo/remove_verified_internal_zero_callers/card.md)   |
| 7    | O093            | [`characterize_explicit_backend_mapping`](../../todo/characterize_explicit_backend_mapping/card.md)   |
| 7    | O092, O096      | [`retire_test_only_settings_helpers`](../../todo/retire_test_only_settings_helpers/card.md)           |
| 7    | O096            | [`remove_unreachable_fork_routing_branch`](../../todo/remove_unreachable_fork_routing_branch/card.md) |

## Execution Waves

The canonical wave definitions and finding ranges live in
[`review_combined.md` § Backlog Conversion and Sequencing](../../review_combined.md#backlog-conversion-and-sequencing).
The ordering constraint is:

1. resolve DG1–DG4 and reproduce every CRITICAL/HIGH finding on its execution branch;
2. ship policy and supervision correctness;
3. ship Stop/artifact, session/state, installer, and CLI/proxy correctness in dependency order;
4. process bounded MED/LOW maintenance findings; and
5. refactor or delete only after behavior and compatibility are characterized.

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

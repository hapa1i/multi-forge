# Epic: Repository maintenance round

**Epic** -- coordinating card for the cleanup, bug-fix, refactor, and maintenance findings below. Lane: `todo/` --
accepted work, parked until an execution branch becomes active.

## Goal

Turn the whole-repository review into independently shippable, verified work without losing provenance, mixing
unresolved design choices into implementation, or destabilizing the healthy invariants the review identified.

The evidence source is [`review_combined.md`](../../review_combined.md), reviewed at commit
`0a03786fc9b333e9890a64bf80436bb09d8606cf`. It contains 144 severity-ranked rows, two unranked design-drift notes, the
execution-admission rules, and the proposed waves. The report remains the evidence ledger; this epic owns member
coordination, sequencing, and final disposition.

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

| Gate | Card                                                                            | Findings                   | Unblocks                         |
| ---- | ------------------------------------------------------------------------------- | -------------------------- | -------------------------------- |
| DG1  | [`stop_verification_contract`](../stop_verification_contract/card.md)           | D006, U002                 | Stop/artifact correctness        |
| DG2  | [`missing_worktree_authority`](../missing_worktree_authority/card.md)           | D009                       | Session and durable-state safety |
| DG3  | [`downstream_retention_ownership`](../downstream_retention_ownership/card.md)   | D015                       | Proxy/telemetry retention fixes  |
| DG4  | [`deletion_compatibility_contract`](../deletion_compatibility_contract/card.md) | O047–O052, O092–O093, O096 | Refactor and deletion work       |

These decisions are separate cards because they govern different authorities, state owners, tests, and downstream waves.
The epic coordinates their completion; it does not collapse them into one implementation unit.

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

- Treating all 144 rows as accepted implementation work without triage.
- Implementing unverified findings.
- A bulk dead-code deletion sweep.
- Replacing shipped architecture in design docs before the corresponding code ships.
- Using this epic as a substitute for member-card acceptance criteria and verification.

## Closeout

Move the epic to `done/` only when every live member is done, all accepted findings have a recorded disposition, the
combined review points to the shipped/retired outcomes, verification is recorded, and normative docs are synchronized. A
retired member does not count as shipped; record its rationale and successor on both the member and epic.

# Jev support: coordination checklist

## Current focus

Execute [A2: warnings-only rule pack](../jev_rule_pack/checklist.md) on `codex/jev-rule-pack`, rebased onto `main` at
`18b5670e` after the Claude permission fix's closeout on 2026-10-15. [A1](../../done/jev_client_probes/card.md) shipped
through [PR #268](https://github.com/hapa1i/multi-forge/pull/268) at `9778007a`. The epic stays active with one selected
member. A1's [evidence report](../../done/jev_client_probes/evidence/2026-10-14/report.md) records successful
ZDR-required routing, latency, accounting and limitations. A2's session-consent and explicit evaluation-identity
foundations are in draft [PR #270](https://github.com/hapa1i/multi-forge/pull/270); the user selected broader wrappers
on 2026-10-15. Its revised evidence contract and provisional corpus do not yet establish quality. A3 remains proposed.
Neither decision quality nor quota savings has been evaluated.

## Activation and sequence

- [x] Verify clean `main` at `1ae9667d`, create the A1 execution branch, and move the epic/A1 to `doing/` on 2026-10-14.
- [x] Confirm shipped prerequisites through [B1 closeout](../../done/plan_file_supervision/checklist.md#merged-closeout)
  and [B3 closeout](../../done/codex_policy_warnings/checklist.md#merged-closeout); they no longer block sequencing.
- [x] Keep A2/A3 proposed during A1 execution, with separate branches/checklists when activated. Preserve the
  [shared contract](card.md#shared-contract); Jev Router remains separate.
- [x] Verify activation links: the initial 2026-10-14 audit passed for all 672 Markdown sources.

| Member                                     | Lane     | Prerequisites  | Acceptance owner                                                         |
| ------------------------------------------ | -------- | -------------- | ------------------------------------------------------------------------ |
| [A1](../../done/jev_client_probes/card.md) | Done     | None           | [A1 closeout](../../done/jev_client_probes/checklist.md#merged-closeout) |
| [A2](../jev_rule_pack/card.md)             | Doing    | A1; shipped B3 | [A2 checklist](../jev_rule_pack/checklist.md)                            |
| [A3](../../proposed/jev_cascade/card.md)   | Proposed | A1; shipped B1 | [A3 card](../../proposed/jev_cascade/card.md#acceptance-and-validation)  |

A2 is not an A3 dependency. Neither member's quality evidence validates the other. A valid live ZDR-required Decisions
request gates consumer availability, even when offline transport is ready.

A2 now includes the independent [feedback-permissions fix, PR #269](https://github.com/hapa1i/multi-forge/pull/269),
merged as `e9c144eb`. Its [closeout](../../done/claude_policy_feedback_permissions/checklist.md#merged-closeout) records
the user's decision to merge with paid native testing skipped. The fix is outside this epic's membership; A2's native
warning-delivery evidence remains its own open gate.

## Gate 1: shared transport handoff

- [x] Review A1's early capture outcome before it finalizes retries, telemetry and estimator assumptions. Record a
  failed/unavailable capture as a blocker or an explicit provisional-work decision; never as verified readiness.
- [x] Accept the typed boundary, size/error contract and caller-owned deadline against the epic's shared contract.
  Confirm A2 can distinguish unavailable judgments and A3 can reserve time for its reviewer.
- [x] Accept the telemetry handoff, including Decisions token/cost mapping, usable trace IDs, distinct attempts and
  preservation of existing v2 history. Link A1's evidence rather than maintaining a second transport test list here.
- [x] Record A1's merged head, supported route/model, ZDR readiness and measured limitations. Carry unresolved
  constraints into any consumer activation; unavailable ZDR routing blocks A2/A3 availability.

Gate 1 evidence: [A1 merged closeout](../../done/jev_client_probes/checklist.md#merged-closeout), with all five PR
checks passing and unchanged production code at merge. The supported route is OpenRouter Decisions with ZDR required;
the captured model resolves to `typesafe/jev-1.13-20260917`. Consumers inherit conservative size admission, distinct
local/attempt/provider outcomes, unknown missing cost and observed answer variance. They still own deadlines, quality
thresholds and any reviewer reserve; A1 supplies no decision-quality or quota-saving evidence.

## Gate 2: consumer activation and drift control

- [x] Select the next member explicitly after reviewing its prerequisites. Create its branch/checklist and update both
  sides of the epic link; no implicit parallel activation or shared implementation batch.
- [ ] Review the selected member against the shared contract and the B1/B3 handoff it consumes. Put its concrete
  fixtures, quality thresholds, corpus/data decisions and paid observation budget in its own checklist, following its
  card's acceptance requirements. Do not duplicate those requirements here.
- [ ] Review shared cache/audit identity at each handoff: canonical action/state, rule/question/plan version,
  route/model and decision-rule version. Keep retry, escalation and sampled-audit accounting distinguishable across
  members.
- [ ] Reconcile any changed A1 contract or runtime admission restriction with both consumers before merging it. Preserve
  the separate everyday supervision path and existing Stop/native-source boundaries.
- [ ] Link each member's acceptance evidence and limitations here when it ships. If findings change scope or
  dependencies, update the owning card first, then this sequence; member quality evidence remains independent.

2026-10-14 selection: A2, on `codex/jev-rule-pack` from `f7ce7a9a`. It exercises A1's first policy integration and B3's
warning delivery before A3's review-skipping decisions. The [A2 checklist](../jev_rule_pack/checklist.md) owns
whole-action coverage, bounded dispatch, warning provenance and quality/data gates. A2's calibration and held-out
acceptance criteria still need review before evaluation; its quality evidence cannot validate A3.

Review handoff, 2026-10-14: A2 owns the user's decision to require a new paid/data-sharing acknowledgment in every
derived session, and runs after existing whole-action checks inside the established hook deadline. A2's A1 extension now
accepts `judge(run_identity=...)` with the ambient fallback retained. Five offline telemetry integrations verify
distinct evaluations, retry identity and run ancestry; A2's dispatch/cache integration remains pending. Gate 2 must
reconcile that API, run ancestry and audit storage with A3 before merge. The
[A2 checklist](../jev_rule_pack/checklist.md) owns the fixtures and numeric limits.

## Coordination acceptance

Member checklists own behavior-level fixtures and tests. The epic verifies their handoffs and the integrated outcome.

| Check               | Evidence fixture                                 | Assertion                                          |
| ------------------- | ------------------------------------------------ | -------------------------------------------------- |
| Route readiness     | A1 sanitized ZDR capture                         | Supported route, or explicit consumer blocker      |
| Shared contract     | A1 typed/telemetry fixtures plus member handoffs | Compatible consumers; retained history             |
| Consumer acceptance | Separate A2/A3 labeled evaluations               | Own thresholds met; limits recorded                |
| Economics           | Same-cohort attempts, escalations and audits     | Reconciled spend and actual reviewer calls avoided |

## Member and epic closeout

- [ ] Record each member's tests, risk-required integrations, non-passing outcomes, reviewed PR/merge evidence and final
  supported scope. Update its lane and links after closeout.
- [ ] Verify design and end-user docs reflect shipped behavior at each member handoff; resolve documentation debt.
- [ ] Review the separate consumer evaluation results against their declared acceptance rules. Report Jev cost, reviewer
  model/tokens, actual calls avoided and audit overhead together. Use provider quota measurements only when available;
  do not convert tokens into an invented quota figure.
- [ ] Confirm every live member is shipped and verified on the final integrated head, with applicable aggregate tests
  and board/link checks. Add the completed-work change-log entry and submit durable lessons for human-reviewed
  implementation-note promotion.
- [ ] Move the epic to `done/` only after that coordinated outcome is verified, then repoint all links.

## Planning verification

2026-10-14: initial activation and the review revisions passed `make pre-commit-md` and `git diff --check`. The final
standalone Markdown link audit passed for 673 sources. That planning checkpoint preceded the A1 implementation and
capture evidence linked above.

# Jev support: coordination checklist

## Current focus

[A2](../../paused/jev_rule_pack/card.md) is **paused** by owner decision on 2026-10-19. Its
[pause handoff](../../paused/jev_rule_pack/evidence/pr-275-pause-handoff.md) records the tested runner, failed bounded
study, inconclusive native audit and unmet runtime gates. PR #275 wraps that investigation without enabling A2.

Active member: [A3](../jev_cascade/card.md), for its own bounded feasibility study before runtime implementation. Branch
`codex/jev-cascade-feasibility` starts at `8dea95f5` after PR #275 merged as `fe2d09a1`; its
[checklist](../jev_cascade/checklist.md) and [study plan](../jev_cascade/evidence/feasibility-plan.md) own the gates. A3
depends on shipped A1 and B1, not A2; A2's results supply caution and reusable transport/tooling, not A3 quality
evidence. The epic stays `doing/` as the living coordinator. A1 remains done, and consumer acceptance and quota savings
remain unproven.

## Activation and sequence

- [x] Verify clean `main` at `1ae9667d`, create the A1 execution branch, and move the epic/A1 to `doing/` on 2026-10-14.
- [x] Confirm shipped prerequisites through [B1 closeout](../../done/plan_file_supervision/checklist.md#merged-closeout)
  and [B3 closeout](../../done/codex_policy_warnings/checklist.md#merged-closeout); they no longer block sequencing.
- [x] Keep A2/A3 proposed during A1 execution, with separate branches/checklists when activated. Preserve the
  [shared contract](card.md#shared-contract); Jev Router remains separate.
- [x] Verify activation links: the initial 2026-10-14 audit passed for all 672 Markdown sources.

| Member                                     | Lane   | Prerequisites  | Acceptance owner                                                         |
| ------------------------------------------ | ------ | -------------- | ------------------------------------------------------------------------ |
| [A1](../../done/jev_client_probes/card.md) | Done   | None           | [A1 closeout](../../done/jev_client_probes/checklist.md#merged-closeout) |
| [A2](../../paused/jev_rule_pack/card.md)   | Paused | A1; shipped B3 | [A2 checklist](../../paused/jev_rule_pack/checklist.md)                  |
| [A3](../jev_cascade/card.md)               | Doing  | A1; shipped B1 | [A3 checklist](../jev_cascade/checklist.md)                              |

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
warning delivery before A3's review-skipping decisions. The [A2 checklist](../../paused/jev_rule_pack/checklist.md) owns
whole-action coverage, bounded dispatch, warning provenance and quality/data gates. A2's calibration and held-out
acceptance criteria still need review before evaluation; its quality evidence cannot validate A3.

Review handoff, 2026-10-14: A2 owns the user's decision to require a new paid/data-sharing acknowledgment in every
derived session, and runs after existing whole-action checks inside the established hook deadline. A2's A1 extension now
accepts `judge(run_identity=...)` with the ambient fallback retained. Five offline telemetry integrations verify
distinct evaluations, retry identity and run ancestry; A2's dispatch/cache integration remains pending. Gate 2 must
reconcile that API, run ancestry and audit storage with A3 before merge. The
[A2 checklist](../../paused/jev_rule_pack/checklist.md) owns the fixtures and numeric limits.

Foundation handoff, 2026-10-15: PR #270 merged as `9442c1e5`. The additive `judge(run_identity=...)` contract is
available to either consumer; omitted identity retains the ambient fallback, and session/grouping attribution still
comes from the environment. Downstream v2 and usage v1 are unchanged. A3 remains unimplemented and must derive its own
evaluation runs; A2's unfinished cache/audit and quality gates remain separate. See the
[foundation handoff](../../paused/jev_rule_pack/checklist.md#foundation-merge-and-continuation).

Offline evaluation handoff, 2026-10-15: PR #271 merged as `791d9872` with all five CI checks passing and the same tree
as reviewed head `cd008613`. It changes no A1 API or telemetry schema. Its saved-response identities, human/host audit
and metric definitions belong to A2; they supply no quality evidence for A3. The
[A2 handoff](../../paused/jev_rule_pack/checklist.md#offline-evaluation-merge-and-next-gate) records validation and
remaining acceptance gates. A2 and the epic remain active; A3 is not activated.

Feasibility handoff, 2026-10-17: PR #274 merged as `09984440`. It changes no A1 API or telemetry schema and establishes
no consumer quality or runtime admission. The [A2 handoff](../../paused/jev_rule_pack/evidence/pr-274-merge-handoff.md)
preserves review provenance and the next gates. A2 and the epic remain active; A3 remains proposed.

Pause handoff, 2026-10-19: the owner stopped A2's current implementation path and selected A3 feasibility next. The
[A2 handoff](../../paused/jev_rule_pack/evidence/pr-275-pause-handoff.md) retains the failed frozen judgments and all
unmet acceptance items. PR #275 changes no A1 runtime API or telemetry schema and supplies no review-skipping evidence.
A3 activated on `codex/jev-cascade-feasibility` from `8dea95f5` after the merge. Its
[study plan](../jev_cascade/evidence/feasibility-plan.md) begins with offline evidence admission and human review;
proposed numeric gates and a future exact capture require review before execution. No A3 capture or runtime behavior has
shipped.

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

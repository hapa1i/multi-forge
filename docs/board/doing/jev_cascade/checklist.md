# A3: Jev cascade feasibility checklist

## Current focus

A3 starts with an offline feasibility gate after the A2 pause and PR #275 merge. The [card](card.md) owns the intended
review-skipping outcome; the [study plan](evidence/feasibility-plan.md) owns the bounded experiment. Runtime integration
waits for an explicit proceed decision. A1 and B1 are shipped prerequisites; A2 is not a dependency.

Execution branch: `codex/jev-cascade-feasibility`, based on `main` at `8dea95f5` after PR #275 merged as `fe2d09a1`. No
A3 paid calls, native data collection or production review skipping have run. New numerical limits in the study plan are
proposals to review before a capture manifest can be approved.

## Activation and code handoff

- [x] Record PR #275's merge and this card's execution branch/base; move A3 to `doing/` and update the epic links.
- [x] Inspect the current checker, shared plan snapshot, resolver, auth validation and whole-hook deadline. The study
  plan records per-file evidence limits and the subscription-only/cascade incompatibility.
- [x] Run the existing offline baseline suites: plan check, cascade hook composition, engine, retry deadline and shadow
  evidence. All 110 tests passed on reviewed PR #275 head `06074f0c`; this establishes fixture behavior, not A3 quality.
- [x] Reconcile A1's optional `judge(run_identity=...)`, parent/root ancestry and attempt accounting with the proposed
  checker, frontier and audit identities. The [handoff](evidence/identity-handoff.md) records current gaps and future
  ownership; no telemetry schema or A1 API change is needed for offline preparation.

## First gate: evidence and labels

- [x] Prepare four synthetic plan families and 24 action records with fixed identities, authored clause inventories and
  explicit supported/unsupported evidence. The [corpus](evidence/cascade-corpus.json) includes multi-file, deletion,
  truncation and stale-plan controls; human review must verify the completeness claims.
- [ ] Export a compact review packet; obtain human review of authority, relevant clauses, decomposition, evidence
  sufficiency, per-question answers and expected routing. Retain pending/disputed labels and provenance.
- [x] Fix whole-family calibration/held-out membership and record any exposure. Separate human-reviewed decomposition
  feasibility from automatic runtime decomposition; no implementation of the latter is part of this slice.
- [ ] Implement only the offline admission/composition and reporting needed for this experiment. Compare always-escalate
  and bounded deterministic controls using identical evidence. Stop if no useful supported semantic subset remains.
- [ ] Review the finite calibration procedure, proposed false-allow/usefulness gates, exact model screen and hard stops
  before any capture. Human labels, host coverage and model confidence remain separate inputs.

Offline preparation: the [review guide](evidence/human-review.md) links four compact worksheets and a blank,
identity-bound template. The [retained ledger](evidence/human-review-ledger.json) records ten user reviews; 14 remain
pending. The preparation report distinguishes 12 declared exclusions from 12 review candidates. Fixture composition
requires reviewed evidence, exact current identity and explicit probabilities/bands; it preserves existing denials and
unrelated review. It has no dispatch or quality-scoring mode. The semantic deterministic baseline and usefulness
comparison remain open; always-escalate alone cannot establish incremental model benefit. No paid manifest is prepared.

Offline validation: `tests/src/scripts/test_jev_cascade_offline.py` passes 107 fixture tests, including missing-clause
confidence, denial precedence, malformed inputs, copied/stale human reviews and absence of provider/native access. The
generated report and pending ledger reproduce from the corpus; these checks establish tool behavior, not model quality.

| Fixture                                         | Required observation                                           |
| ----------------------------------------------- | -------------------------------------------------------------- |
| Relevant clause omitted; confidence 1.0         | Escalates before model confidence can authorize an allow       |
| Partial action; deleted or uncovered sibling    | Full-action coverage remains unsupported                       |
| Changed plan/question/model/decision version    | Prior allow cannot be reused                                   |
| Deterministic deny; unrelated unresolved review | Jev allow cannot clear either finding                          |
| Service error; timeout; unknown outcome         | Unavailable judgment stays distinct from reviewed alignment    |
| Repeated or interrupted capture                 | Reserved attempts remain consumed; no implicit retry or resume |

## Second gate: bounded model screen

- [ ] Build the exact manifest after review: slots/bodies, labels excluded, routes/privacy, code and input identities,
  request/time/spend/output caps, isolated telemetry and explicit evaluation runs. Keep paid execution disabled by
  default.
- [ ] Verify all runner/admission paths with fixtures and clocks. Reuse appropriate A1 transport and experimental
  journal boundaries; do not copy A2's question contract or alter its frozen evidence to serve A3.
- [ ] Obtain separate approval of that concrete capture. A2's consumed allowances and this planning checklist do not
  authorize A3 requests. Run only the approved slots with no retries or adaptive tuning.
- [ ] Report the frozen result, unknown/missing observations, per-family coverage, repeat consistency, latency and
  costs. Stop before held-out dispatch if no calibration setting is admissible; a held-out false allow stops the
  candidate. An all-escalate result or no benefit beyond deterministic checks stops this study.
- [ ] Record owner-reviewed stop/revise/proceed-to-observation. A synthetic pass does not authorize runtime skipping or
  establish representative accuracy, quota savings or a production threshold.

## Deferred consumer acceptance

- [ ] If warranted, design separate paid-checker consent and guarded reviewer auth without weakening the existing
  subscription-only refusal. Preserve everyday no-API-spend supervision.
- [ ] Establish complete native action coverage, question compilation and invalidation; preserve shared deadline and
  frontier reserve, denial precedence, resolver ownership and visible unavailable-review behavior.
- [ ] Compare B1-only, existing generative cascade and proposed Jev paths on an independently reviewed cohort. Account
  for per-file calls, cache hits, existing checker skips, retries, escalations and bounded audits.
- [ ] Demonstrate actual avoided calls and real escalation under an approved integration/native manifest. Run applicable
  hook/auth/telemetry integrations and sync workflow, telemetry and end-user docs as behavior ships.
- [ ] Record acceptance, validation and PR evidence before any `done/` move; otherwise preserve open gates in a pause or
  retirement decision. The [epic](../epic_jev_support/checklist.md) remains the sequencing authority.

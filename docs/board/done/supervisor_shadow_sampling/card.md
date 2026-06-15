# Supervisor Shadow Sampling — measure the cascade's false-aligned rate

**Status**: Done (`done/`) — shipped to `main` via PR #27. Follow-up to `supervisor_cascade`; provides the audit
instrument that gates any future default-on cascade decision (the rate-bounding data is now collectible, not yet
collected).

> **Shipped design (supersedes the sketch below).** Two parts of the original sketch changed during implementation; the
> normative description is [`design_workflows.md` §1.2](../../../design_workflows.md) and the [checklist](checklist.md):
>
> - **Recording is an artifact directory, not a decision-log entry.** Shadow records live in
>   `.forge/artifacts/<session>/shadow/<hash>.{json,processing,done}` (with a `<hash>.plan.md` sidecar), keeping the
>   audit plane fully separate from the enforcement decision log (which is capped at `MAX_DECISION_LOG`).
> - **Capture freezes a candidate; the drain is a Stop-batch.** The hook freezes the *raw* action + a copied plan +
>   routing snapshot (it does not pack content into the queue payload); a Stop-hook marker spawns a detached
>   `forge policy shadow run` worker that replays the frontier and finalizes each candidate. Counts surface as
>   `checked`/`disagree`/`pending` in `forge activity`; disagreement artifacts via `forge policy shadow show`.

## Problem

The cascade's tier-1 plan check can be wrong in two directions, and only one of them is visible:

- **False escalation** (`needs_review` on an aligned action): costs one frontier call. Shows up in the
  `plan_check_needs_review` counter; harmless to safety.
- **False aligned** (`allow` on a divergent action): the frontier never runs, the divergent edit proceeds, and nothing
  records that supervision failed. Silently converts a supervised session into a mostly-unsupervised one.

The shipped counters measure short-circuit **rate**, not **quality** — a wrong allow is indistinguishable from a correct
one in the decision log. Ground truth ("was this action actually plan-aligned?") is exactly the frontier verdict the
cascade skipped, so every successful short-circuit destroys the evidence needed to audit it. Allow rationales are
debug-logged only, and would be the checker grading its own homework anyway.

Cascade stays opt-in until this rate is bounded. That is the gate this card exists to lift.

## Design sketch

Run the frontier supervisor on a random sample of tier-1 `allow` verdicts as a **shadow**: verdict recorded, never
enforced. The action proceeds on tier-1's allow regardless.

- `SupervisorConfig.shadow_sample_rate: float = 0.0` (session-owned, like `cascade`/`checker_model`).
- Sampling point: uncached tier-1 allows only (a cached allow re-validates content already sampled or skipped).
- Decouple from the hook: enqueue via `forge.core.workqueue` and run post-hoc. The payload must carry the **action
  content** (truncated to the supervisor's content window), not a file path — the file mutates after the hook fires,
  starting with the Write being checked.
- Shadow worker: same `claude -p --resume <resume_id> --fork-session` invocation and prompt as the real supervisor,
  bypassing the ThrottleCache (it is an audit, not a gate). Never blocks, never warns, no stderr.
- Recording: decision-log entry tagged shadow (excluded from enforcement-plane counters); ledger event
  (`command="supervisor-shadow"`, session-tagged) so sampling cost is visible; `forge activity` gains `shadow_checked` /
  `shadow_disagree`.
- A disagreement is a concrete review artifact: action content, plan snapshot, tier-1 reason (from the violation
  message), frontier verdict with citations. These drive checker-prompt or checker-model tuning.

Cost model: sampling spends `shadow_sample_rate x frontier-check cost` of the cascade's savings. At 10%, ~90% of the
savings survive while audit data accumulates.

## Open questions

- **Queue vs batch**: per-allow workqueue enqueue at hook time, or a Stop-hook batch sweep over the session's decision
  log (memory-writer pattern)? Batch is simpler and amortizes; per-allow is fresher.
- **Verdict comparability**: the shadow check runs seconds-to-minutes after the action; the planning session is frozen
  but the fork timestamp differs. Confirm verdict stability across that gap before trusting disagreement counts.
- **Sample bookkeeping**: how many samples before a default-flip decision is defensible, and does the rate need
  per-checker-model tracking (`checker_model` varies per session)?
- **Randomness**: sampling needs a seedable source for deterministic tests (never skip, never flake).
- **Runaway cost guard**: cap shadow checks per session in addition to the rate?

## Risks

- Shadow disagreements may reflect frontier nondeterminism rather than tier-1 error (the supervisor's own
  confidence>=0.8+citations bar mitigates; only count high-confidence divergent shadows as disagreements).
- Post-hoc shadow checks bill real frontier calls; a forgotten nonzero rate on a long session is a silent spend
  multiplier. Ledger visibility + the per-session cap address this.
- Workqueue workers run outside the hook's lifetime; orphaned queue entries after session end need a cleanup story.

## Acceptance sketch (if accepted)

| Test                  | Fixture                                           | Assertion                                                       |
| --------------------- | ------------------------------------------------- | --------------------------------------------------------------- |
| Shadow never enforces | rate=1.0, frontier returns divergent              | hook exit 0; action proceeds; no stderr                         |
| Disagreement counted  | tier-1 allow + shadow divergent (high confidence) | `shadow_disagree` increments; artifact persisted                |
| Rate=0 is free        | default config                                    | no queue entries, no ledger events, decision log byte-identical |
| Cost visible          | rate>0 session                                    | `supervisor-shadow` ledger events session-tagged                |

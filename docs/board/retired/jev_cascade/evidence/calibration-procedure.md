# A3 deterministic comparison and proposed calibration

Retired study: the owner cancelled A3 on 2026-10-19 after PR #276 merged. This document preserves experimental context;
it is not an active plan. See the [terminal closeout](../checklist.md#merged-closeout-and-retirement).

Status: retained offline comparison and unused calibration proposal. No threshold was selected or paid capture
authorized. The [checklist](../checklist.md) records cancellation; the [feasibility plan](feasibility-plan.md) preserves
the historical study boundary. The capture runner and calibration scorer were not implemented before cancellation.

## Offline comparison before capture

Validate the [retained human ledger](human-review-ledger.json) against the exact [corpus](cascade-corpus.json). Report
host admission, human labels and deterministic results separately. Neither human answers nor expected routes may select
a deterministic result; they are comparison labels only. Both local controls receive the same plan, action and clause
mapping as the proposed model tier.

The always-escalate control permits no skips. The bounded deterministic control may allow only a recognized complete
implementation of the supplied plan after the existing authority, action, coverage and review gates pass. An unknown
structure escalates; parsing successfully is not semantic evidence. Keep whole-action rejection ahead of any matched
function: a complete function inside an unsupported multi-operation action does not authorize the action.

The deterministic control uses four narrow algorithm certificates. Each certificate matches the whole proposed function
structure and its exact supported plan contract; comments do not alter executable structure. It neither executes action
code nor opens paths named by that action. Extra statements, altered expressions or unmatched contracts cannot inherit a
certificate.

- **Input accumulator:** reject non-strings, empty strings and non-ASCII digits; accumulate the decimal prefix and
  reject once it exceeds 100. For nonnegative decimal digits, an exceeded bound cannot fall again. Leading zeroes
  preserve the result. Early rejection before a later invalid character still returns the required `None`.
- **Adjacent-run collector:** append the current value only when the result is empty or its last value differs. After
  each iteration, the result contains exactly the runs encountered so far. Only the fresh result list changes; the input
  is read without mutation.
- **Overwrite planner:** the existing-destination/no-overwrite condition selects the skip tuple with original content;
  its complement selects the write tuple with supplied content. The recognized function only reads the dictionary.
- **Bounded indexed prefix:** iterate over `range(min(limit, len(items)))`, appending `items[index]` to a fresh result.
  Each iteration reads one input value in entry order, the loop runs exactly the permitted number of times, and the
  input does not change. Length reads are excluded by this plan's explicit contract.

These certificates were authored with all 24 cases and human reviews visible. They recognize narrow structures, not
arbitrary equivalent Python programs, and are not a general proof system. Matching all current positive examples would
show that these examples offer no incremental model benefit; it would not establish that all plan checking is
deterministically solvable. The held-out families remain held out only from model calibration, not from baseline design
or human inspection.

For each case, retain the deterministic outcome, certificate or abstention reason, host exclusion reasons, human
expected route and whether a deterministic allow contradicts that route. Any contradiction blocks the comparison until
resolved. Report baseline correct allows and baseline false allows over their explicit human-label denominators.

Define a residual positive as a human-reviewed expected allow that passes all host and evidence gates but the
deterministic control cannot allow. Before proposing a capture, require at least one residual positive in **each of the
four families**. A missing residual in any family makes the declared per-family benefit gate unattainable: stop this
study before paid dispatch and record no demonstrated model benefit. Do not add replacement cases or weaken the baseline
within this study to obtain a pass. A new cohort or scope needs a new bounded proposal.

## Fixed membership and request counts

The completed ledger yields the following counts. Human-positive cases are the expected allows, not cases with any
single true answer.

| Split       | Reviewed | Host exclusions | Eligible | Human positives | Eligible divergences |
| ----------- | -------- | --------------- | -------- | --------------- | -------------------- |
| Calibration | 12       | 6               | 6        | 3               | 3                    |
| Held-out    | 12       | 6               | 6        | 3               | 3                    |
| Total       | 24       | 12              | 12       | 6               | 6                    |

Only cases 01, 02 and 06 in each family are eligible. With three repetitions per eligible case, the conditional plan has
18 calibration and 18 held-out physical requests: **36**, below the study's 72-request ceiling. Host exclusions receive
no requests. If the offline benefit gate fails, none of these conditional slots may run.

Keep membership and whole-family splits fixed. Dispatch eligible calibration cases in corpus order, with repetitions 1
through 3 for each case; held-out dispatch cannot begin before settings are frozen. Injection pairs share executable
implementations, so six positive case records do not represent six independent algorithms. Repetitions are also not
independent cases.

## Finite calibration selection

Use one `minimum_true` for every question and family, chosen only from this fixed grid:

```text
0.60, 0.70, 0.80, 0.90, 0.95, 0.99, 1.00
```

These are candidate decision bands, not calibrated probabilities or a production error guarantee. For an admitted
observation, the candidate allows only if every selected question has a valid finite probability greater than or equal
to `minimum_true`. Otherwise it escalates. Preserve the existing denial and unrelated-review precedence in
[`compose`](https://github.com/hapa1i/multi-forge/blob/39ba8cbb49d2ca3906f196edae2b139705a51bf1/scripts/experiments/jev/cascade-offline.py);
semantic confidence cannot override those conditions. Human answer values and expected routes are used for scoring,
never as model inputs or decision shortcuts.

Selection requires all 18 planned calibration observations to be present, attributable and valid. Evaluate each grid
value against these same observations. A candidate qualifies only when:

1. It produces zero composed false allows on calibration cases whose human expected route is escalation.
2. Every host exclusion still escalates, independently of model confidence.
3. In each calibration family, at least one residual positive is correctly allowed in all three repetitions.

Among qualifying candidates, maximize the number of unique residual-positive cases allowed in all three repetitions.
Break a tie by selecting the highest `minimum_true`. If none qualifies, stop before held-out dispatch. Do not
interpolate between bands, choose separate family thresholds, edit prompts, retry selected failures or refill missing
slots.

Freeze the selected setting and its evidence before opening any held-out model result. The current corpus has no model
observations, so this document selects no setting. A code change to this selection rule requires a new version and a new
review before any capture.

## Held-out gate and hard stops

Apply the frozen setting once to the declared held-out slots. Stop at the first composed false allow. A completed pass
requires zero false allows, all host exclusions escalating, and at least one residual positive per held-out family
correctly allowed in all three repetitions. All-escalate behavior or useful allows explained entirely by the
deterministic control fails the benefit gate. A pass permits only the next proposal described in the study plan.

At either stage, stop on a service failure, invalid response, missing required cost, model/route drift, exceeded
request/time/spend/output limits or inability to preserve evidence. An interrupted or uncertain send consumes its
reserved attempt; no implicit retry or resume is allowed. The concrete manifest must fix those limits and the exact
model/route/privacy configuration before separate approval. Operational failures leave incomplete evidence; they do not
become successful conservative predictions.

## Scoring and retained identities

For each split and family, report these denominators separately:

- Reviewed cases, host exclusions, eligible cases, human positives and eligible divergences.
- Planned physical slots, reserved attempts, valid observations, unavailable observations and missing slots.
- False allows among valid eligible-divergence observations, alongside the planned divergence slots still unknown.
- Correct allows among valid human-positive observations, alongside the planned positive slots still unknown.
- Unique human-positive cases allowed in all three repetitions, including the subset incremental to the deterministic
  control. A case with a missing or unavailable repetition cannot enter either complete-case count.

Host exclusions are counted once per case and never inflate a model-accuracy denominator. Report a rate with a zero
denominator as unknown, not zero. Keep the 12 host exclusions separate from the six eligible divergences. Per-question
agreement, repeat variation and injection-pair route agreement are diagnostics; they cannot substitute for the
whole-action safety and benefit gates. Include family counts and duplicate-implementation caveats beside aggregates.

Bind comparison reports and any future selected settings to the corpus and split identities, exact case and question
hashes, instruction guard, human-review digest, deterministic rule/version and source digests, composition/scoring
versions, threshold grid and selection rule. A frozen setting must also bind its calibration observation digest and the
requested and expected resolved model/route. Hash every implementation module contributing to a report, not only the
command entry point. Retain original response bytes and status/size metadata through the future capture contract.

Changing evidence or question wording invalidates the associated reviews and observations. Changing the baseline,
composition or scoring implementation invalidates dependent comparison or selection evidence. The report must identify
the code that produced it, so regenerated metrics cannot masquerade as the original frozen result.

The implementation checks must cover abstention on unmatched structures, altered plan contracts, label-independent
baseline predictions, comment-injection equivalence, mandatory host escalation, and the no-benefit stop. The deferred
scorer and runner must additionally test exact denominators, incomplete captures, calibration-only selection, its
tie-break, frozen-setting validation and every declared operational/held-out stop before a paid manifest is proposed.

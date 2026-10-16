# A2 offline evaluation plan

Status: the offline evaluator shipped through [PR #271](https://github.com/hapa1i/multi-forge/pull/271). Human
adjudication is complete for the 17 constructed cases; calibrated thresholds and numerical acceptance limits remain
unset. The [merge handoff](../checklist.md#offline-evaluation-merge-and-next-gate) records validation and the next gate.
This document authorizes no collection, provider request or native trial. A1's probe approvals do not carry over.

## Scope and current evidence

The [candidate contract](initial-rule-review.md) owns the broader compatibility-wrapper semantics. The
[corpus](wrapper-corpus.json) contains 17 constructed actions in seven source families: 12 calibration and five
held-out. Four cases are decided from fixture applicability/history facts; 13 require semantic assessment. The
[first](human-review-2026-10-16.json), [second](human-review-2026-10-16-batch-2.json),
[third](human-review-2026-10-16-batch-3.json), [fourth](human-review-2026-10-16-batch-4.json),
[fifth](human-review-2026-10-16-batch-5.json) and [sixth](human-review-2026-10-16-batch-6.json) 2026-10-16 ledgers
record human adjudications for all 12 calibration cases: six warnings, three no warnings, two host-decided
not-applicable outcomes and one host-decided unavailable outcome across four source families. The
[seventh](human-review-2026-10-16-batch-7.json) and [eighth](human-review-2026-10-16-batch-8.json) ledgers complete all
five held-out labels: one warning, two no warnings and two unavailable outcomes across three families. Only one held-out
family supplies a positive label. The four host-decided cases have no question answers and contribute no model
observations. Each question has nine known calibration answers. Held-out has four answer objects: coverage is known for
all four, but `partial-edit` leaves retention and boundary unknown, so those questions have three known answers each.
That partial Edit remains a model candidate; its unavailable human label is distinct from the host-decided Write. There
is no human-labeled historical cohort or measured model accuracy. Preparation no longer reports incomplete adjudication;
its retained report lists unset numeric gates, absent predictions/quality evaluation, unimplemented live execution and
absent historical evidence. The separate [calibration capture harness](calibration-run-plan.md) now prepares a bounded
live proposal; the evaluator itself remains offline. The
[first approved calibration capture](calibration-2026-10-16/README.md) is now complete. Its required-boundary scores
cannot recover the human labels under any allowed bands, so settings remain unset and held-out capture is deferred.
`quality_accepted` remains false.

The [2026-10-17 boundary instruction revision](boundary-question-proposal.md) preserves coverage, criteria and human
adjudications. Current preparation reports bind its new prompt/payload hashes. The
[separately approved follow-up](calibration-boundary-2026-10-17/README.md) is complete and its allowance is consumed. It
still cannot recover the two required-boundary labels; the clean-break case also cannot clear coverage. All three human
no-warning cases remain unrecoverable under allowed settings, so the decision remains revise.

The shared `policy.rule_pack.definitions` module owns the draft-3 questions and contract version 4. The
`policy.rule_pack.outcomes` module owns decision version `draft-2`. These modules are available for offline evaluation;
they do not register a bundle, enable a session or dispatch a request. Runtime surface/exception authority remains a
separate gate.

The [feasibility checkpoint](corpus-feasibility.md) counts current families and action shapes without treating proposed
labels as truth. The [human review workflow](human-review.md) exports exact evidence with authored labels/rationales
withheld, validates partial adjudications and retains disagreements/exclusions in the review ledger. The
[runtime evidence proposal](runtime-evidence-contract.md) remains separate from fixture governance and does not activate
the bundle. The held-out action evidence and authored proposals were visible while draft-3 semantics were developed.
Human review also followed AI-assisted discussion. Holding back model outputs supports a limited check after
calibration; it does not make these scenarios unseen or establish rule generalization. Select question bands only on
calibration responses. If future results motivate a rule change, version the contract and obtain new, unexposed
evaluation scenarios before making a generalization claim.

## Decision contract

Each question requires an explicit false-maximum and true-minimum. The false cutoff must be below 0.5 and the true
cutoff above 0.5; their endpoints are inclusive, and the gap means uncertain. There is no default or borrowed supervisor
threshold. Evaluate coverage first:

| Covered evidence | Compatibility retention | Independent boundary | Outcome                          |
| ---------------- | ----------------------- | -------------------- | -------------------------------- |
| False            | Any                     | Any                  | Unavailable                      |
| Uncertain        | Any                     | Any                  | Uncertain                        |
| True             | False                   | False or uncertain   | No warning                       |
| True             | False                   | True                 | Uncertain: contradictory answers |
| True             | Uncertain               | Any                  | Uncertain                        |
| True             | True                    | Uncertain            | Uncertain                        |
| True             | True                    | True                 | No warning: required boundary    |
| True             | True                    | False                | Warning                          |

The 2026-10-16 semantic revision makes a warning advisory: covered retention with no justification established by the
supplied evidence. Missing structural/history/policy evidence remains unavailable. Materially ambiguous or conflicting
supplied boundary evidence remains uncertain; no justification at all is not such a conflict. A required protocol name,
signature or identity can justify a pure alias without additional behavior. The warning makes no claim about unseen
requirements. Updated question/case/payload hashes invalidate old packets and predictions; decision version `draft-2`
rejects old threshold settings even though the composition table is unchanged. No thresholds are yet calibrated.

Validate answer IDs/types through A1's contract before composition or collecting calibration probabilities. Malformed
answers and saved failures are unavailable. Fixed diagnostic text describes the assessment without inventing a provider
explanation. A warning asks for caller and compatibility review; it does not authorize deletion. No combination returns
an engine deny, needs-review or permission allow. The shared outcome module also owns host applicability and fixed
diagnostics. Host-decided not-applicable/unavailable cases do not enter model accuracy or latency denominators; their
human labels are compared with the host outcomes separately, and labeled positives contribute to the pipeline miss
metric.

## Saved-response workflow

Prepare payloads as before, or generate an empty fixture manifest for one split:

```bash
uv run python scripts/experiments/jev/rule-pack-eval.py \
  docs/board/doing/jev_rule_pack/evidence/wrapper-corpus.json --include-payloads
uv run python scripts/experiments/jev/rule-pack-eval.py \
  docs/board/doing/jev_rule_pack/evidence/wrapper-corpus.json \
  --prediction-template --split calibration --expected-model fixture-model > /tmp/jev-predictions.json
```

Manifest schema 2 declares its fixture/capture source, source reference, corpus and prompt hashes, split, repetition
count, expected resolved model and saved observations. Its corpus hash binds only case IDs, families and split
assignments; each scored observation's case and payload hashes bind its content. Editing held-out evidence therefore
does not invalidate a calibration capture's identity. The corpus must still pass its integrity and annotation checks.

`expected_model` must match every reported model. Use one manifest per resolved model snapshot, including across
repetitions; an alias in the request payload does not establish snapshot identity. The example's `fixture-model` is only
for fabricated responses. A capture needs the actual resolved identifier.

Each observation supplies `case_id`, `case_sha256`, `payload_sha256`, `repetition`, optional `latency_ms`, and exactly
one of a raw Decisions `response` or a `failure` string of at most 256 characters. Response rows additionally require
`status_code` and the original `response_bytes`. Only status 200 and responses within A1's 256,000-byte limit can
contribute answers. The saved original size is authoritative: re-serializing a parsed body can change its size.
Oversized bodies provide no accepted accounting metadata, matching A1's early stop. Preserve original status and wire
size when converting captures; the evaluator trusts this provenance and cannot recover wire size from a parsed body.
Never invent those fields to admit a body. One observation represents one attempt; retries are not modeled. Real
captures must retain their original approved provenance. Never label invented responses as captures.

The evaluator rejects stale hashes, observations from the other split, duplicate or excess repetitions, and predictions
for host-decided cases. Missing observations remain unavailable and appear in both counts and report blockers. The
current limits are 500 corpus cases, 100 repetitions and 5,000 saved observations, with bounded input files. Templates
require a split containing model candidates, and both template construction and evaluation reject plans whose candidate
count times repetitions exceeds 5,000. Use `--repetitions` when preparing a repeated-input template. These are offline
storage limits, not a request allowance. Non-finite numbers, non-JSON values and lone surrogates in a saved response are
rejected with its case ID before scoring; valid JSON with an invalid answer contract counts as unavailable. Excessive
JSON nesting and numeric aggregation overflow produce CLI errors rather than tracebacks.

Supply a separate settings file. The following values are **mechanical test examples only**, not calibrated candidates
or approved quality gates:

```json
{
  "schema_version": 1,
  "decision_version": "draft-2",
  "thresholds": {
    "coverage": {"false_max": 0.1, "true_min": 0.9},
    "compatibility_retention": {"false_max": 0.1, "true_min": 0.9},
    "independent_boundary": {"false_max": 0.1, "true_min": 0.9}
  }
}
```

Save explicitly selected settings to `/tmp/jev-settings.json`, then evaluate without credentials or a client:

```bash
uv run python scripts/experiments/jev/rule-pack-eval.py \
  docs/board/doing/jev_rule_pack/evidence/wrapper-corpus.json \
  --predictions /tmp/jev-predictions.json --settings /tmp/jev-settings.json
```

The report binds settings, saved predictions and adjudications separately and includes SHA-256 digests of the evaluator,
shared rule/outcome modules and A1 request/response modules. Changing a human label does not require a new capture, but
changes report identity. Changing evidence or prompt invalidates the saved observation. Changing only reviewer notes
changes neither model input nor semantic annotation identity.

## Metric interpretation

Reports separate constructed/historical cohorts, calibration/held-out splits, and individual repetitions. Repetitions do
not increase the unique case or source-family counts. Observed outcome variation lists cases whose saved outcomes
differ. Neither another model's answer nor a proposed label enters the confusion table as human truth.

- Confusion tables include uncertain/unavailable outcomes. Positive and negative abstentions remain explicit. Fixed
  unavailable-reason counts and bounded saved-failure counts distinguish missing evidence from request failures.
- Host rows retain outcome, reason, diagnostic, human label and agreement status. A separate confusion table and blocker
  expose conflicting host labels. Model `source_groups` counts only model-candidate families; host-only groups are
  reported separately.
- Assessed false-positive and miss rates use only labeled binary cases with warning/no-warning assessments. Effective
  miss rate also counts positive cases that abstained or lack a saved response. Coverage and warning rate use all model
  candidates in that repetition, including missing observations. The separate pipeline effective miss rate also counts
  host-decided human positives as misses, without treating host decisions as model results. These denominators must be
  considered together.
- Rates expose numerator, denominator and nominal Wilson 95% intervals. An empty denominator gives null, never zero.
  These intervals assume independent Bernoulli observations; shared templates/history can violate that assumption. They
  are descriptive summaries, not sufficient release evidence. Source-family counts remain visible.
- Per-question Brier scores and ten probability bins require explicit human per-question labels. Null answers and absent
  adjudications do not contribute. Final labels alone cannot establish question calibration.
- Latency uses nearest-rank p50/p95 on known observations; unknown latency includes all planned missing rows. Cost
  preserves independently valid reported values, including from malformed answers; absent cost or missing observations
  keeps the total unknown. Fixture accounting is synthetic. These summaries do not reconcile a provider invoice or infer
  how many unsaved attempts occurred.

`quality_accepted` remains false for every report. Fixture predictions, incomplete adjudication, missing observations
and absent historical evidence remain visible. The current evaluator does not implement a release verdict.

## Before real evaluation or runtime admission

Finish this feasibility stage before implementing declaration resolution, action envelopes, activation, cache/audit or
warning delivery. The existing transport, consent and offline-evaluation foundations are enough to prepare evidence;
building runtime machinery first would leave its central evidence assumptions untested.

### Representative evidence and practical usefulness

All 17 constructed cases have human outcomes, but the corpus has no historical cohort and only one held-out positive
family. First choose a separately reviewed acquisition scope or retain a constructed-only smoke-test claim. The latter
cannot establish runtime quality or authorize runtime implementation on that claim. An acquisition plan must name the
repository revision range or selected native actions, reconstruction assumptions, sanitization, local data retained,
exclusions and family split. Obtain the data decision before collection; native transcripts require explicit selection
and authorization. Keep actual hook actions, reconstructed actions and CLI whole diffs separate. Merged history and
marker searches are discovery sources, not semantic ground truth. Human reviewers must label acquired cases against
exact hashes with per-question answers, reviewer/reference identity, disagreements and exclusions recorded before
scoring. Keep each originating change and its related mutations within one split; recount positive/negative families.

Measure the proposed runtime restrictions on the selected real actions without expanding their evidence. Count total
actions, supported action shapes, complete before/after and replacement evidence, known governance, uniquely attributed
symbol exceptions, unknown/conflicting facts, mixed applicability, oversize inputs and each local-refusal reason. Report
both total-action and applicable-action denominators. Include representative partial method edits, aliases, renamed
symbols and mixed public/private files; an easy full-definition fixture cannot establish mapping feasibility. Use only
the selected action and separately attributed policy declaration; do not read undeclared file bodies to repair gaps.
These local measurements may use an offline prototype or manual mapping review; production runtime wiring waits for the
decision below.

Measure two distinct judgments. Packet-label accuracy assesses adherence to the bounded supplied-evidence rule.
Practical warning usefulness requires a separate human caller/contract review recording whether the warning exposes an
unnecessary retained interface or an unseen legitimate requirement, the evidence for that conclusion and unresolved
cases. Record useful warnings, unhelpful warnings and unresolved reviews with explicit denominators and review effort.
Never silently add that wider context to model payloads or replace the original packet-bound labels. A high packet
accuracy or low warning rate alone cannot pass this usefulness gate.

Compare two deterministic baselines with Jev: today's marker/regex checks and a bounded structural AST detector. Fix
each baseline's supported syntax and candidate rules before inspecting held-out outputs. Give all three the same action
bytes, applicability facts and admission limits; report unsupported/unknown cases explicitly. The AST baseline must not
use caller inventories unavailable to Jev or become an unbounded implementation of semantic boundary inference. Preserve
the regex comparison because it measures improvement over today's policy. The
[constructed baseline report](constructed-baselines.json) records raw signals from the bounded offline implementation;
its structural candidates do not establish semantic warnings or practical usefulness.

### Capture order and decision gates

1. Review independent positive/negative family counts and the required minimums for each evidence claim. Declare
   false-positive and effective/pipeline-miss limits, real-action coverage and symbol-mapping floors,
   practical-usefulness floor, warning-rate ceiling and uncertainty-interval treatment. Specify what unresolved
   usefulness reviews count against and the response to each failure: revise/re-evaluate, narrow scope or stop. These
   numerical choices remain unset until the inventory and claim support them; empty strata cannot pass.
2. Prepare the first bounded synthetic capture for the nine calibration model candidates only. Review exact payloads,
   repetitions, model snapshot, timeouts, physical request and cost limits including controls, dated price assumptions
   and provenance. Use a fresh isolated `FORGE_HOME`, clear cached runtime configuration, and copy no session history or
   user telemetry into it. Obtain explicit paid/data approval before dispatch; A1's exhausted approvals do not apply. A
   separate real-action manifest requires its own approved data scope. A constructed capture can reveal contract/model
   problems early while representative acquisition is being decided; it cannot substitute for that evidence.
3. Run only the authorized requests with ZDR, retries disabled, a physical request cap and a reported-cost stop check.
   Missing cost stays unknown; estimated spend and a post-response check cannot guarantee an invoice cap. Retain failed
   and interrupted attempts without silently repeating them. Select prompt wording and question bands using calibration
   responses only, then freeze prompt, settings, versions and split identities before inspecting held-out model outputs.
4. Prepare and separately authorize the four held-out model candidates after that freeze. Keep the four host-decided
   corpus cases outside provider captures. Report confusion, coverage, uncertain/unavailable reasons, calibration,
   warning burden, latency, reported cost and repeated-input variation by cohort/split/family against both baselines.
   Current held-out scenarios were exposed during rule development; these outputs are a limited check, not evidence of
   generalization to unseen scenarios. Repetitions add observations, not independent examples.
5. Review representative evidence sufficiency, governance/mapping refusals, useful warnings and model/baseline results
   against the predeclared gates. Record proceed, revise/narrow or stop before runtime implementation. Constructed-only
   success remains a smoke-test result. A runtime go-ahead needs the supported action/context matrix and evidence for
   these feasibility gates; final runtime integrations, telemetry joins, native delivery and release verification remain
   the separate checklist acceptance work. This document neither grants that go-ahead nor authorizes collection or
   spend.

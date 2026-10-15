# A2 offline evaluation plan

Status: methodology and report implementation ready for review; human labels, calibrated thresholds and numerical
acceptance limits remain unset. This document authorizes no collection, provider request or native trial. A1's probe
approvals do not carry over.

## Scope and current evidence

The [candidate contract](initial-rule-review.md) owns the broader compatibility-wrapper semantics. The
[corpus](wrapper-corpus.json) contains 17 constructed actions in seven source families: 12 calibration and five
held-out. Four cases are decided from fixture applicability/history facts; 13 require semantic assessment. Every
proposed label remains unadjudicated. There is no human-labeled historical cohort or measured model accuracy.

The shared `policy.rule_pack.definitions` module owns the unchanged draft-2 questions and contract version 3. The
`policy.rule_pack.outcomes` module owns decision version `draft-1`. These modules are available for offline evaluation;
they do not register a bundle, enable a session or dispatch a request. Runtime surface/exception authority remains a
separate gate.

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
  "decision_version": "draft-1",
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

1. A human reviewer must adjudicate outcomes and per-question answers against the exact case hashes, recording reviewer,
   reference, disagreements and exclusions. Count independent positive/negative source families in each cohort/split.
   Stop or narrow the claim when historical positives cannot support it; constructed cases cannot substitute for them.
2. Review minimum positive/negative counts, family independence, false-positive/miss limits, coverage floor,
   warning-rate ceiling and interval treatment. These numerical acceptance choices remain pending corpus feasibility.
   Select question bands only on calibration responses, then freeze settings and split identities before inspecting
   held-out results.
3. Review a bounded live manifest containing exact payloads, repetitions, timeouts, request/cost limits, provenance,
   sanitization and an isolated Forge home. Obtain explicit approval before dispatch. Any additional data acquisition or
   provider request needs its own approved scope.
4. Apply approved gates to captured responses, compare the deterministic baseline on the same eligible actions and
   resolve failures. Runtime fact resolution, hooks, telemetry joins and native delivery remain separate acceptance
   work.

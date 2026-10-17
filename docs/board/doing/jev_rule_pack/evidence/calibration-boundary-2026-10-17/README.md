# Boundary-instruction calibration result

The user approved the [exact nine-request manifest](../calibration-boundary-manifest.json) on 2026-10-17. Its single run
completed at `970de77a` under the [reviewed limits](../calibration-boundary-run-plan.md). All nine request slots are
consumed. No retry, control, held-out case, native action or repository history was sent.

The [capture journal](capture.json) retains sanitized responses, exact request and source identities, statuses and
timings. [Saved predictions](predictions.json) preserve evaluator schema 2 and the original case/payload identities. The
original output and isolated telemetry home remain at `/private/tmp/jev-a2-calibration-boundary-2026-10-17/`. Retained
JSON preserves the original values with repository formatting. The [first capture](../calibration-2026-10-16/README.md),
human labels and semantic criteria are unchanged.

## Transport and accounting

- Nine physical requests, one attempt each, nine HTTP 200 responses; no client, answer-contract or accounting failure.
- Every payload required ZDR and every response reported `typesafe/jev-1.13-20260917`.
- Reported usage: 12,308 input tokens and 549 output tokens. All costs were present and matched the declared price:
  **$0.000516936 total**, below the $0.05 planning allowance. Each case used 147 more input tokens than the first
  capture; each still reported 61 output tokens.
- Median client-call latency: **539.68 ms**. Nearest-rank p95 and maximum: **742.99 ms**. All nine calls were below the
  proposed five-second runtime stage. These timings include journal I/O and local telemetry, excluding initial
  credential resolution. This sample establishes neither an SLA nor repeated-input variability.
- All nine request IDs join the isolated downstream ledger under one capture run ID. A sampled
  `forge telemetry trace show` read succeeded. The retained [costs view](costs-by-verb.json) reports nine requests and
  one invocation with matching model/token totals. Its **$0.000517** total rounds each request to integer microdollars;
  the response-cost sum above preserves provider precision. Neither value reconciles an invoice.

The approved manifest reproduces from the capture revision, and saved predictions reproduce from the journal. Every
answer passes the typed validator. Compared with the first manifest, each payload changes only the boundary instruction;
coverage, retention, criteria, action evidence and case identity remain identical.

## Observations against human labels

The table records raw Noul probabilities. The final column is the boundary probability from the first capture. All nine
human coverage labels are true. Boundary is human-true only for `validation-boundary` and `callback-protocol`; retention
is human-false only for `module-direct-update`.

| Case                    | Human outcome | Coverage | Retention | Boundary | Prior boundary |
| ----------------------- | ------------- | -------- | --------- | -------- | -------------- |
| module-forwarding       | warning       | 0.63     | 0.94      | 0.12     | 0.09           |
| module-direct-update    | no_warning    | 0.47     | 0.21      | 0.08     | 0.09           |
| module-injection        | warning       | 0.56     | 0.94      | 0.08     | 0.08           |
| method-argument-adapter | warning       | 0.73     | 0.90      | 0.17     | 0.15           |
| validation-boundary     | no_warning    | 0.59     | 0.68      | 0.15     | 0.14           |
| validation-gratuitous   | warning       | 0.59     | 0.90      | 0.28     | 0.29           |
| preview-alias           | warning       | 0.64     | 0.95      | 0.12     | 0.12           |
| callback-protocol       | no_warning    | 0.48     | 0.81      | 0.28     | 0.16           |
| multi-file-wrapper      | warning       | 0.67     | 0.90      | 0.15     | 0.11           |

The two boundary-positive scores remain below every legal true cutoff. Callback's boundary score now equals the
gratuitous-validation negative at 0.28; the validation-boundary positive remains below that negative. Coverage is also
below every legal true cutoff for callback (0.45 before, 0.48 now) and the clean-break case (0.51 before, 0.47 now),
despite unchanged coverage instructions. Retention separates the single negative at 0.21 from the eight positives at
0.68–0.95 in this sample.

These are differences between historical single observations, without contemporaneous controls or repetitions. They do
not establish that the instruction caused an improvement or regression. The provider supplies no rationale, so these
scores do not identify which reasoning step failed.

## Decision: revise; do not calibrate around the failures

Under decision version `draft-2`, true cutoffs must exceed 0.5 and false cutoffs must be below 0.5. **All three human
`no_warning` cases are unrecoverable under any allowed settings for this capture.** For validation-boundary, retention
0.68 cannot classify false and boundary 0.15 cannot classify true, so it can only warn or abstain. Callback's coverage
0.48 and module-direct-update's coverage 0.47 independently prevent covered assessments. Callback's boundary answer also
fails the required distinction. This is not a fitted confusion table: no threshold settings were selected.

The instruction clarification did not resolve the calibration blocker. Keep settings unset and do not advance to
held-out capture or runtime wiring. Before another paid run, review whether to decompose contract identification and
replacement compatibility into separate questions, change model/rule fit, or stop this candidate. A semantic redesign
requires its own versioned contract and human review; the current evidence does not select one. Further wording changes
should have a concrete, reviewable hypothesis rather than silently repeating captures.

The [representative study](../feasibility-progress.md#approved-local-inventory) still lacks admitted native sources,
governance mapping and practical-usefulness evidence. Neither capture establishes generalization, and the two captures
must not be pooled as repetitions of one prompt. No approval for additional paid requests follows from this result.

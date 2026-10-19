# First A2 calibration capture

The user approved the [nine-request manifest](../calibration-manifest.json) on 2026-10-16 after offline checks. The
unchanged [run plan](../calibration-run-plan.md) ran once at `a6e748cb`; all nine request slots are consumed. No
held-out case, native transcript or historical repository action was sent. This approval cannot be reused for another
run.

The [capture journal](capture.json) retains request/model identities, source digests, status, sanitized responses and
client-call timings. [Saved predictions](predictions.json) use evaluator schema 2 and preserve the original case/payload
identities. The original output and isolated telemetry home remain at `/private/tmp/jev-a2-calibration-2026-10-16/`.
Retained JSON preserves captured values; formatting is normalized for the repository. Human labels and question text are
unchanged.

## Transport and accounting

- Nine physical requests, one attempt each, nine HTTP 200 responses and no client, contract or accounting failures.
- Every payload required ZDR; every response reported `typesafe/jev-1.13-20260917`.
- Reported usage: 10,985 input tokens and 549 output tokens. All nine costs were present and matched the declared input
  price: **$0.000461370 total**, below the $0.05 planning allowance.
- Median client-call latency: **523.75 ms**. Nearest-rank p95 and maximum: **724.51 ms**. All nine calls were below the
  proposed five-second runtime stage budget. Timings include capture journal I/O and local telemetry but exclude initial
  credential resolution; nine single observations establish neither an SLA nor repeated-input variability.
- All nine capture request IDs join the isolated downstream ledger. `forge telemetry trace show` resolved a sampled
  request. The retained [costs view](costs-by-verb.json) reports nine requests in one calibration run, with the same
  model and token totals. Its $0.000460 total rounds each request to integer microdollars; the response-cost sum above
  preserves provider precision. Neither value reconciles an invoice.

## Calibration observations

The three scores below are the returned Noul probabilities for coverage, compatibility retention and independent
boundary. The human outcome comes from the already reviewed calibration corpus. All nine human coverage answers are
true; the only retention-negative case is `module-direct-update`. Boundary is human-true only for `validation-boundary`
and `callback-protocol`.

| Case                    | Human outcome | Coverage | Retention | Boundary |
| ----------------------- | ------------- | -------- | --------- | -------- |
| module-forwarding       | warning       | 0.65     | 0.93      | 0.09     |
| module-direct-update    | no_warning    | 0.51     | 0.24      | 0.09     |
| module-injection        | warning       | 0.51     | 0.95      | 0.08     |
| method-argument-adapter | warning       | 0.72     | 0.90      | 0.15     |
| validation-boundary     | no_warning    | 0.59     | 0.74      | 0.14     |
| validation-gratuitous   | warning       | 0.61     | 0.89      | 0.29     |
| preview-alias           | warning       | 0.65     | 0.95      | 0.12     |
| callback-protocol       | no_warning    | 0.45     | 0.80      | 0.16     |
| multi-file-wrapper      | warning       | 0.68     | 0.90      | 0.11     |

## Calibration decision: revise

No allowed threshold bands can produce the human `no_warning` outcomes for either required-boundary case. Under
`draft-2`, every true cutoff must exceed 0.5 and every false cutoff must be below 0.5. Boundary scores 0.14 and 0.16
therefore cannot classify true. Their retention scores, 0.74 and 0.80, also cannot classify false. The combiner can only
abstain or warn on these cases; it cannot recover the required-boundary no-warning outcome. Callback coverage of 0.45
independently prevents a covered assessment.

The boundary-positive scores also overlap the seven boundary-negative scores, which range from 0.08 to 0.29. Moving
cutoffs to hide the hard cases would not demonstrate the intended distinction. Retention separates in this small sample
(one false at 0.24; eight true at 0.74–0.95), but coverage has no negative calibration examples. Those limitations do
not support a usable three-question calibration.

Leave threshold settings unset and do not prepare a held-out request from this calibration. Revisit the boundary
question/model fit before proposing another versioned, separately authorized capture. These observations do not identify
whether prompt changes, another snapshot or a different rule would resolve the problem. Any semantic change needs the
corresponding contract and human-review updates; exposed examples cannot establish generalization.

The separate [real-action study](../feasibility-progress.md#approved-local-inventory) still lacks admitted native
sources, attributable governance and usefulness evidence. Runtime implementation remains gated. This report records raw
calibration observations and threshold impossibility, not a tuned confusion table or a quality acceptance verdict.

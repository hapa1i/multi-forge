# Bounded diagnostic capture, 2026-10-18

**Decision: stop this model/formulation pairing. Neither arm passes the frozen diagnostic screen.** Jev triggered its
sentinel stop after two requests. Opus completed its 36 requests but disagreed with one critical human answer in all
three repetitions. No runtime or quality gate is accepted, and no further prompt, retry or capture is authorized by the
unused allowance.

The user explicitly authorized the [reviewed study](../bounded-capture-review.md) after implementation and fixture
verification. The runner executed at commit `2dea88cd`, using [manifest](../bounded-capture-manifest.json) digest
`2e5940f910d71eab4b9eaddd1bc183f349d1b04d21f5a0ed335cd77fd18a51c4`. Provider bodies, slots, scoring and limits match the
earlier proposal at `17c0b0de`; only implementation metadata changed. The 95 human answers remained frozen.

## Observed result

| Arm     | Requests sent / planned | Correct / observed answers | Planned answers | Reported USD |
| ------- | ----------------------- | -------------------------- | --------------- | ------------ |
| J: Jev  | 2 / 36                  | 16 / 20                    | 285             | 0.000378756  |
| R: Opus | 36 / 36                 | 282 / 285                  | 285             | 1.028852     |

All 38 attempts returned HTTP 200 and passed response/accounting admission. No technical stop, retry, unknown cost or
Jev probability tie occurred. The scheduler finished in 201.01 seconds after skipping Jev's 34 remaining slots. Reported
cost totals **$1.029230756**, below the $8 planning allowance; reported accounting is not an invoice guarantee.

Jev returned `typesafe/jev-1.13-20260917` from TypeSafe. Opus returned `anthropic/claude-opus-5.5` from Google on every
request. Its alias-only response does not establish the dated snapshot identity; the catalog's dated name and stable
response name do not prove immutable weights. Public endpoint/ZDR catalogs matched the frozen route, model, price,
supported parameters and token bounds before dispatch.

### Jev sentinel failure

Both Jev requests were for `validation-boundary`, with identical provider bytes. Both answered `partial` for
`parser.proposed_definition`, against the human answer `complete`. The proposed image supplies the whole
`parse_document` definition: the blank-input guard, `BlankDocument` exception and return through `decode_json`. The
second disagreement on this sentinel stopped J before its third repetition.

| Question                     | Human answer  | Repetition 1 | Repetition 2  |
| ---------------------------- | ------------- | ------------ | ------------- |
| `parser.proposed_definition` | `complete`    | `partial`    | `partial`     |
| `parser.consumer_constraint` | `established` | `none_shown` | `established` |
| `parser.decoder_blank_guard` | `no`          | `yes`        | `no`          |

The other seven answers agreed in both requests. These 20 observations come from one constructed case, leaving 265
planned Jev observations missing. They establish the declared stop, not its cause or general model accuracy.

### Reference critical failure

Opus answered every question correctly except `module-forwarding-without-replacement / normalizer.retention`. It chose
`retained` in all three repetitions, against the frozen human answer `not_supplied`. The case supplies the before/after
`normalize` definitions and its caller but only a call to `normalize_text`, without that replacement's definition or
interface contract. The reviewed retention criteria classify missing required definitions as `not_supplied`. Opus
separately answered `normalizer.replacement_definition=not_supplied` correctly each time.

This misses both the two-of-three agreement requirement and the three-of-three critical gate. Retention is a critical
question, not a sentinel, so it did not trigger early termination. The remaining cases, including all nine injection
answers and their same-repetition comparisons with the uninjected callback, passed. No labels or criteria were changed
after observing these outputs.

Only 20 question observations have both arms present: 16 were correct for both and four only for R. Missing Jev
observations supply no reference wins. Repetitions, shared templates, prior exposure and human-selected targets limit
generalization; this is not a production accuracy estimate or proof of automatic hook evidence selection.

## Latency and accounting

| Arm | Observed requests | Median  | Nearest-rank p95 / maximum | Over five seconds |
| --- | ----------------- | ------- | -------------------------- | ----------------- |
| J   | 2                 | 0.497 s | 0.634 s / 0.634 s          | 0 / 2             |
| R   | 36                | 5.330 s | 8.167 s / 11.793 s         | 21 / 36           |

Request latency includes reservation, HTTP and response validation. Evidence finalization is recorded separately;
aggregate local time was 0.019 seconds for J and 0.374 seconds for R. No deadline or finalization overrun occurred.
These small synthetic observations do not establish a hook latency guarantee.

The isolated telemetry readers found all 38 request/event joins and separate arm run IDs, with one invocation per arm.
Trace list/show/explain and cost-by-verb checks passed. The existing ledger rounds each attempt to integer microdollars:
[costs-by-verb.json](costs-by-verb.json) totals 1,029,230 microdollars, while the capture retains the exact reported
USD. No ambient session or grouping was attached to provider bodies or telemetry.

## Retained evidence

- [capture.json](capture.json): unchanged attempt evidence and run metadata, referencing the already tracked manifest
  instead of duplicating it; the machine-local claim path is omitted. It includes the original full journal's SHA-256.
- [report.json](report.json): per-question observations, critical gates, family/predicate summaries and paired counts;
  reproduces exactly from the original capture and frozen manifest.
- [traces.json](traces.json) and [costs-by-verb.json](costs-by-verb.json): isolated operator read surfaces.
- The original private journal and Forge home remain at `/private/tmp/jev-bounded-diagnostic-2026-10-18`. An exclusive
  local proposal claim and the published capture prevent replay. This allowance is consumed even though 34 slots were
  intentionally unused.

Before execution, 632 focused tests, five offline observability integration tests, pre-commit, manifest equivalence and
public catalog checks passed. No native session actions, repository history or conversations were sent. The existing
active classifier, human labels, unset thresholds and open feasibility gates remain unchanged.

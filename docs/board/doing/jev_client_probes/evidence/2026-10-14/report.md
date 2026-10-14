# Jev capture and measurement results — 2026-10-14

The OpenRouter Decisions route accepted synthetic Choice, Noul and Score requests with `provider.zdr: true`. All
successful responses resolved `typesafe/jev-1.13` to `typesafe/jev-1.13-20260917`, provider `TypeSafe`. This establishes
transport readiness for A1; A2/A3 remain proposed and have no decision-quality or quota-saving evidence.

## Authorization and provenance

The user approved the exact [four-request early manifest](../early-manifest.json), then the
[25-request measurement manifest](../measurement-manifest.json). Their planning budgets were $0.01 and $0.05,
respectively. Exactly 29 physical requests ran, with retries disabled. Inputs were fixed synthetic text only.
Credentials resolved read-only through the existing owner; every run wrote telemetry to a fresh isolated `FORGE_HOME`.
No sessions, configuration files or telemetry were copied from the user's home. However, credential resolution cached
the original home's runtime config, so these historical captures inherited its provider-trace settings. Approved-payload
comparison prevented unapproved attribution fields from being dispatched. The revised runner clears that cache after
switching homes; offline regression coverage verifies a previously enabled grouping setting is no longer inherited and
the original home's files remain unchanged. No further paid requests were run for this correction.

Captures retain the then-current Git revision/dirty state; measurement captures additionally record implementation
hashes. The source-artifact hashes identify original runner files, before retained JSON formatting and account-ID
redaction. `resumed_from_sha256` refers to those original bytes. Provider response IDs remain intact.

All live captures ran with uncommitted implementation changes over `bde11e5f`, before the final fixes and formatting.
Their recorded implementation hashes therefore differ from the PR code. The [offline replay record](replay.json)
identifies the exact source hashes checked after review: all 27 successful responses pass the current answer validator
and accounting checks; the malformed and over-limit HTTP 400 responses classify as `validation` and `payload_too_large`.
Replay uses the saved payloads and responses without inference. Historical timings and failure flags still describe the
original capture code, not the revised client.

- [Early interrupted capture](early-interrupted.json): one successful provider response; a capture-wrapper compression
  bug caused a local transport failure. The wrapper was fixed and an offline reproduction added.
- [Early complete capture](early-capture.json): continued with the remaining three approved requests, without repeating
  the first. Choice/Noul/Score passed replay; malformed questions returned HTTP 400.
- [Measurement interrupted capture](measurement-interrupted.json): 24 completed requests, stopping on one local Score
  parser refusal. Every response was HTTP 200 with valid reported accounting.
- [Measurement complete capture](measurement-capture.json): retained those 24 results, then used the last approved
  request for the over-limit control. The original failure flags remain historical evidence.
- [Summary](measurement-summary.json), [operator readback](observability.json) and
  [promoted fixtures](../../../../../../tests/fixtures/jev/README.md).

## Contract corrections from live evidence

One Score response reported 0.99 with probabilities `{0: 0.02, 1: 0.98, 2: 0}`. The displayed weighted mean is 0.98.
Independent rounding to two decimal places is consistent with this difference; the provider's internal calculation was
not observed. The original 0.001 tolerance was too strict for this capture. Validation now allows half a 0.01 unit per
probability and propagates that allowance through the weighted score, plus half a unit for score rounding. It preserves
every value and still rejects differences outside the bound. The captured case and a clearly inconsistent mutation are
tested offline. [TypeSafe's Score contract](https://docs.typesafe.ai/primitives/score) defines the weighted mean and
limits the scale to ten levels; the client admits 2–10.

The 120,234-byte wire control returned HTTP 400 containing `detail.error_type=max_tokens_exceeded`, not the documented
413\. The client recognizes this structured error type as `payload_too_large`, tolerating additional detail fields; other
400 responses remain validation failures. Neither is retried. The ordinary 30,000-byte guard was never weakened: only
the harness replaced the approved control payload at the transport boundary.

## Latency and size

Milliseconds are end-to-end client timings, including cached credential access, connection setup, parsing and local
telemetry. Initial credential resolution is excluded. Percentiles use nearest rank; with three samples, p95 is the
maximum. There were no live retries, rate limits or timeouts. The one initial Score parser refusal is included in its
shape's timings. These small samples are not an SLA or a quality evaluation.

| Shape         | N   | Serialized bytes | Reported input tokens | p50 ms | p95 ms |
| ------------- | --- | ---------------- | --------------------- | ------ | ------ |
| small         | 3   | 269              | 302                   | 469.8  | 628.8  |
| medium        | 3   | 4,554            | 1017                  | 370.1  | 476.5  |
| near-budget   | 3   | 29,754           | 5217                  | 434.5  | 542.8  |
| unicode       | 3   | 8,134            | 3196                  | 435.0  | 535.7  |
| code          | 3   | 6,154            | 1736                  | 407.5  | 415.3  |
| many-criteria | 3   | 2,384            | 1150                  | 386.3  | 399.1  |
| shared-one    | 3   | 1,835            | 577                   | 408.0  | 408.8  |
| shared-three  | 3   | 2,150            | 674                   | 415.5  | 432.7  |
| over-limit    | 1   | 120,234          | unknown               | 658.8  | 658.8  |

The near-budget English payload used 5,217 tokens despite taking 29,754 bytes; Unicode and code had different ratios.
Keep the 30,000-byte admission screen. These repeated synthetic shapes do not justify a general token ratio or prove
that all admitted inputs fit the provider's 32,000-token prompt limit. Provider size failures remain possible below the
screen. `tiktoken` is not a runtime requirement for this client.

The same state with one versus three questions used 577 versus 674 input tokens per request, with reported costs
$0.000024234 versus $0.000028308. This is evidence for these exact shapes, not a general linear billing rule.

## Answer repeatability

Identical serialized payloads did not always produce identical answers. The three Unicode Noul responses were 0.38, 0.35
and 0.33. For `shared-three`, Score confidence was 0.95, 0.98 and 0.97; its reported score stayed at 0.99 while the
distribution changed. The accompanying damage Noul response was 0.12, 0.14 and 0.12. Each shape's repeats have the same
payload SHA-256 in the manifest. These samples establish observed variance, not calibration or decision quality.
Consumer evaluations must account for repeat variance near thresholds; identical cache identity does not imply a
deterministic fresh answer.

## Accounting and operator visibility

The early successes reported $0.000039816. The 24 measurement successes reported $0.001747494, for $0.00178731 across
all 27 successes. Neither HTTP 400 control returned usage or cost; both remain unknown, not zero-cost claims. Reported
successful cost matched the dated catalog input price of $0.042 per million tokens, with output free. A post-response
check cannot guarantee an invoice cap. [Catalog source](https://openrouter.ai/api/v1/endpoints/zdr).

The measurement ledgers contain 25 downstream attempts and 25 usage events across the two isolated homes. Trace list,
show and explain found every local request ID. Cost by-model/by-verb reported 24 known-cost attempts plus one unknown;
per-attempt half-up conversion totals 1,746 micro-USD, which differs from rounding the aggregate raw cost. The initial
Score refusal retained its billed usage. No Jev traffic appeared in proxy metrics. Managed-session activity and
provider-grouping opt-in/off are covered by four offline integration cases; standalone live probes invent no session.

There was no reproducible live ZDR refusal or rate-limit response. Those paths remain deterministic fixture evidence.
Catalog membership and successful ZDR-required routing do not establish the provider's internal retention practices.
Attribution fields being transported does not prove provider-side recognition. Consumer quality, reviewer escalation and
quota effects remain outside A1.

## Verification

Final command results and PR handoff are recorded in the [A1 checklist](../../checklist.md). The epic remains active; A1
moves to done only after review and merge.

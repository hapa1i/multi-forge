# A2 synthetic calibration capture

Status: the user separately approved this exact nine-request manifest on 2026-10-16; its single run is complete and the
allowance is consumed. The [capture result](calibration-2026-10-16/README.md) records a semantic calibration blocker.
This is the first model observation for the already reviewed constructed corpus, not a runtime admission or
representative-quality claim. The [evaluation plan](evaluation-plan.md#capture-order-and-decision-gates) owns the order
and decision limits.

## Candidate and scope

Use the existing `typesafe/jev-1.13` request model and require the reported snapshot `typesafe/jev-1.13-20260917`. The
[2026-10-16 public catalog snapshot](2026-10-16-pricing.json) retains the selected fields from the
[OpenRouter ZDR catalog](https://openrouter.ai/api/v1/endpoints/zdr). Jev 1.14 is also listed but is outside this
proposal. The catalog's larger advertised context does not expand A1's conservative input admission.

Send one request for each of the nine calibration model candidates, with the current three Noul questions and their
exact supplied action/scope facts. The other three calibration cases are host-decided and make no request. All five
held-out cases are excluded. Payloads contain constructed examples and fixed rule text; reviewer names, notes, proposed
labels and human outcomes stay local. There are no native transcripts, historical repository changes or user-session
records in this capture.

The manifest must be regenerated and reviewed if the prompt, case evidence, model, request count, deadline or other
bound changes. Preparing a manifest does not select thresholds or approve dispatch.

The [retained manifest](calibration-manifest.json) contains all nine exact payloads, their identities and the source
digests checked before credential resolution. Prepared payloads range from 4,250 to 6,334 bytes. Reproduce it offline:

```bash
PYTHON_DOTENV_DISABLED=1 uv run python scripts/experiments/jev/rule-pack-capture.py > /tmp/jev-calibration.json
```

After explicit approval of that unchanged manifest, the completed run used:

```bash
PYTHON_DOTENV_DISABLED=1 uv run python scripts/experiments/jev/rule-pack-capture.py \
  --live --manifest docs/board/doing/jev_rule_pack/evidence/calibration-manifest.json \
  --output /private/tmp/jev-a2-calibration-2026-10-16
```

The output directory must not exist. Keep its isolated telemetry ledger; only reviewed, sanitized capture evidence may
be copied into this card. A1's exhausted approvals do not cover this command.

## Request and accounting limits

- Exactly nine planned physical requests; one attempt each, no retries or additional controls.
- ZDR required on every request, to `https://openrouter.ai/api/alpha/decisions` only.
- A 30-second deadline per client call; at most 270 seconds of cumulative call deadlines. This transport observation
  does not extend the proposed five-second runtime stage. Report whether each observed call meets that proposed limit.
- Published input price: $0.000000042 per token; output: $0, verified 2026-10-16. A1 observed input accounting grow with
  question count. Reserve 32,000 input tokens per question, three questions per request: $0.004032 per request and
  $0.036288 for all nine. Planning budget: $0.05. These are conservative planning bounds, not provider-enforced caps.
- Stop on the first transport/answer-contract failure, unexpected model, pricing inconsistency or reported cost over its
  bound. Missing reported cost remains unknown. A post-response stop cannot undo a charge. Interrupted or failed
  attempts remain recorded; any continuation needs a new reviewed request scope.

## Isolation and retained evidence

Use a new absolute output directory with a fresh `forge-home` beneath it. Resolve only the OpenRouter credential through
A1's existing owner, then clear cached runtime configuration and isolate session/run attribution. Copy no credentials
file, session history or user telemetry. Do not persist headers, credentials or account identifiers.

Retain the reviewed manifest, code digests/revision, bounded sanitized responses, original response byte sizes and
status codes, request IDs, elapsed times, failures and the cumulative physical-attempt count. Persist results after each
attempt. Export saved predictions in the evaluator's schema 2 with exact case/payload identities and the resolved-model
guard; failed attempts remain explicit and unsent observations remain missing. Malformed response bodies are withheld
while their byte counts and hashes remain; parsed sensitive-field values are redacted. Nine single observations cannot
measure repeated-input variation. No report can claim quality acceptance.

## After capture

Inspect calibration responses only. Record contract failures, question distributions and latency/accounting limits
before selecting question bands. Freeze the prompt, semantic versions, settings and split identities before preparing
any held-out request. A separate four-candidate held-out manifest requires its own approval. Exposed constructed
scenarios cannot establish generalization or practical warning usefulness; those require the separately scoped
representative study and caller/contract review.

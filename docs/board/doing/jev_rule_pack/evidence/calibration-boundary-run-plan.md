# A2 boundary-instruction calibration capture

Status: prepared on 2026-10-17; paid dispatch requires a new approval of the
[exact manifest](calibration-boundary-manifest.json). The first nine-request approval is consumed. Approving the
boundary instruction change and preparing this manifest do not authorize provider calls.

## Candidate and comparison

Use the [adopted boundary instruction](boundary-question-proposal.md#adopted-boundary-instruction) with unchanged
coverage and compatibility-retention instructions, shared guard, semantic criteria, human labels and decision contract.
The same nine constructed calibration cases each receive one request containing the three Noul questions. The three
host-decided calibration cases and all held-out cases make no request. Reviewer identities, notes and labels remain
local; payloads contain only constructed action evidence, fixed scope facts and rule text.

Compare the results with the [first capture](calibration-2026-10-16/README.md), which remains unchanged. The existing
runner fixes request order in the manifest and supplies one observation per case. There is no contemporaneous
original-prompt control or repetition. Any score difference is an observed difference between these runs, not an
established causal effect of the instruction or evidence of stability.

Inspect both boundary-positive cases, `validation-boundary` and `callback-protocol`, against all boundary-negative
controls, especially duplicated validation and the ordinary argument adapter. Record all three outputs for every case:
callback coverage was 0.45 in the first capture, so improving its boundary score alone may not recover `no_warning`.
Check retention as well; a change in one instruction can affect the combined response. No threshold settings are
selected by this plan, and no held-out or runtime work follows automatically from a successful transport run.

## Identity and dispatch

Request `typesafe/jev-1.13` and require reported model `typesafe/jev-1.13-20260917`. The
[OpenRouter endpoint catalog](https://openrouter.ai/api/v1/models/typesafe/jev-1.13/endpoints) still lists that snapshot
and the price below as verified on 2026-10-17. Do not substitute another model or snapshot if admission fails.

The manifest binds exact payloads, prompt/case identities and implementation digests before credential resolution. The
instruction change preserves human case identities but changes prompt and payload hashes. The first capture is evidence
for its recorded implementation; it is not a replayable manifest for the revised prompt. Regenerate and review this new
manifest if any bound changes before dispatch.

Prepared payloads range from 5,107 to 7,191 bytes. Offline comparison against the first manifest confirms that every
payload changes only `independent_boundary.instructions`; all 17 human case identities and the review packet remain
unchanged. The prompt SHA-256 is `d86acd463f9febcbadab104ee1006fb4c4040305b511f6af725f3d416eea3efb`.

Reproduce the proposal offline:

```bash
PYTHON_DOTENV_DISABLED=1 uv run python scripts/experiments/jev/rule-pack-capture.py \
  > /tmp/jev-calibration-boundary.json
```

Only after separate approval of the unchanged manifest:

```bash
PYTHON_DOTENV_DISABLED=1 uv run python scripts/experiments/jev/rule-pack-capture.py \
  --live --manifest docs/board/doing/jev_rule_pack/evidence/calibration-boundary-manifest.json \
  --output /private/tmp/jev-a2-calibration-boundary-2026-10-17
```

The output directory must not exist. The runner creates a fresh isolated `forge-home` beneath it, resolves only the
OpenRouter credential through A1's existing owner and isolates session/run attribution. No native actions, repository
history, transcripts or user telemetry enter this capture.

## Request and accounting limits

- Exactly nine physical requests at most, one attempt each, no retries, resumption or extra controls.
- ZDR required on every request to `https://openrouter.ai/api/alpha/decisions` only.
- A 30-second deadline per request, at most 270 seconds of cumulative call deadlines. Compare each observed latency with
  the proposed five-second runtime stage without treating this transport setting as a runtime budget change.
- Published input price verified 2026-10-17: $0.000000042 per token; output: $0. Retain the conservative allowance of
  32,000 input tokens per question, three questions per request: $0.004032 per request and $0.036288 for nine. This is a
  planning/accounting bound, not the endpoint's advertised context limit. Planning budget: $0.05; post-response checks
  cannot guarantee an invoice cap.
- Stop on the first transport/answer-contract failure, unexpected model, pricing inconsistency or reported cost above
  its bound. Missing cost stays unknown. A stop cannot undo a charge; interrupted attempts remain recorded. Any
  continuation needs a new reviewed scope and approval.

Retain the manifest, code revision/digests, bounded sanitized responses, status/byte counts, request IDs, elapsed times,
failures and physical-attempt count. Keep the isolated telemetry ledger. The runner persists after each attempt and
exports schema-2 saved predictions; failed attempts remain explicit and unsent observations remain missing. Malformed
bodies are withheld and sensitive-field values redacted. Only reviewed sanitized evidence may be copied into this card.

## Decision after capture

Review contract/accounting checks and the three question distributions before any calibration decision. Compare the two
legitimate-boundary cases with their negative controls; do not fit bands merely to turn difficult cases into
abstentions. If the instruction still misses the distinction, revisit question decomposition or model/rule fit under the
existing semantic-review requirements. Keep the representative-evidence and practical-usefulness gates open: nine
exposed constructed cases cannot establish either. The
[evaluation plan](evaluation-plan.md#capture-order-and-decision-gates) continues to govern threshold freezing and any
separately approved held-out capture.

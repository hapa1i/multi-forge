# Codex Responses probe results

## Probe verdicts

| Stage                              | Verdict                                                                                                                                              | Limit on the claim                                                                                                                            |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| 50 · Native Codex on loopback      | All four pins completed local tool use, follow-up and compaction with the launcher overrides, including the 0.141.0 floor.                           | The client hides the cap recovery at HTTP 429. Compaction retries differ by version.                                                          |
| 60 · ZDR                           | Passed the accepted account criterion. OpenRouter refused Qwen and served Astra with account ZDR and the request flag enabled.                       | The independent effect of the request flag is unverified. Only the structured refusal attributes the exclusion to the account.                |
| 70 · Cost and identity             | Astra reported cost on unary and streaming requests. The metadata header exposed the selected endpoint. All four generation IDs eventually resolved. | Lookup can lag. The receipts retain the BYOK field names without their values.                                                                |
| 80 · Native and HTTP compatibility | Native 0.170.0 completed both tasks. All 13 HTTP fixtures and the native Astra metadata run passed.                                                  | Live encrypted reasoning replay was exercised on Gemini. Astra emitted no reasoning item. The bridge buffered SSE and built upstream headers. |

## Paid acceptance through Forge on 2026-11-21

Native Codex 0.170.0 launched through the installed Forge wheel. With account ZDR enabled, each model read `fixture.txt`
using a local tool, then wrote the word it had read to `proof.txt` on the follow-up turn. Both files contained
`FORGE_FIXTURE_173`. Gemini displayed Codex's fallback model metadata warning and completed both turns.
[Approved manifest](paid-acceptance-manifest.json) · [Acceptance receipt](evidence/paid-36567394/acceptance.json)

| Model                    | Selected provider | Responses creates | OpenRouter credit (USD) | Forge (micros) | Encrypted reasoning replay |
| ------------------------ | ----------------- | ----------------: | ----------------------: | -------------: | -------------------------- |
| `openai/gpt-6.2-astra`   | Azure             |                 5 |               0.2390352 |        239,035 | Unverified on Astra        |
| `google/gemini-4-carbon` | Google            |                 5 |               0.0500030 |         50,003 | Observed on three requests |

All ten creates streamed, returned HTTP 200 and reported terminal usage. Two were title requests. Five downstream
records also flagged a client disconnect after recording final usage. Per-request rounding produced 289,038 micros from
$0.2890382 of reported OpenRouter credit. The traces, per-model cost summaries and proxy metrics agreed. Forge's daily
reject cap was $0.50. Each model's first generation lookup returned HTTP 200 and joined its local trace.
[Downstream records](evidence/paid-36567394/downstream.json) ·
[Reconciliation results](evidence/paid-36567394/acceptance.json)

The run used ten of 16 creates and three of seven metadata reads, including the dedicated-key check. The $5 key had a
20-minute expiry and included BYOK in its non-resetting limit. Every create carried `provider.zdr=true` and omitted
`client_metadata` and `prompt_cache_key`. Codex made four local identity reads and no catalog requests. The upstream
received no `openai-beta` header on these ten requests. [Key setup](evidence/paid-36567394/key-setup.json) ·
[Acceptance receipt](evidence/paid-36567394/acceptance.json)

## Direct route acceptance on loopback

The 0.170.0 TUI used the packaged Forge proxy for a local read and a follow-up edit on each slug. Both scratch files
contained the expected word and the provider received the matching tool results. Astra and Gemini each used five
creates, including a title. The client made no catalog request. Gemini displayed its fallback model metadata warning.

The fixture supplied $0.0100004 per create. Per-request rounding produced 50,000 micros per model. The individual
traces, cost summaries and running metrics agreed. Both remote lookups joined on the third read, after the fixture
returned two 404s. The run used ten creates and seven metadata reads, including the dedicated-key check.
[Loopback receipt](evidence/forge-tui-acceptance-loopback.json) · [Live scope](paid-acceptance-manifest.json)

## Follow-up loopback controls

The four pinned Codex binaries ran 72 additional cases against a local stub, with 210 POSTs. Each comparison included
the TUI and `exec`. Every case ended within its request and time limits. The receipt records the envelopes, headers,
metadata placement, per-client counts and visible diagnostics. [Loopback receipt](evidence/review-loopback.json)

| Control                                                                        | Observed result                                                                                                                                                                                             |
| ------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Same spend-cap message, code and headers with both OpenAI and Anthropic bodies | At HTTP 400, all eight client/version pairs showed `costs.caps.per_day` with either body. At HTTP 429 all eight showed a generic 429 with either body. Each used one foreground POST.                       |
| Ingress's actual invalid-body 400                                              | All eight displayed “Request body must be a JSON object” from the Anthropic-shaped envelope.                                                                                                                |
| Cap first applied to the compaction request                                    | With a 200,000-token completion and a 1,000-token threshold, 0.141.0, 0.149.1 and 0.161.0 each sent six compaction POSTs. 0.170.0 sent one. Every compaction POST received 429. All clients ended the turn. |
| Provider's sanitized 402 credit message                                        | All eight displayed the reason and both token counts. Each sent six foreground requests. The 0.161.0 and 0.170.0 TUIs also sent six title requests each.                                                    |
| Selected endpoint in the SSE response                                          | With `openrouter_metadata` in the `response.created` and `response.completed` response objects, all 16 version/mode/model combinations completed the tool read and follow-up.                               |

Changing only the cap envelope cannot expose the recovery setting on these pins. Forge's Responses ingress shares the
429 with the LiteLLM route. On a running LiteLLM Responses proxy, `forge proxy metrics <id>` displayed the reached cap,
the exact amount and the instance-specific setting. One foreground retry and six replayed compaction attempts all
stopped locally. The first live 402 bridge stopped forwarding after one refusal. The six-attempt result above measures a
client that keeps receiving 402 from the stub.
[Integration](../../../../tests/integration/proxy/test_codex_openrouter_responses_e2e.py) ·
[Live 402 receipt](evidence/paid-0a6ac1d0/codex.json)

The 402 put the Astra admission estimate at $2.62144 for the reported 65,536-token allowance. A dedicated $5 key
subsequently admitted the unmodified request. Its first native Astra response reported $0.123214. The receipt retained
no cached-input count for that request. These figures distinguish an observed credit requirement from the cost of the
completed generation. [Credit refusal](evidence/paid-0a6ac1d0/codex.json) ·
[Stage 80 receipt](evidence/paid-63d4a6f0/codex.json)

The last stage 70 stream's third lookup succeeded 17.15 seconds after the first lookup was reserved. The pauses were 4
and 12 seconds plus request time. Stage 80's raw costs sum to $0.4547193. Rounding each of the 35 requests to the
nearest microdollar yields 454,718 micros. Rounding the total once yields 454,719. Acceptance compares the same
per-request units Forge stores. [Lookup ledger](evidence/paid-0a6ac1d0/state.json) ·
[Per-request costs](evidence/paid-63d4a6f0/codex.json)

### Native Codex spend caps through Forge

With `codex-responses-local` at `b3929615`, each TUI and `exec` run admitted one foreground request. The loopback
provider reported $0.125 and 200,000 input tokens for that request, reaching the daily reject cap and triggering Codex's
1,000-token compaction threshold. A fresh launch then sent a foreground turn to the same capped proxy.

| Codex   | Mode | Compaction POSTs refused | Fresh foreground POSTs refused | Title POSTs refused across both launches | Upstream POSTs |
| ------- | ---- | ------------------------ | ------------------------------ | ---------------------------------------- | -------------- |
| 0.161.0 | exec | 6                        | 1                              | 0                                        | 1              |
| 0.161.0 | TUI  | 6                        | 1                              | 3                                        | 1              |
| 0.170.0 | exec | 1                        | 1                              | 0                                        | 1              |
| 0.170.0 | TUI  | 1                        | 1                              | 2                                        | 1              |

All 23 refused requests stopped at Forge. Both clients showed generic 429s. In every case `forge proxy metrics <id>`
identified the reached cap and the recovery setting. The TUI turns ended and the exec processes exited within the
harness deadline. The direct OpenRouter template still needs this check.
[Loopback receipt](evidence/forge-cap-loopback.json)

## Stage 80 passed on 2026-11-20

With account ZDR enabled, Codex 0.170.0 read `fixture.txt` through a local tool, resumed the same thread, and wrote
`FORGE_FIXTURE_173` to `proof.txt` on both Astra and Gemini. The harness verified each edit on disk. All eight native
baseline requests used the original Codex bodies and omitted `max_output_tokens`. The $5 dedicated key admitted the
Astra request that had returned HTTP 402 under the $2 cap. [Approved manifest](paid-probe-manifest-codex-only.json) ·
[Live receipt](evidence/paid-63d4a6f0/codex.json) · [Earlier credit refusal](evidence/paid-0a6ac1d0/codex.json)

| Live check                                                      | Result                                                       | Responses POSTs | Reported cost (USD) |
| --------------------------------------------------------------- | ------------------------------------------------------------ | --------------: | ------------------: |
| Native Astra, default tools                                     | Read and resumed edit with `functions.exec`                  |               4 |           0.1441384 |
| Native Gemini, default tools                                    | Read and resumed edit with `exec_command`                    |               4 |           0.0502313 |
| HTTP replay with ZDR and routing metadata                       | 10 verified tool continuations and 3 schema-valid titles     |              23 |           0.1164140 |
| Native Astra with ZDR, routing metadata and web search disabled | Read and resumed edit, Azure identified on all four requests |               4 |           0.1439356 |
| **Total**                                                       | **35 HTTP 200 streams ended with `response.completed`**      |          **35** |       **0.4547193** |

Gemini logged the fallback-metadata warning on both turns. Its default native requests declared `web_search`, and the
streams contained no hosted-tool execution events. Astra used a custom tool declared in `additional_tools`. Both models
accepted the native `client_metadata` fields. [Native request shapes and diagnostics](evidence/paid-63d4a6f0/codex.json)

All ten tool fixtures continued with the returned tool call, its matching ID and the synthetic read result. All five
Gemini tool fixtures also replayed encrypted reasoning. The five Astra tool fixtures supplied no encrypted item, so
encrypted replay on Astra remains unverified. All 27 requests with `provider.zdr=true` and `X-OpenRouter-Metadata`
identified the selected provider and model. Azure served 16 requests on `openai/gpt-6.2-astra-20261117` and Google
served 11 on `google/gemini-4-carbon-20261110`. [Live replay and routing evidence](evidence/paid-63d4a6f0/codex.json)

The run used 35 of 40 allowed generation attempts and one key read. The total above sums OpenRouter's `usage.cost` on
all 35 responses. One management POST created a 20-minute, non-resetting $5 key with BYOK included. The standalone
loopback rehearsal used the same request counts. [Attempt ledger](evidence/paid-63d4a6f0/state.json) ·
[Key setup](evidence/paid-63d4a6f0/key-setup.json) · [Loopback receipt](evidence/codex-only-loopback.json)

## First live run of stages 70 and 80 on 2026-11-20

**Stage 70 passed. Stage 80 stopped on its first native Astra request with HTTP 402.** The approved manifest ran once on
the stage 60 account with ZDR enabled. The runner used one dedicated, non-resetting $2 key with BYOK included and a
20-minute expiry. It reserved six generation attempts and ten metadata reads. One management POST created the key.
[Approved manifest](paid-probe-manifest-cost-codex.json) · [Attempt ledger](evidence/paid-0a6ac1d0/state.json) ·
[Key setup](evidence/paid-0a6ac1d0/key-setup.json)

### Stage 70 · Cost and provider identity

All four Astra Responses requests completed. Each used the same one-word task, `store=false`, `provider.zdr=true` and a
128-token output limit. Both streams delivered `response.completed` with final usage. The metadata header identified the
selected provider and model on both requests that enabled it. [Cost receipt](evidence/paid-0a6ac1d0/cost.json)

| Mode   | `X-OpenRouter-Metadata` | `usage.cost` (USD) | Selected provider | Generation lookup (HTTP) |
| ------ | ----------------------- | -----------------: | ----------------- | ------------------------ |
| Unary  | Omitted                 |           0.000304 | Unreported        | 200                      |
| Unary  | `enabled`               |           0.000304 | Azure             | 200                      |
| Stream | Omitted                 |           0.000304 | Unreported        | 200                      |
| Stream | `enabled`               |           0.000304 | Azure             | 404, 404, 200            |

Both Azure samples named `openai/gpt-6.2-astra-20261117`. On all four calls, the Responses body ID matched the
`x-generation-id` header and resolved through `/api/v1/generation`. The completed Chat Completions indexing control
resolved on its second lookup (404, 200). The public receipt substitutes stable labels for the five IDs so the matches
and retry sequence remain visible. Stage 70 used five generations and nine metadata reads. The next key check showed
$1.998480 remaining, a decrease of **$0.001520**. [Cost receipt](evidence/paid-0a6ac1d0/cost.json) ·
[Stage 80 key check](evidence/paid-0a6ac1d0/codex.json)

### Stage 80 · Native Codex and HTTP replay

Codex 0.170.0 sent a streaming Astra request with the client's default tools and no explicit `max_output_tokens`.
OpenRouter returned HTTP 402 on the first POST. Its message said, “This request requires more credits, or fewer
max_tokens. You requested up to 65536 tokens, but can only afford 49962.” The receipt redacts the key-specific dashboard
URL. The process exited with code 1 before the first scratch-file read completed.
[Native Codex receipt](evidence/paid-0a6ac1d0/codex.json)

The stage used one key read and one generation attempt. It stopped before the first turn completed. The maintainer
selected a higher dedicated-key limit for the stage 80 retry so the original native request could run.
[Native Codex receipt](evidence/paid-0a6ac1d0/codex.json)

## Stage 60 passed on 2026-11-20

With account ZDR enabled and `provider.zdr=true`, OpenRouter refused Qwen and served Astra. The maintainer accepted the
previously recorded Qwen HTTP 404, which explicitly named zero data retention. The continuation verified the hashes of
that receipt and the earlier account-policy refusal. The fresh ZDR catalog listed Astra and omitted both Qwen slugs
across 1,051 entries. The sole generation went to `openai/gpt-6.2-astra` with `store=false`. It returned HTTP 200 and
completed, nonempty assistant text. The independent effect of the request flag remains unverified.
[Accepted Qwen refusal](evidence/paid-2feeec7f/zdr.json) · [Astra result](evidence/paid-1ee865aa/zdr.json)

OpenRouter reported **$0.000304** in `usage.cost` for the Astra response. It supplied no selected provider or endpoint
in the fields the harness inspects. The two metadata reads returned HTTP 200. One separate management call created a
20-minute key with a non-resetting $2 limit including BYOK. The published receipts omit request and response
identifiers. [Attempt ledger](evidence/paid-1ee865aa/state.json) · [Key setup](evidence/paid-1ee865aa/key-setup.json)

The loopback listener received the same two reads and one Astra POST. The regression suite covers refusal-receipt
tampering, an additional model or fallback, and a positive response with blank text or incomplete status.
[Loopback receipt](evidence/astra-positive-loopback.json) ·
[Continuation manifest](paid-probe-manifest-astra-positive.json)

## Stages 70 and 80 on loopback

On loopback, stage 70 used five generations and three reads. Stage 80 used 35 generations and one read. Pinned Codex
0.170.0 completed the scratch read, resume and edit on both models. The stub returned selected-provider metadata and
triggered the additional Astra run. All 13 HTTP fixtures passed in 23 requests. The native baselines kept the client's
original request bodies, as required to test compatibility under the account policy. The policy replays and additional
Astra run sent `provider.zdr=true`. [Loopback receipt](evidence/cost-codex-loopback.json)

## Qwen paid run on 2026-11-19

OpenRouter returned HTTP 404 on the baseline `POST /api/v1/responses` for `qwen/qwen4-max` with `provider.zdr` omitted.
At `Filter by Guardrails`, the only entry in `error.metadata.ineligibility_reasons` was `zdr-violation-by-account`, with
`endpoint_count: 1`. The account's **All other models → ZDR only** setting excluded Qwen's sole Alibaba endpoint. The
signed-in privacy dashboard confirmed that setting. The workspace default guardrail was unconfigured, and the management
API returned no explicit key or member guardrail assignments. [Stage 60 receipt](evidence/paid-3bb021f0/zdr.json) ·
[Account privacy settings](https://openrouter.ai/settings/privacy)

The original receipt recorded the first message line, body length and SHA-256. The reconstructed 625-byte HTTP body
matches that digest, `6ae1793c7b1c43899a5569ce8adf967485e631f164e20024034e64e9a1e623ab`. Replaying those bytes offline
now retains the reason, endpoint count and privacy settings URL in the diagnostic. The regression uses a synthetic
request-level refusal for the comparison. The only live Qwen refusal in this run came from account ZDR.
[Exact-response regression](../../../../tests/regression/test_bug_stage60_openrouter_ineligibility_reasons.py)

| Stage                             | Outcome                                                                                                                                                 | Completed requests                                                  |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| 60 · ZDR enforcement              | Inconclusive. The live catalog listed Astra and omitted both Qwen IDs among 1,047 entries. The Qwen baseline failed before either ZDR-required request. | Key and catalog GETs returned 200. One Responses POST returned 404. |
| 70 · Cost and identity            | Unstarted after stage 60.                                                                                                                               | 0                                                                   |
| 80 · Native Codex and HTTP replay | Unstarted after stage 60.                                                                                                                               | 0                                                                   |

The maintainer approved all three stages of manifest `3bb021f0`. A separate management request created the dedicated key
with a 20-minute expiry. The stage verified $2.00 available at startup, a non-resetting $2.00 limit, and BYOK charges
included. There were two metadata reads, one generation attempt and zero successful generations. Final billed spend was
unmeasured. [Attempt ledger](evidence/paid-3bb021f0/state.json) · [Approved manifest](paid-probe-manifest-qwen.json)

### Revised stage 60 on this account

The maintainer selected a narrower criterion that keeps **All other models → ZDR only** enabled. Its purpose was to
verify that Qwen is refused and Astra can return text on this account when both requests specify `provider.zdr=true`.
Account ZDR also excludes Qwen when the field is omitted, so the independent effect of the request flag remains
unverified.
[OpenRouter's per-request ZDR rules](https://openrouter.ai/docs/guides/features/zdr#per-request-zdr-enforcement)

**The live run of `2feeec7f` was inconclusive.** Qwen returned HTTP 404 with `provider.zdr=true`. OpenRouter said, “No
endpoints found matching your data policy (Zero data retention).” The diagnostic contained no structured exclusion list
or endpoint count. The approved manifest required both, so the harness stopped before sending the Astra request. The
message identifies ZDR as the reason for refusal. The account and request settings were both active.
[Live receipt](evidence/paid-2feeec7f/zdr.json) · [Approved manifest](paid-probe-manifest-qwen-account-zdr.json)

The key check and ZDR catalog both returned HTTP 200. The catalog listed Astra and omitted both Qwen slugs across 1,052
entries. The ledger recorded two metadata reads and one generation attempt. One separate management POST created the
20-minute, non-resetting $2 key with BYOK included. Final billed spend was unmeasured.
[Attempt ledger](evidence/paid-2feeec7f/state.json) · [Key setup receipt](evidence/paid-2feeec7f/key-setup.json)

The approved manifest specified the following checks in order.

1. Verify the key's credit limit and refresh the ZDR catalog. Require `openai/gpt-6.2-astra` to be listed and both the
   public and dated canonical Qwen slugs to be absent.
2. Submit the original synthetic Qwen task with `provider.zdr=true`. Require HTTP 400, 403, 404 or 422 with a complete,
   nonempty exclusion list. Every entry must have a positive endpoint count and name `zdr-violation-by-account` or
   `zdr-violation-by-request`. Stop if Qwen is served or the refusal is inconclusive.
3. Submit the one-word task to Astra with `provider.zdr=true`. Require a completed assistant text response.

**Loopback passed for manifest `2feeec7f`.** The listener received two metadata GETs and exactly two Responses POSTs.
Both POSTs used `provider.zdr=true`, `store=false` and the single-word task. The stub returned HTTP 404 for Qwen with
`zdr-violation-by-account` and one excluded endpoint, then HTTP 200 with completed text for Astra. The harness read the
historical baseline from its pinned receipt. All 29 targeted regressions passed at that point.
[Loopback receipt](evidence/qwen-account-zdr-loopback.json)

## Replacement for the Fable control

On 2026-11-19, OpenRouter advertised `/api/v1/responses` for `qwen/qwen4-max` and listed one Alibaba endpoint. Neither
the public slug nor its canonical slug, `qwen/qwen4-max-20261115`, appeared in the 1,052-entry ZDR catalog. The same
catalog had one entry for the Astra positive control. Alibaba also demonstrates a native Responses request using this
exact model. [Dated catalog evidence](evidence/qwen4-max-catalog.json) ·
[Alibaba Responses example](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-responses)

The [Qwen manifest](paid-probe-manifest-qwen.json) uses the same synthetic prompt for its unrestricted and required-ZDR
requests. Qwen defaults to high reasoning effort, so both use its advertised `none` setting to leave the 128 output
tokens for a visible answer. A completed text baseline establishes availability for this account. A subsequent
policy-specific refusal establishes ZDR enforcement. A generic 404 leaves the question open.

The revised harness retained a simulated baseline failure's provider message, code and nested upstream cause. The
loopback tests also exercised a JSON error in an HTTP 200 response, a failed event in a stream, and an unreadable error
body. All 13 replay fixtures and both native scratch edits completed on loopback.
[Qwen manifest loopback receipt](evidence/qwen-loopback.json)

## Fable paid run on 2026-11-19

The approved run stopped in stage 60. OpenRouter returned HTTP 404 when asked to generate a one-word response on
`anthropic/claude-fable-5.2` with no `provider.zdr` setting. The negative control requires that same model to succeed
unrestricted before a refusal with ZDR required can establish enforcement. The receipt contains the baseline HTTP status
only. The provider's reason for the 404 and any billed amount are unknown.
[Stage receipt](evidence/paid-53895a11/zdr.json)

| Stage                             | Outcome                                                                                                                                                                           | Requests completed                                 |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| 60 · ZDR enforcement              | Inconclusive. The live ZDR catalog listed Astra and omitted Fable among 1,047 entries. The unrestricted Fable baseline returned 404, so both ZDR-required requests were untested. | 2 metadata GETs (both 200), 1 Responses POST (404) |
| 70 · Cost and identity            | Unstarted after stage 60. Live unary and streaming cost, provider identity and generation lookup remain unknown.                                                                  | 0                                                  |
| 80 · Native Codex and HTTP replay | Unstarted after stage 60. Live tool use and replay compatibility remain unknown for both models.                                                                                  | 0                                                  |

The operator approved manifest `53895a11` and separately authorized creation of a dedicated key. The authenticated key
check confirmed USD 2.00 available at startup, a non-resetting limit of USD 2.00, and BYOK charges included. Key
creation was a separate management request. The probe ledger recorded one generation attempt and two metadata attempts.
The run produced zero successful generations. Each stage can start once under this manifest.
[Attempt ledger](evidence/paid-53895a11/state.json) · [Approved manifest](paid-probe-manifest.json)

## Free loopback run

On 2026-11-19 the four pinned macOS arm64 Codex clients completed 104 loopback cases. The stub received 276 requests,
all streaming `POST /v1/responses` with `store: false` and no non-null `previous_response_id`. This includes the 36
title requests. No client queried the model catalog or a Responses subresource. OpenRouter received zero model requests.
[Per-request evidence](evidence/loopback-requests.csv)

## Tool use and compaction

| Codex   | Astra with default web setting                                         | Gemini with default web setting          | TUI title requests across two successful user turns |
| ------- | ---------------------------------------------------------------------- | ---------------------------------------- | --------------------------------------------------- |
| 0.141.0 | Functions, namespaces, hosted web search                               | Same                                     | 0                                                   |
| 0.149.1 | Functions, namespaces, hosted web search                               | Same                                     | 0                                                   |
| 0.161.0 | Functions, namespaces, hosted web search                               | Same                                     | 1                                                   |
| 0.170.0 | Namespaced custom `functions.exec` in an `additional_tools` input item | Functions, namespaces, hosted web search | 1                                                   |

All 32 tool cases exercised a real local shell read. The next create carried its matching call ID and the value read
from `fixture.txt`. The second TUI prompt or resumed `codex exec` turn carried that history and displayed the stub's
follow-up response. Disabling web search removed the hosted declaration wherever it appeared. On 0.170.0, Astra already
omitted it. Codex showed its fallback-model-metadata warning for both slugs through 0.161.0 and for Gemini on 0.170.0.
0.141.0 therefore clears the **local launcher floor** for this task with the override.

All 16 forced-compaction cases used ordinary create requests. The stub reported 200,000 tokens against a configured
1,000-token threshold. Codex sent its compaction prompt, received `FORGE_COMPACT_SUMMARY`, and included that summary in
the follow-up. A create-only route covered the observed control traffic.

Foreground requests carried session, thread, turn, installation and window identifiers and nested turn metadata.
`root_turn_id` appeared from 0.149.1. All 18 retained fixtures have a `prompt_cache_key` equal to the session and thread
IDs in `client_metadata`. The fixtures use synthetic identifiers. Their input arrays contain no reasoning item. The
checklist assigns the synthetic encrypted-item test and the identifier policy decision.
[Execution checklist](checklist.md)

The fixture index maps each capture to its client, model, source request and SHA-256. Thirteen distinct admissible
first-request bodies cover ten foreground tool layouts and three title layouts. The 0.170.0 Astra body includes
`text.verbosity` and `reasoning.context`. Its Gemini counterpart carries `reasoning.summary`. The hosted web control is
for offline tests. [Fixture index](evidence/fixture-index.json)

## Refusals and retries

Each row covers four binaries in both TUI and `exec`, using the default Astra slug. The stub injected the refusal on a
create. All eight clients ended the foreground turn on their own in every row. The PTY driver then closed the
interactive session. Newer TUIs generated their own title requests, which received the same refusal.

| Injected response                          | Foreground POSTs per case | Total POSTs per case including titles | What the operator saw on all eight clients                     |
| ------------------------------------------ | ------------------------: | ------------------------------------: | -------------------------------------------------------------- |
| Hosted tool, 400                           |                         1 |                                   1–2 | `allow_non_zdr=true`                                           |
| Subresource, 400                           |                         1 |                                   1–2 | Only `POST /v1/responses` is supported                         |
| Missing cost, 403                          |                         6 |                                  6–12 | The cost override and restart instruction, after retries       |
| Missing cost, 400                          |                         1 |                                   1–2 | The same override and restart instruction on the first attempt |
| Translated ZDR refusal, 400                |                         1 |                                   1–2 | Inspect the model or set `allow_non_zdr=true`                  |
| Spend cap, 429, marked control             |                         1 |                                   1–2 | Generic 429                                                    |
| Spend cap, 429, Forge envelope and headers |                         1 |                                   1–2 | Generic 429. The `costs.caps.per_day` recovery was hidden      |

Use the measured HTTP 400 and nested `error.message` for the proposed deterministic local refusals. Missing-cost 403
retries were 0.187–3.462 seconds apart and took 5.977–6.588 seconds from first to last foreground attempt. The existing
429 controls ended the turn but hid the cap-specific message. The operator can inspect the running proxy with
`forge proxy metrics <id>`. [Follow-up controls](#follow-up-loopback-controls) ·
[Stub envelopes](../../../../scripts/experiments/openrouter/helpers/responses_stub.py) ·
[Forge's existing 429](../../../../src/forge/proxy/responses_ingress.py)

## Paid controls tested on loopback

Six concurrent generation requests using separately opened ledgers contended for two reservations. The listener received
exactly two. A 1.5-second process deadline swept a detached child and left zero survivors. A canned upstream also
exercised ZDR controls, explicit zero cost, provider metadata, and both function and custom-tool replay. All 13 paid
replay candidates passed against the canned server in 23 creates, including three schema-validated titles. Against that
upstream, native 0.170.0 read the synthetic file, resumed the thread and correctly wrote `proof.txt` on both models,
using four creates apiece. These measurements describe the local fixture run. [Guard evidence](evidence/guard.json) ·
[Paid manifest](paid-probe-manifest.json)

## Reproduction and binary identity

Run stage 50 with the retained distributions and a fresh private capture directory. The three npm distributions were
verified against their registry SHA-512 integrity values. The 0.170.0 distribution was copied from the local install.
`ROUND` denotes the private run directory. The capture's `50-loopback/binaries.json` records the absolute paths.
[Harness instructions](../../../../scripts/experiments/openrouter/README.md)

| Codex   | Executable under `ROUND`                                        | Native executable SHA-256                                          |
| ------- | --------------------------------------------------------------- | ------------------------------------------------------------------ |
| 0.141.0 | `runtime/0.141.0/package/vendor/aarch64-apple-darwin/bin/codex` | `51f848c212ee24e8da923a7175813a74c113d47e01f0d40f1fea46b12644c363` |
| 0.149.1 | `runtime/0.149.1/package/vendor/aarch64-apple-darwin/bin/codex` | `f0d8762236594359b60cfbe17f4c7e945a3ce8d1c91e74778838c968d250fb6c` |
| 0.161.0 | `runtime/0.161.0/package/vendor/aarch64-apple-darwin/bin/codex` | `12ac11d2c7eee27cfae34393986d7b7c9ed0dea537cb749831cdd7033893e6de` |
| 0.170.0 | `runtime/0.170.0/bin/codex`                                     | `9248cfeebec9b4cc3034d5114caab10fbf426cbfa79dba410c5fa1b72762abd6` |

The retained run answered each auxiliary title request with the JSON object Codex requested. An earlier run returned
plain text and produced six extra title attempts on 0.161.0. The counts above use the corrected run.

The request CSV gives elapsed seconds from that case's stub start and marks title, follow-up, tool-result and compaction
requests individually. The full private capture passed `sanitize.sh`. All 104 process guards reported zero remaining
processes.

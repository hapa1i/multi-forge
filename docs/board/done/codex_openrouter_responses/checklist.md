# Launch Codex through a direct OpenRouter proxy

**Completed 2026-11-21.** Both native sessions passed on the packaged Forge proxy with account ZDR enabled. OpenRouter
reported $0.2890382 across ten creates. [Paid acceptance receipt](evidence/paid-36567394/acceptance.json) ·
[Probe results](probe-results.md) · [Card](card.md)

**Probe models.** Use `openai/gpt-6.2-astra` as the template default and `google/gemini-4-carbon` for explicit `-m`
selection. Astra is the Sonnet-tier default on the shipped local Responses template. The existing
`openrouter-openai-codex` Messages template selects a different Sonnet model.

## 1. Establish the provider and client contracts

- [x] The maintainer approved this checklist on 2026-11-19 and authorized the free loopback probes.
- [x] Add the Responses stages to the OpenRouter runner's `EXPLICIT_STAGES`. Reuse the Codex harness's retained packages
  and TUI process controls. Run each stage separately. Keep raw captures in private, run-specific directories under
  `OPENROUTER_CAPTURE_DIR`. Run `sanitize.sh` before retaining fixtures. Put verdicts and fixture references in this
  card's `probe-results.md` and correct the harness README's pointer to the earlier card's evidence.
  [OpenRouter harness](../../../../scripts/experiments/openrouter/README.md) ·
  [Codex harness](../../../../scripts/experiments/codex-hooks/README.md)
- [x] **1. Capture Codex locally.** Use only a bounded loopback stub and dummy key. Pin 0.141.0 (proxy floor), 0.149.1
  (QA), 0.161.0 (general validation ceiling) and 0.170.0 (repeat the preliminary capture). Record each package's
  version, executable path and SHA-256. For each binary and slug, compare TUI and `exec` with and without
  `-c web_search="disabled"`. Record catalog requests, method/path, resolved metadata, tool declarations, storage flags,
  `client_metadata`, full-history replay and compaction. Retain every distinct layout. The floor passes for this route
  only if the launcher's override allows the default task using local tools.
  [Runtime matrix](../../../../src/skills/qa/resources/runtime-matrix.json)
- [x] Use the same free stub to inject the proposed hosted-tool, subresource and missing-cost refusals, the translated
  upstream ZDR diagnostic, and the existing spend-cap 429. Record the status, envelope, visible TUI message, `exec`
  diagnostic, request count and retry timing per binary. Distinguish injected errors from paths the client calls itself.
  Select statuses and envelopes that surface the recovery action and let Codex stop on its own. Record any cutoff by the
  harness as a retry-limit failure. Reopen compatibility if a supported client hides the refusal or loops.
- [x] Preserve HTTP 429. Native 0.161.0 and 0.170.0, in both TUI and exec, reached a $0.125 cap through the LiteLLM
  Responses proxy. All 23 subsequent compaction, foreground and title requests stopped before dispatch. Each run exposed
  the cap and recovery setting in `forge proxy metrics <id>`. Repeat on the new template in the dispatch-boundary
  acceptance case. [Native cap receipt](evidence/forge-cap-loopback.json) ·
  [Integration](../../../../tests/integration/proxy/test_codex_openrouter_responses_e2e.py)
- [x] Cross the cap status with both error bodies, refuse forced compaction, replay the sanitized credit error, and send
  routing metadata to every pinned binary. The 72 free cases showed that cap text visibility depended on status. All
  four versions tolerated the metadata on both model layouts. [Results](probe-results.md#follow-up-loopback-controls)
- [x] Obtain operator approval for the original paid manifests. Record models, binary identities, synthetic inputs,
  endpoints, credit ceiling, maximum HTTP attempts and deadline. For all paid arms, use a test-only forwarding counter
  that reserves each attempt before sending and refuses attempt N+1, including retries, tool turns and compaction.
  Budget metadata lookups separately. Demonstrate the counter and process-tree deadline on loopback first. Use an
  independently limited probe key for the USD ceiling when Forge cannot measure spend.
  [OpenRouter key limits](https://openrouter.ai/docs/api/api-reference/api-keys/create-a-new-api-key)
- [x] **2. Set the stage 60 criterion.** Keep account ZDR enabled. Use the recorded Qwen HTTP 404 with the
  digest-verified reason `zdr-violation-by-account` as the historical baseline. The operator accepts that this test
  leaves the independent effect of the request flag unverified.
- [x] Exercise the revised manifest `2feeec7f` on loopback. Both generation requests carried `provider.zdr=true`. The
  stub returned a structured account-ZDR 404 for Qwen and completed text for Astra.
  [Loopback receipt](evidence/qwen-account-zdr-loopback.json)
- [x] Obtain operator approval for the [stage 60 manifest](paid-probe-manifest-qwen-account-zdr.json). It allows two
  metadata reads and at most two generation attempts in five minutes, on a dedicated, non-resetting key capped at $2
  with BYOK charges included. If an eligible key is unavailable, the approval can include one management POST to create
  a probe key with a 20-minute expiry.
- [x] Run stage 60 on this account under `2feeec7f`. The key and catalog checks passed. The Qwen 404 explicitly named
  zero data retention. Its diagnostic lacked the mandatory structured exclusions, which stopped the run before Astra.
  [Live stage 60 receipt](evidence/paid-2feeec7f/zdr.json)
- [x] Complete stage 60 using the accepted Qwen HTTP 404 and a single Astra call. The continuation verified both
  historical receipts and the current catalog. Astra returned HTTP 200 with completed, nonempty assistant text under
  `provider.zdr=true`. Only Astra received a generation request in this run.
  [Continuation manifest](paid-probe-manifest-astra-positive.json) · [Live receipt](evidence/paid-1ee865aa/zdr.json) ·
  [Loopback receipt](evidence/astra-positive-loopback.json)
- [x] Rehearse the remaining stages with the pinned stage 60 receipt, Codex 0.170.0 and all 13 fixtures. Both native
  model runs and the optional metadata run completed on loopback. [Loopback receipt](evidence/cost-codex-loopback.json)
- [x] The maintainer approved manifest `0a6ac1d0` for stages 70 and 80 under one $2 cap and one 15-minute deadline.
  [Stages 70 and 80 manifest](paid-probe-manifest-cost-codex.json)
- [x] **3. Measure cost and identity.** Unary and streaming Astra responses each reported $0.000304 with the metadata
  header omitted or enabled. Enabling it identified Azure in both modes. Each response ID matched its generation header
  and resolved through `/api/v1/generation`. The Chat Completions control also indexed.
  [Stage 70 receipt](evidence/paid-0a6ac1d0/cost.json)
- [x] Run stage 80 under the same key. OpenRouter refused the native Astra request on credit grounds before the first
  tool turn. The request omitted `max_output_tokens`. [Stage 80 receipt](evidence/paid-0a6ac1d0/codex.json)
- [x] Exercise standalone stage 80 on loopback against the pinned stage 70 receipt. The listener received the original
  eight native baseline bodies and 27 ZDR-required POSTs across the fixtures and Astra metadata run.
  [Loopback receipt](evidence/codex-only-loopback.json)
- [x] Run the approved stage 80-only manifest `63d4a6f0`. All 35 Responses requests completed. OpenRouter reported
  $0.4547193 in total usage. [Approved $5 manifest](paid-probe-manifest-codex-only.json) ·
  [Live stage 80 receipt](evidence/paid-63d4a6f0/codex.json)
- [x] **4. Exercise Codex and the policy-shaped request.** Both native slugs completed the scratch read and verified
  edit on resume. Gemini used fallback metadata and declared web search. Its streams showed only local tool calls. All
  ten tool fixtures consumed the matching call results, and all three titles met their schemas. The five Gemini tool
  fixtures replayed encrypted reasoning. The five Astra tool fixtures emitted none. The native Astra run also completed
  both turns with explicit ZDR and the routing-metadata header. Azure and Google were identified on every
  metadata-enabled request to their respective models. [Probe results](probe-results.md)
- [x] The maintainer chose to omit `client_metadata` and `prompt_cache_key` by default, count OpenRouter account credit
  for BYOK, and forward configured cross-family ZDR fallbacks. Codex builds the request for the requested slug.
  [Probe verdicts](probe-results.md#probe-verdicts)
- [x] The shared Responses relay preserved a synthetic `reasoning` item, its position, the tool call and the matching
  result in both captured tool continuations. A loopback upstream released the terminal only after the client received
  its first delta. It received the supplied `openai-beta` and Forge's upstream bearer.
  [Integration](../../../../tests/integration/proxy/test_codex_openrouter_responses_e2e.py)
- [x] Both synthetic opaque-item continuations passed through the direct OpenRouter route. Live encrypted replay is
  verified on Gemini and unverified on Astra.

## 2. Wire the sessionless route

- [x] Register `codex-responses-openrouter` on the canonical `openrouter` source and package a template with
  `openai_responses_passthrough`. Require only the OpenRouter credential. Preserve the live identity, wire-shape and
  source-capability checks, translated Messages ingress and user-owned proxy snapshots. Keep model-first session routing
  and managed Codex sessions outside this change. [Source catalog](../../../../src/forge/backend/sources.py)
- [x] Join versioned and unversioned bases exactly once, preserving custom prefixes. Verified create and subresource
  URLs, bearer replacement and encoded query parameters for HTTP LiteLLM and HTTPS gateways.
  [Regression](../../../../tests/regression/test_bug_responses_versioned_base.py)
- [x] Validate the OpenRouter base before attaching its bearer. Require HTTPS except for `localhost`, `127.0.0.1` and
  `::1`, and reject userinfo, query strings and fragments. Relay only the create operation to OpenRouter. Use the
  captured local refusal contract for subresources and keep a single upstream attempt per incoming request.
  [Ingress](../../../../src/forge/proxy/responses_ingress.py)
- [x] On required-ZDR requests force `provider.zdr=true`, apply `model_for_zdr_policy`, and accept only the
  client-executed tool types established by the captures. Check top-level `tools`, namespaces and `additional_tools`
  input items. Preserve sibling provider options and other caller fields by value. With `allow_non_zdr`, preserve the
  caller's model and provider settings. Test both Qwen 404s. For `zdr-violation-by-account`, name the model and point to
  OpenRouter's privacy settings or a ZDR-eligible model. For the ZDR-specific text alone, name the restriction and
  suggest a ZDR-eligible model. Explain that `allow_non_zdr=true` can relax Forge's requirement only where account and
  guardrail policies permit it. Preserve unrelated provider 404s.
  [Qwen evidence](probe-results.md#qwen-paid-run-on-2026-11-19)
- [x] Scrub `OPENROUTER_API_KEY` in the shared sessionless launcher. An actual child received its loopback token. With
  dotenv disabled, nested `forge auth status` resolved only the stored test key. Both credential cases and all four
  LiteLLM streaming-cost integration cases passed via `./scripts/test-integration.sh`.
  [Integration](../../../../tests/integration/proxy/test_codex_openrouter_responses_e2e.py) ·
  [Proxy guide](../../../end-user/proxy.md#start-codex-with-a-responses-capable-proxy)
- [x] Under required ZDR, supply `-c web_search="disabled"` before operator arguments. Use the verified live proxy to
  report the requested and dispatched launch model when they differ, including an explicit off-tier `-m`.
  [Launcher](../../../../src/forge/cli/codex.py)
- [x] Run the route and launcher cases in the new Docker integration suite via `./scripts/test-integration.sh` in this
  slice. Exercise both documented template-name launches, a saved Messages-only proxy, and the translated Messages
  ingress on the new template. All 12 cases passed via
  `PYTHON_DOTENV_DISABLED=1 ./scripts/test-integration.sh tests/integration/proxy/test_codex_openrouter_responses_e2e.py`.

## 3. Account for each dispatched generation

- [x] Write one downstream attempt per dispatch, joining cost and trace on `downstream_event_id`. On this route store
  the requested slug in `model` and the dispatched slug in `mapped_model`. Group metrics and `costs show --by-model` by
  the dispatched slug. Extend the trace projection so `trace show` displays a fallback's two slugs in both human and
  JSON output. Test older records and Messages callers without inferring a historical requested slug. Preserve the
  downstream schema.
- [x] Exercise the chosen BYOK accounting policy with `is_byok=true`, zero `usage.cost` and a positive
  `cost_details.upstream_inference_cost`. Assert the documented amount in the per-request record, cap and metrics.
- [x] Parse observed unary and SSE evidence once per attempt. Preserve explicit zero, unavailable cost, upstream
  failures, disconnects and an ID received before cancellation. Send `X-OpenRouter-Metadata: enabled` on direct
  OpenRouter Responses and extract the endpoint marked selected. Use `provider_response_id` for the response identity
  and `provider_generation_id` only for a verified generation identity. Missing provider or generation evidence stays
  empty. [Relay](../../../../src/forge/proxy/responses_passthrough.py) ·
  [Trace projection](../../../../src/forge/proxy/provider_trace_logger.py)
- [x] Wire `costs.on_unreported_cost=reject|allow` through saved config, both loader steps, `forge proxy set` and live
  policy. In shared config, leave an omitted key unset. Resolve and advertise the default `reject` only for direct
  OpenRouter Responses creates. A source-declared cost gap rejects the first such call. The same proxy's Messages
  ingress and other sources retain their current accounting behavior.
- [x] Under `reject`, an observed `completed` or `incomplete` terminal with missing cost blocks subsequent Responses
  creates on that proxy. Forge already treats `incomplete` as a partial billable success. Explicit zero, a local
  refusal, an HTTP or transport error, `response.failed`, and disconnect/EOF before a terminal leave the flag unchanged.
  A restart clears an observed gap and reloads the source declaration and dollar-cap totals. Test the next request after
  each outcome, including with no configured dollar cap.
- [x] Make the unary create/start smoke evaluate its own response using the effective policy and Forge's existing
  `X-Request-Cost` convention. Emit the header for reported cost including zero. A text-bearing success without cost
  under `reject` fails that smoke and reports the override. Preserve the first diagnostic and issue no second generation
  for an unpriced success or deterministic refusal. Under `allow`, that smoke can pass. Print the uncounted-spend
  warning on each launch. Test recovery with `forge proxy set <id> costs.on_unreported_cost=allow` followed by restart.
- [x] With `PYTHON_DOTENV_DISABLED=1`, exercise `forge proxy create codex-responses-openrouter --json --smoke-test`,
  `forge proxy start <id> --smoke-test` and `forge runtime preflight codex --proxy <id>` against a local upstream.
  Repeat with only the environment key and only the Forge credential store. Inspect the child's environment in both
  runs.
- [x] Run the accounting cases in the new integration suite, relevant CLI smoke cases and
  `tests/integration/proxy/test_litellm_streaming_cost_e2e.py` via `./scripts/test-integration.sh` in this slice. All 34
  selected cases passed with dotenv disabled via the integration wrapper, including
  `TestProxyCreateAndStart::test_create_json_failed_smoke_is_one_result_and_preserves_proxy`. Both credential sources
  passed create/start smoke, the account-credit total matched telemetry, and a duplicate stream terminal charged once. A
  restart retained $0.125 of spend under the new cost policy. Two unpriced LiteLLM Responses creates succeeded. The
  OpenRouter smoke sends the originally requested default so a chained fallback maps it once.

## Acceptance fixtures

Replay the layouts and provider responses indexed in `probe-results.md` against the real proxy and a recording loopback
upstream. Add the route and accounting cases to `tests/integration/proxy/test_codex_openrouter_responses_e2e.py`. Hold
the upstream terminal until the client receives the first SSE delta. Check cancellation before the terminal. Record
receipt of a deliberately supplied `openai-beta` header and the absence of inbound credentials at the upstream. The paid
bridge buffered the stream and constructed its own upstream headers.

| Test                    | Fixture                                                                                            | Observable result                                                                                                                                               | Test file                                                                                                                                                                                     |
| ----------------------- | -------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Endpoint and credential | Versioned, prefixed and invalid OpenRouter bases, missing key, HTTP LAN LiteLLM                    | Exact URL and bearer on dispatch. Invalid OpenRouter input sends zero requests. LiteLLM still relays subresources.                                              | [Transport](../../../../tests/src/proxy/test_responses_transport.py)                                                                                                                          |
| ZDR and fidelity        | All captured layouts, synthetic encrypted items, both Qwen errors, opt-out, fallback, hosted tools | Agreed routing and identifier fields account for every change. Opaque items, tool arguments and call IDs survive. Hosted tools stop locally under required ZDR. | New integration suite                                                                                                                                                                         |
| Dispatch boundary       | Subresources, transport errors, foreground and compaction retries after a cap                      | One upstream attempt per admitted create. Every rejected retry, including all six compaction attempts on older pins, makes zero upstream calls.                 | [Transport](../../../../tests/src/proxy/test_responses_transport.py)                                                                                                                          |
| Launch and preflight    | Both launch forms, stale identity, saved Messages proxy, both Responses templates                  | Correct slugs and web-search setting. Neither bare child inherits the OpenRouter key. Only capable proxies with matching identities launch.                     | [Launch](../../../../tests/src/cli/test_codex_start.py), [child](../../../../tests/src/session/test_codex_invoke.py), [preflight](../../../../tests/src/core/runtime/test_codex_preflight.py) |
| Trace and cost          | Fallback, duplicate SSE terminal, explicit zero, cancelled stream, reject cap                      | One charge. Dispatched-model totals agree. Both slugs in trace show. Over-cap retry stops locally.                                                              | New integration suite                                                                                                                                                                         |
| Missing cost            | Declared gap, completed, incomplete, failed, HTTP error, pre-terminal EOF or cancel, restart       | First or next create refused only in the specified states. Messages and unpriced LiteLLM still serve.                                                           | New integration suite, [config](../../../../tests/src/config/test_proxy_block_wiring.py)                                                                                                      |
| Smoke commands          | Env-only and store-only credentials, a first unpriced 200, then opt-in                             | One POST for the unpriced success. Create emits one JSON object and retains the proxy on failure. Start gives the same verdict.                                 | [CLI integration](../../../../tests/integration/cli/test_proxy_commands_integration.py), [create regression](../../../../tests/regression/test_bug_d016_proxy_create_smoke_json.py)           |

## Live acceptance and closeout

- [x] Rehearse [live acceptance manifest `36567394`](paid-acceptance-manifest.json) on loopback. Native TUI 0.170.0
  completed both turns on each model, including the matched local read and edit. Ten creates and seven metadata reads
  sufficed. Two initial lookup 404s per model exercised the 4- and 12-second waits. The attempt limit and absolute
  streaming deadline passed separate negative controls.
  [Acceptance receipt](evidence/forge-tui-acceptance-loopback.json)
- [x] The maintainer approved [manifest `36567394`](paid-acceptance-manifest.json). It ran once on the stage 60 account
  with ZDR enabled. One management POST created the dedicated 20-minute, non-resetting, BYOK-inclusive $5 key. Forge
  enforced its $0.50 daily reject cap and unreported-cost policy. Two prompts per model used ten of 16 creates and three
  of seven reads. [Key setup](evidence/paid-36567394/key-setup.json) ·
  [Paid acceptance receipt](evidence/paid-36567394/acceptance.json)
- [x] Both native 0.170.0 sessions read the fixture and wrote its word on the follow-up. The proxy received ten
  Responses creates and four identity reads. No catalog request was observed. The first lookup joined Astra on Azure
  (`req_abf301664fec`) and Gemini on Google (`req_ca761be0dff8`). The traces, cost summaries and proxy metrics agreed on
  239,035 and 50,003 micros respectively. Each request was within half a micro of its reported charge. Gemini replayed
  encrypted reasoning on three requests. Astra replay remains unverified.
  [Downstream records](evidence/paid-36567394/downstream.json) ·
  [Paid acceptance receipt](evidence/paid-36567394/acceptance.json)
- [x] Synchronized the runtime, installation and telemetry designs, CLI reference, packaged QA inventory and
  [Codex proxy guide](../../../end-user/codex_proxy.md). The guide documents both identifier fields, the OpenRouter
  credit scope, cross-family fallbacks, missing-cost recovery and the Astra encrypted-replay limitation.
- [x] `make test-unit` passed 11,809 tests. `make test-regression` passed 2,632 on rerun. On the preceding run,
  `test_claude_ignores_codex_format_preference` compared independently measured 0.0s and 0.1s in its output. Its 16-test
  file also passed in isolation.
- [x] Verified the wheel and sdist build, full hooks, shared LiteLLM clean-install start/health/stop, and a separate
  hash-locked wheel installation. The wheel realized the direct template, selected Astra, passed unary loopback smoke
  and reported `proxy_supported` with native Codex. Both native TUI launches exercised the wheel on loopback. The
  installed wheel SHA-256 was `cf550c277a77e4402232d5ac4c4bd3628675c0eeb7143d539384d19dd280d862`.
- [x] Rehearse the board move in a temporary `done/` directory. All four approved replay manifests passed their loopback
  selftests there with the pinned Codex binary. The relocation regression verifies the index, the stage 80 receipt, file
  digests and rejection of a changed or escaping fixture. From the final lane, the stage 80 selftest passed all 35
  creates. The 71 probe regressions and six fixture-dependent integration cases also passed.
  [Regression](../../../../tests/regression/test_bug_openrouter_paid_stage_continuation.py)
- [x] Closed the card in `done/`, updated inbound links and recorded acceptance in the
  [change log](../../change_log.md). The [2026-08-22 archive](../../archive/change_log_2026-08-22.md) keeps the oldest
  date block verbatim. The original manifests and historical receipts are among 54 relocated files verified
  byte-for-byte. After merging the Gemini defaults, the change log used 24,402 of its 25,000 target tokens. The
  implementation-note correction below was submitted to the local shadow notes for human review.

### Proposed correction to the June 23 launcher note

The [runtime and telemetry implementation note](../../impl_notes/runtime_telemetry.md) describes byte-for-byte relay.
Forge parses and serializes the Responses request while preserving JSON values, including tool continuations and opaque
reasoning items. With required ZDR, the direct OpenRouter route sets `provider.zdr` and applies any configured model
fallback. It strips `client_metadata` and `prompt_cache_key` on every create. LiteLLM also relays Responses
subresources. The direct route accepts creates only. Before launch, `read_responses_launch` checks the live proxy
identity, template, wire shape and Responses ingress capability together.
[Request preparation](../../../../src/forge/proxy/openrouter_responses.py) ·
[Launch check](../../../../src/forge/proxy/proxy_orchestrator.py)

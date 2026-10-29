# Prompt-cache correctness execution checklist

## Current focus

Completed on 2026-10-16. [PR #273](https://github.com/hapa1i/multi-forge/pull/273) merged the `prompt-caching` branch,
based on `main` at `203e4404`, as `3573c147b61b68b4b5be977038a808891594408b`. The [card](card.md) preserves scope; the
user's 2026-10-15 decisions excluded Forge-placed markers, LiteLLM-specific work and provider pinning, and authorized
the bounded paid checks recorded below. [Merged closeout](#merged-closeout) records final verification.

## Phase 0: Evidence

- [x] Capture Claude Code request shapes against a local fake upstream (no network): 2.1.296 headless, 2.1.294 headless
  and 2.1.296 interactive through a pseudo-terminal. All 988 interactive tool-loop requests end with a marked
  `role: system` message and carry mid-conversation system messages; no tool result carries a marker.
- [x] Reproduce offline that Forge forwards those messages as OpenAI `system` messages, keeps the trailing marker only
  when the client model name contains "claude", and drops tool-result markers.
- [x] Paid OpenRouter probe, `provider.zdr=true`, synthetic data, $0.59 of the authorized budget. Results are summarized
  in the [card](card.md#evidence). The deciding facts: system-role messages are hoisted for Gemini, Anthropic and Kimi
  on Wafer; user-role reminders restore conversation caching; Gemini markers never write on Argon and double reported
  input on Flash; OpenRouter accepts markers on tool-message content parts for Claude.
- [x] Confirm streaming chunks carry `provider` and usage carries `prompt_tokens_details.cache_write_tokens`.

## Phase 1: Translator

- [x] Catalog: parse `prompt_caching` into `ModelSpec` with validated `mechanism` values; reject unknown mechanisms at
  load. Correct stale Gemini notes, using OpenRouter endpoint metadata where it adds evidence. Argon and 3.8 Flash
  (probe) and MiniMax M3 and Gemma 4 31B (endpoint metadata) now declare `auto`; 3.6 Flash stays unsupported pending a
  probe.
- [x] Replace the client-name gate with a resolved-backend decision. `cache_control` models keep client markers,
  including `ttl`; others lose them. Unknown models fall back to Anthropic name detection on the resolved model.
- [x] Accept `cache_control` on tool results; emit tool-message markers as text content parts.
- [x] Convert system-role messages after the first non-system message into user `<system-reminder>` text, preserving a
  marker on the converted part; do not double-wrap text that already carries the tag.

## Phase 2: Usage returned to Claude Code

- [x] Carry cache writes from OpenAI-shaped usage (`cache_write_tokens`) through the OpenRouter client and adapter.
- [x] Streaming and non-streaming translated responses report `cache_read_input_tokens`, `cache_creation_input_tokens`
  and uncached `input_tokens`; totals equal provider prompt tokens. Malformed counts still fail response validation and
  conversion-failure accounting.

## Phase 3: Accounting and telemetry

- [x] Normalize Anthropic-native usage in the passthrough proxy and headless Claude results: total input, reads in
  `cached_tokens`, writes in `cache_write_tokens`.
- [x] Statusline cache rate divides reads by total input and cannot exceed 100%.
- [x] Downstream attempts record `cache_write_tokens` when present and the streaming selected provider.

## Phase 4: Docs

- [x] Update the runtime and telemetry design docs for role translation, marker forwarding, usage semantics and the new
  optional field. Update the end-user proxy guide for per-model caching behavior. Fix the misleading docstrings.

## Acceptance tests

| Test                                     | Fixture                                                             | Assertion                                                          | Test File                                                           |
| ---------------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------- |
| Mid-conversation system becomes reminder | Claude Code 2.1.296-shaped request                                  | trailing message is user-role `<system-reminder>` text with marker | `tests/src/proxy/test_cache_control.py`                             |
| Leading system stays system              | top-level system plus leading system message                        | one system prompt; no user conversion                              | `tests/src/proxy/test_cache_control.py`                             |
| Markers follow the backend               | client `claude-opus-5-5`, backends Argon, Opus, GPT, unknown Claude | kept only for Claude backends                                      | `tests/regression/test_bug_cache_marker_client_name_gate.py`        |
| Tool-result marker and ttl               | tool result with `{"ttl": "1h"}` on Claude backend                  | tool content part carries the same marker                          | `tests/src/proxy/test_cache_control.py`                             |
| Hoisting regression                      | 2.1.296 shape, Gemini backend                                       | no system message after the first non-system message               | `tests/regression/test_bug_mid_conversation_system_cache_prefix.py` |
| Streaming cache usage                    | OpenAI usage with reads and writes                                  | final `message_delta` reports Anthropic cache fields               | `tests/src/proxy/test_converters.py`                                |
| Non-streaming cache usage                | OpenAI usage with reads and writes                                  | response usage splits reads and writes out of input                | `tests/src/proxy/test_converters.py`                                |
| OpenRouter stream provider and writes    | fake chunks with `provider`, `cache_write_tokens`                   | usage and provider meta carry both                                 | `tests/src/core/llm/test_openrouter.py`                             |
| Passthrough usage normalization          | Anthropic usage with reads and writes                               | input is total; rate at most 100%                                  | `tests/regression/test_bug_anthropic_usage_cache_rate_overflow.py`  |
| Statusline rate                          | transcript with tiny fresh input and large reads                    | rate at most 100%                                                  | `tests/src/cli/test_status_line.py`                                 |
| Telemetry field compatibility            | attempt with and without writes                                     | omitted when absent; round-trips when set                          | `tests/src/core/telemetry/test_downstream.py`                       |
| Catalog mechanism validation             | `prompt_caching` with bad shape or unknown mechanism                | load rejects it; unsupported yields no mechanism                   | `tests/src/core/models/test_model_catalog_validation.py`            |

## Phase 5: Verification

- [x] Focused unit and regression tests, `make test-unit` (11,029 passed), `make test-regression` (1,904 passed) and
  `make pre-commit` (clean).

- [x] Targeted integration tests for proxy runtime and telemetry paths: OpenRouter proxy, provider trace, cost
  visibility, downstream retention, passthrough headers, Sonnet 5.5, the paid cache canary, finish reason and the
  headless cost contract. 66 passed, 1 failed. `test_local_litellm_streaming_cost_unavailable` asserts that a local
  LiteLLM gateway reports no streaming cost, but LiteLLM 1.102.0 (bumped in #255) stamps `usage.cost` on streamed usage
  (`_stamp_streaming_usage_cost`). The failure is independent of this card and LiteLLM-specific; the
  [streaming-cost contract follow-up](../../doing/litellm_streaming_cost_contract/card.md) owns its tests and
  documentation reconciliation.

- [x] Paid end-to-end check, about $0.49 of the $1 budget. Headless Claude Code 2.1.296 ran a seven-request `Read` tool
  loop through proxies under isolated `FORGE_HOME`s, with the environment from `build_claude_env`:

  | Route                                | Code                | Input cached                            | Writes | Cost   | Selected provider |
  | ------------------------------------ | ------------------- | --------------------------------------- | ------ | ------ | ----------------- |
  | Argon via `openrouter-gemini`        | `203e4404` baseline | 0.0% (0 of 122,829)                     | 0      | $0.249 | not recorded      |
  | Argon via `openrouter-gemini`        | this branch, run 1  | 73.7% (90,807 of 123,256); 81-86% after | 0      | $0.077 | Google            |
  | Argon via `openrouter-gemini`        | this branch, run 2  | 73.7%; one 0% request, others 83-86%    | 0      | $0.077 | Google            |
  | Haiku 4.5 via `openrouter-anthropic` | this branch         | 71.4%; 97% from the third request       | 57,275 | $0.089 | Amazon Bedrock    |

  Claude Code's result usage is Forge's total split Anthropic-style (Argon 32,449 fresh plus 90,807 read; Haiku 40 fresh
  plus 142,885 read plus 57,275 written), and the statusline rate equals Forge's. `forge proxy metrics`,
  `forge telemetry costs show --by-model` and `forge telemetry trace list --json` read the new records. The second
  request of the Haiku run and of Argon run 2 read nothing, although the request before each was cached and every later
  request read the whole previous prompt. Captured requests show Claude Code's system, tools and leading messages are
  identical across those turns, so the misses are provider-side cache routing (see the provider-pinning follow-up).

## Review fixes (round 1)

- [x] **Headless cache writes** (`structured_output.py`, `session_runner.py`, `invoker/claude.py`, `measurement.py`,
  `emit.py`): the envelope folded writes into total input but dropped their count, so direct `claude -p` verbs and
  workers wrote downstream attempts with input 3,000 and reads 2,519 but no writes. The count now rides
  `HeadlessEnvelope`, `SessionResult`, `HeadlessResult` and `UsageMeasurement` to every direct downstream writer,
  including direct `core.llm` calls; zero writes stay omitted, and usage-ledger events keep reads only. Tests:
  `test_bug_anthropic_usage_cache_rate_overflow.py` (verb and worker paths from a real envelope) and
  `test_emit.py::test_direct_cache_writes_persist_downstream_and_zero_is_omitted`.
- [x] **CI formatting**: Black with the configured `--line-length 120` reformats
  `tests/fixtures/claude_code_requests.py`. Local `make pre-commit` skipped the file while it was untracked.

## Closeout

- [x] Commit series split by intent; PR #273 with probe evidence and the role-semantics risk called out.
- [x] Verify runtime design, telemetry design and the end-user proxy guide against the merged implementation.
- [x] Move the card to `done/` after merge; no inbound references required repointing.
- [x] Record completion in the change log.

## Merged closeout

Closed on 2026-10-16 after [PR #273](https://github.com/hapa1i/multi-forge/pull/273) merged at
`3573c147b61b68b4b5be977038a808891594408b`. The reviewed head was `d57a41d06ac21af0679c386d7da8657b23292bd4`; all five
GitHub checks succeeded. Local comparison found all 44 implementation, test, documentation and card paths changed by the
PR byte-identical between that head and the merge. The remaining changed path, `.file-token-counts.json`, differs only
in the `docs/design.md` digest and count for intervening Jev work; the complete repository trees are not identical.

The merged [runtime design](../../../design_runtime.md#7x-optional-always-on-proxy-audit-and-control),
[telemetry design](../../../design_telemetry.md#314-cost-tracking-and-spend-caps) and
[proxy guide](../../../end-user/proxy.md#prompt-caching) match the translator, catalog gate, cache-usage conversion and
downstream writers. Verification remains the evidence in Phase 5: 11,029 unit tests, 1,904 regression tests, clean
pre-commit, and targeted integration with 66 passed and one deferred LiteLLM streaming-cost failure. Closeout ran no
additional model calls or tests.

The pre-existing LiteLLM streaming-cost assertions in telemetry documentation remain part of the
[separate follow-up](../../doing/litellm_streaming_cost_contract/card.md); this closeout verifies the cache changes.

The $0.59 synthetic probe and approximately $0.49 end-to-end check establish the recorded short-loop behavior, not a
guaranteed cache rate or real-session saving. Provider-side cache misses, provider pinning and the role-semantics
observation remain the limitations recorded above. LiteLLM-specific behavior stays outside this card's scope.

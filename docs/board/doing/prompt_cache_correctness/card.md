# Prompt-cache correctness on translated proxy routes

Status: **doing** on branch `prompt-caching`, based on `main` at `203e4404`. The [execution checklist](checklist.md)
tracks slices, evidence and closeout.

## Problem and outcome

Gemini 4 Argon behind `openrouter-gemini` cached 11.4% of input across 122 requests on 2026-10-13..15 and cost $52.88.
At the 90% hit rate Kimi K3 reached through the same proxy, the same traffic would cost about $9.41. Forge must deliver
Claude Code's cacheable conversation prefix to OpenRouter in a shape each provider can reuse, forward client cache
markers only where they help, and report cache reads and writes accurately to Claude Code and Forge telemetry.

The user's 2026-10-15 decision limits this card to OpenRouter routes and the shared translator. Forge must not place its
own cache markers. LiteLLM-specific behavior and probes stay out of scope.

## Evidence

**Request shape.** Captures of Claude Code 2.1.294 and 2.1.296 against a local fake upstream show the same shape in
headless and interactive modes. Each tool-loop request carries mid-conversation `role: system` messages: an environment
block, then one trailing per-turn message such as `<total_tokens>…</total_tokens>`. Claude Code puts its rolling cache
marker on the trailing system message, not on the tool result. Forge's translator forwards both messages to
OpenAI-compatible backends as `system` messages.

**Paid probe.** Synthetic Claude Code-shaped tool loops ran against OpenRouter with `provider.zdr=true` and no user
data. The full run cost about $0.59. Cells show the share of prompt tokens cached on the last request:

| Model (served by)          | System messages kept (today)          | Converted to user `<system-reminder>`         |
| -------------------------- | ------------------------------------- | --------------------------------------------- |
| Gemini 4 Argon (Google)    | 0% on every request, markers or not   | 65% at turn 5; 78% at turn 8; never writes    |
| Gemini 3.8 Flash (Google)  | 32% at turn 8; system re-written/turn | 84% at turn 7 unmarked; markers double input  |
| Claude Haiku 4.5 (Bedrock) | 64% (system prompt only)              | 91% with markers; 92% with tool-result marker |
| Kimi K3 (Wafer)            | 65%                                   | 91%                                           |
| GPT-5.4-mini (Azure)       | 88%                                   | 87% (no change)                               |

OpenRouter evidently hoists every `system` message into the provider's system prompt for Gemini and Anthropic and for at
least one Kimi host. The per-turn reminder therefore changes the system prompt on every request, and no conversation
prefix after it can be reused. With user-role reminders, Google's implicit cache trails the prompt by a roughly constant
few thousand tokens, so long Argon sessions should approach the Kimi-like hit rate. Gemini cache markers never produced
writes on Argon. On Flash with user-role messages, they made OpenRouter report about twice the prompt tokens.

**Secondary defects found by code review:**

- `_model_supports_cache_control(request.model)` keys on the client's model name, so plain `--proxy` launches forward
  markers to every backend while `--model` launches strip them for every non-Claude model. Its docstring states the
  opposite intent.
- `ContentBlockToolResult` has no `cache_control`, and `CacheControl` drops `ttl`. Other Anthropic clients put rolling
  markers on tool results.
- The translated path never returns cache reads or writes to Claude Code, so transcripts show zero cache use.
- Anthropic-native usage counts only uncached input in `input_tokens`, while Forge's translated convention counts total
  prompt input. The passthrough proxy, headless Claude results and the statusline mix the two. They drop cache writes
  and report cache rates above 100%; the statusline computed 14,546,605% for a direct session. Two docstrings say cache
  writes are billed as normal input; Anthropic bills them at 1.25x (5-minute) or 2x (1-hour).
- `cache_write_tokens` and the OpenRouter-selected provider for streaming requests are never recorded, although
  OpenRouter sends both.
- No code reads the catalog's `prompt_caching` metadata, and its Gemini notes are stale.

## Scope

1. **Message roles.** On the translated path, send system-role messages that follow the first non-system message as
   user-role text wrapped in `<system-reminder>` tags. Keep content, position and any client marker. Leading system
   content stays in the system prompt. Apply this to every translated backend: the probe shows no harm on OpenAI and
   large gains elsewhere.
2. **Marker forwarding.** Decide from the resolved backend model's catalog `prompt_caching.mechanism`, not the client's
   model name. Forward client markers verbatim, including `ttl` and tool-result markers, only for `cache_control`
   models; strip them for every other model and for models unknown to the catalog unless their name identifies an
   Anthropic model. Gemini models use implicit caching and lose markers. Keep the existing opt-in system-prompt
   `auto_inject` behind the same decision; add no new placement.
3. **Usage to Claude Code.** Return `cache_read_input_tokens` and `cache_creation_input_tokens` on translated streaming
   and non-streaming responses, with `input_tokens` reduced to the uncached remainder (Anthropic semantics).
4. **Forge accounting.** Normalize Anthropic-native usage to Forge's convention: total input, cache reads in
   `cached_tokens`, cache writes in a new optional `cache_write_tokens`. Fix cache-rate formulas so they cannot exceed
   100%.
5. **Telemetry.** Record OpenRouter `cache_write_tokens` and the streaming selected provider on downstream attempts.
6. **Catalog.** Parse and validate `prompt_caching` into `ModelSpec` and correct entries using the probe evidence and
   OpenRouter endpoint metadata.

Out of scope: Forge-placed or staircase markers; LiteLLM-specific handling (shared translator changes still reach
LiteLLM routes); OpenRouter provider pinning. The probe saw host spread: four Qwen 27B requests reached three hosts, and
Kimi hit rates ranged from 42% to 88% across hosts. Provider pinning is a follow-up candidate.

## Risks and decisions

- **Role semantics.** Non-Claude models see reminders as user-turn text instead of system instructions. Claude Code
  itself uses `<system-reminder>` user text for other reminders, and OpenRouter already moved these messages out of
  position. The translator already emitted the same tool-result-then-user-reminder shape for older Claude Code, which
  put reminders inside user messages. In the end-to-end check, one of two Argon runs prefixed its final answer with a
  leaked reasoning line (Chinese for "thinking process:") before the correct sum; the other run and the unmodified
  baseline answered cleanly. The sample is too small to attribute; watch for it in real sessions.
- **Telemetry compatibility.** `cache_write_tokens` is additive, optional and omitted when absent, with no schema bump.
  Older Forge readers parse strictly and skip only records that carry it. Mixed-version proxies could undercount spend
  caps from those records.
- **Claude Code drift.** The fix depends on Claude Code's current request shape. Fixtures mirror the captured shape so a
  future change shows up as a failing test rather than a silent cache regression.
- **Probe limits.** Short synthetic loops measure prefix reuse, not real session economics. Google's implicit caching is
  best-effort, so an end-to-end session check is part of acceptance.

# Choosing models for each Forge role

Forge templates default per **role**, not per "newest available." A coding executor, a plan supervisor, a one-shot
reviewer, and a panel quorum worker reward different capabilities — and as of mid-2026, the same provider's flagship
release can be the right pick for one role and the wrong pick for another.

This page explains the trade-offs across model families so you can match each Forge role to the right backend, and tune
proxy defaults as new versions ship.

- Proxy templates and tier mappings: [`proxies.md`](proxies.md)
- Skill model-family detection: [`skills.md`](skills.md#model-aware-resource-selection)
- Supervisor configuration: [`policies.md`](policies.md#semantic-supervisor-advanced)
- Auth and credentials: [`auth.md`](auth.md#which-auth-do-i-need)

---

## TL;DR — per-role recommendations

| Role                                                                        | Recommended default                                                    | Why                                                                                              |
| --------------------------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| **Executor** (writes code, multi-turn)                                      | Claude Opus 4.6 (`openrouter-anthropic` / `litellm-anthropic` default) | Holds plan + design docs across long sessions                                                    |
| **Executor** (short, focused sessions)                                      | Claude Opus 4.7 via `--model claude-opus-4-7`                          | Stricter literal instruction following, leads SWE-bench Pro and MCP-Atlas                        |
| **Supervisor** (judges diffs against plan via `--resume`)                   | Claude Opus 4.6 on the proxied `opus` tier — *do not pin 4.7*          | Multi-needle retrieval across the planner's conversation is what the role does, and 4.6 leads it |
| **One-shot review** (`/forge:review`, fresh context)                        | Claude Opus 4.7-backed session                                         | Real capability gains on bounded review; the skill follows the active session/proxy              |
| **Panel quorum** (`/forge:panel`)                                           | Mix: Opus 4.6 + Opus 4.7 + GPT-5.5 + Gemini 3.1 Pro                    | Different training distributions and effort tiers catch different defects                        |
| **Adversarial debate** (`/forge:debate`)                                    | Mix across providers                                                   | Different defaults expose different gaps                                                         |
| **Handoff agent** (post-session memory updates)                             | Claude Sonnet 4.6 or Haiku 4.5; or `litellm-gemini-flash-local`        | Single-transcript summarization; cost matters more than multi-needle                             |
| **Cost-conscious supervisor** (warn-only or paired with a stricter primary) | DeepSeek V4 Pro via `openrouter-deepseek`                              | Hybrid-attention design retains long-context fidelity at ~10× lower cost than Opus               |

The rest of this page explains the reasoning so you can adapt these defaults as new models ship.

---

## Why context fidelity varies across model versions

All current frontier transformer models face an **attention-budget problem** at long context. Maintaining high-fidelity
representations of every token across a 1M-token window is computationally expensive — quadratic in context length for
standard dense attention. To make long-context economic to serve, providers apply compression techniques (KV cache
compression, sparse attention, latent attention) that preserve coarse structure while softening fine-grained
distinctions between similar items.

Different model families approach this differently:

### Compression-as-serving-optimization (typical of Western frontier labs)

Anthropic, OpenAI, and Google ship standard dense-attention architectures and apply compression at the serving layer to
reduce per-request cost. Peak retrieval can be excellent — Claude Opus 4.6 leads multi-needle MRCR at 1M tokens (~78%) —
but compression-stack changes between releases can produce sharp regressions on long-context multi-needle tasks even
when shorter-context capability improves.

The Opus 4.6 → 4.7 release is the clearest example: 4.7 improved on SWE-bench Pro (53.4% → 64.3%), MCP-Atlas (+14.6
points), and instruction-following discipline, while dropping on MRCR v2 8-needle at 256K (91.9% → 59.2%) and at 1M
(78.3% → 32.2%). Anthropic's own system card states: "Opus 4.6 with 64k extended-thinking mode dominates 4.7 on
long-context multi-needle retrieval."

### Compression-as-architecture (typical of Chinese open-weights labs)

DeepSeek, Moonshot, Z.ai, and Alibaba operate under compute constraints from US export controls. Their long-context
architectures bake compression into the model itself rather than bolting it onto the serving stack:

- **DeepSeek V4** uses hybrid Compressed Sparse Attention (CSA) + Heavily Compressed Attention (HCA), interleaved across
  layers. At 1M context, V4-Pro runs at 27% of V3.2's per-token FLOPs and 10% of its KV cache memory.
- **Kimi K2.6** uses Multi-Head Latent Attention (MLA) with native INT4 quantization-aware training.
- **GLM-5.1** and **Qwen 3.6** use sparse-attention variants and aggressive MoE expert routing.

The trade-off: predictable degradation curves and dramatically lower serving cost ($0.435/$0.87 per Mtok for DeepSeek V4
Pro under current Forge catalog pricing, vs $5/$25 for Opus), at retrieval scores below the best dense-attention models
at peak. DeepSeek V4 Pro scores 0.59 on MRCR v2 8-needle at 1M — well above Opus 4.7's 0.32, below Opus 4.6's 0.78, and
roughly competitive with GPT-5.5 (0.74) and Gemini 3.1 Pro at the same context depth.

### Why this matters for Forge

Neither approach is "right" — they are different design points on the same curve. What matters for picking a Forge proxy
is:

1. **Whether the version you're routing to was optimized for short-context or long-context fidelity**, and
2. **Whether your role stresses long-context multi-needle retrieval** (supervisor reading the planner's `--resume`
   conversation) **or short-context capability** (one-shot review of a single file).

Forge's `model_alternatives` field in proxy templates exists so you can keep both versions of a vendor's model available
at the same proxy. You don't have to choose once for all roles. See [Forge-specific patterns](#forge-specific-patterns)
below.

---

## The supervisor's actual capability requirements

The semantic supervisor (`forge guard supervise`) runs `claude -p --resume <planner_uuid> --fork-session` on every
Write/Edit, throttled to 30 seconds. When routed through a proxy, Forge passes `--model opus` and clears inherited
executor model pins so the supervisor uses that proxy's `opus` tier. Its job is to read the planner's full conversation,
locate the relevant plan section for the action being taken, and emit a JSON verdict with cited evidence:

```json
{
  "verdict": "aligned" | "divergent",
  "confidence": 0.95,
  "violations": [
    {
      "severity": "high",
      "evidence": "what was done that violates the plan",
      "suggested_fix": "what should be done instead",
      "citations": ["quoted plan section that was violated"]
    }
  ]
}
```

This is **not** code writing. SWE-bench Verified, the headline metric most coding-model comparisons use, is the wrong
benchmark for picking a supervisor model. The supervisor's effectiveness depends on:

| Capability                               | What it controls                                                                                   | Best benchmark proxy                                                                                 |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Multi-round coreference resolution       | Whether the supervisor can locate and cite the right plan item among similar distractors           | MRCR v2 8-needle at the planner's context size                                                       |
| Literal instruction following            | Whether the JSON schema is honored without prose preamble or schema drift                          | Anthropic's "stricter literal instruction following" descriptor; structured-output reliability tests |
| Confidence calibration                   | Whether confidence ≥0.8 means the verdict is actually right (false positives cause noisy blocks)   | AA-Omniscience hallucination rate (lower is better)                                                  |
| Citation fidelity                        | Whether quoted plan text appears verbatim or is paraphrased into something the user can't grep for | Indirect — correlates with low hallucination rate and high MRCR                                      |
| Cache effectiveness on the stable prefix | Whether the supervisor prompt + plan override hits the provider's cache on each call               | Provider's cache mechanism and minimum cacheable token threshold                                     |

Supervisor invocations are cached in a 30-second window keyed by `tool/path/content + plan_fingerprint`
(`supervisor.py:96-105`). Across that window, the variable part of each call is ~2K tokens of diff content (capped at
2000 chars in `supervisor.py:414`). Everything else — the prompt template, the plan override content, the planner's
`--resume` context — is a stable prefix that hits the provider's cache on every call after the first.

The cost lever for the supervisor is therefore **cache hit rate on the stable prefix**, not the visible token count.

---

## Per-family deep dive

The current frontier (May 2026), with the dimensions that matter for supervision and review. Pricing rows follow Forge's
bundled proxy catalog unless a provider-direct price is called out; gateway limits can differ from the provider's own
API limits.

### Claude (Anthropic)

| Variant    | Pricing ($ in/out per Mtok) | Context                  | MRCR v2 8-needle @ 256K / 1M            | AA-Omniscience hallucination | Best Forge role                                                             |
| ---------- | --------------------------- | ------------------------ | --------------------------------------- | ---------------------------- | --------------------------------------------------------------------------- |
| Opus 4.7   | $5 / $25 base               | 1M                       | 59% / 32%                               | **36%** (lowest)             | Executor (short sessions), one-shot review, panel worker on bounded targets |
| Opus 4.6   | $5 / $25 base               | 200K default; 1M variant | **92% / 78%**                           | ~38%                         | Executor (long sessions), **supervisor default**, multi-needle review       |
| Sonnet 4.6 | $3 / $15                    | 200K default; 1M variant | strong mid-context; validate 1M variant | similar to Opus              | Handoff agent, mid-cost supervisor, panel worker                            |
| Haiku 4.5  | $1 / $5                     | 200K                     | not the role                            | n/a                          | Handoff agent, tagger, cheap pre-check                                      |

**Cache**: explicit `cache_control` breakpoints, 90% read discount, 1.25× write cost. Forge's `litellm-anthropic` and
`litellm-anthropic-local` templates set `prompt_caching: passthrough` to honor Anthropic's 4-breakpoint limit. Anthropic
charges premium rates above 200K input tokens on the 1M context tier (Opus 4.6: $10 / $37.50 per Mtok), so don't
extrapolate the base row to million-token supervisor runs.

**Key call-out**: Opus 4.7's strict literal instruction following helps JSON schema adherence in one-shot tasks. Its
MRCR regression is real and documented in Anthropic's own system card. For supervision specifically, the default
`tiers.opus: anthropic/claude-opus-4.6` in `openrouter-anthropic.yaml` and `litellm-anthropic.yaml` is the correct
choice. That default maps to Forge's 200K `claude-opus-4-6` catalog entry; keep Opus 4.7 and 1M Opus 4.6 variants as
explicit pins/alternatives, not as the supervisor's `opus` tier default.

### OpenAI

| Variant            | Pricing ($ in/out per Mtok) | Context | MRCR v2 @ 128K / ultra-long | AA-Omniscience hallucination       | Best Forge role                                                                        |
| ------------------ | --------------------------- | ------- | --------------------------- | ---------------------------------- | -------------------------------------------------------------------------------------- |
| GPT-5.5            | $5 / $30                    | ~1.05M  | **94.8% / 74%**             | **86%** (highest in frontier tier) | One-shot review, panel quorum (paired with citation-checker), executor for short tasks |
| GPT-5.4-mini       | $0.75 / $4.50               | n/a     | strong at short context     | n/a                                | Cheap pre-check, panel worker, handoff agent                                           |
| GPT-5.3-Codex      | $1.75 / $14                 | 400K    | n/a                         | n/a                                | Code-tuned executor, codex-style review                                                |
| GPT-5.1-Codex-mini | $0.25 / $2                  | 400K    | n/a                         | n/a                                | Cheap code pre-check                                                                   |

**Cache**: automatic prefix match from 1,024 tokens, 90% read discount (GPT-5.5: $0.50 cached vs $5 standard), free
writes. **Reasoning tokens are billed as output** — at `reasoning_effort: high` (Forge's opus-tier default), hidden
thinking tokens can add 2-5K to the output bill per call at $30/Mtok.

**Key call-out**: GPT-5.5's 86% AA-Omniscience hallucination rate is the highest in the frontier tier. For a supervisor
whose verdict must include verbatim plan citations, this is a real risk — the model can produce confident-but-fabricated
citations. Pair with a strict structured-output schema and treat as a verification reviewer rather than sole fail-closed
authority. The Codex variants (5.3, 5.1-mini) are safer GPT picks for code-specific supervision.

### Gemini (Google)

| Variant                | Pricing ($ in/out per Mtok)   | Context | MRCR v2 @ 128K / 1M    | Notes                                                                                                     | Best Forge role                                                                  |
| ---------------------- | ----------------------------- | ------- | ---------------------- | --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Gemini 3.1 Pro         | $2 / $12 (+$4/$18 above 200K) | 1M      | **85% / drops to 26%** | 7.5× cheaper than Opus on input; long-context attention dropoff at extreme depth                          | Mid-cost supervisor, large-codebase review, cross-routed long-context supervisor |
| Gemini 3 Flash Preview | $0.50 / $3                    | 1M      | strong at \<256K       | Anthropic's frontier scores at Flash price; codebase template comment notes "beats Pro on SWE benchmarks" | Cheap supervisor, panel worker, handoff agent                                    |
| Gemini 2.5 Flash       | $0.30 / $2.50                 | 1M      | weaker than 3 Flash    | Lowest frontier-adjacent price                                                                            | Handoff agent, tagger, bulk classification                                       |

**Cache**: Vertex pricing shows a 90% read discount on Gemini 3 cache hits (Gemini 3.1 Pro: $0.20 cached vs $2 standard
below 200K input tokens). Cache minimums and support are model- and gateway-specific; verify `cached_input_tokens` in
Forge proxy metrics before relying on Gemini cache savings.

**Key call-out**: Gemini 3.1 Pro is the canonical cross-routed supervisor when the executor runs on Claude and the
planner context is mid-long or multimodal. It gives you a different retrieval profile than Claude at lower input cost,
but its public 1M MRCR drop means it is not a blanket replacement for Opus 4.6 on extremely long planner transcripts.

### DeepSeek

| Variant  | Pricing ($ in/out per Mtok) | Context | MRCR v2 8-needle @ 256K / 1M | Notes                                 | Best Forge role                                                                                          |
| -------- | --------------------------- | ------- | ---------------------------- | ------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| V4 Pro   | $0.435 / $0.87              | 1M      | **~82% / 59%**               | Hybrid CSA+HCA attention, MIT license | Cost-efficient supervisor for long-context work, panel dissent worker, executor for cost-sensitive teams |
| V4 Flash | $0.14 / $0.28               | 1M      | weaker                       | Same architecture, smaller            | Bulk inference, drop-in cheap replacement for GPT-5.4                                                    |

**Cache**: automatic, disk-based, persistent across days, with a very steep read discount (V4 Pro: $0.003625 cached vs
$0.435 standard; V4 Flash: $0.0028 cached vs $0.14 standard). No configuration required — repeated prompts hit the cache
automatically.

**Key call-out**: DeepSeek's architecture-first compression delivers competitive long-context multi-needle retrieval at
roughly one-tenth the per-token cost of Opus. On MRCR v2 8-needle at 1M, V4 Pro at 0.59 is below Opus 4.6's 0.78 but
well above Opus 4.7's 0.32 and within reach of GPT-5.5 (0.74). For Forge supervisor work in `warn` mode or as a
second-opinion in panel review, V4 Pro is now a serious candidate, not a budget fallback. Documented limitation: weak
confidence calibration on "unknown-answer" tasks — pair with a strict structured-output schema and validate locally
before promoting to a sole fail-closed authority.

### Kimi (Moonshot AI)

| Variant | Pricing ($ in/out per Mtok)        | Context              | Long-context strength                                                                  | Best Forge role                                                                  |
| ------- | ---------------------------------- | -------------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| K2.6    | $0.74 / $3.50 via Forge/OpenRouter | 32K in Forge catalog | MLA attention, agentic-tuned, 39% AA-Omniscience hallucination (down from 65% on K2.5) | Code-heavy review, panel dissent; verify gateway context before long supervision |
| K2.5    | $0.40 / $1.98 via Forge/OpenRouter | 256K                 | Lower cost, similar architecture without vision                                        | Cheap multimodal executor, panel worker                                          |

**Cache**: standard hit pricing, less aggressive discount than DeepSeek. Forge's bundled catalog currently records
cached input at $0.25/Mtok for K2.6 and $0.05/Mtok for K2.5 via OpenRouter.

Moonshot direct pricing and limits differ from Forge's OpenRouter-backed defaults: Moonshot lists K2.6 at $0.95 / $4.00
per Mtok, K2.5 at $0.60 / $2.50 per Mtok, and larger direct context windows. If you route to Moonshot directly, verify
both price and context at that gateway instead of copying the Forge/OpenRouter row.

**Key call-out**: K2.6 is specifically post-trained for long-horizon multi-tool agent workflows (Agent Swarm to 300
sub-agents over 4000 coordinated steps). For supervising long-running agentic sessions where the planner conversation
includes many tool calls and intermediate states, K2.6's training distribution is a strong match, but Forge's current
OpenRouter catalog records a 32K context window. Validate the gateway limit before using it as a long-context
supervisor.

### GLM (Z.ai), Qwen, MiniMax

| Family  | Variant                   | Pricing                                              | Context                 | Best Forge role                                                   |
| ------- | ------------------------- | ---------------------------------------------------- | ----------------------- | ----------------------------------------------------------------- |
| GLM     | 5.1                       | Subscription: $3 promo / $10 standard per month plan | 203K                    | Budget supervisor, designed for 8-hour autonomous runs            |
| Qwen    | 3.6 Max Preview           | varies by gateway                                    | 260K (extensible to 1M) | Strong general-purpose reviewer, preserve_thinking for multi-turn |
| Qwen    | qwen3-coder (alternative) | varies                                               | similar                 | Code-specific review and supervision                              |
| MiniMax | M2.7                      | $0.299 / $1.20                                       | 196.6K                  | Cheapest warn-only background reviewer; not a reasoning model     |

**Key call-out**: These three families share Chinese-open-weights compression-first architecture characteristics. They
are all reasonable warn-only supervisors at substantially lower cost than Western frontier models. None is currently the
best choice for sole fail-closed authority — validate locally on your repo with
`forge guard supervisor -f <file> -r <session-id> --json` before promoting any of them to blocker status.

---

## Forge-specific patterns

### Use `model_alternatives` instead of multiple proxies

The default `tiers.opus` in `openrouter-anthropic.yaml` and `litellm-anthropic.yaml` is `claude-opus-4.6`. The newer 4.7
is exposed via `model_alternatives.opus.claude-opus-4-7`. You don't need separate proxies for 4.6 vs 4.7 — you pin the
executor session:

```bash
# Planner/supervisor source on Opus 4.6
forge session start planner --proxy openrouter-anthropic

# Executor on Opus 4.7; supervisor reads planner through proxy opus tier (4.6)
forge session start exec --proxy openrouter-anthropic --model claude-opus-4-7 --supervise planner
```

The executor's `--model` pin changes routing for that session's main Claude process. Proxied supervisor calls clear
inherited Claude model-pin environment variables and pass `--model opus`, so the proxy resolves the supervisor through
its `tiers.opus` mapping unless you choose a different supervisor proxy.

### Cross-route the supervisor for mid-long or multimodal planning sessions

When the planner conversation is mid-long, multimodal, or expensive to supervise with Claude, route the supervisor
through a different family with a better fit for that envelope:

```bash
# Executor on Claude (any version), supervisor on Gemini 3.1 Pro
forge guard supervise planner --session exec --supervisor-proxy openrouter-gemini

# Executor on Claude, cost-efficient supervisor on DeepSeek V4 Pro
forge guard supervise planner --session exec --supervisor-proxy openrouter-deepseek
```

This is the "side-channel architecture" pattern: executor and supervisor use different proxies, intentionally. The
`apply_supervisor_routing()` function in `src/forge/guard/semantic/supervisor.py` handles auto-seeding the supervisor
proxy from the planner's `confirmed.started_with_proxy` when you don't pass `--supervisor-proxy` explicitly, so you only
need to override when you want non-default routing.

### Model-pin scope

Model pins are intentionally session-local for proxied supervisors. If you pin `--model claude-opus-4-7` on the
executor, the supervisor does not reuse that pin; it requests the configured supervisor proxy's `opus` tier. Two common
ways to choose a different supervisor route:

```bash
# Option A: use the Anthropic supervisor proxy default (opus tier = 4.6)
forge guard supervise planner --session exec --supervisor-proxy openrouter-anthropic

# Option B: cross-route the supervisor to a different family
forge guard supervise planner --session exec --supervisor-proxy openrouter-gemini
```

For same-worktree final review, you can also move the planner itself back to Opus 4.6 before resuming it:

```bash
forge session resume planner --model claude-opus-4.6
```

`resume --model` updates the session's stored model pin, so later resumes keep using the selected Claude version until
you change it again.

When forking into the reviewer/executor role instead, pin the child directly:

```bash
forge session fork planner --name reviewer --model claude-opus-4.6
```

### Direct-mode planner constraint

If the planner runs in direct mode (no proxy, `ANTHROPIC_API_KEY` only), `should_supervisor_use_direct()` in
`supervisor.py:582` makes the auto-seeded supervisor direct too — otherwise the executor's inherited
`ANTHROPIC_BASE_URL` could silently hijack the supervisor's request. In direct mode there is no proxy `opus` tier to
restore; use `--supervisor-proxy` when you need the supervisor to follow a Forge proxy mapping.

### Skill model-family detection follows the proxy

`/forge:review` and `/forge:understand` auto-detect the model family from the proxy template's `opus` tier via
`forge session context --field model_family` (implemented at `src/forge/core/ops/session_context.py:198`). Today,
specialized resources exist for OpenAI and Gemini; Anthropic and currently-unmapped families use the Anthropic-tuned
default unless additional `code-{family}.md` resources and family mappings are added.

---

## Cost optimization order

Three levers, applied in order. Skip ahead only if the cheaper lever doesn't move the cost enough:

### 1. Verify cache is hitting before changing anything

The supervisor's prompt template + plan override is a stable prefix that should cache on every call after the first.
Check that the cache is actually active:

```bash
forge proxy metrics <proxy_id> --json   # look for cached_input_tokens > 0
```

Provider-specific notes:

- **Anthropic via `litellm-anthropic` / `litellm-anthropic-local`**: `prompt_caching: passthrough` is set by default —
  the cache_control breakpoints from `claude` flow through to the upstream Anthropic API. Verify by checking that
  `cached_input_tokens` grows with successive supervisor invocations.
- **Anthropic via `openrouter-anthropic`**: OpenRouter does not always pass cache_control breakpoints through. If
  `cached_input_tokens` stays at 0, switch to `litellm-anthropic` or `litellm-anthropic-local`.
- **OpenAI**: automatic, no config — should "just work" above the 1024-token prefix minimum.
- **DeepSeek**: automatic disk-based caching, persistent across days. No config needed.
- **Gemini**: cache thresholds and cache support vary by model and gateway. Verify `cached_input_tokens` in proxy
  metrics before assuming Gemini cache savings.

### 2. Tune `reasoning_effort` before swapping models

The same model can swing 5-10× in cost between `reasoning_effort: low` and `high`. The supervisor's task — emit a
structured JSON verdict with a citation — does not require maximum reasoning at every call. Try a lower effort:

```bash
forge proxy set <proxy_id> tier_overrides.opus.reasoning_effort=medium
```

Re-validate that the supervisor still catches the divergences you care about. If verdict quality holds at `medium`, keep
it. Reserve `high` and `xhigh` for executor sessions where reasoning depth is the work.

### 3. Swap the model only if the first two levers didn't suffice

If cache is hitting and effort is tuned and the cost is still too high, swap to a cheaper family. The supervisor-tier
picks above are ranked by cost-quality trade-off:

| Approximate hourly cost at 60 supervisor calls | Pick                         |
| ---------------------------------------------- | ---------------------------- |
| $1.75 – $3.60                                  | Claude Opus 4.6/4.7          |
| $1.00 – $1.50                                  | Claude Sonnet 4.6            |
| $0.90 – $2.40                                  | Gemini 3.1 Pro               |
| $0.40 – $0.72                                  | Gemini 3 Flash Preview       |
| $0.12 – $0.36                                  | DeepSeek V4 Pro (with cache) |
| $0.21                                          | MiniMax M2.7                 |
| $0.04 – $0.12                                  | DeepSeek V4 Flash            |

These estimates assume an 8K cached prefix + 2K variable diff + 600 visible output tokens per call. Reasoning models at
`high` effort add 2-5K hidden thinking tokens billed as output, which can multiply the output cost by 4-10×. Recompute
for your own envelope before committing.

---

## Validating new model releases

Major model releases periodically change behavior in ways that affect role suitability. Before adopting a new version as
your role default, check:

1. **Are long-context benchmarks reported in launch materials, or only in the system-card appendix?** When a benchmark
   that was a headline in the previous release becomes appendix material in the new one, that's a signal to validate the
   new version locally for any role that depends on that capability. (Example: MRCR was a competitive differentiator in
   Anthropic's March 2026 Opus 4.6 1M-window announcement; it was not mentioned in the April 2026 Opus 4.7 launch blog.
   The system card retained the regressed numbers.)
2. **Has the tokenizer changed?** Effective cost can shift at unchanged per-token pricing if the same text now tokenizes
   to more tokens. Opus 4.7 tokenizes 1.0-1.35× more tokens than 4.6 for the same input.
3. **Are explicit inference controls (reasoning budgets, effort tiers, thinking budget tokens) still exposed, or have
   they been mediated behind opaque defaults?** Less user control means less ability to validate cost-quality
   trade-offs.
4. **Is the prior version still available?** Forge's `model_alternatives` is the mechanism for keeping a validated prior
   choice accessible while new versions ship. As long as the provider keeps the old model on the API and your proxy
   template exposes it, you can pin per-session.

These apply equally to every provider — they're release-hygiene practices, not provider-specific concerns. A model whose
reliability shifts silently between releases is not a stable foundation for fail-closed roles. The validation loop:

```bash
# Pin the new version on an executor session
forge session start trial --proxy openrouter-anthropic --model claude-opus-4-7

# Run your own supervisor evaluation on representative diffs
forge guard supervisor -f src/forge/session/store.py -r <trial-session-id> \
  --proxy openrouter-anthropic --json

# Compare verdict quality, citation accuracy, and false-positive rate
# against the prior version before promoting the new default
```

If verdict quality holds, update the template default. If it regresses on the role you're testing, keep the validated
prior version as the template default and expose the new version through `model_alternatives` for the roles where its
strengths matter.

---

## Reference: where each role lives in code

| Role            | CLI entry point                                    | Implementation                                               |
| --------------- | -------------------------------------------------- | ------------------------------------------------------------ |
| Executor        | `forge session start [--proxy <id>] [--model <m>]` | `src/forge/session/manager.py`, `src/forge/cli/session.py`   |
| Supervisor      | `forge guard supervise <target>`                   | `src/forge/guard/semantic/supervisor.py`                     |
| `/forge:review` | `src/skills/review/SKILL.md` (Claude Code skill)   | `src/forge/core/ops/session_context.py` for family detection |
| `/forge:panel`  | `forge workflow panel ...`                         | `src/forge/review/engine.py`, `src/forge/review/models.py`   |
| `/forge:debate` | `forge workflow debate ...`                        | `src/forge/review/engine.py` (adversarial runner)            |
| Handoff agent   | Runs at Stop hook + async work queue               | `src/forge/session/handoff_agent.py`                         |

For the panel and debate model catalog (which family backs which worker), see `src/forge/review/models.py:110-200`. To
add a new model alternative or change the default tier mapping, edit the proxy template under
`src/forge/config/defaults/templates/` and reset proxies that use it with `forge proxy template reset <name>`.

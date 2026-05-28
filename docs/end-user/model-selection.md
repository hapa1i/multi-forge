# Choosing Models for Each Forge Role

Forge templates default per **role**, not per "newest available." A coding executor, a plan supervisor, a one-shot
reviewer, and a panel quorum worker reward different capabilities. A new model can be excellent for bounded coding work
and still be the wrong default for a long-context supervisor.

This page explains the stable selection process. Provider benchmarks, pricing, context windows, and cache behavior
change quickly; use provider documentation and `forge proxy template show <name> --raw` as the dated source of truth
before changing a team default.

- Proxy templates and tier mappings: [`proxies.md`](proxies.md)
- Skill model-family detection: [`skills.md`](skills.md#model-aware-resource-selection)
- Supervisor configuration: [`policies.md`](policies.md#semantic-supervisor-advanced)
- Auth and credentials: [`authentication.md`](authentication.md#which-auth-do-i-need)

---

## TL;DR

| Role                                  | Default posture                                                             | Why                                                              |
| ------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| **Executor** (writes code)            | Use the proxy/session model that performs best on your task envelope        | Coding quality, tool discipline, and latency matter most         |
| **Supervisor** (judges diffs vs plan) | Prefer the validated long-context default for that proxy's `opus` tier      | The job is retrieving and citing the right plan item             |
| **One-shot review**                   | Try newer/high-capability models freely                                     | The context is bounded and easier to validate                    |
| **Panel / debate**                    | Mix providers and model families                                            | Different defaults expose different bugs                         |
| **Handoff agent**                     | Prefer a cheaper summarization-capable model after a review-only smoke test | Single-transcript synthesis is usually cost-sensitive            |
| **Cost-conscious supervision**        | Use warn-only mode until local validation proves blocker quality            | False-positive blocks are more expensive than missed suggestions |

The rule of thumb: **pin models per role, then validate locally**. Do not promote a newly released model to a
fail-closed supervisor role just because it improved on coding benchmarks.

---

## Why Context Fidelity Varies

Long-context behavior can change between model releases even when short-context coding scores improve. Providers tune
attention, caching, compression, reasoning budgets, and serving policy differently across versions. Those changes can
alter a model's ability to retrieve several similar facts from a long conversation.

That matters because Forge roles stress different failure modes:

1. **Supervisor**: long-context retrieval, citation fidelity, and confidence calibration.
2. **Executor**: coding quality, tool discipline, latency, and instruction following.
3. **One-shot reviewer**: bounded-context reasoning and bug finding.
4. **Handoff agent**: summarization quality and cost.

Forge's `model_alternatives` field in proxy templates exists so you can keep more than one version of a vendor's model
available at the same proxy. You do not have to choose once for all roles.

---

## Supervisor Requirements

The semantic supervisor (`forge policy supervise`) runs `claude -p --resume <planner_uuid> --fork-session` on
Write/Edit, throttled by policy settings. When routed through a proxy, Forge passes `--model opus` and clears inherited
executor model pins so the supervisor uses that proxy's `opus` tier. Its job is to read the planner's conversation,
locate the relevant plan section for the action being taken, and emit a verdict with cited evidence.

This is **not** code writing. Coding leaderboards are useful context, but they are not sufficient for choosing a
supervisor. Validate these dimensions locally:

| Capability                               | What it controls                                                                                   | How to validate locally                                           |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| Long-context retrieval                   | Whether the supervisor locates the right plan item among similar distractors                       | Run known aligned/divergent diffs against real planner sessions   |
| Structured output                        | Whether the verdict schema is honored without prose preamble or schema drift                       | Inspect `--json` output and parser failures                       |
| Confidence calibration                   | Whether high confidence means the verdict is actually right                                        | Track false-positive and false-negative examples                  |
| Citation fidelity                        | Whether quoted plan text appears verbatim or is paraphrased into something the user cannot inspect | Grep every cited phrase in the source plan/transcript             |
| Cache effectiveness on the stable prefix | Whether the supervisor prompt + plan override hits the provider's cache on each call               | Check `forge proxy metrics <proxy_id> --json` after repeated runs |

Supervisor cost is usually driven by the stable prompt/context prefix and any hidden reasoning tokens. Before changing
the model, confirm the selected provider is caching repeated supervisor calls and tune `reasoning_effort` if the proxy
exposes it.

---

## Role-Fit Matrix

Use this matrix with the current template catalog and provider docs:

| Family shape                    | Usually good for                                            | Be careful with                                     |
| ------------------------------- | ----------------------------------------------------------- | --------------------------------------------------- |
| Claude-family coding models     | Long-running executor sessions, supervisors, review passes  | Version-to-version long-context behavior changes    |
| OpenAI/Codex-family models      | Code review, code-focused execution, panel diversity        | Citation fidelity in fail-closed supervision        |
| Gemini-family models            | Cross-family supervision, large-context review, low latency | Gateway-specific cache/context limits               |
| DeepSeek/Kimi/Qwen/GLM/MiniMax  | Cost-conscious warn-only checks, panel dissent, bulk tasks  | Promoting to sole blocker without repo-local trials |
| Cheap/fast models in any family | Handoff agent, taggers, pre-checks                          | High-consequence enforcement                        |

Treat this as a starting posture, not a benchmark table. Record the exact model version, provider route, source date,
and local validation result whenever you change a proxy default.

---

## Forge-Specific Patterns

### Use `model_alternatives` Instead Of Multiple Proxies

The bundled Anthropic proxy templates keep the validated `opus` tier default and expose newer alternatives for explicit
session pins. You do not need separate proxies just to compare two Claude versions:

```bash
# Planner/supervisor source on the proxy's default opus tier
forge session start planner --proxy openrouter-anthropic

# Executor pinned to an alternative exposed by the same proxy
forge session start exec --proxy openrouter-anthropic --model claude-opus-4-7 --supervise planner
```

The executor's `--model` pin changes routing for that session's main Claude process. Proxied supervisor calls clear
inherited Claude model-pin environment variables and pass `--model opus`, so the proxy resolves the supervisor through
its `tiers.opus` mapping unless you choose a different supervisor proxy.

### Cross-Route The Supervisor

When the planner conversation is mid-long, multimodal, or expensive to supervise with the executor's family, route the
supervisor through another proxy and validate the result:

```bash
# Executor on one proxy, supervisor on another
forge policy supervise planner --session exec --supervisor-proxy openrouter-gemini

# Cost-conscious supervisor candidate in warn-only workflows
forge policy supervise planner --session exec --supervisor-proxy openrouter-deepseek
```

This is the side-channel architecture pattern: executor and supervisor use different proxies intentionally.
`apply_supervisor_routing()` auto-seeds the supervisor proxy from the planner's `confirmed.started_with_proxy` when you
do not pass `--supervisor-proxy`, so override only when you want non-default routing.

### Model-Pin Scope

Model pins are intentionally session-local for proxied supervisors. If you pin `--model claude-opus-4-7` on the
executor, the supervisor does not reuse that pin; it requests the configured supervisor proxy's `opus` tier.

For same-worktree final review, you can move the planner itself to a different model before resuming it:

```bash
forge session resume planner --model claude-opus-4-6
```

`resume --model` updates the session's stored model pin, so later resumes keep using the selected Claude version until
you change it again.

When forking into the reviewer/executor role instead, pin the child directly:

```bash
forge session fork planner --name reviewer --model claude-opus-4-6
```

### Direct-Mode Planner Constraint

If the planner runs in direct mode (no proxy, `ANTHROPIC_API_KEY` only), `should_supervisor_use_direct()` makes the
auto-seeded supervisor direct too. Otherwise the executor's inherited `ANTHROPIC_BASE_URL` could silently hijack the
supervisor request. In direct mode there is no proxy `opus` tier to restore; use `--supervisor-proxy` when you need the
supervisor to follow a Forge proxy mapping.

### Skill Model-Family Detection Follows The Proxy

`/forge:review` and `/forge:understand` auto-detect the model family from the proxy template's `opus` tier via
`forge session context --field model_family`. Today, specialized resources exist for OpenAI and Gemini; Anthropic and
currently-unmapped families use the Anthropic-tuned default unless additional `code-{family}.md` resources and family
mappings are added.

---

## Cost Optimization Order

Three levers, applied in order. Skip ahead only if the cheaper lever does not move the cost enough:

### 1. Verify Cache Is Hitting

The supervisor's prompt template + plan override should behave like a stable prefix on providers that support prompt
caching. Check that the cache is actually active:

```bash
forge proxy metrics <proxy_id> --json   # look for cached_input_tokens > 0
```

Cache thresholds and discounts vary by provider and gateway. If the metric stays at zero after repeated comparable
supervisor calls, verify the proxy template and gateway support caching before changing models.

### 2. Tune `reasoning_effort`

The same model can vary dramatically in cost between low and high effort. The supervisor's task is a structured verdict
with citations; it does not always require maximum reasoning. Try a lower effort and re-run known aligned/divergent
examples:

```bash
forge proxy set <proxy_id> tier_overrides.opus.reasoning_effort=medium
```

Reserve higher effort for executor sessions or for supervisors where local validation proves it catches materially more
important divergences.

### 3. Swap The Model

If cache is hitting and effort is tuned but cost is still too high, test a cheaper family. Start in warn-only mode or as
a panel worker, collect false positives/negatives, and promote only after it performs well on your repo's real plans and
diffs.

---

## Validating New Model Releases

Major model releases periodically change behavior in ways that affect role suitability. Before adopting a new version as
your role default, check:

1. **Are long-context benchmarks reported for the context sizes you use?** If not, run local trials before using it for
   supervision.
2. **Has the tokenizer changed?** Effective cost can shift at unchanged per-token pricing.
3. **Are inference controls still exposed?** Less control over effort/reasoning budgets means less ability to tune
   cost-quality trade-offs.
4. **Is the prior version still available?** Forge's `model_alternatives` is the mechanism for keeping a validated prior
   choice accessible while new versions ship.
5. **Did your local validation pass?** A model whose reliability shifts silently between releases is not a stable
   foundation for fail-closed roles.

The validation loop:

```bash
# Pin the candidate on an executor session
forge session start trial --proxy openrouter-anthropic --model claude-opus-4-7

# Run supervisor evaluation on representative diffs
forge policy supervisor -f src/forge/session/store.py -r <trial-session-id> \
  --proxy openrouter-anthropic --json

# Compare verdict quality, citation accuracy, and false-positive rate
# against the prior version before promoting the new default
```

If verdict quality holds, update the template default. If it regresses on the role you are testing, keep the validated
prior version as the template default and expose the new version through `model_alternatives` for the roles where its
strengths matter.

---

## Reference

| Role            | CLI entry point                                    | Implementation                                               |
| --------------- | -------------------------------------------------- | ------------------------------------------------------------ |
| Executor        | `forge session start [--proxy <id>] [--model <m>]` | `src/forge/session/manager.py`, `src/forge/cli/session.py`   |
| Supervisor      | `forge policy supervise <target>`                  | `src/forge/policy/semantic/supervisor.py`                    |
| `/forge:review` | `src/skills/review/SKILL.md` (Claude Code skill)   | `src/forge/core/ops/session_context.py` for family detection |
| `/forge:panel`  | `forge workflow panel ...`                         | `src/forge/review/engine.py`, `src/forge/review/models.py`   |
| `/forge:debate` | `forge workflow debate ...`                        | `src/forge/review/engine.py` (adversarial runner)            |
| Handoff agent   | Runs at Stop hook + async work queue               | `src/forge/session/handoff_agent.py`                         |

For the panel and debate model catalog, see `src/forge/review/models.py`. To add a new model alternative or change the
default tier mapping, edit the proxy template under `src/forge/config/defaults/templates/` and reset proxies that use it
with `forge proxy template reset <name>`.

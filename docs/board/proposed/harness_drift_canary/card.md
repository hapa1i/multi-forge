# Harness Drift Canary -- golden-prompt eval observability (no MITM)

**Status**: Proposed. Spun out of the `runtime_abstraction` OAuth-MITM deferral (2026-06-07). This is the **ToS-clean,
no-interception** half of "observe the harness boundary" -- worth doing on its own merits, independent of whether MITM
is ever built.

**References**: design.md §"Optional Always-On Proxy" (the counterweight note: drift Forge "can only detect indirectly
-- output distribution changes, failed golden prompts"), `runtime_abstraction` card.md ("OAuth interactive wire
observability -- deferred decision").

## Problem

Agent quality can change at the **harness boundary** without leaving the user local evidence -- the April-2026 Anthropic
postmortem case (silent reasoning-effort downgrade; a thinking-cache bug; a hidden "\<=100 words" system-prompt
injection). Forge's only *wire-level* answer is the optional audit proxy, and the one regression that is **invisible at
the wire** (a system prompt injected *downstream* of the proxy) can't be caught by inspection at all -- only by its
*effects*. For OAuth/subscription interactive sessions, even the wire is out of reach without MITM, which is
[deferred and account-risky](../../doing/runtime_abstraction/card.md).

## Proposal

A periodic **golden-prompt eval canary**: run a small fixed battery of prompts on a schedule (and/or on demand), capture
structured outputs, and watch for distribution shifts that signal a harness/model change -- regardless of route,
runtime, or auth mode.

```text
fixed prompt battery
  -> run via the user's normal route (claude -p, or a chosen proxy/model)
  -> capture structured signals (length, refusal rate, reasoning-token usage,
     tool-call shape, a rubric score from a cheap judge model)
  -> compare against a rolling baseline
  -> alert on drift (effect detected); user investigates
```

It detects **effects**, not wire bytes, so it needs **zero interception, zero CA injection, zero account risk** -- and
it catches the one class (downstream system-prompt injection) that even wire inspection misses.

## Why this over (or before) MITM

- **ToS-clean**: no TLS interception, no credential handling, no fingerprint divergence -- none of the
  account-suspension risk that defers the OAuth-MITM tier.
- **Runtime-neutral**: works for `claude -p`, proxy routes, and Codex -- it observes outputs, not a specific wire.
- **Flight-recorder-correct**: cheap enough to keep running *before* an incident, which is the only time an observer has
  value (see the timing trap in the runtime_abstraction decision note).
- **Not coupled to runtime abstraction**: it is an eval/observability feature, not a runtime seam -- which is why it is
  its own card rather than a `runtime_abstraction` slice.

## Open questions

- Battery design: how many prompts, which signals, and what makes a baseline "drifted" vs noisy run-to-run variance?
- Judge model: a cheap rubric scorer (`core.llm`) vs purely mechanical signals (length, refusal, reasoning tokens, tool
  shape)? Start mechanical; add a judge only if it earns its cost.
- Cadence + cost: scheduled (cron-like) vs on-demand `forge` verb; what is an acceptable per-run token budget?
- Storage: reuse the usage ledger / a new `~/.forge/evals/` plane? Baselines must persist across runs.
- Surface: a `forge` verb (e.g. `forge eval canary`) + a status-line drift signal?

## Out of scope

- Any wire interception / MITM / CA injection (that is the deferred `runtime_abstraction` OAuth tier).
- Attributing a detected drift to a *specific* harness change -- the canary flags that *something* changed; diagnosis is
  the user's (or a follow-up wire audit's) job.
- Becoming a benchmark suite. This is a drift *tripwire*, not a model-quality leaderboard.

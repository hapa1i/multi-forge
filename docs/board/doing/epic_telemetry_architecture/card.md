# Epic: Telemetry Architecture -- two planes, one source key

**Status**: Doing **epic** (`doing/epic_telemetry_architecture`). Created 2026-06-16 to hold the shared contract between
two refactor proposals that were spun -- independently -- from the same root investigation (the 2026-06-14
supervisor-timeout / shadow-sampling incident) and that both re-architect Forge's telemetry planes, along **orthogonal
axes**. This card is the single consistent view the member cards lean on; it does **not** replace them. Its
`checklist.md` is for coordination and sequencing only; member cards remain the execution units.

**Current coordination goal**: `unified_backend` is the active member after `upstream_downstream_ledgers` landed. Keep
remote reconciliation paused until the backend/source identity key lands or this epic deliberately changes the sequence.

## Why an epic, not a merged card

The two member proposals overlap at exactly one seam -- the `src/forge/core/usage/emit.py` provenance branch and the
plane layout -- but answer different questions with very different blast radii. Merging them into one card would chain a
focused, near-ready telemetry-plane refactor to a large, "spike-first" backend-concept refactor (config + CLI + auth +
`ProviderType` + templates) and break independent shippability. So they stay separate cards with a shared contract
recorded here. (`unified_backend` itself keeps "the three axes -- proxy / provider / backend -- distinct"; this epic
applies the same discipline one level up.)

## North star

Two telemetry planes, joined by run-tree identity, with one canonical source key:

| Plane          | Unit           | Absorbs today's               | Keyed by                                      | Session?       |
| -------------- | -------------- | ----------------------------- | --------------------------------------------- | -------------- |
| **Downstream** | one model call | cost + audit + provider-trace | `request`/`run`/`root` ids + **`backend_id`** | session-blind  |
| **Upstream**   | one operation  | (new) operation outcome       | `session` + `run`/`root` ids                  | session-tagged |

- **Downstream** = per-call model-interaction evidence (tokens, cost, provenance, optional redacted req/resp, provider
  lifecycle/correlation). It unifies **three** of today's four planes.
- **Upstream** = per-operation outcome (success/failure + reason), first-class, covering the no-call operations
  (deterministic TDD, auth fail-open, cached allow) that emit nothing today.
- **Correlation** flows session -> run-tree -> downstream. Downstream is session-blind (the proxy never sees a session
  id); the run-tree id is the only join key that reaches it. Source identity on downstream is `backend_id`.

## Member cards and ownership split

| Concern                                     | Owner card                                                                                  | Status                                             |
| ------------------------------------------- | ------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| Plane **structure** (direction: up/down)    | [`upstream_downstream_ledgers`](../../done/upstream_downstream_ledgers/card.md)             | done                                               |
| Source-identity **key** (`backend_id`)      | [`unified_backend`](../unified_backend/card.md)                                             | doing                                              |
| Provider-trace plane (first to be absorbed) | [`openrouter_observability`](../../done/openrouter_observability/card.md)                   | done                                               |
| Source-identity consumer: logs              | [`proxy_log_hygiene`](../../done/proxy_log_hygiene/card.md)                                 | done                                               |
| Source-identity consumer: remote reconcile  | [`openrouter_remote_reconciliation`](../../paused/openrouter_remote_reconciliation/card.md) | paused after Phase 0 pending source-key foundation |

**Contract (the consistency anchor):**

1. **Structure was delivered by `upstream_downstream_ledgers`.** It established the two planes (downstream/upstream) and
   owns the shipped `core/usage/measurement.py` provenance seam (`UsageMeasurement` plus the
   `resolve_claude_p_measurement`, `resolve_codex_measurement`, and `resolve_direct_llm_measurement` resolvers) on the
   downstream write.
2. **The key is owned by `unified_backend`.** It defines `backend_id` as the canonical model-source identity; downstream
   telemetry attributes to it, retiring provider-trace's hardcoded `provider_name == "openrouter"` gate.
3. **`unified_backend` §5 defers plane count to this epic / `upstream_downstream_ledgers`.** It should assert only "the
   downstream plane keys on `backend_id`," not "the four planes persist."
4. **One `emit.py` refactor, not two.** Whichever card executes the telemetry change second builds on the first; they
   must not author independent, mutually blind refactors of the shared provenance branch.

**Source of truth & drift.** This contract is canonical; each member card restates it as a copy for local context. If
the contract changes, change it **here first**, then update linked member cards. The active branch may still carry
proposed sibling cards until sequencing is decided; this epic is the reconciliation point.

## Sequencing

`openrouter_observability` shipped provider-trace as a standalone fourth plane -- correctly: a clean break owned later,
not a speculative seam built on a sample size of one. The sequencing question was whether to resume
`openrouter_remote_reconciliation` as planned or first execute one of the sibling foundation cards. Either foundation
order works:

- **`unified_backend` first** -> `backend_id` exists, and `upstream_downstream_ledgers` keys downstream correctly from
  day one.
- **`upstream_downstream_ledgers` first** -> downstream keys on `proxy_id` initially and re-keys to `backend_id` when
  `unified_backend` lands.

**Decision (2026-06-17): run `upstream_downstream_ledgers` first.** It fixed the telemetry plane shape before more
OpenRouter-specific reconciliation logic lands, so remote reconciliation can return later as a general downstream
consumer instead of another special-purpose telemetry path. `unified_backend` remains the source-key foundation that
should follow or be sliced as a `backend_id` precursor, but it is a larger config/auth/template/CLI refactor.

**Update (2026-06-18):** the ledger foundation has landed, and `unified_backend` is the next active member. Remote
reconciliation remains paused until the backend/source identity key lands or this epic deliberately changes the
sequence. The hard rule remains contract item 4: one shared `emit.py` provenance refactor, not independent sibling
rewrites.

## Not in scope here

This epic carries no feature implementation detail of its own -- each member card holds its own problem framing, design
sketch, risks, and execution checklist. Update this card when the contract, member set, or sequencing changes.

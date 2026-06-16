# Telemetry Architecture (epic) -- two planes, one source key

**Status**: Proposed **epic** (a coordinating note, not a directly-executed card). Created 2026-06-16 to hold the shared
contract between two refactor proposals that were spun -- independently -- from the same root investigation (the
2026-06-14 supervisor-timeout / shadow-sampling incident) and that both re-architect Forge's telemetry planes, along
**orthogonal axes**. This card is the single consistent view the member cards lean on; it does **not** replace them and
carries **no checklist of its own** (its members are the execution units).

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

| Concern                                     | Owner card                                              | Status                                                      |
| ------------------------------------------- | ------------------------------------------------------- | ----------------------------------------------------------- |
| Plane **structure** (direction: up/down)    | `upstream_downstream_ledgers`                           | proposed (this branch)                                      |
| Source-identity **key** (`backend_id`)      | `unified_backend`                                       | proposed (on the `openrouter-observability` branch)         |
| Provider-trace plane (first to be absorbed) | `openrouter_observability`                              | Phases 0-3 shipped on the `openrouter-observability` branch |
| Source-identity consumers (logs/reconcile)  | `proxy_log_hygiene`, `openrouter_remote_reconciliation` | proposed                                                    |

**Contract (the consistency anchor):**

1. **Structure is owned by `upstream_downstream_ledgers`.** It decides there are two planes (downstream/upstream) and
   owns the `resolve_measurement` provenance resolver on the downstream write.
2. **The key is owned by `unified_backend`.** It defines `backend_id` as the canonical model-source identity; downstream
   telemetry attributes to it, retiring provider-trace's hardcoded `provider_name == "openrouter"` gate.
3. **`unified_backend` §5 defers plane count to this epic / `upstream_downstream_ledgers`.** It should assert only "the
   downstream plane keys on `backend_id`," not "the four planes persist."
4. **One `emit.py` refactor, not two.** Whichever card executes the telemetry change second builds on the first; they
   must not author independent, mutually blind refactors of the shared provenance branch.

**Source of truth & drift.** This contract is canonical; each member card restates it as a copy for local context. If
the contract changes, change it **here first**. The members currently live on separate branches (`unified_backend` on
`openrouter-observability`; `upstream_downstream_ledgers` + this epic on `supervisor_statusline_health`), so until both
reach `main` the restatements can drift -- this epic is the reconciliation point.

## Sequencing

`openrouter_observability` ships provider-trace as a standalone fourth plane now -- correctly: a clean break owned
later, not a speculative seam built on a sample size of one. Then either order works:

- **`unified_backend` first** -> `backend_id` exists, and `upstream_downstream_ledgers` keys downstream correctly from
  day one.
- **`upstream_downstream_ledgers` first** -> downstream keys on `proxy_id` initially and re-keys to `backend_id` when
  `unified_backend` lands.

Both are acceptable; the only hard rule is contract item 4 (single shared `emit.py` refactor).

## Not in scope here

This epic carries no implementation detail of its own -- each member card holds its own problem framing, design sketch,
risks, and (when executed) checklist. Update this card only when the contract or the member set changes.

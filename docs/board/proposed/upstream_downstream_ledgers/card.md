# Upstream / Downstream Ledgers -- collapse four telemetry planes into two

**Status**: Proposed. Spun out of the `supervisor_statusline_health` investigation (2026-06-16) -- a first-principles
dialogue on why surfacing a supervisor timeout on the status line kept colliding with telemetry complexity. The
conclusion: the messiness is a symptom of Forge's **telemetry planes being split along the wrong axis** -- consumption,
redacted wire capture, per-call provider lifecycle, and outcome scattered across **four** planes, with the usage plane
conflating two of them.

**Updated 2026-06-17.** The now-done `openrouter_observability` card shipped a fourth plane -- provider-trace
(`~/.forge/providers/<source>/traces/`, `src/forge/proxy/provider_trace_logger.py`) -- and the sibling `unified_backend`
card proposes a canonical model-source id (`backend_id`) the telemetry planes should key on. Provider-trace is
**downstream by this card's taxonomy** (per-call, session-blind, metadata-only model-interaction evidence), so the
target is **four planes -> two**, not three. This card owns plane **structure**; `unified_backend` owns the
source-identity **key**. The shared contract and member list live in the
[`epic_telemetry_architecture`](../../doing/epic_telemetry_architecture/card.md).

**Epic**: [`epic_telemetry_architecture`](../../doing/epic_telemetry_architecture/card.md).

**References**: `src/forge/core/usage/emit.py` (the proxied/direct provenance branch, inline in two emitters),
`src/forge/core/usage/ledger.py` (`UsageEvent`), `src/forge/proxy/cost_logger.py` + `src/forge/proxy/audit_logger.py` +
`src/forge/proxy/provider_trace_logger.py` (the cost + audit + provider-trace planes -- the three per-call/downstream
planes), `src/forge/core/ops/usage_summary.py` (joins the tangle today), `src/forge/policy/store.py`
(`confirmed.policy.decisions` -- the accidental outcome side-channel), [design.md §3.14](../../../design.md),
[design_appendix §A.12-A.14](../../../design_appendix.md).

## Problem

Forge has **four** durable telemetry planes today -- cost (`~/.forge/costs/requests/`), audit (`~/.forge/audit/`), usage
(`~/.forge/usage/events/`), and provider-trace (`~/.forge/providers/<source>/traces/`, shipped on the
`openrouter-observability` branch) -- split along the **wrong axis**. The natural axis is two:

- **Downstream** -- model-interaction evidence: tokens, cost, provenance, and optional redacted request/response
  capture. Per call.
- **Upstream** -- operation outcome: success/failure + reason. Per operation.

On that axis the current planes are mis-cut:

- **cost, audit, and provider-trace are all downstream** (per-call metrics, redacted wire capture, and per-call provider
  lifecycle/correlation) but live as **three** separate planes -- provider-trace landing as a standalone fourth plane is
  itself the per-feature-plane proliferation this card argues against;
- the **usage ledger straddles both** -- `cost_micro_usd`/tokens (downstream) and `status`/`failure_type` (upstream) on
  one record, emitted at the **subprocess-call** layer (`emit_usage_for_session_result`, fired only when a `claude -p`
  actually runs);
- **attribution** (run/session/command/model) is bolted onto usage instead of being correlation metadata carried on each
  plane.

The conflation surfaces as -- each observed during the supervisor investigation:

- **Misses no-call operations.** A deterministic TDD check (emits nothing), an auth/proxy-not-found fail-open (returns
  before the call, `supervisor.py:461-469`), and a cached supervisor allow (no call) produce **no usage event** -- so
  nothing answers "did this verb succeed?" for them.
- **Conflates call-success with operation-success.** A parse fail-open is a *successful subprocess* (`status="success"`)
  whose *verb* failed -- the wrong outcome is recorded.
- **Forces an accidental outcome side-channel.** Because the usage ledger cannot answer outcome for no-call ops,
  `confirmed.policy.decisions` became the de-facto outcome log for the supervisor -- a policy-only side-channel that
  overlaps and disagrees with the usage ledger's `status`.
- **Scatters provenance.** The proxied-vs-direct cost/token source resolution lives inline in **two** emitters
  (`emit_usage_for_session_result`, `emit_worker_usage`); only the *direct* half (`_direct_cost_provenance`) is shared,
  and the two proxied halves intentionally **diverge** (the verb attributes the proxy snapshot; a per-worker event stays
  unattributed so it does not double-count). `emit_verb_usage` is a snapshot-only aggregate with no direct path. It
  "looks duplicated but subtly isn't" -- which is what makes extracting one resolver delicate.

The motivating symptom: surfacing "the supervisor timed out" on the status line *appeared* to need a new `failure_kind`
field on `PolicyDecision` plus a classifier -- patching the *accidental* outcome record because the *real* one does not
exist as a plane.

## First-principles model

Two planes, one correlation:

| Plane          | Unit           | Records                                              | Wrapped at                   | Session?                                       |
| -------------- | -------------- | ---------------------------------------------------- | ---------------------------- | ---------------------------------------------- |
| **Downstream** | one model call | tokens, cost, provenance, optional redacted req/resp | the call (proxy/self-report) | **session-blind** -- request/run/root ids only |
| **Upstream**   | one operation  | success/failure + reason, latency                    | operation boundary           | session + run/root ids                         |

- **Downstream absorbs today's cost + audit + provider-trace.** Metrics always; the optional redacted request/response
  capture is exactly today's `audit.audit_full_body`; provider-trace's per-call lifecycle/correlation (generation id,
  stream-lifecycle flags, `local_usage_status`) is the same per-call evidence under a different name. They are one
  plane: per-call evidence about the model interaction.
- **Upstream is new and first-class.** It records operation outcome for *every* operation, including no-call ops (TDD,
  auth fail-open, cached allow), retiring the supervisor's reliance on `confirmed.policy.decisions`.
- **Correlation flows session -> run-tree -> downstream.** **Upstream** records carry `session` + `run`/`root` id;
  **downstream** records carry `request`/`run`/`root` ids but **no session** (the proxy never sees one -- session-blind
  by design). Readers **select upstream by `session`, then join downstream by run tree** (`forge_root_run_id`). Session
  alone cannot reach downstream (it is not there) and is too coarse anyway -- upstream:downstream is 1:N (one operation
  makes many calls).
- **Operations have well-defined boundaries, because the CLI is the universal seam.** Nearly every Forge operation is
  reachable via a `forge` verb (hooks are `forge hook <name>`; the memory writer is `forge memory-writer run`; shadow
  drain is `forge policy shadow run`; a supervisor check is `forge policy check`) **or runs in-process inside one** (the
  action tagger and the per-marker index handler have no standalone verb -- they execute within an enclosing CLI/hook
  command). The upstream ledger wraps at the **operation boundary**, which is the CLI verb **or finer**: one
  `forge hook policy-check` runs TDD + coding-standards + supervisor as separate evaluations and may nest a tagger call,
  so "ledger-wrapped" is a finer set than "top-level verb." The wrap is uniform across boundaries -- general, not
  per-feature.

Reading the upstream ledger then answers every "did Forge's automation work?" question -- supervisor health,
memory-writer health, TDD outcomes, panel-worker failures -- from one place, with no per-feature schema surgery.

## Two constraints this refactor does NOT remove (essential, not accidental)

1. **Correlation is session -> run-tree, not session-on-everything.** Downstream is **session-blind** by design (the
   proxy never sees a session id); the run-tree id (`FORGE_ROOT_RUN_ID`) is the only join key that reaches it. Keep the
   run tree -- it is what *prevents* the mess, not part of it.
2. **Downstream cost source is proxied-vs-direct.** A `claude -p` self-report is authoritative when **direct** but
   Anthropic-priced-and-wrong when **proxied** (use the proxy's figure). The `if proxied` is "which downstream source is
   authoritative" -- it reflects who physically measured the call. The refactor **consolidates** it into one resolver
   (`resolve_measurement`); it does not delete it.

## Design sketch

- **Collapse four planes into two -- do NOT merely split `UsageEvent`.** The trap for the implementer: splitting the
  usage ledger while leaving cost, audit, and provider-trace as separate planes leaves the old architecture intact. The
  target is **two** planes -- **downstream** = today's cost + audit + provider-trace unified (per-call metrics +
  optional redacted req/resp + provider lifecycle/correlation), and **upstream** = a new operation-outcome plane. The
  usage ledger's two halves migrate to those homes; attribution becomes run-tree metadata on each, not a plane.
- **Emit outcome at each operation boundary**, not just CLI command-core ops: CLI ops (`core/ops/`), **hook policy
  evaluations** (`cli/hooks/` + `policy/` -- where TDD and supervisor checks fire, at finer granularity than the
  enclosing `forge hook` command), **async workers** (memory writer, shadow drain), and **workflow invocations**
  (panel/debate workers). A `try/finally`/context manager at each boundary so no-call ops emit an outcome too.
- **One provenance resolver for downstream.** Collapse the proxied/direct branch -- inline in two emitters, with
  intentionally divergent proxied halves -- into a single
  `resolve_measurement(proxied, cost, envelope, caller) -> Measurement`, ideally returned by the invoker
  (`core/invoker/`), so the downstream write becomes `record(measurement, attribution)`. The resolver must **preserve**
  the divergence (a per-worker call stays unattributed) or it reintroduces the double-count it was meant to remove.
  - **The same proxied/direct asymmetry is also a *persistence* gap, not only a cost-source choice.** Provider-trace is
    persisted **only on the proxied path today** -- the proxy's `on_complete` writes it (`server.py` ->
    `provider_trace_logger.py`), gated on `provider_name == "openrouter"`. The direct `core.llm` clients already
    **build** the same per-call evidence onto the response object (`CompletionResponse.provider_meta` /
    `StreamEvent.provider_meta`, `ProviderTraceMeta` at `core/llm/types.py:155`), but `emit.py` never reads it -- so a
    direct call (action tagger, tier-1 plan-check, transfer curation) constructs `provider_meta` and **drops it**,
    persisting no provider correlation even though cost/tokens are kept. The unified downstream writer must consume
    `provider_meta` on the direct path too -- a `Measurement` that carries provider metadata (not just cost/tokens)
    closes this in one place. (Cross-branch: these symbols live on `openrouter-observability`, not this branch.)
- **Downstream keys on `backend_id` (owned by `unified_backend`).** Today downstream attribution is `proxy_id` + ad-hoc
  provider strings (provider-trace literally hardcodes `provider_name == "openrouter"`). The canonical model-source id
  is the `unified_backend` card's deliverable; this refactor **consumes** it as the downstream attribution key rather
  than minting its own. Plane **structure** is owned here; the source-identity **key** is owned there. If
  `unified_backend` lands first, downstream is keyed correctly from day one; if this card lands first, downstream keys
  on `proxy_id` and re-keys on adoption -- the
  [`epic_telemetry_architecture`](../../doing/epic_telemetry_architecture/card.md) records the sequencing.
- **Consumers read the right plane -- and `forge activity` becomes the honest join.** Upstream answers health/outcome
  (select by session), downstream answers spend (join by run tree). `forge activity` is then a **two-pane outer join,
  not one conflated row**: an upstream pane (outcomes grouped by verb/session, including the no-call ops downstream
  lacks) and a downstream pane (tokens/cost joined by run tree, authoritative). Today it instead joins the usage ledger
  against `confirmed.policy.decisions` (the accidental outcome record) and reports *estimated, best-effort* cost rather
  than the authoritative cost plane -- so the redefinition upgrades both panes at once: the real upstream plane replaces
  the policy side-channel, and authoritative run-tree cost replaces the estimate.

## Failure modes the downstream ledger must survive

The classic ways a usage/billing system rots. Each was checked against current code; the merge must not regress any of
them.

- **No idempotency on writes (replay / double-write).** The per-call `request_id` (`cost_logger.py:96`) is a *join* key,
  not an idempotency key: no reader de-dupes on it, a client may supply `X-Request-ID` verbatim, and the auto fallback
  is a truncated uuid4. The dedupe-tagged id (`event_id`) lives on a different plane. The merged downstream writer must
  define an explicit idempotency/replay contract -- today there is none.
- **Double-count is guarded but fragile.** The 4g run-tree suppression (`usage_summary.py:382`,
  `sum_reported_cost_by_root`) does prevent the snapshot-vs-exact and per-worker-vs-verb overlaps -- per-run-*subtree*,
  and **best-effort** (a cost-read failure falls back to the snapshot). It is the most intricate code in the stack;
  change it behind the invoker seam with the suppression suite as the guard, never in the read layer.
- **Best-effort writes back a cap that is not fail-closed.** Every cost/usage write swallows all exceptions to a warning
  (`cost_logger.py:101-111`, `ledger.py:159-185`), and spend-cap accounting runs *inside that same swallow path* -- so a
  dropped write silently under-counts spend against the cap. Fail-open is correct for *outcome* telemetry; the cap is
  the one consumer that needs a fail-closed or reconciled read. The merge must not fold cap accounting into the
  best-effort contract.
- **Integer micros, and `None` is not `0`.** Money is integer micro-USD on both planes (no float drift) but **named
  differently** -- `cost_micros` on the cost log, `cost_micro_usd` on the usage ledger -- and `None` means "no route
  reported a cost," not free. The merged schema must unify the name and **preserve the `None`-is-not-`0` distinction**:
  coalescing `None` to `0` silently converts unmeasured spend into free spend.
- **Attribution degrades silently when the run-tree key is absent.** The cost record is session-blind and joined only by
  `forge_root_run_id` (`cost_logger.py:82-99`); for interactive/native traffic that key is `None`, so cost falls back to
  *estimated snapshots*. Carry the run-tree key end-to-end and keep the measured-vs-estimated label, so a join miss is
  visible -- not absorbed into an authoritative-looking total.

## Risks / open questions

- **Durable-schema change across four planes.** All four are versioned durable JSONL, but read with **three different**
  strictness contracts: `UsageEvent` and provider-trace are strict-read (dacite, unknown fields rejected);
  `read_cost_logs`/`read_audit_logs` are shape-tolerant dict readers that skip records from a newer `schema_version`
  (§A.12-A.14). Re-cutting them into two is a research-preview clean break (bump/reset + changelog + reset instructions
  per coding-standards §5); the merged downstream reader must pick one strictness contract, not inherit three.
- **Upstream scope = event volume.** What counts as a recorded operation? Every TDD check (one per Write/Edit) and every
  cached allow could flood the upstream ledger. Draw the boundary deliberately (likely: enforced verbs + fail-opens, not
  every deterministic pass). **Open question.**
- **Audit's redaction guarantees must survive the merge.** Downstream's optional body capture inherits the
  no-plaintext-secret invariant (`audit_logger` redacts before persisting); folding audit into downstream must not
  weaken it.
- **Are tool/function calls downstream?** Out of scope for v1 unless they carry independent cost.

## Relationship to `supervisor_statusline_health`

That card ([`done/supervisor_statusline_health`](../../done/supervisor_statusline_health/card.md)) is the forcing
function that revealed this. It shipped the **minimal on-model step**: read the outcome data the usage ledger already
records (`command="supervisor"` `status`) for the timeout marker -- *not* the off-model `PolicyDecision.failure_kind`.
This card is the principled completion: make upstream/downstream first-class so the next health surface needs no new
field.

## Relationship to `unified_backend` (source identity)

`unified_backend` and this card are the **two orthogonal axes** of the telemetry rethink, not duplicates:

- **This card** re-cuts the planes by **direction** -- per-call *downstream* vs per-operation *upstream*. It owns plane
  **structure** and the `resolve_measurement` provenance resolver.
- **`unified_backend`** promotes "model source" to a first-class noun and makes `backend_id` the **canonical source
  key**. Its telemetry section (§5) owns the **key**, not the plane count -- it should defer "how many planes" to this
  card.

They are **composable** (collapse-to-two *and* key downstream on `backend_id` is the intended end state) and both edit
the same `emit.py` provenance branch, so they must not run as independent, mutually blind refactors. They are
**deliberately not merged** into one card: the bulk of `unified_backend` (backend lifecycle, `forge backend list`, auth
provenance, the model-source catalog) is config/CLI/auth work with its own large blast radius and "spike first" posture,
and chaining this telemetry refactor to it would break independent shippability. The shared contract -- *downstream keys
on `backend_id`; structure owned here, key owned there* -- and the sequencing live in
[`epic_telemetry_architecture`](../../doing/epic_telemetry_architecture/card.md).

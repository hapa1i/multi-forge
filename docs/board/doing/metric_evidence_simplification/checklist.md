# Metric Evidence Simplification — Execution Checklist

Branch: `feat/metric-evidence-simplification`. Card: `card.md` (this directory).

Internal map to fold/supersede during execution: `docs/auth_cost_metric.md` (the auth/cost/usage audit these bugs came
from, 384 lines).

**North star: Forge is not a cost oracle.** Every task here serves one principle — Forge records what a route *reported*
and says *unavailable* otherwise; it never invents a dollar figure from a local price table or presents an estimate as
truth. The concrete tell in today's code is `cost_micros: int` + hardcoded `estimated: True` (`cost_logger.py:52,72`):
there is no way to represent "cost unavailable" (`0` means both free and unknown). Making cost nullable and
provenance-tagged is the heart of this card, not a side detail.

## Current Focus

**Phase 0 (independent, ship first): corruption-class cost-log fix (Bug #4).** It is self-contained, blocks nothing, is
blocked by nothing, and matches an already-shipped pattern. Land it while the Phase 1 decision gate is being settled.

In parallel, resolve the **Phase 1 schema decision gate** (evolve usage ledger vs. new metric-event ledger) — it shapes
every later phase.

## Sequencing Note (verified against code)

The local pricing catalog (`calculate_cost()` / `get_pricing()`) is called from **three** proxy callsites, two of which
are cap **enforcement**:

| Callsite                                         | Path                             | Role                                        | Removed/replaced by                   |
| ------------------------------------------------ | -------------------------------- | ------------------------------------------- | ------------------------------------- |
| `proxy/server.py:674`                            | passthrough strict preflight     | cap enforcement (estimates pending request) | **Phase 3** (removed with `cap_mode`) |
| `proxy/server.py:884`                            | translated strict preflight      | cap enforcement (estimates pending request) | **Phase 3** (removed with `cap_mode`) |
| `proxy/server.py:174-216` (`_calc_and_log_cost`) | post-flight logging (both paths) | writes `cost_micros` to the cost log        | **Phase 2** (reported cost wins)      |

Post-mode caps and `CostTracker.bootstrap_from_logs()` read already-logged `cost_micros` and do **not** call the pricing
module. Therefore:

> **Slice 3 (remove `cap_mode` entirely) lands before or with Slice 2 (de-catalog the cost path).** Removing the
> `strict` branches deletes **both** cap-enforcement catalog calls (674 + 884), so Slice 2 only has to replace the
> single logging call (`_calc_and_log_cost`) with reported cost — and the catalog can then be isolated/removed without
> breaking caps. Slice order: 0 → 1 → 3 → 2 → 4 → 5 → 6.

> **Both strict callsites must die together.** Removing only `674-695` (the passthrough path) would leave the translated
> path at `884` still pricing pending requests from the catalog — strict mode and the catalog dependency survive Phase 3
> if either is missed.

---

## Decision Gates (resolve before the dependent phase)

| Gate   | Question                                                                                                     | Phase blocked            | Recommendation (challenge-checked)                                                                                                                                                                                                                                                                                                                               |
| ------ | ------------------------------------------------------------------------------------------------------------ | ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **G1** | Evolve the existing usage ledger, or introduce a broader metric-event ledger?                                | Phase 1 (all downstream) | **Evolve.** `core/usage/ledger.py` already carries `measurement_source`, `billing_mode`, `attribution_granularity`, versioned strict reads, and a nullable cost field. The card's metric-event model is ~90% the existing schema; a parallel ledger would duplicate the read/prune/shard machinery. Add `route`/`reporter`/`confidence` fields rather than fork. |
| **G2** | Rename `forge usage`, or keep the name with a clear subtitle/scope label? (Bug #7)                           | Phase 6                  | **Subtitle, not rename.** It is a shipped public CLI surface; a rename is a research-preview clean break with tombstone cost. A subtitle ("Forge automation activity — not total interactive usage") plus consistent doc labeling fixes the misread at lower cost. Revisit rename only if subtitle proves insufficient.                                          |
| **G3** | Where does launch metadata live: session manifest, status-line sidecar file, or both?                        | Phase 4                  | **Manifest `confirmed.launch_*` + read by status line via `FORGE_SESSION`.** Reuses the existing hook-owned `confirmed` writer and `FORGE_SESSION` discovery the status line already uses. A sidecar file adds a second writer/cleanup surface. Ambient sessions (no manifest) fall back to stdin-only.                                                          |
| **G4** | `auth_ignore_env` redefined narrowly, or new key for interactive/headless credential separation? (Bug #2/#6) | Phase 4                  | **New opt-in key** (e.g. `keep_api_key_out_of_interactive`). `auth_ignore_env` has shipped semantics (credential resolution source); overloading it for a different axis (interactive vs headless hydration) would conflate two concerns. Keep hydration as the labeled default; add an opt-in separation path.                                                  |
| **G5** | Should dollar caps ignore cost-unavailable events, or support a token-only fallback policy?                  | Phase 3                  | **Ignore for dollar caps in this card; keep schema compatible with token caps.** The card's scope is "no reported cost → record nothing." Token-only caps are a listed future aggregate row, not this card's commitment.                                                                                                                                         |

> These are the user's calls. G1 and G2 most affect structure; the rest are local to their phase.

---

## Phase 0 — Corruption-class cost-log fix (Bug #4)

**Goal**: A valid-but-non-object JSONL line (`[]` / `1` / `"x"`) must not crash cost-log reads (`read_cost_logs`,
`read_verb_logs` genuinely crash today; the `cost_tracker` bootstrap is already broad-except-guarded — see per-reader
notes below). One guard pattern, applied consistently across the cost plane.

Mirror the canonical guard at `core/usage/ledger.py:215-218` (`if not isinstance(record, dict): continue`, with the
explanatory comment). Place the guard immediately after the `json.loads` / `JSONDecodeError` block, before any `.get()`.

- [ ] `proxy/cost_logger.py` `read_cost_logs()` — add `isinstance(record, dict)` guard after `json.loads` (line ~123),
  before the `schema_version` `.get` (line 127), the period `.get` (137), and the sort `.get` (152).
- [ ] `proxy/cost_tracker.py` `_parse_record()` — guard returning `None` after `json.loads` (line 136) before `.get`
  (137). **Correctness/honesty fix, not a crash fix**: `bootstrap_from_logs()` already wraps `_parse_record` in
  `except Exception: continue` (`cost_tracker.py:103-106`), so a non-dict line is silently swallowed there today. The
  guard makes `_parse_record` honest (explicit `None`, not reliant on a broad-except backstop). Its test must exercise
  `_parse_record` **directly** — a bootstrap-level test passes before the fix and proves nothing.
- [ ] `core/reactive/cost_tracking.py` `read_verb_logs()` — guard after `json.loads` (line ~284) before `.get` (289,
  303). **Genuine crasher** (no broad-except around the loop) and **not named in the card** — found during scoping;
  crashes `forge proxy costs` verb display on a non-object line.
- [ ] Verify no other `.get`-on-decoded-line readers in the cost plane (grep `json.loads` in `proxy/` + `core/reactive/`
  cost paths).

**Acceptance**

| Test                                      | Fixture                                  | Assertion                                                        | Test File                                                                                                                      |
| ----------------------------------------- | ---------------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `read_cost_logs` survives non-object line | JSONL with `[]` then a valid record      | returns the valid record; no `AttributeError`                    | `tests/regression/test_bug_cost_log_non_dict_line.py` (new, mirrors `test_bug_usage_ledger_non_dict_line.py`)                  |
| `_parse_record` guard exists              | `_parse_record("[]")` called directly    | returns `None` (proves the guard, not the broad-except backstop) | `tests/src/proxy/test_cost_tracker.py`                                                                                         |
| Verb-log read survives non-object line    | verb shard with `null` then valid record | returns valid record only; no `AttributeError`                   | `tests/regression/test_bug_cost_log_non_dict_line.py`                                                                          |
| Existing reads unchanged                  | normal shards                            | byte-for-byte same aggregation                                   | `tests/src/proxy/test_cost_logger.py`, `tests/src/proxy/test_cost_tracker.py`, `tests/src/core/reactive/test_cost_tracking.py` |

**Closeout**: regression test green; targeted unit suites green; `make pre-commit` clean. Changelog entry (bug-fix
size). No design-doc change (internal corruption fix).

---

## Phase 1 — Schema & vocabulary pass (Slice 1) — gated on G1

**Goal**: Name metric evidence plainly. Separate `route`, `reporter`, `measurement_source`, `payer`, `confidence`,
`scope`, `policy_action` (card terminology table) without yet changing accounting behavior.

- [ ] **Resolve G1** (evolve vs new ledger) and record the resolution inline here with rationale.
- [ ] (If evolve) Extend `UsageEvent` / cost record schema with the missing metric-evidence fields **additively, with
  defaults**. `UsageEvent` is explicitly designed for this — its docstring (`ledger.py:90-98`) says "everything else is
  defaulted so a record stays loadable as the schema grows," and `read_usage_events` is `dacite(strict=True)` (unknown
  fields rejected, missing fields filled by default). So purely additive defaulted fields keep v1 records loadable
  **without** a `schema_version` bump.
- [ ] **Challenge the card's "bump the version" instruction.** Bump `schema_version` (1→2) only if a field's *meaning*
  changes, a field becomes *required*, or a value is *removed/renamed* — not for additive defaulted fields. Decide and
  record which case applies. (Strict reads already skip records with `schema_version > current`, so a bump means "old
  Forge can't read new records," never the reverse.)
- [ ] **v1-compat decision (explicit, per the durable-state rules).** Choose and TEST one: (a) existing v1
  `usage/events/*.jsonl` and `costs/requests/*.jsonl` still load under the new schema (the additive path), or (b) they
  are rejected with a clear reset/migration message. Do not leave this implicit — strict readers will surface it either
  way.
- [ ] Map existing values onto the new vocabulary (e.g. `pricing_source="catalog"` → `confidence="inferred"`; provider
  in-band tokens → `measurement_source="provider_usage_exact"`, already present).
- [ ] Define the `confidence` literal (`reported | gateway_calculated | inferred | unknown`) and `reporter` enum; keep
  `measurement_source` and `billing_mode` aligned with the card's terminology table.
- [ ] Preserve the "provenance is recorded, never inferred" discipline already in `ledger.py`.
- [ ] **Design-doc sync**: update `design.md` §3.14 + `design_appendix.md` §A.13 (schema) **only for shipped fields**.
  Begin folding `docs/auth_cost_metric.md` into the internal map (do not delete until superseded).

**Acceptance**

| Test                        | Fixture                                                               | Assertion                                                                                                   | Test File                             |
| --------------------------- | --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| v1 usage event still loads  | a `schema_version=1` `UsageEvent` JSONL line (pre-change fields only) | loads; new fields take defaults (path a) OR rejected with reset message (path b) — match the G1/v1 decision | `tests/src/core/usage/test_ledger.py` |
| v1 cost record still loads  | a `schema_version=1` cost-log line                                    | same chosen behavior as above                                                                               | `tests/src/proxy/test_cost_logger.py` |
| New fields round-trip       | event written with `reporter`/`confidence`/`route` set                | read back identical; strict read accepts                                                                    | `tests/src/core/usage/test_ledger.py` |
| Newer-schema record skipped | `schema_version = current+1`                                          | skipped with one-time warning (existing contract preserved)                                                 | `tests/src/core/usage/test_ledger.py` |

**Deferred decision**: aggregate rows beyond cost (tokens/rate-limits/failures/latency/tool-errors — card §"Post-Flight
Policies" table) are kept **schema-compatible** but NOT implemented in this card.

---

## Phase 3 — Post-flight aggregate policies (Slice 3) — do before Phase 2; gated on G5

**Goal**: There is **one** cap behavior — post-event enforcement from reported route cost. A request may cross a cap;
Forge records reported cost, then warns/blocks the **next** request. `cap_mode` is removed as a product/config concept
entirely (not reduced to a one-valued enum — keeping `post` as a "mode" would still imply a mode axis exists).

- [ ] **Remove `cap_mode` from the schema entirely** (`config/schema.py`): drop the `CostConfig.cap_mode` field (line
  212), its `valid_modes` validation (219-220), and the `.get("cap_mode", ...)` load (238).
- [ ] **Reject any stale `cap_mode` key** as a *recognized removed key* (not a generic unknown-key warning), so the
  message names the replacement behavior. Reuse the `_reject_unknown_keys` "removed/unknown proxy-config key =
  corruption → raise" posture already used for `intercept`/`audit` (`schema.py:261-270`); add a `cap_mode`-specific
  message at `CostConfig` parse: >
  `costs.cap_mode is no longer supported. Forge caps are enforced after completed requests using reported route` >
  `cost. Remove costs.cap_mode from proxy.yaml.`
- [ ] Delete the strict-mode preflight estimate at **both** callsites — they die with the `if cap_mode == "strict"`
  branches (see Sequencing Note):
  - [ ] `proxy/server.py:674` — passthrough path (`calculate_cost as _est_cost` on `_textish_chars` estimates).
  - [ ] `proxy/server.py:884` — translated path (`calculate_cost as _est_cost` on `_estimate_input_tokens`).
  - [ ] After both are gone, `check_cap()` is only ever called with `projected_cost_micros=0` — simplify the signature,
    and confirm no `from forge.core.models.pricing import` remains in the cap path.
- [ ] Document the single behavior — but **evidence-neutral if Phase 3 ships before Phase 2**. Until Phase 2 lands,
  `_calc_and_log_cost` still records catalog-estimated cost, so design docs must say "post-event enforcement over
  **recorded cost evidence**" (true for both the catalog-estimate intermediate and the post-Phase-2 reported value).
  Reserve the card's verbatim "reported route cost" wording for Phase 2's doc sync — using it now would make the design
  doc aspirational (documentation-guidelines: describe shipped behavior, not desired). **Changelog**: breaking change +
  reset path (remove the key).
- [ ] **Phase-coupling decision** (record it): (a) land Phase 3 + Phase 2 together so "reported route cost" is always
  accurate, or (b) ship Phase 3 alone with evidence-neutral wording and upgrade to "reported" in Phase 2. **Recommend
  (b)** — strict-removal is self-contained and valuable on its own; coupling forfeits that.
- [ ] **Design-doc sync**: `design.md` §3.7 + §3.14 (one post-event behavior; no preflight/strict mention; evidence
  wording per the decision above) + `design_appendix.md` §A.9 (cap config table: remove the `cap_mode` row entirely).

**Acceptance**

| Test                                      | Fixture                                                                  | Assertion                                                                      | Test File                                                    |
| ----------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------ | ------------------------------------------------------------ |
| No catalog call in cap path (passthrough) | passthrough proxy, caps set, request over cap                            | `calculate_cost` not invoked; reject is post-flight only                       | `tests/src/proxy/test_passthrough.py` / `test_server*`       |
| No catalog call in cap path (translated)  | translated proxy, caps set, request over cap                             | `calculate_cost` not invoked; reject is post-flight only                       | `tests/src/proxy/test_server*`                               |
| Post-flight cap rejects next request      | spend already over `per_day`; `on_cap_hit=reject`                        | next request → 429 `spend_cap_exceeded`; the over-cap request itself completed | `tests/src/proxy/test_cost_tracker.py` (+ proxy server test) |
| Any `cap_mode` key rejected               | proxy.yaml with `cap_mode: strict` **and** (separately) `cap_mode: post` | both fail at load with the stale-key message naming the post-event behavior    | `tests/src/config/test_*` (+ regression for the removed key) |
| Bootstrap unaffected                      | existing cost shards                                                     | totals initialize identically                                                  | `tests/src/proxy/test_cost_tracker.py`                       |

---

## Phase 2 — Cost source replacement (Slice 2) — gated on Phase 3 + G1

**Goal**: Reported cost wins. Local pricing is no longer the normal user-facing accounting source. No reported cost →
record/display *cost unavailable* (but **preserve route-reported tokens**). This is the "not a cost oracle" payload.

**Schema change (prerequisite — the conflation lives here):**

- [ ] Make cost **nullable**: `cost_logger.log_request_cost(cost_micros: int)` → `int | None` (line 52), and the
  record's hardcoded `"estimated": True` (line 72) → a provenance field aligned with Phase 1
  (`reported | gateway_calculated |     inferred | unavailable`). Today `0` means both "free" and "unknown" — that
  conflation is the cost-oracle bug.
- [ ] Make the proxy producer honest: `_calc_and_log_cost` (`server.py:174-216`) returns `int` always (0 on failure).
  Change so it returns / logs `None` when no reported cost is available instead of a catalog estimate or `0`.
- [ ] **Unavailable cost must not advance cap aggregates** (latent crash, not just display). `_calc_and_log_cost` calls
  `cost_tracker.record(cost_micros)` (`server.py:210-211`); `CostTracker.record(cost_micros: int)` guards `<= 0` but a
  `None` raises `TypeError` (`None <= 0`, `cost_tracker.py:153`). When cost is unavailable, **skip `record()` entirely**
  — do not advance `_monthly_total`/`_daily_window`. Doc note: caps account only for cost-reported requests;
  cost-unavailable traffic is uncapped-by-cost (a future token/rate-limit aggregate row, not this card).
- [ ] **Displays and metrics must not treat unavailable as `$0`:**
  - [ ] `proxy/metrics.py` `record_request` — skip `None` in `total_cost_micros` accumulation (don't add 0-as-known).
  - [ ] `cli/proxy_costs.py` `_display_by_model` / `_display_by_verb` — render "cost unavailable", not `$0.00`.
  - [ ] `cli/usage.py` + `core/ops/usage_summary.py` — `cost_partial`/unavailable surfaced, never summed as 0.
  - [ ] `cli/status_line.py` cost segment — unavailable renders as such, not `~$0`.

**Reported-cost wiring (the proxy path matrix — a `cost_logger` unit test will NOT prove these):**

- [ ] Persist reported cost when the reporter returns it (`pricing_source="openrouter|litellm|reported"`). Cover **every
  proxy path** where cost is logged — each extracts reported cost differently (or reports none):
  - [ ] translated **non-streaming** (converted response body usage/cost)
  - [ ] translated **streaming** (usage in the final SSE event)
  - [ ] passthrough **non-streaming** (raw provider body)
  - [ ] passthrough **streaming** (raw provider SSE)
  - [ ] retry / tool-compat re-request paths (cost not double-counted, or counted once on the final attempt)
  - [ ] failure logging (`failed=True`) — record tokens/None cost, never a phantom estimate
- [ ] Identify reported-cost surfaces: OpenRouter response cost, LiteLLM `response.cost` / proxy spend metadata. Wire
  what is synchronously available from responses; defer follow-up-lookup APIs (open question in card).
- [ ] Preserve route-reported tokens even when cost is unavailable (`measurement_source` token-only path already
  exists).
- [ ] **Display language** (card "Preferred display language"): `$0.23 OpenRouter reported`, `$0.23 LiteLLM reported`,
  `cost unavailable` — never bare "cost"/"exact"/"authoritative" for estimates.
- [ ] Decide: keep `pricing.py` as an **isolated, explicitly-labeled estimate** behind a flag, or remove. Sweep for any
  hidden non-display catalog dependency before deletion (cap path is catalog-free after Phase 3; display CLIs read
  logged `cost_micro(s)` — both ✔ verified during scoping).
- [ ] **Design-doc sync**: `design.md` §3.14 + `design_appendix.md` §A.9 (reported-cost as source; catalog isolated;
  `estimated` flag superseded by provenance).

**Acceptance**

| Test                                   | Fixture                                      | Assertion                                                                                                 | Test File                                                              |
| -------------------------------------- | -------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Reported cost persisted with source    | gateway response carrying reported cost      | log record `pricing_source="openrouter"`, provenance `reported` (not `catalog`/`estimated`)               | `tests/src/proxy/test_cost_logger.py`                                  |
| Unavailable cost is `None`, not `0`    | response with tokens, no reported cost       | record `cost_micros=None`; tokens present; provenance `unavailable`                                       | `tests/src/proxy/test_cost_logger.py`                                  |
| None cost skips cap aggregate          | request with unavailable cost                | `CostTracker.record()` not called with `None`; `_monthly_total`/`_daily_window` unchanged; no `TypeError` | `tests/src/proxy/test_cost_tracker.py`                                 |
| Translated path stops pricing locally  | translated proxy, real request               | logged cost is reported-or-`None`; `calculate_cost` not called for logging                                | `tests/src/proxy/test_server*`                                         |
| Passthrough path stops pricing locally | passthrough proxy, streaming + non-streaming | reported-or-`None` for each; no catalog call                                                              | `tests/src/proxy/test_passthrough.py`                                  |
| Streaming usage extracted              | streaming response with final-event usage    | cost/tokens captured from the final SSE event                                                             | `tests/src/proxy/test_passthrough.py` / `test_server*`                 |
| Display/metrics treat `None` ≠ `$0`    | log with mixed reported + `None` records     | model/verb display shows "unavailable"; metrics total excludes `None`                                     | `tests/src/cli/test_proxy_costs.py`, `tests/src/proxy/test_metrics.py` |
| Catalog isolation safe                 | catalog absent/flagged off                   | caps + display + logging still function                                                                   | `tests/src/proxy/test_cost_tracker.py`                                 |

> **Integration (required by CLAUDE.md for proxy-runtime changes):** the path matrix is the reason — unit tests don't
> exercise real translated/passthrough streaming. Run the proxy integration suite (e.g.
> `./scripts/test-integration.sh tests/integration/.../test_proxy_*`) and a real-wire check that reported cost lands.

---

## Phase 4 — Status-line honesty (Slice 4) — gated on G3, G4

**Scope guardrail (card §Scope)**: Forge never owns/recomputes the main harness cost. Status line shows TWO separated
things: (a) Claude's native signal as Claude's; (b) Forge's additional `claude -p` cost as a distinct `forge +$Y`
segment. Never merge.

- [ ] **Bug #1 — billing inference.** `billing_mode` (`statusline/context.py:87-96`) currently returns `api` whenever
  `has_api_key` in `auto`. Make `auto` **prefer `rate_limits` presence** (subscription/quota evidence) over key
  presence. Key availability is a capability signal, not a payer signal. (`has_api_key` already reads raw env at
  `context.py:84` — keep that; the bug is the `auto`→`api` inference, not the read source.)
- [ ] **Bug #2 — hydration coupling.** `build_claude_env()` (`core/reactive/env.py:190`) hydrates a resolvable
  `ANTHROPIC_API_KEY` into **interactive and headless** envs unconditionally. Per **G4**, add an opt-in path that keeps
  the key out of interactive sessions while preserving headless auth (or keep as labeled default — record G4
  resolution).
- [ ] **Bug #3 — ambient sessions.** When `forge status-line` runs inside a plain `claude` (no `FORGE_SESSION` /
  manifest), render an **ambient Claude** session using only stdin + immediate env. Do **not** consult Forge
  credential-file resolution to classify billing.
- [ ] **Launch metadata (G3).** Add the card's launch fields (`launch_route`, `proxy_id`/`base_url`,
  `api_key_available_to_child`, `api_key_source`, `user_declared_billing_mode`, `runtime_reported_quota_seen`) to
  `confirmed.launch_*`; status line reads them via `FORGE_SESSION`.
- [ ] `forge +$Y` distinct segment: render Forge additional `claude -p` cost separately; only when the route reporter
  returned cost. Keep `statusline.cost_mode=api|subscription` as explicit user **declaration**, not inference.
- [ ] **Design-doc sync**: `design.md` §3.4/§3.7 + `design_appendix.md` §A.8 (status-line sources, billing-aware cost).

**Acceptance**

| Test                       | Fixture                                              | Assertion                                       | Test File                                                          |
| -------------------------- | ---------------------------------------------------- | ----------------------------------------------- | ------------------------------------------------------------------ |
| `auto` prefers rate_limits | stdin has `rate_limits`, env has key                 | renders subscription/quota, not `$` API cost    | `tests/src/cli/statusline/test_context.py` / `test_status_line.py` |
| Key presence ≠ API payer   | env has hydrated key, no rate_limits, no declaration | payer not asserted as API in `auto` (hedged)    | `tests/src/cli/.../test_status_line.py`                            |
| Ambient session path       | no `FORGE_SESSION`, plain `claude` stdin             | classified ambient; no credential-file lookup   | `tests/src/cli/.../test_status_line.py`                            |
| Forge +$Y separate         | session with a reported-cost `claude -p` verb        | `forge +$Y` distinct from Claude native segment | `tests/src/cli/.../test_status_line.py`                            |

> **Integration**: status-line + env hydration touch the launcher/hook path — run
> `./scripts/test-integration.sh tests/integration/cli/test_status_line_integration.py` (per CLAUDE.md, unit runs don't
> exercise the real launch/env path).

---

## Phase 5 — Headless runtime reporters (Slice 5)

**Goal**: Let runtimes report their own cost/usage; keep runtime-native values separate from gateway-reported values.

- [ ] Claude headless **(spike → decide → wire, not "consider")**: does `claude -p --output-format json|stream-json`
  expose per-run cost/usage Forge can record? Acceptance: present → recorded with provenance `reported`; absent →
  `unavailable` (never estimated). Record the outcome — wire it, or defer with the gap named. ("consider" is not a
  tickable assertion.)
- [ ] Codex headless: ingest `codex exec --json` `turn.completed.usage` token counts (cost unavailable unless a Codex/
  OpenAI surface reports it). Reuses the runtime-neutral `HeadlessInvoker` seam (Phase 4 of runtime-abstraction, already
  shipped).
- [ ] Keep runtime-native reported values distinct from proxy/gateway reported values in the ledger
  (`reporter`/`route`).
- [ ] **Design-doc sync**: `design_appendix.md` §A.13 (per-emitter coverage table: add runtime reporters).

**Deferred**: `claude -p` exact per-request cost correlation stays the runtime-abstraction "Phase 4g" item (null
`source_refs`); this card does not close it.

---

## Phase 6 — Docs & CLI cleanup (Slice 6) — folds remaining bugs

- [ ] **Bug #7 (G2)**: subtitle/label `forge usage` scope ("Forge automation activity, not total interactive usage") in
  CLI output + docs; consistent labeling. (Rename only if G2 flips.)
- [ ] **Bug #8**: purge unsafe "exact"/"authoritative" language for dollar values across CLI + docs. Exact is allowed
  for `request_id` joins and provider token counts, never for dollar estimates.
- [ ] **Bug #5**: credential docs — add `OPENROUTER_BASE_URL` (non-secret connection value) to end-user + design
  credential tables; clarify `anthropic-passthrough` template coverage.
- [ ] **Bug #6**: `auth_ignore_env` docs — state actual hydration behavior (applies to interactive launches too), or
  point at the G4 separation key once it ships.
- [ ] Update `docs/end-user/{authentication,config,proxy,session}.md` with new terms/scopes; add the card's user-facing
  "which surface answers which question?" table.
- [ ] Fold/supersede `docs/auth_cost_metric.md` as the internal map.

---

## Closeout (card-level)

- [ ] Each phase's acceptance assertions ticked with recorded verification.
- [ ] Acceptance-shape questions answerable by a user without Forge internals (card §Acceptance Shape): route? reporter?
  reported/calculated/estimated/unavailable? scope? next-threshold policy? Forge-launched vs ambient?
- [ ] `change_log.md` entries per shipped phase (newest-first; Goal/Key changes/Verification).
- [ ] Promote durable lessons to `impl_notes.md` after human review (candidates: the **two** strict-preflight catalog
  callsites — `server.py:674` passthrough + `:884` translated — must be removed together; cost-unavailable must be
  `None` not `0` (the `estimated:True` conflation was the cost-oracle bug); the isinstance-guard pattern for all JSONL
  cost readers, noting `bootstrap_from_logs` is already broad-except-guarded; billing_mode ≠ key presence).
- [ ] Integration tests run for status-line/env/proxy-runtime/hook changes (not just unit).
- [ ] Design docs + end-user docs reflect shipped behavior; `docs/auth_cost_metric.md` folded.
- [ ] Move card `doing/ → done/` after final merge to `main`.

## Out of Scope (this card)

- MITM-by-default / always-on proxy on the wire for harness traffic (runtime-abstraction Phase 2 territory).
- Non-cost aggregate policies (failures/latency/content-filters/tool-errors) — schema-compatible only.
- `claude -p` exact per-request cost correlation (runtime-abstraction "4g").
- Native Codex/Gemini invokers beyond reading their headless usage output (runtime-abstraction Phase 5).

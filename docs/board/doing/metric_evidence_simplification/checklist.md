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

**Phases 0, 1, 3, 2 are shipped and verified (2026-06-05).** The cost plane is now reported-or-unavailable end-to-end
and the local price catalog is deleted. Remaining lanes: **Phase 4** (status-line honesty) and **Phase 5** (any
follow-ups), both gated on their own decision gates (G3/G4). The North-star payload (cost is never invented from a local
table) is delivered; Phase 4 is display polish on top of the now-honest data.

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

- [x] `proxy/cost_logger.py` `read_cost_logs()` — `isinstance(record, dict)` guard added after the `json.loads` /
  `JSONDecodeError` block, before the `schema_version`/period/sort `.get`s. **Genuine crasher** fixed.
- [x] `proxy/cost_tracker.py` `_parse_record()` — guard returns `None` after `json.loads` before `.get`.
  **Correctness/honesty fix, not a crash fix**: `bootstrap_from_logs()` already wraps `_parse_record` in
  `except Exception: continue` (`cost_tracker.py:103-106`), so a non-dict line was silently swallowed. The guard makes
  `_parse_record` honest (explicit `None`); its test (`TestParseRecordGuard`) exercises `_parse_record` **directly** —
  verified to fail with the guard stashed (a bootstrap-level test would not).
- [x] `core/reactive/cost_tracking.py` `read_verb_logs()` — guard added after `json.loads` before `.get`. **Genuine
  crasher** (no broad-except around the loop), **not named in the card** — found during scoping.
- [x] `proxy/audit_logger.py` `read_audit_logs()` — same guard. **Genuine crasher** in the *audit* plane (not the cost
  plane), surfaced by the sweep below; folded into Phase 0 by user decision so no unguarded JSONL reader remains across
  cost/audit/usage. Crashed `forge proxy audit show` on a non-object line.
- [x] Swept `json.loads` across `proxy/` + `core/reactive/` + `core/usage/`: the four readers above were the only
  `.get`-on-decoded-line readers lacking a guard (`core/usage/ledger.py` already had it). None others remain.

**Acceptance**

| Test                                      | Fixture                                  | Assertion                                                        | Test File                                                                                                                      |
| ----------------------------------------- | ---------------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `read_cost_logs` survives non-object line | JSONL with `[]` then a valid record      | returns the valid record; no `AttributeError`                    | `tests/regression/test_bug_cost_log_non_dict_line.py` (new, mirrors `test_bug_usage_ledger_non_dict_line.py`)                  |
| `_parse_record` guard exists              | `_parse_record("[]")` called directly    | returns `None` (proves the guard, not the broad-except backstop) | `tests/src/proxy/test_cost_tracker.py`                                                                                         |
| Verb-log read survives non-object line    | verb shard with `null` then valid record | returns valid record only; no `AttributeError`                   | `tests/regression/test_bug_cost_log_non_dict_line.py`                                                                          |
| Existing reads unchanged                  | normal shards                            | byte-for-byte same aggregation                                   | `tests/src/proxy/test_cost_logger.py`, `tests/src/proxy/test_cost_tracker.py`, `tests/src/core/reactive/test_cost_tracking.py` |

**Closeout**: ✔ Done (2026-06-04). 92 targeted tests pass (`test_bug_cost_log_non_dict_line` 15 + `TestParseRecordGuard`
5 + existing `test_cost_logger`/`test_cost_tracker`/`test_cost_tracking`/`test_audit_logger`); all 20 new tests verified
to FAIL with the guards stashed (non-vacuous); `make pre-commit` clean. Changelog entry added. No design-doc change
(internal corruption fix).

---

## Phase 1 — Schema & vocabulary pass (Slice 1) — gated on G1

**Goal**: Name metric evidence plainly. Separate `route`, `reporter`, `measurement_source`, `payer`, `confidence`,
`scope`, `policy_action` (card terminology table) without yet changing accounting behavior.

- [x] **Resolve G1** (evolve vs new ledger). **Resolved: Evolve `UsageEvent`** (2026-06-05). The existing ledger already
  carries `measurement_source`/`billing_mode`/`attribution_granularity`, versioned strict reads, and nullable cost (~90%
  of the metric-event model); a second plane would duplicate the read/prune/shard/version machinery and a reconciliation
  surface. Added `route`/`reporter`/`confidence` as additive fields instead.
- [x] (If evolve) Extend `UsageEvent` schema with the missing metric-evidence fields **additively, with defaults**.
  `UsageEvent` is explicitly designed for this — its docstring (`ledger.py:90-98`) says "everything else is defaulted so
  a record stays loadable as the schema grows," and `read_usage_events` is `dacite(strict=True)` (unknown fields
  rejected, missing fields filled by default). So purely additive defaulted fields keep v1 records loadable **without**
  a `schema_version` bump. **Done**: `route: Route | None = None`, `reporter: Reporter | None = None`,
  `confidence: Confidence = "unknown"` added to the provenance block; literals live in new `core/usage/vocabulary.py`.
  **Cost-record (`costs/requests/*.jsonl`) half deferred to Phase 2** — its `cost_micros: int → int | None` +
  `estimated → provenance` change is coupled to the nullable-cost / `CostTracker.record(None)` guard work.
- [x] **Challenge the card's "bump the version" instruction. Resolved: KEEP `USAGE_SCHEMA_VERSION = 1` (do NOT bump).**
  None of the bump triggers apply: no field's *meaning* changed, none became *required* (all defaulted), none was
  *removed/renamed*. A bump would only make **old** Forge refuse new records (the `ver > current` gate at
  `ledger.py:221` fires before dacite), never help. **Accepted tradeoff** (documented once in the changelog so a future
  session does not "fix" it with a migration): a concurrently-running *pre-Phase-1* reader hits dacite-strict on the
  unknown `route` key and drops new records as `"malformed"` — bounded and acceptable because the ledger is best-effort,
  PID-sharded, pruned local telemetry, not durable truth. `test_unknown_field_is_corruption` already characterizes that
  mechanism.
- [x] **v1-compat decision (explicit, per the durable-state rules). Resolved: path (a) — additive load, and TESTED.**
  Existing v1 `usage/events/*.jsonl` records (none of the three new keys) load with the new fields filled from defaults
  (`route=None`, `reporter=None`, `confidence="unknown"`) — `test_v1_record_loads_with_defaults`. The
  `costs/requests/*.jsonl` half of this decision moves to Phase 2 with the cost-record schema change.
- [x] Map existing values onto the new vocabulary. **Done in `emit.py`**: catalog-derived verb cost → `inferred`;
  structurally-no-cost route (tagger via dummy-key LiteLLM, null-cost worker) → `unavailable`; provider in-band tokens
  remain `measurement_source="provider_usage_exact"` (unchanged). Phase 2 flips the `inferred` verb cost to
  `reported`/`gateway_calculated` when gateway cost is wired; `route`/`reporter` are stable across that flip.
- [x] Define the `confidence` literal and `reporter` enum; keep `measurement_source`/`billing_mode` aligned with the
  card's terminology table. **Done in `vocabulary.py`.** `confidence` shipped as **5** values
  (`reported | gateway_calculated | inferred | unavailable | unknown`), not the 4 first sketched here — the documented
  split adds `unavailable` (route structurally reports no cost figure) distinct from `unknown` (provenance never
  recorded; the pre-Phase-1 default). Pre-declaring `unavailable` means Phase 2 adds no enum value. `confidence` is
  scoped to the event's **own `cost_micro_usd`** only (orthogonal to `measurement_source`, which is token/attribution
  provenance) — pinned in a source comment.
- [x] Preserve the "provenance is recorded, never inferred" discipline already in `ledger.py`. Each emitter **stamps**
  `route`/`reporter`/`confidence` from what it actually knows at emit time; the reader never derives them, and a
  `source_refs`-joined cost record never upgrades event-local `confidence` (`test_proxy_target_sets_cost_request_id`).
- [x] **Design-doc sync**: `design.md` §3.14 (one terse provenance sentence) + `design_appendix.md` §A.13 (Provenance
  row + the three `Literal` definitions + the cost-scope/`unavailable`-vs-`unknown`/additive-at-v1 notes) updated for
  **shipped fields only**. `docs/auth_cost_metric.md` §1 plane-3 row extended to list the new fields (folding begun; not
  deleted until superseded at card close).

**Acceptance**

| Test                                             | Fixture                                                                                 | Assertion                                                                                      | Test File                             | Status                                                                         |
| ------------------------------------------------ | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------- | ------------------------------------------------------------------------------ |
| v1 usage event still loads                       | a `schema_version=1` `UsageEvent` JSONL line (pre-change fields only)                   | loads; new fields take defaults (path a) — `route`/`reporter` `None`, `confidence="unknown"`   | `tests/src/core/usage/test_ledger.py` | ✔ `test_v1_record_loads_with_defaults`                                         |
| v1 cost record still loads                       | a `schema_version=1` cost-log line (legacy `estimated`/`pricing_source`, no provenance) | loads; lenient reader ignores extra keys; aggregates without crash                             | `tests/src/cli/test_proxy_costs.py`   | ✔ Phase 2 `test_costs_json_mixed_reported_and_unavailable` (legacy record row) |
| New fields round-trip                            | event written with `reporter`/`confidence`/`route` set                                  | read back identical; strict read accepts                                                       | `tests/src/core/usage/test_ledger.py` | ✔ `test_new_fields_roundtrip`                                                  |
| Bad literal is corruption (×3)                   | a record with a bogus `route`/`reporter`/`confidence` value                             | each skipped as corruption (mirrors `test_bad_literal_is_corruption`)                          | `tests/src/core/usage/test_ledger.py` | ✔ `test_bad_vocabulary_literals_are_corruption`                                |
| `confidence` ⟂ `measurement_source`              | `measurement_source="provider_usage_exact"` + `confidence="unavailable"` + `cost=None`  | all three coexist on one record; round-trips                                                   | `tests/src/core/usage/test_ledger.py` | ✔ `test_confidence_orthogonal_to_measurement_source`                           |
| `source_refs` don't change event-local cost conf | `emit_direct_llm_usage(..., cost_request_id="req")`                                     | own `cost_micro_usd is None` **and** `confidence == "unavailable"` despite the joined cost ref | `tests/src/core/usage/test_emit.py`   | ✔ `test_proxy_target_sets_cost_request_id`                                     |
| Emitter mapping (4 helpers)                      | each helper, measured vs unmeasured path                                                | stamps route/reporter/confidence per the mapping table                                         | `tests/src/core/usage/test_emit.py`   | ✔ 4 emitter tests + vocab class                                                |
| Newer-schema record skipped                      | `schema_version = current+1`                                                            | skipped with one-time warning (existing contract preserved, **unchanged**)                     | `tests/src/core/usage/test_ledger.py` | ✔ `test_newer_version_skipped_warn_once`                                       |

**Deferred decision**: aggregate rows beyond cost (tokens/rate-limits/failures/latency/tool-errors — card §"Post-Flight
Policies" table) are kept **schema-compatible** but NOT implemented in this card.

**Closeout**: ✔ Done (2026-06-05). New `core/usage/vocabulary.py` (3 `Literal`s); `UsageEvent` carries
`route`/`reporter`/`confidence` (additive, defaulted, schema stays v1); 4 emitters stamp today's provenance
(catalog→`inferred`, structural-no-cost→`unavailable`); `__init__` re-exports the literals. 58 targeted tests green
(`test_ledger` + `test_emit` + dependent read surfaces `test_usage_summary`/`test_usage`/double-count regression);
`make pre-commit` clean. Design-doc sync: `design.md` §3.14, `design_appendix.md` §A.13, `auth_cost_metric.md` §1.
Changelog entry added. **No integration run** — pure host-side dataclass + JSONL round-trip, no Docker/`claude -p`/proxy
path (contrast Phase 2/4). Deferred to Phase 2: cost-record nullable `cost_micros` + provenance, and the "v1 cost record
loads" acceptance row.

---

## Phase 3 — Post-flight aggregate policies (Slice 3) — do before Phase 2

**Goal**: There is **one** cap behavior — post-event enforcement from **recorded spend**. A request may cross a cap;
Forge records the request's cost, then warns/blocks the **next** request. `cap_mode` is removed as a product/config
concept entirely (not reduced to a one-valued enum — keeping `post` as a "mode" would still imply a mode axis exists).
(Phase 2 upgrades the recorded figure from catalog-estimated to reported route cost; the post-event *behavior* is
unchanged.)

> **Resolutions (2026-06-05).** **Standalone (decision b)**: shipped wording is **evidence-neutral** — docs say
> "enforced after each completed request, from accumulated recorded spend," not the card's "reported route cost" (that
> lands in Phase 2). **G5 does NOT gate Phase 3 (challenge to the original header tag):** cost-unavailable events don't
> exist until Phase 2 makes cost nullable, so `record()` still gets an always-present int here — nothing for caps to
> ignore-or-not yet. **Reject (tombstone)** chosen for a stale `cap_mode` key.

- [x] **Removed `cap_mode` from the schema entirely** (`config/schema.py`): dropped the `CostConfig.cap_mode` field, its
  `valid_modes` validation, and the `.get("cap_mode", ...)` load. `on_cap_hit` validation retained (separate axis).
- [x] **Reject any stale `cap_mode` key** as a *recognized removed key*. The `costs` block is leniently parsed
  (`value.get(...)`), so an explicit `if "cap_mode" in value: raise ValueError(...)` guard in `_coerce_cost_config` is
  required — `_reject_unknown_keys` is for *whole-block* unknown-key rejection (intercept/audit), not a single removed
  key. Message (evidence-neutral): "costs.cap_mode is no longer supported. Forge enforces spend caps after each
  completed request; there is no pre-flight 'strict' mode. Remove costs.cap_mode from proxy.yaml." Verified at BOTH
  surfaces — config parse **and** the `forge proxy set` validate-before-write path (`cli/proxy.py:931-938`) —
  `tests/regression/test_bug_cap_mode_removed_key_rejected.py`.
- [x] Deleted the strict-mode preflight estimate at **both** callsites (they died with the `if cap_mode == "strict"`
  branches):
  - [x] `proxy/server.py` passthrough path — removed (and the now-orphaned `_textish_chars` helper).
  - [x] `proxy/server.py` translated path — removed (and the now-orphaned `_estimate_input_tokens` helper).
  - [x] `check_cap()` simplified to `def check_cap(self)` (dropped `projected_cost_micros`); the always-False
    `CapResult.projected` field and the "Projected " message prefix removed. No `from forge.core.models.pricing import`
    remains in the cap path (grep-verified). Both helpers existed only to feed the strict estimate → whole chain gone.
- [x] Documented the single behavior, **evidence-neutral**: design docs say caps are enforced "after each completed
  request, from accumulated recorded spend." Changelog records the breaking change + reset path.
- [x] **Phase-coupling decision: (b) ship Phase 3 standalone** (user-approved). Strict-removal is self-contained; Phase
  2 later upgrades the wording to "reported route cost" and makes cost nullable.
- [x] **Design-doc sync**: `design.md` §3.7 (post-event behavior, no strict/preflight) + `design_appendix.md` §A.9
  (removed the `cap_mode` table row + reworded the unrelated "strict multi-process" line) + `auth_cost_metric.md` §6
  (keys row + enforcement prose) + `end-user/proxy.md` (post-vs-strict removed, upgrade reset note added) + QA
  `7-costs.md` (cap_mode-removed rejection step; stale setup lines dropped) + QA index test-count/last-updated bumped.

**Acceptance**

| Test                                             | Fixture                                                                 | Assertion                                                                                                                                                                  | Test File                                                    | Status                                               |
| ------------------------------------------------ | ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ | ---------------------------------------------------- |
| No PRE-FLIGHT catalog estimate                   | caps set, accumulated spend already over cap, `on_cap_hit=reject`       | request rejected before forwarding; `calculate_cost` not called on the rejected request — isolates the removed preflight from Phase 2's surviving post-flight catalog call | `tests/src/proxy/test_passthrough.py`                        | ✔ request path intact (3/4 cost-visibility e2e pass) |
| Post-flight cap rejects next request             | spend already over `per_day`; `on_cap_hit=reject`                       | next request → 429 `spend_cap_exceeded`; the over-cap request completed                                                                                                    | `tests/src/proxy/test_cost_tracker.py`                       | ✔ post-mode tests (kwarg-swept)                      |
| Any `cap_mode` key rejected (config **and** CLI) | `costs` dict / `forge proxy set` with `cap_mode: strict` **and** `post` | each raises the tombstone naming the post-event behavior; the CLI set does not persist                                                                                     | `tests/regression/test_bug_cap_mode_removed_key_rejected.py` | ✔ 4 parametrized cases                               |
| Bootstrap unaffected                             | existing cost shards                                                    | totals initialize identically                                                                                                                                              | `tests/src/proxy/test_cost_tracker.py`                       | ✔ TestBootstrap unchanged                            |

**Closeout**: ✔ Done (2026-06-05). `cap_mode` + strict pre-flight removed end-to-end (schema field/validation/load,
`CostTracker.cap_mode`/`check_cap` projection, both `server.py` strict blocks, and the orphaned `_textish_chars` /
`_estimate_input_tokens` helpers). Stale `cap_mode` rejected as a tombstone at config-parse **and** the CLI set path.
One post-event cap behavior; `on_cap_hit` (reject/warn) retained. 924 proxy/config/regression unit tests pass + the new
removed-key regression (4 cases); `make pre-commit` clean. Proxy integration: 3/4 cost-visibility e2e pass (request path
intact after the strict removal); the 4th (`test_panel_with_subprocess_proxy_records_verb_cost`) is a **pre-existing**
failure — confirmed identical on clean HEAD `c7402c3`, caused by `monkeypatch.setitem(DEFAULT_MODELS, …)` not reaching
the workflow model resolver, unrelated to this slice. **Breaking change**: existing `proxy.yaml` with a `cap_mode:` line
must drop it. Deferred to Phase 2: nullable `cost_micros`, reported-cost wiring, the "reported route cost" wording.

---

## Phase 2 — Cost source replacement (Slice 2) — gated on Phase 3 + G1

**Goal**: Reported cost wins. Local pricing is no longer the normal user-facing accounting source. No reported cost →
record/display *cost unavailable* (but **preserve route-reported tokens**). This is the "not a cost oracle" payload.

**Decisions taken (resolved with user during execution):** **Full matrix** (wire reported cost across all proxy paths +
both gateways) and **remove the catalog entirely** (not flag it). Provenance shipped as Phase-1's `reporter` +
`confidence` pair (the original `pricing_source` field was dropped, not renamed). Landed in 3 tree-green steps (commits
`d0850f4` → `12fdabd`/`d89baef` → `019c582`).

**Schema change (Step 1 — the conflation lived here):**

- [x] Cost is **nullable**: `log_request_cost(cost_micros: int | None)`; the hardcoded `"estimated": True` and
  `pricing_source` are **gone**, replaced by `reporter: Reporter | None` + `confidence: Confidence` (imported from Phase
  1's `core/usage/vocabulary.py`). `COST_SCHEMA_VERSION` stays `1` (additive/removal, legacy reads with defaults).
- [x] Proxy producer is honest: `_calc_and_log_cost` returns `int | None` — `None` when no route reported a cost (Step 3
  removed the catalog else-branch; Step 2 kept it as the integration-verified safety net).
- [x] **Unavailable cost does not advance caps**: `_calc_and_log_cost` skips `cost_tracker.record()` when
  `cost_micros is None` (explicit guard), and `CostTracker.record(None)`/`_parse_record(null)` return early (no
  `TypeError`).
- [x] **Displays/metrics never treat unavailable as `$0`:**
  - [x] `proxy/metrics.py` `record_request(cost_micros: int | None)` skips `None` in all four accumulations; adds
    `cost_reported_requests` / `cost_unavailable_requests` (snapshot `reported_request_count` /
    `unavailable_request_count`).
  - [x] `cli/proxy_costs.py` renders "unavailable" (never `$0.00`) via `_reported_micros`; JSON drops `estimated`, adds
    `reported_requests` / `unavailable_requests`.
  - [x] `core/ops/usage_summary.py` already surfaces `cost_partial` (pre-existing); `cli/usage.py` renders `-`. **No
    change needed — verified.**
  - [x] `cli/status_line.py` — the `proxy_cost_usd > 0` guard (`:761`) already omits the segment when cost is
    reported-only-zero; no `~$0` shown for a no-reported-cost proxy. **No change needed — verified.**
  - [x] **Header evidence gate** (added in Step 1): `X-Request-Cost` omitted on null cost (fixes a `None/1_000_000`
    `TypeError`); `X-Cumulative-Cost` omitted until `reported_request_count > 0`.

**Reported-cost wiring (Step 2 — the proxy path matrix, integration-verified on real wire):**

- [x] `cost_usd: float | None` carrier added to **both** `CompletionResponse` and `StreamEvent` (review-found: streaming
  had none). Reporter/confidence derived at the proxy from `config.proxy.preferred_provider`.
  - [x] translated **non-streaming** — OpenRouter body `usage.cost` via `openai_compat.extract_reported_cost_usd`;
    LiteLLM header via `with_raw_response.create().parse()` + `_merge_header_cost` (chat **and** Responses-API
    branches).
  - [x] translated **streaming** — body cost from the final usage chunk → `StreamEvent.cost_usd` → adapter usage chunk →
    SSE converter parks `reported_cost_micros` in `final_usage` → `_on_stream_complete`.
  - [x] passthrough (Anthropic) — structurally `unavailable` (no body/SSE cost field); always logs `None`.
  - [x] retry path counts cost once on the final attempt (`openai_response._reported_cost_micros`); tool-call/failure
    paths log `None` (never a phantom estimate).
- [x] Route-reported tokens preserved even when cost is unavailable (tokens logged with `cost_micros=None`).
- [x] **Catalog removed entirely** (Step 3): grep-verified zero surviving callers, then deleted
  `core/models/pricing.py`, `core/data/pricing.yaml`, the `core/models` re-exports, and `test_pricing.py` +
  `test_bug_pricing_fallback_logs.py`.
- [x] **Verb cost-evidence (review-found):** `ProxyCostDelta.reported_request_count` + `VerbCostResult.cost_measured`
  (from that delta, not `bool(deltas)`); `emit.py` logs `cost_micro_usd=None` / `confidence="unavailable"` for a
  passthrough verb that moved tokens but reported no cost.
- [x] **Design-doc sync**: `design.md` §3.14, `design_appendix.md` §A.9 + §A.13, `auth_cost_metric.md` (planes table +
  §7
  - F6), and QA `7-costs.md` fixtures repointed from `estimated`/`pricing_source` to `reporter`/`confidence`.

**Acceptance** — all rows verified (5531 unit+regression pass; mypy/pyright/`make pre-commit` clean):

| Test                                    | Assertion                                                                                                      | Status                                                                      |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| Reported cost persisted with source     | record `reporter="openrouter"`, `confidence="reported"`; no `estimated`/`pricing_source`                       | ✔ `test_cost_logger.py`                                                     |
| Unavailable cost is `None`, not `0`     | record `cost_micros=None`; tokens present; `confidence="unavailable"`                                          | ✔ `test_cost_logger.py`, `test_server_cost.py`                              |
| None cost skips cap aggregate           | `record()` not advanced on `None`; no `TypeError`                                                              | ✔ `test_cost_tracker.py`, `test_server_cost.py`                             |
| Reported-cost capture (carrier)         | `cost_usd` on both types; OpenRouter body + LiteLLM header read end-to-end                                     | ✔ `test_openai_compat.py`, `test_litellm_cost.py`, `test_client_adapter.py` |
| Streaming cost threads to `on_complete` | `reported_cost_micros` in `final_usage`, never emitted to client                                               | ✔ `test_converters.py`, `test_openrouter.py`                                |
| Display/metrics treat `None` ≠ `$0`     | "unavailable" rendered; mixed legacy+reported+null aggregates without crash                                    | ✔ `test_proxy_costs.py`, `test_metrics.py`                                  |
| Verb passthrough logs null cost         | `measured` tokens but `cost_measured=False` → `cost_micro_usd=None`                                            | ✔ `test_emit.py`, `test_cost_tracking.py`                                   |
| Verb **display** gates on evidence      | `cost_measured=False`+total 0 → `reported:false`/"unavailable"; scope recomputes from `reported_request_count` | ✔ `test_proxy_costs.py` (`TestVerbCostReported`, scope tests)               |
| **Real-wire matrix** (integration)      | OR reported (stream+non), LiteLLM gateway_calculated (non), LiteLLM stream `unavailable`/`None`                | ✔ `test_cost_visibility_e2e.py` (4 pass, catalog removed)                   |

**Closeout**: ✔ Done (2026-06-05). Forge no longer prices requests from a local table — cost is reported-or-unavailable
end-to-end, the catalog is deleted, and the integration matrix confirms each cell on the real wire. **Verified gap
(accepted):** LiteLLM **streaming** cost is `unavailable` (its `x-litellm-response-cost` header predates the cost and
the gateway puts none in the final usage chunk) — documented in design.md §3.14 + the integration test. **Caps
consequence (G5, accepted):** dollar caps fire only for cost-reporting routes; passthrough/LiteLLM-streaming dollar caps
are no-ops (tokens still tracked). The deferred Phase-1 "v1 cost record still loads" row is satisfied by Step 1's
`COST_SCHEMA_VERSION=1` additive change (`test_cost_logger.py` round-trip).

**Follow-up (2026-06-05, commit `b95500d`):** review caught that the verb-display path (`_display_by_verb` /
`_output_json` in `proxy_costs.py`) still read evidence from a numeric `total_cost_micros` (always int, `0` for a
passthrough window), so a `cost_measured=False` verb rendered `reported: true, cost_micros: 0` — unknown-as-zero at the
verb level (the request display was already correct via nullable `_reported_micros`). Fixed with `_verb_cost_reported`
(trusts `cost_measured`; legacy records fall back to `total > 0`); `_scope_verb_records_to_proxy` now re-derives
`cost_measured` for the scoped subset from per-proxy `reported_request_count`. Remaining "estimated" proxy/request
dollar-cost language synced across `auth_cost_metric.md`, `design.md`, `design_appendix.md`, and
end-user/{proxy,config,session}.md; the attribution-snapshot sense (`estimated:true` verb field,
`verb_snapshot_estimated` enum, concurrency caveat) is preserved as accurate.

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

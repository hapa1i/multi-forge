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

**Phases 0, 1, 3, 2, 4 are shipped and verified (2026-06-05).** The cost plane is reported-or-unavailable end-to-end
(price catalog deleted) and the status line is now billing-honest: `auto` never infers an API payer from key presence,
launch metadata (`confirmed.launch`) is recorded + rendered via the opt-in `launch` segment, and
`interactive_anthropic_api_key: omit` keeps a key out of interactive sessions (host + sidecar) while headless auth is
untouched. **Phase 5** (headless runtime reporters) is next; it carries the deferred `forge +$Y` Forge-additional-cost
segment. **Phase 6** (docs/CLI cleanup) follows.

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

| Gate   | Question                                                                                                     | Phase blocked            | Recommendation (challenge-checked)                                                                                                                                                                                                                                                                                                                                                              |
| ------ | ------------------------------------------------------------------------------------------------------------ | ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **G1** | Evolve the existing usage ledger, or introduce a broader metric-event ledger?                                | Phase 1 (all downstream) | **Evolve.** `core/usage/ledger.py` already carries `measurement_source`, `billing_mode`, `attribution_granularity`, versioned strict reads, and a nullable cost field. The card's metric-event model is ~90% the existing schema; a parallel ledger would duplicate the read/prune/shard machinery. Add `route`/`reporter`/`confidence` fields rather than fork.                                |
| **G2** | Rename `forge usage`, or keep the name with a clear subtitle/scope label? (Bug #7)                           | Phase 6                  | **RESOLVED 2026-06-06: clean-break rename to `forge activity`** (user chose rename over the subtitle recommendation). The name `usage` itself read as "total interactive usage"; `activity` matches the internal `build_session_activity_summary`/`SessionActivitySummary` and fixes the misread at the name level. Shipped with a hidden flag-tolerant `usage` tombstone + honest scope label. |
| **G3** | Where does launch metadata live: session manifest, status-line sidecar file, or both?                        | Phase 4                  | **Manifest `confirmed.launch_*` + read by status line via `FORGE_SESSION`.** Reuses the existing hook-owned `confirmed` writer and `FORGE_SESSION` discovery the status line already uses. A sidecar file adds a second writer/cleanup surface. Ambient sessions (no manifest) fall back to stdin-only.                                                                                         |
| **G4** | `auth_ignore_env` redefined narrowly, or new key for interactive/headless credential separation? (Bug #2/#6) | Phase 4                  | **New opt-in key** (e.g. `keep_api_key_out_of_interactive`). `auth_ignore_env` has shipped semantics (credential resolution source); overloading it for a different axis (interactive vs headless hydration) would conflate two concerns. Keep hydration as the labeled default; add an opt-in separation path.                                                                                 |
| **G5** | Should dollar caps ignore cost-unavailable events, or support a token-only fallback policy?                  | Phase 3                  | **Ignore for dollar caps in this card; keep schema compatible with token caps.** The card's scope is "no reported cost → record nothing." Token-only caps are a listed future aggregate row, not this card's commitment.                                                                                                                                                                        |

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
intact after the strict removal); the 4th (`test_panel_with_subprocess_proxy_records_verb_cost`) was a **pre-existing**
test bug — confirmed identical on clean HEAD `c7402c3`, caused by `monkeypatch.setitem(DEFAULT_MODELS, …)` not reaching
the workflow model resolver, unrelated to this slice. **Resolved 2026-06-05** by patching the canary into
`AVAILABLE_MODELS` (the registry `resolve_model_specs` validates `--models` against); the panel test now passes on real
wire — cost-visibility matrix is 5/5. **Breaking change**: existing `proxy.yaml` with a `cap_mode:` line must drop it.
Deferred to Phase 2: nullable `cost_micros`, reported-cost wiring, the "reported route cost" wording.

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

| Test                                    | Assertion                                                                                                      | Status                                                                       |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Reported cost persisted with source     | record `reporter="openrouter"`, `confidence="reported"`; no `estimated`/`pricing_source`                       | ✔ `test_cost_logger.py`                                                      |
| Unavailable cost is `None`, not `0`     | record `cost_micros=None`; tokens present; `confidence="unavailable"`                                          | ✔ `test_cost_logger.py`, `test_server_cost.py`                               |
| None cost skips cap aggregate           | `record()` not advanced on `None`; no `TypeError`                                                              | ✔ `test_cost_tracker.py`, `test_server_cost.py`                              |
| Reported-cost capture (carrier)         | `cost_usd` on both types; OpenRouter body + LiteLLM header read end-to-end                                     | ✔ `test_openai_compat.py`, `test_litellm_cost.py`, `test_client_adapter.py`  |
| Streaming cost threads to `on_complete` | `reported_cost_micros` in `final_usage`, never emitted to client                                               | ✔ `test_converters.py`, `test_openrouter.py`                                 |
| Display/metrics treat `None` ≠ `$0`     | "unavailable" rendered; mixed legacy+reported+null aggregates without crash                                    | ✔ `test_proxy_costs.py`, `test_metrics.py`                                   |
| Verb passthrough logs null cost         | `measured` tokens but `cost_measured=False` → `cost_micro_usd=None`                                            | ✔ `test_emit.py`, `test_cost_tracking.py`                                    |
| Verb **display** gates on evidence      | `cost_measured=False`+total 0 → `reported:false`/"unavailable"; scope recomputes from `reported_request_count` | ✔ `test_proxy_costs.py` (`TestVerbCostReported`, scope tests)                |
| **Real-wire matrix** (integration)      | OR reported (stream+non), LiteLLM gateway_calculated (non), LiteLLM stream `unavailable`/`None`                | ✔ `test_cost_visibility_e2e.py` (5 pass incl. panel canary, catalog removed) |

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

## Phase 4 — Status-line honesty (Slice 4) — SHIPPED (2026-06-05)

**Scope guardrail (card §Scope)**: Forge never owns/recomputes the main harness cost. Status line shows TWO separated
things: (a) Claude's native signal as Claude's; (b) Forge's additional `claude -p` cost as a distinct `forge +$Y`
segment. Never merge.

> **Resolutions (2026-06-05) — G3 + G4 settled (design dialogue, code-verified).**
>
> **G3 — launch metadata in the manifest, nested `confirmed.launch` (`LaunchConfirmed`).** Mirrors the existing
> `confirmed` sub-object convention
> (`PolicyConfirmed`/`VerificationConfirmed`/`CompactionConfirmed`/`SubagentConfirmed`, `models.py`), not the card's
> scattered `launch_*` fields. Read by the status line via `FORGE_SESSION`; ambient sessions (no manifest) fall back to
> stdin + immediate env only.
>
> ```yaml
> confirmed:
>   launch:                              # LaunchConfirmed — immutable launch facts
>     routing_mode: direct | proxy | custom_base_url
>     proxy_id: openrouter-anthropic     # nullable
>     base_url: http://localhost:...     # nullable
>     api_key_available_to_child: true
>     api_key_source: env | credential_file | none | omitted_by_config | unknown
> ```
>
> - **Drop `runtime_mode`.** `confirmed.is_sandboxed` (`models.py:401`; read at `status_line.py:970`,
>   `session_fork.py:382/452`, `session_start.py:318`) stays the **sole** host/sidecar truth — a second field duplicates
>   it. Sidecar-ness doesn't affect who pays, so Phase 4 billing honesty doesn't need it.
> - **`routing_mode`, not `route`** — deliberately distinct from `UsageEvent.route` (invocation channel:
>   `claude_p`/`forge_proxy`/…). Avoids re-overloading the term this card exists to disambiguate.
> - **Do NOT persist `runtime_reported_quota_seen` / `user_declared_billing_mode`** (the card "Recommended launch
>   metadata" table listed them). Those are **render-time reporter evidence**, not immutable launch facts: read stdin
>   `rate_limits` and current `statusline.cost_mode` at render time (effective-not-confirmed discipline, §A.8). Freezing
>   them into `confirmed` is a category error.
>
> **G4 — new opt-in key, flat sibling to `auth_ignore_env` (NOT nested under `auth:`).**
>
> ```yaml
> # ~/.forge/config.yaml (RuntimeConfig — flat, beside auth_ignore_env at runtime_config.py:189)
> interactive_anthropic_api_key: inherit   # inherit (default) | omit
> ```
>
> - **Flat, not nested.** A nested `auth:` block would sit inconsistently beside the flat `auth_ignore_env` or force
>   migrating it (clean-break scope-creep — defer the namespace to its own card; same reasoning as dropping
>   `runtime_mode`).
> - **`omit` definition:** for Forge-managed **interactive** Claude launches, remove `ANTHROPIC_API_KEY` from the child
>   env **and** do not hydrate it from stored credentials — strips **both** the shell-inherited and credential-file key.
>   Forge **headless** subprocesses (supervisor, memory writer, panel workers, `claude -p --bare`) keep normal
>   credential resolution. `inherit` (default) = current behavior, no break.
> - **Wiring:** thread an explicit `interactive` flag into `build_claude_env` (`env.py:156`) → `_hydrate_credentials`
>   (`:239`); default preserves today's hydration. The key-removal machinery already exists (the `auth_ignore_env` pop
>   at `env.py:263`) — `omit` mirrors it, gated on `interactive AND interactive_anthropic_api_key == "omit"`. Keep it a
>   **separate** flag from `derive_run_identity` (interactive launchers already pass `derive_run_identity=False`, so the
>   callsites are known — but api-key omission ≠ run-identity rooting; do not overload one flag for both).
> - **Status-line bridge:** when `omit` fires, `api_key_source: omitted_by_config` is the manifest breadcrumb the status
>   line reads to render billing honestly (closes Bug #1).

> **Shipped notes (2026-06-05) — as-built vs the resolutions.**
>
> - **`forge +$Y` deferred to Phase 5.** Most direct `claude -p` cost is "unavailable" until the headless reporters land
>   (Phase 5), so the segment would be sparse and needs new hot-path throttle infra. Co-deliver it there.
> - **Visible `launch` segment added (opt-in, off by default).** The launch metadata is not just recorded — a new
>   Forge-unique segment renders `<route>·key:<posture>` (`format_launch`). Off by default preserves the golden guard.
> - **Sidecar omit (4.2b) added.** Sidecar launches bypass `build_claude_env`; `session_lifecycle` sets
>   `FORGE_OMIT_INTERACTIVE_KEY=1` and `docker/entrypoint.sh` unsets the key for Claude *after* the proxy captured its
>   upstream credential (works for anthropic-upstream templates).
> - **Single source-aware api-key helper.** `apply_interactive_api_key`/`compute_interactive_api_key_decision` (env.py)
>   over `resolve_env_or_credential_with_source` (template_secrets.py) — apply runs LAST (after extra_vars/unset), so
>   the recorded `source` always equals the child env (no env-first guess; honors `auth_ignore_env`).
> - **`has_api_key` removed.** After Bug #1, `billing_mode` no longer reads the key; the launch segment reads
>   `confirmed.launch.api_key_source` (manifest), so the property had no honest consumer left (dead code deleted).

- [x] **Bug #1 — billing inference.** `billing_mode` (`statusline/context.py`) `auto` now returns `ambiguous` (never
  `api` from key presence); `format_billing_cost` shows quota-if-`rate_limits`-else-`≈$`. Golden `$0.42`→`≈$0.42`; the
  divergence test became a key-invariance test. Stale `cost_mode` seed comment fixed (`runtime_config.py`).
- [x] **Bug #2 — hydration coupling (G4).** Flat `interactive_anthropic_api_key: inherit|omit` on `RuntimeConfig`;
  `interactive` flag on `build_claude_env` suppresses the early hydrate; the interactive wrapper (`invoke.py`) runs
  `apply_interactive_api_key` LAST. `omit` strips shell + credential-file key for interactive only; headless
  (`session_runner`, `review/engine`, `--bare`) untouched. Tests: `test_env.py::TestInteractiveApiKey`.
- [x] **Bug #3 — ambient sessions.** `billing_mode` no longer reads env/credentials at all (declaration + `rate_limits`
  only); the `launch` producer is manifest-gated. Test: `test_statusline_billing.py::TestAmbientHonesty`.
- [x] **Launch metadata (G3).** `LaunchConfirmed` under `confirmed.launch` (`models.py`, additive — dacite strict).
  Wrote via centralized `record_launch_confirmed` (best-effort) from start/resume + host fork closures
  (`session_fork.py`) + sidecar. Tests: `test_models.py::TestLaunchConfirmed`, `test_launch_confirmed.py`.
- [x] **Visible `launch` segment.** `format_launch` + `_produce_launch` (shape-defensive, opt-in). Tests:
  `test_statusline_forge_segments.py::{TestFormatHelpers,TestLaunchProducer}`.
- [~] `forge +$Y` distinct segment — **deferred to Phase 5** (see Shipped notes). `cost_mode=api|subscription` stays an
  explicit declaration (Bug #1).
- [x] **Design + end-user docs sync**: `design_appendix.md` §A.7 (new key) + §A.8 (billing-as-declaration, `launch`
  segment); `docs/end-user/config.md` + `authentication.md` (new key, corrected `cost_mode=auto`, the `omit` control).

**Acceptance**

| Test                       | Fixture                                            | Assertion                                           | Test File                                                      |
| -------------------------- | -------------------------------------------------- | --------------------------------------------------- | -------------------------------------------------------------- |
| Key presence ≠ API payer   | `auto`, env has key, no rate_limits                | hedges `≈$`, not `$` (golden + billing)             | `tests/src/cli/test_statusline_registry.py` + `_billing.py`    |
| `auto` shows quota         | `auto`, `rate_limits` present                      | renders `RL:%`, hides phantom dollars               | `tests/src/cli/test_statusline_billing.py`                     |
| Ambient session            | no `FORGE_SESSION`, key in env, no rate_limits     | hedges `≈$`, no launch segment, no cred lookup      | `tests/src/cli/test_statusline_billing.py::TestAmbientHonesty` |
| omit strips interactive    | `interactive=True`, omit, key in env               | key popped; source `omitted_by_config`              | `tests/src/core/reactive/test_env.py::TestInteractiveApiKey`   |
| omit recorded (real start) | `forge session start`, omit, shell key             | `confirmed.launch.api_key_source=omitted_by_config` | `tests/integration/cli/test_status_line_integration.py`        |
| sidecar omit (real)        | sidecar entrypoint, `FORGE_OMIT_INTERACTIVE_KEY=1` | Claude PID has no key; proxy kept it                | `tests/integration/sidecar/test_sidecar_omit.py`               |

> **Verification (done):** focused unit suites + full blast-radius sweep (2991 passed); `make pre-commit` clean;
> integration `tests/integration/cli/test_status_line_integration.py` (13, incl. launch metadata) +
> `tests/integration/sidecar/test_sidecar_omit.py` (1) green.

---

## Phase 5 — Headless runtime reporters (Slice 5) — SHIPPED (2026-06-05)

**Goal**: Let the Claude runtime report its own cost/usage on the headless `claude -p` path; keep runtime-native values
distinct from proxy/gateway values; surface Forge's additional headless spend in the status line.

**Scope (locked with the user)**: **Claude-only** (Codex deferred — no `CodexHeadlessInvoker` exists; it stays the
paused `runtime_abstraction` card's work). **Broad wiring** (request JSON for all `claude -p` runs). **`forge +$Y`
included** (deferred here from Phase 4).

- [x] **5a spike (hard gate)** — `scripts/experiments/headless-cost-report/` (`reproduce.sh` + `README.md`). DECISION =
  **GO (broad), direct path**. Load-bearing finding: 2.1.165 emits a JSON **array** `[system, assistant, result]`, cost/
  usage in the last `result` element (NOT the documented single object). Direct API key → COST-REPORTED + USAGE-REPORTED
  for every flag combo. Verdicts encoded as named constants (`_JSON_INCOMPATIBLE=frozenset()`,
  `_JSON_IS_ERROR_RELIABLE=True`); capability guard = **retry-once-and-latch, no version probe**.
- [x] **5b envelope unwrap + capability guard** — shared `core/reactive/headless_json.py` (capability latch,
  `prepare_json_argv`, `usd_to_micros`); `parse_headless_envelope` (never raises; array + bare-object + stream-json +
  raw-text fallback) in `structured_output.py`; `SessionResult`/`HeadlessResult` gain nullable cost/usage +
  `envelope_parsed` + `runtime_is_error`. BOTH runners (`run_claude_session` + `ClaudeHeadlessInvoker`) inject the flag
  via the shared helper and retry-once on rejection — `.result` unwrapped into `.stdout` so text consumers are
  unchanged.
- [x] **5c cost-provenance precedence** (`emit.py`) — exactly **one** reporter per run: proxied → `forge_proxy`/
  `verb_snapshot_estimated` (snapshot tokens; Anthropic-priced self-cost ignored); direct → `claude_code`/
  `runtime_native` (self-cost) or `provider_usage_exact`/`unavailable` (tokens-only). Tokens follow the cost source (no
  mixed provenance). Same precedence in `emit_worker_usage`. First emission of `claude_code` + `runtime_native`.
- [x] **5d `forge +$Y` segment** — opt-in `forge_cost` (allowlist only, not `DEFAULT_ORDER`); `sum_forge_added_cost`
  (reported cost, **excludes `route=claude_interactive`**); time-only `read_or_compute_session_cost` throttle (keyed on
  Forge identity not the Claude UUID, caches a legit 0, fail-open uncached); `forge_cost_ttl` config (default 10).
- [x] Runtime-native reported values kept distinct from proxy/gateway in the ledger (`reporter`/`route`/
  `measurement_source`).
- [x] **5e tests** — 11 new/extended unit+regression files (envelope parse, unwrap-preserves-text, token-only,
  json-flag-compat **both runners**, is_error→status, `usd_to_micros` parity, verb+worker precedence,
  `sum_forge_added_cost`, statusline producer/format, session-cost throttle). 2 new Docker tests (5a contract twin +
  `run_claude_session` seam) + updated memory/workers assertions (direct verb/worker now `runtime_native`).
  **Verification**: 5285 unit pass; **6 real-Claude integration tests pass on 2.1.165** (98s) — 5a verdict + self-report
  pipeline confirmed end-to-end; `make pre-commit` clean.
- [x] **5f design-doc sync**: `design.md` §3.14 (headless self-report + `forge +$Y`), `design_appendix.md` §A.13
  (`reporter=claude_code` + `measurement_source=runtime_native` emitted; precedence + per-worker paragraphs rewritten;
  corrected a stale `inferred`→`reported`) + §A.8 (`forge_cost` default-off, `forge_cost_ttl`, "Forge session cost"),
  `vocabulary.py`/`ledger.py` comments (claude_code/runtime_native emitted).

**Deferred (unchanged)**: Codex headless (`codex exec --json`) → `runtime_abstraction` card. `claude -p` exact
per-request cost correlation stays "Phase 4g" (null `source_refs`).

**Follow-up (new, non-blocking)**: `usd_to_micros` (truncate-Decimal) and the proxy cost plane's `round(usd*1e6)`
(`client_adapter.py:229,410`) diverge by ≤1 micro only at exact half-micro fractions real costs never emit, and run on
separate planes (a run is proxied XOR direct, never both). Pinned by `test_headless_json.py` so aligning them later is a
deliberate, test-visible choice — not silently diverging.

---

## Phase 6 — Docs & CLI cleanup (Slice 6) — folds remaining bugs — SHIPPED (2026-06-06, on branch)

- [x] **Bug #7 (G2 — flipped to clean-break rename, 2026-06-06)**: `forge usage` → `forge activity` (`cli/usage.py` →
  `cli/activity.py`, `activity_cmd`), registered in `main.py`. Hidden, **flag-tolerant** `usage` tombstone
  (`ignore_unknown_options` + `UNPROCESSED`, mirrors `memory_writer.py`) so
  `forge usage my-session --all --json --days 7` reaches the rename message, not Click's "No such option". Honest scope
  in help/output ("Forge automation activity — not your full interactive session") and the blanket "Estimated spend
  only" label corrected to "reported-or-estimated, best-effort". `test_usage.py` → `test_activity.py` retargeted + 2
  tombstone tests. Verified: `forge activity --help`, both `forge usage` forms tombstone; 9 unit tests + the renamed
  integration test **ran green**
  (`./scripts/test-integration.sh tests/integration/cli/test_session_commands_integration.py -k Activity` → 1 passed,
  5.8s, real wheel CLI in Docker).
- [x] **Bug #8**: **verified clean, not swept.** A scoped grep of `src/forge` + docs found every "exact"/"authoritative"
  hit applied to tokens (`provider_usage_exact`, "exact tokens"), `request_id` joins (`proxy_request_exact`), enum
  names, or `forge proxy costs` authority — zero unsafe dollar prose survives Phases 2–5. The only substantive change
  was the `forge activity` honest-label fix (folded into Bug #7).
- [x] **Bug #5**: `OPENROUTER_BASE_URL` (non-secret connection value) added to both credential tables
  (`end-user/authentication.md`, `design_appendix.md §A.6`); `anthropic-passthrough` added to
  `anthropic-api.unlocks_features` (`capabilities.py`, + `test_capabilities.py` assertion) and a "which auth?" row.
- [x] **Bug #6**: `auth_ignore_env` reworded in `authentication.md` + `design_appendix.md §A.6` — it changes the key
  **source** (file vs env) for both interactive and headless; the interactive/headless separation is
  `interactive_anthropic_api_key` (the G4 key, shipped Phase 4). Cross-referenced.
- [x] Updated `end-user/{authentication,config,proxy,session,policy}.md`; added the user-facing "which surface answers
  which question?" table to `proxy.md` (adapted from the internal `auth_cost_metric.md` table) with cross-links from
  `session.md` + `config.md`.
- [x] Folded `auth_cost_metric.md` into an **internal audit map** — banner + links to `design.md §3.14` /
  `design_appendix.md §A.8/§A.9/§A.13`; preserved the durable reference (three planes, resolution chain, file index);
  **rewrote** the Phase-4-falsified findings (F1/F2 → RESOLVED, §14 `has_api_key` deleted, billing-mode-as-declaration)
  rather than keeping them verbatim; deleted the superseded operator playbook + proposals (P1/P2 shipped in Phase 4).

---

## Closeout (card-level)

- [x] Each phase's acceptance assertions ticked with recorded verification (Phases 0–6 above).
- [x] Acceptance-shape questions answerable by a user without Forge internals: the new `proxy.md` "which surface answers
  which question?" table (route/reporter/scope/provenance) + the honest `forge activity` scope label + the `launch`
  segment (Forge-launched vs ambient) close this.
- [x] `change_log.md` entries per shipped phase (newest-first; Phases 0–5 present, Phase 6 added 2026-06-06).
- [~] **Durable lessons drafted for human promotion** — added under a clearly-labeled
  `### Proposed Promotions From Metric Evidence (awaiting human review, 2026-06-06)` subsection in `impl_notes.md` (two
  strict callsites die together; cost-unavailable = `None` not `0`; the isinstance JSONL guard; `billing_mode` ≠ key
  presence). **Human promotes** — not yet moved into the durable body.
- [x] Integration coverage: Phase 6 touches no hooks/session-lifecycle/proxy-runtime/installer **code** — only a CLI
  command rename + a `capabilities.py` line + docs. The one integration test that drives the renamed command
  (`test_session_commands_integration.py::TestActivityCommand`) was updated to `forge activity` and **ran green**
  (`-k Activity` → 1 passed, 5.8s, real wheel CLI in Docker). `test_audit_plumbing.py` is comment-only (no behavior
  change) — optional to re-run before merge.
- [x] Design docs + end-user docs reflect shipped behavior; `docs/auth_cost_metric.md` folded to an internal map.
- [x] **QA-checklist coverage (audit-driven follow-up, 2026-06-06)**: an adversarially-verified audit of
  `src/skills/qa/` + `docs/end-user/` found end-user docs clean and six QA gaps; closed all six (§3.4 masking misfire,
  §7.12 `forge activity` cost honesty, §7.13 provenance split, §7.14 rename tombstone, §8.5 `forge_cost` segment, §5.21
  `~` marker; test-count 512→532). Every `<!-- auto -->` fixture validated against real code on the host. See the
  `change_log.md` "Phase 6 follow-up" entry.
- [ ] **Move card `doing/ → done/` after final merge to `main`** — gated: branch not yet merged. **PR #18 open** (user
  owns the merge/lane-move). Phase 6 complete on branch 2026-06-06; PR #18 review fixes landed (commit `97b2098`);
  awaiting merge.

## Post-Review Follow-ups — RESOLVED on branch (2026-06-06)

From the PR #18 adversarial review (2026-06-06). The merge-gating findings were fixed on the branch (commit `97b2098`,
see the `change_log.md` "Phase 6 review fixes" entry). The three verified-but-narrow / cleanup items below were folded
in before the `doing/ → done/` move (rather than deferred to separate cards) — see the `change_log.md` "Phase 6
follow-up: deferred cleanups" entry.

- [x] **Bound the `forge_cost` ledger scan**: `sum_forge_added_cost` (`core/ops/usage_summary.py`) gained a keyword
  `since: datetime | None`, threaded to `read_usage_events(period_start=since)`; the status producer
  (`statusline/registry.py` `_produce_forge_cost`) derives it from the manifest `created_at` (defensive `parse_iso`,
  unbounded fallback on absent/malformed). An event can't predate its session, so the bound is loss-free. **Verified**:
  `test_usage_summary.py::TestSumForgeAddedCost::test_since_bounds_the_scan` (06-01 event excluded, unbounded sums
  both).
- [x] **Resolve the dormant `stream-json` branch**: **removed** (not threaded — Forge consumes headless output in batch,
  where `json` is equivalent and simpler; streaming stays a proxy concern). Dropped the `output_format` param + the
  `stream-json` branch from `_find_result_object`/`parse_headless_envelope`; left a seam note at both halves
  (`prepare_json_argv` + `_find_result_object`) so a future streaming mode wires the parser AND request side together.
  **Verified**: `test_bug_headless_envelope_parse.py::test_ndjson_stream_json_falls_back_to_raw_text` (NDJSON →
  `parsed=False` raw-text fallback, no crash, no silent half-parse).
- [x] **Duplication cleanup**: (a) the `isinstance(record, dict)` JSONL guard now lives once as
  `core.state.decode_json_object`, routed through all **5** readers (`cost_logger`, `cost_tracker`, `cost_tracking`,
  `audit_logger`, `ledger`); (b) `proxy_costs.py` verb/model/total aggregation extracted to `_aggregate_by_verb` /
  `_aggregate_by_model` / `_request_cost_totals`, shared by `_display_by_*` + `_output_json` (table vs JSON can't
  drift); (c) `emit.py`'s **direct-path** one-reporter precedence extracted to `_direct_cost_provenance`, shared by the
  verb + worker emitters — the **proxied** path stays per-caller (verb attributes the snapshot; a worker stays
  unattributed to avoid double-counting the verb aggregate). **Verified**: `test_io.py::TestDecodeJsonObject`,
  `test_emit.py::TestDirectCostProvenance` + `TestVerbWorkerPrecedenceInvariant` (direct verb == worker; proxied
  diverges — no double-count).

## Out of Scope (this card)

- MITM-by-default / always-on proxy on the wire for harness traffic (runtime-abstraction Phase 2 territory).
- Non-cost aggregate policies (failures/latency/content-filters/tool-errors) — schema-compatible only.
- `claude -p` exact per-request cost correlation (runtime-abstraction "4g").
- Native Codex/Gemini invokers beyond reading their headless usage output (runtime-abstraction Phase 5).

# Change Log

Completed-work record for Forge implementation sessions.

## Maintenance

- Updated by the memory writer with `strategy=changelog`, and by humans when closing a phase.
- Add compact entries for completed work only. Pending tasks belong in card checklists.
- Follow `docs/developer/board-contract.md` "Change Log Policy": each entry needs Goal, Key changes, and Verification.
- Keep entries short. Do not list every file unless the file list is the point of the work.
- Use newest-first order so active work stays near the top.
- When this file approaches the documentation size limits, compact the oldest entries at the bottom into a dated summary
  that preserves decisions, verification, and deferred items. Archive detailed old entries only if the summary is still
  too large.
- Check size before long sessions or when the file feels slow to scan:

```bash
wc -l docs/board/change_log.md
./scripts/count-tokens.py --model <agent-model> docs/board/change_log.md
```

## Entries

> Format: `## YYYY-MM-DD`, then `### Phase X.Y: Short Title`, with `**Goal**:`, `**Key changes**:` as bullets, and
> `**Verification**:`. Use newest-first order. See `docs/developer/board-contract.md` "Change Log Policy" for the full
> spec.

## 2026-06-05

### Phase 4: Status-line honesty (metric-evidence-simplification)

**Goal**: Make the status line honest about billing and add the user control the auth/cost audit demands — never infer
an API payer from key presence, record + show how a session reached the model, and let users keep a key out of
interactive sessions.

**Key changes**:

- **Bug #1 (billing honesty)**: `RenderContext.billing_mode` `auto` returns `ambiguous` instead of inferring `api` from
  `ANTHROPIC_API_KEY`; `format_billing_cost` already shows quota-if-`rate_limits`-else-`≈$`. Golden `$0.42`→`≈$0.42`;
  the old divergence test became a key-invariance test. Removed the now-dead `RenderContext.has_api_key`.
- **G4 (env omit)**: flat `interactive_anthropic_api_key: inherit|omit` on `RuntimeConfig`; one source-aware
  `apply_interactive_api_key`/`compute_interactive_api_key_decision` (env.py) over new
  `resolve_env_or_credential_with_source` (template_secrets.py). Applied LAST via the interactive wrapper in `invoke.py`
  (after extra_vars/unset), so it's authoritative and the recorded `source` matches the child. Headless callers
  untouched.
- **Sidecar omit**: `session_lifecycle` sets `FORGE_OMIT_INTERACTIVE_KEY=1`; `docker/entrypoint.sh` unsets the key for
  Claude *after* the in-container proxy captured its upstream credential (works for anthropic-upstream templates).
- **G3 (launch metadata)**: additive `LaunchConfirmed` under `confirmed.launch` (models.py); centralized best-effort
  `record_launch_confirmed` called from start/resume + host fork closures (session_fork.py) + sidecar.
- **Visible `launch` segment**: opt-in (off by default) `format_launch`/`_produce_launch` renders
  `<route>·key:<posture>`.
- **Deferred**: `forge +$Y` Forge-additional-cost segment → Phase 5 (sparse until headless reporters report cost).
- **Docs**: design_appendix §A.7/§A.8 + end-user config.md/authentication.md (new key, corrected `cost_mode=auto`).

**Verification**: Focused unit suites + full blast-radius sweep (2991 passed); `make pre-commit` clean
(ruff/black/isort/mypy/pyright/mdformat/gitleaks); integration `test_status_line_integration.py` (13, incl. real-CLI
launch-metadata + omit recording) and `test_sidecar_omit.py` (1, `/proc` proof Claude lacks the key while the proxy
keeps it) green.

### Phase 2 follow-up: Fix panel cost-visibility canary (wrong monkeypatch target)

**Goal**: Make the panel integration test previously filed as a "pre-existing" failure
(`test_panel_with_subprocess_proxy_records_verb_cost`) pass, so the panel verb-cost path is actually real-wire verified
rather than left red.

**Key changes**:

- Root cause was a **test bug**, not a product bug. The test registered its canary model via
  `monkeypatch.setitem(DEFAULT_MODELS, …)`, but `forge workflow panel --models <name>` resolves through
  `resolve_model_specs`, which validates an explicit `--models` against `AVAILABLE_MODELS` (the full registry).
  `DEFAULT_MODELS` is only the no-args fallback quorum, so the canary read as `Unknown models`. Patched it into
  `AVAILABLE_MODELS` — the registry the resolver actually reads.

**Verification**: `test_cost_visibility_e2e.py::test_panel_with_subprocess_proxy_records_verb_cost` passes on real
OpenRouter (4.2s); cost-visibility matrix now 5/5. Diagnosis confirmed with an isolated `resolve_model_specs` repro
(DEFAULT_MODELS patch → `Unknown models`; AVAILABLE_MODELS patch → resolves).

### Phase 2 follow-up: Verb cost-evidence in `forge proxy costs` + docs sync (review fixes)

**Goal**: Close two review findings on the shipped Phase 2 work — the verb display ignored the cost-evidence flag
(reintroducing unknown-as-zero), and several proxy/request dollar-cost references still said "estimated."

**Key changes**:

- **Verb display now reads evidence, not a number.** `_display_by_verb` / `_output_json` gated cost-evidence on a
  numeric `total_cost_micros` (always int, `0` for a passthrough window), so a `cost_measured=False` verb rendered
  `reported: true, cost_micros: 0`. Added `_verb_cost_reported` (trusts `cost_measured`; legacy records fall back to
  `total > 0`); `_scope_verb_records_to_proxy` re-derives `cost_measured` for the scoped subset from per-proxy
  `reported_request_count`. The request display was already correct via nullable `_reported_micros`.
- **Docs sync.** Aligned remaining "estimated" proxy/request dollar-cost language to reported-or-unavailable across
  `auth_cost_metric.md`, the normative `design.md` / `design_appendix.md` (they contradicted the synced authority
  table), and end-user/{proxy,config,session}.md. Preserved the attribution-snapshot sense (`estimated:true` verb field,
  `verb_snapshot_estimated` enum, concurrency caveat) as accurate.

**Verification**: `test_proxy_costs.py` +5 (reproduces `cost_measured=False` + total 0 → `reported:false`; reported-$0;
legacy fallback; scoped recompute); 23 focused tests pass; `make pre-commit` clean (commit `b95500d`).

### Phase 2: Cost source replacement — Forge is not a cost oracle (metric-evidence Slice 2)

**Goal**: Stop inventing dollars from a local price table. Proxy cost is now **reported-or-unavailable**: Forge records
the cost a route actually reported and says `unavailable` otherwise, then deletes the price catalog so it cannot
re-enter the accounting path. Landed in three tree-green steps (1: nullable+provenance plumbing → 2: reported-cost
capture → 3: de-catalog), Step 2 integration-verified before Step 3 removed the catalog safety net.

**Key changes**:

- **Reported-cost capture, full matrix.** Added a `cost_usd` carrier on `CompletionResponse` **and** `StreamEvent`
  (review-found: streaming had no carrier). OpenRouter cost comes from the response body (`usage.cost`), extracted in
  the shared `openai_compat` converter (covers both clients, stream + non-stream). LiteLLM-gateway cost comes from the
  `x-litellm-response-cost` **header**, recovered by switching non-streaming chat **and** the Responses-API branch to
  `with_raw_response.create().parse()` + `_merge_header_cost`. The proxy threads cost as an internal
  `_reported_cost_micros` key (non-stream) / usage-chunk field (stream, parked in the SSE converter's `final_usage` like
  `cached_tokens`), never leaked to the client.
- **Provenance at the proxy.** `_calc_and_log_cost` stamps `reporter` + `confidence` from
  `config.proxy.preferred_provider` (openrouter→`reported`, litellm→`gateway_calculated`); unreported →
  `cost_micros=None` / `confidence="unavailable"`, tokens still logged, `cost_tracker.record` + metrics cost
  accumulation skipped.
- **Verb cost-evidence (review-found conflation fix).** `ProxyCostDelta.reported_request_count` +
  `VerbCostResult.cost_measured` (derived from that delta, not `bool(deltas)`); `emit.py` logs `cost_micro_usd=None` /
  `confidence="unavailable"` for a passthrough verb that moved tokens but reported no cost — never a fabricated measured
  $0.
- **Catalog deleted** (zero surviving callers): `core/models/pricing.py`, `core/data/pricing.yaml`, the `core/models`
  re-exports, and `test_pricing.py` + `test_bug_pricing_fallback_logs.py`.
- **Header evidence gate** (Step 1): `X-Request-Cost` omitted when this request's cost is null (fixes a `None/1_000_000`
  crash); `X-Cumulative-Cost` omitted until a reported-cost event exists
  (`reported_request_count`/`unavailable_request_count` on `ProxyMetrics`).

**Breaking change / reset**: Plane-1 cost record fields `estimated:true` and `pricing_source` are **removed**, replaced
by `reporter` + `confidence` (research-preview clean break; `COST_SCHEMA_VERSION` stays `1` — new records omit the old
keys, legacy records read with defaults). **Spend caps now fire only for routes that report cost**:
Anthropic-passthrough and LiteLLM-**streaming** dollar caps become no-ops (tokens still tracked). No user action
required; existing logs read fine.

**Verification**: 5531 unit+regression pass; mypy/pyright clean; `make pre-commit` clean. Real-wire integration
(`test_cost_visibility_e2e.py`) confirmed the matrix with the catalog removed — OpenRouter `reported`
(stream+non-stream), LiteLLM `gateway_calculated` (non-stream), LiteLLM **streaming**
`cost_micros=None`/`confidence="unavailable"` (the documented gap: the header predates the cost and the gateway puts
none in the final usage chunk). Design docs (§3.14, §A.9, §A.13), `auth_cost_metric.md`, and the QA `7-costs.md`
fixtures updated to the reported/unavailable model.

### Phase 3: Remove `cap_mode` & strict pre-flight (metric-evidence Slice 3)

**Goal**: Collapse the proxy's two cap behaviors (`post` / `strict`) into one — post-event enforcement — by removing
`cap_mode` and the strict pre-flight cost estimate. Strict was the cost-oracle pattern in the cap path: it priced an
unsent request from the local catalog and blocked on that guess.

**Key changes**:

- **`cap_mode` removed entirely** from `CostConfig` (field + `valid_modes` validation + load). The `costs` block is
  leniently parsed, so a stale `cap_mode:` key is rejected with an explicit tombstone in `_coerce_cost_config` rather
  than silently ignored — verified at both config-parse and the `forge proxy set` validate-before-write path.
- **Both strict pre-flight callsites deleted** (`server.py` passthrough + translated). With strict gone the whole
  estimation apparatus is orphaned and removed: the `_textish_chars` / `_estimate_input_tokens` helpers, the cap-path
  `calculate_cost` imports, `check_cap`'s `projected_cost_micros` parameter, and the always-False `CapResult.projected`
  field + "Projected " message prefix. The local price catalog no longer touches cap enforcement (the post-flight
  logging catalog call is separate — Phase 2). `on_cap_hit` (reject/warn) is unchanged.
- Tests: deleted the strict-only regression file + strict unit tests; swept the removed `cap_mode=`/`projected`/old
  `check_cap` signature out of every surviving test (the type-checker, not a hand list, was the change-detector); added
  `tests/regression/test_bug_cap_mode_removed_key_rejected.py` (config-parse + CLI surfaces).
- Docs (evidence-neutral — shipped, not aspirational): `design.md` §3.7, `design_appendix.md` §A.9,
  `auth_cost_metric.md` §6, `end-user/proxy.md` (+ upgrade reset note), QA `7-costs.md`.

**Breaking change + reset**: `costs.cap_mode` is removed. An existing `proxy.yaml` carrying any `cap_mode:` line
(including the old default `post`) now refuses to load with an actionable message; remove the line. Research-preview
clean break — no migration. **Standalone decision** (recorded once so a future session doesn't pre-date it): docs say
caps are "enforced after each completed request, from accumulated recorded spend"; Phase 2 upgrades the wording to
"reported route cost" and makes cost nullable.

**Verification**: 924 proxy/config/regression unit tests pass + the new removed-key regression (4 cases);
`make pre-commit` clean. Proxy integration: 3/4 cost-visibility e2e pass (request path intact after the strict removal);
the 4th (`test_panel_with_subprocess_proxy_records_verb_cost`) is a pre-existing, unrelated failure (confirmed identical
on clean HEAD `c7402c3` — `monkeypatch.setitem(DEFAULT_MODELS, …)` not reaching the workflow model resolver).

### Phase 1: Metric-evidence schema & vocabulary pass (metric-evidence Slice 1)

**Goal**: Add the card's metric-evidence vocabulary (`route`/`reporter`/`confidence`) to the usage ledger **without
changing any accounting behavior** — the schema foundation every later phase builds on (Phase 2 reuses `Confidence` for
cost-log provenance; Phase 4/5 reuse `route`/`reporter`).

**Key changes**:

- New thin `core/usage/vocabulary.py` holds three `Literal` aliases (`Route`, `Reporter`, `Confidence`) with no I/O, so
  Phase 2's cost plane (`proxy/cost_logger.py`) can import `Confidence` without dragging in the ledger's dacite/lock
  machinery (`proxy → core` is the clean import direction).
- `UsageEvent` gains `route`/`reporter`/`confidence` — additive, defaulted (`confidence="unknown"`), re-exported from
  `core/usage/__init__`. **`USAGE_SCHEMA_VERSION` stays `1` — no bump, by decision**: additive defaulted fields change
  no meaning, require nothing, remove nothing, so a current reader loads pre- and post-change v1 records identically.
- The 4 emitters (`emit.py`) stamp **today's** provenance honestly — catalog-derived verb cost → `inferred`;
  structurally-no-cost routes (tagger via dummy-key LiteLLM, null-cost worker) → `unavailable`; `route` = how work
  reached the model; `reporter` = source of the *metric* evidence (tokens and/or cost). No dollar/token/`billing_mode`
  value changed. Phase 2 flips the `inferred` verb cost to `reported`/`gateway_calculated`; `route`/`reporter` are
  stable across that flip.
- **`confidence` is scoped to the event's own `cost_micro_usd`** only — orthogonal to `measurement_source` (token
  provenance). The tagger shape `measurement_source="provider_usage_exact"` + `confidence="unavailable"` is therefore
  not a contradiction: tokens were reported, dollars were not. A `source_refs`-joined cost record never upgrades
  event-local `confidence`. `unavailable` (route structurally reports no cost) is distinct from `unknown` (provenance
  never recorded; the pre-Phase-1 default), pre-declared so Phase 2 adds no enum value.
- Docs synced for shipped fields only: `design.md` §3.14, `design_appendix.md` §A.13 (Provenance row + 3 `Literal`
  definitions), `auth_cost_metric.md` §1 plane-3 row.

**Keep-at-1 tradeoff (documented once — do NOT "fix" it with a migration)**: a concurrently-running *pre-Phase-1* reader
hits `dacite(strict=True)` on the unknown `route` key and **drops** new records as `"malformed"` — it discards keys it
cannot model, it does not understand them. This is expected for additive fields under strict reads and acceptable
precisely because the usage ledger is best-effort, PID-sharded, pruned **local telemetry, not durable truth**. No reset,
no migration path is owed.

**Verification**: 58 targeted tests pass (`tests/src/core/usage/test_ledger.py` + `test_emit.py` + dependent read
surfaces `test_usage_summary.py`/`test_usage.py` + `test_bug_usage_workflow_double_count.py`); `make pre-commit` clean.
No integration run — pure host-side dataclass + JSONL round-trip (no Docker/`claude -p`/proxy path; contrast Phase 2/4).

## 2026-06-04

### Fix: cost/audit JSONL readers crash on valid-but-non-object lines (metric-evidence Phase 0)

**Goal**: A valid-but-non-object JSONL line (`[]`/`1`/`"x"`/`null`/`true`) must not abort cost/audit-plane log reads —
the metric-evidence card's self-contained, ship-first slice (Bug #4).

**Key changes**:

- Added the canonical `isinstance(record, dict)` guard (mirrors `core/usage/ledger.py:215-218`) to the four unguarded
  `.get`-after-`json.loads` readers: `read_cost_logs` (`proxy/cost_logger.py`), `read_verb_logs`
  (`core/reactive/cost_tracking.py`), `read_audit_logs` (`proxy/audit_logger.py`), and `CostTracker._parse_record`
  (`proxy/cost_tracker.py`). `read_audit_logs` (audit plane) was folded in by scope decision so no JSONL reader stays
  unguarded across cost/audit/usage.
- The three readers were genuine crashers (`AttributeError` is not caught by their `except OSError`, so one bad line
  aborted the whole read and crashed `forge proxy costs` / `forge proxy audit show`); `_parse_record` was an honesty fix
  — its caller already broad-excepts, so its test calls it directly.

**Verification**: new `tests/regression/test_bug_cost_log_non_dict_line.py` (3 readers × 5 values) +
`TestParseRecordGuard` (5) — all 20 verified to fail with the guards stashed, pass with them; 92 targeted tests green;
`make pre-commit` clean.

### Fix: status-line enhancement post-PR review — 5 findings (PR #16)

**Goal**: A second self-review pass after opening PR #16 surfaced five issues across the proxy GET / path, status-line
fail-open contract, a duplicated tier scanner, and two documentation claims; each fixed (two with regression tests).

**Key changes**:

- **F1 (proxy)**: `root()` now calls the idempotent `_ensure_runtime_state()` so a freshly-imported proxy GET / reports
  real config and exposes `metrics.costs.caps` before any POST warms the module (caps were load-order dependent; the
  `spend_cap` segment showed nothing on a fresh proxy).
- **F3 (fail-open)**: `render_segments` wraps each producer in `try/except` (one bad segment degrades to absent, never
  crashes the line); `_produce_cache_hit` guards the proxy metrics shape with `isinstance` like `_produce_spend_cap`.
- **F4 (parity)**: test asserting `explicit_tier_from_model` agrees with the proxy's `_tier_from_model_name` (its 1:1
  mirror) over a model corpus; shared-helper extraction deferred to keep `proxy.server` off the status-line hot path.
- **F2 / F5 (docs)**: qualified the "byte-identical default output" claim to the API billing path (the golden guard pins
  `ANTHROPIC_API_KEY`) + added a golden-scope test pinning the sole no-key divergence (`$`→`≈$`); generated
  `statusline.segments` config comment now lists all shipped names (`supervisor`/`policy`/`audit`/`drift`/`spend_cap`).

**Verification**: 5136 unit tests pass (`make test-unit`); 15 proxy metrics-integration (incl. the import-split cap
test); 2 new regression tests (`test_bug_proxy_root_caps_uninitialized.py`, `test_bug_statusline_producer_failopen.py`);
`make pre-commit` clean; PR #16 CI green (Tests, Pre-commit, CodeQL).

## 2026-06-03

### Fix: `forge usage` workflow double-count + supervisor warning misattribution (review fixes)

**Goal**: Two correctness bugs found reviewing today's per-session usage work; each fixed with a regression test.

**Key changes**:

- **Workflow double-count** (`core/ops/usage_summary.py`): a panel emits one verb-aggregate event plus N per-worker
  events that all share `command="panel"`, so `calls` — and the session-end "N workflows" tally derived from it —
  counted N+1 (a 4-worker panel read as 5 workflows). Worker-granularity events now land in a separate
  `CommandUsage.workers`; `calls`/`errors` count verb/session events only. `forge usage` gains a conditional Workers
  column; the Total line is relabeled "events".
- **Supervisor warning misattribution** (`_policy_activity`): collected the entry-level *composite* warnings (which the
  policy engine accumulates across every policy), so a TDD-permissive warning surfaced a phantom "supervisor: 0/0/0"
  section. Warnings now come from the `semantic.supervisor` sub-decision only, and the function returns None when the
  supervisor had no in-window activity.

**Verification**: 2 new regression files (`test_bug_usage_workflow_double_count.py`,
`test_bug_usage_supervisor_warning_misattribution.py`); 28 usage unit + regression tests pass; `make pre-commit` clean.

### Sidecar usage-ledger mount: `forge usage` + session-end summary now cover sidecar sessions

**Goal**: Close the deferred gap from the per-session usage entry below. In sidecar mode the supervisor + workflow verbs
(the only writers of usage events) run inside the `--rm` container and wrote to an unmounted `~/.forge/usage/`, so their
events died with the container — a sidecar session was invisible to `forge usage` and the session-end summary.

**Key changes**:

- **Mount `usage/` rw** in `sidecar/container.py` `_ensure_audit_plumbing_mounts`, symmetric with `audit/` + `costs/`
  (gated on a proxy id). The in-container `FORGE_HOME=/root/.forge` plus the bind mount let `log_usage_event` writes
  land on the host where `forge usage` reads them; PID-sharded shards keep host/container writers contention-free.
- **Docs**: design.md §7 mount enumeration + design_appendix.md §A.13 sidecar note flipped to the closed state
  (template-only sidecars, no proxy id, still mount nothing — consistent with how they already drop audit/costs).

**Verification**: `test_container.py::test_proxy_id_adds_env_and_mounts` asserts the `usage:/root/.forge/usage:rw`
mount; the `test_audit_plumbing.py` integration test (real sidecar image, host-spawned `--rm` container) writes a
supervisor-`error` `UsageEvent` inside the container and asserts the host sees it on the mounted `usage/events/` shard
after teardown. `make pre-commit` clean.

### Per-session usage visibility: `forge usage` + session-end summary (runtime_abstraction Phase 4 follow-up)

**Goal**: The Phase-4 usage ledger and `confirmed.policy.decisions` already record per-session supervisor/cost/token
activity, but nothing surfaced it — supervisor `warn`s exit 0 (Claude Code hides non-blocking hook stderr) and there was
no read surface. Light up two human-visible planes over the already-captured data.

**Key changes**:

- **Ledger read filter**: `read_usage_events(..., session=)` (`core/usage/ledger.py`), applied to the raw record before
  the typed build like the existing filters.
- **Pure aggregator** (`core/ops/usage_summary.py`, design §3.12):
  `build_session_activity_summary(name, forge_root, since=)` -> `SessionActivitySummary`. Two sources kept separate by
  guarantee — the **ledger** for per-command run/error/token/cost (uncapped) and `confirmed.policy.decisions` for
  supervisor allow/warn/deny + warning text (capped, surfaced via `log_capped`). Re-reads the manifest fresh from disk
  (hooks mutate `confirmed.*` during the run). Coverage flags `cost_partial`/`session_tagging_partial`.
  `render_summary_line()` is a shared pure formatter.
- **`forge usage [session]`** (`cli/usage.py`, registered in `main.py`): table + `--json`/`--days`/`--all`; resolves an
  explicit name/UUID via `resolve_session_identifier`, else `$FORGE_SESSION`; not-found tips `forge session list`.
- **Session-end summary**: refactored the launcher so host (`session_lifecycle.py:623`) and the early-returning sidecar
  path (`:557`) converge on one `_post_exit_render`; new best-effort `_print_session_activity_summary` prints a one-line
  rollup before the reconnect tip. Same helper wired into `session_fork.py` (the fork post-exit site). Surfaces
  supervisor `status="error"` runs — i.e. OpenRouter content-filter failures — directly.
- **Coverage**: threaded `session=$FORGE_SESSION` into the 4 workflow verbs' `emit_verb_usage`/`Attribution` so
  panels/debates appear per-session. Action tagger left untagged (documented). Sidecar usage-ledger mount closed in the
  follow-up above; action-tagger session tagging still deferred.
- **Docs**: design.md §3.14 (read surface) + §4.0 (command); design_appendix.md §A.13 (read surface + per-emitter
  coverage table + sidecar caveat).

**Verification**: 172 unit tests across the new + affected suites pass (`test_ledger` session filter,
`test_usage_summary` 11, `test_usage` 6, `test_session_activity_summary` 7, `test_workflow` session assertion); 207
existing session-command/fork/resume tests green (launcher refactor non-regressing); mypy + full pyright clean on
changed src.

### QA hardening: proxy passthrough + system-role + stale-container guard (runtime_abstraction)

**Goal**: A manual `/forge:qa` dry-run of the runtime-refactor branch surfaced real proxy-runtime bugs plus a QA-harness
bug that was *masking* them; fix all, each with a regression test.

**Key changes**:

- **Proxy accepts Claude system-role messages**: Claude Code 2.1.161 emits mid-conversation `{"role": "system"}` entries
  inside `messages`. The translated path binds `MessagesRequest` before conversion, so the `user|assistant`-only role
  Literal made Forge itself return a local 422 before the upstream saw the request. Added `"system"` to `Message.role`
  (`proxy/data_models.py`); `convert_anthropic_to_openai` preserves the block.
- **Passthrough hardening** (`proxy/passthrough.py`, `proxy/server.py`): (1) streaming upstream errors now surface with
  their real status — the upstream connection is opened *before* the `StreamingResponse` is constructed (refactor
  `_stream_upstream` -> `_stream_opened_upstream`), so a non-200 returns that status/body instead of a committed
  `200 text/event-stream` with error bytes inside it; (2) malformed JSON -> 400 and non-object JSON (`[]`/`null`) -> 422
  before forwarding.
- **Smoke-test model resolution** (`proxy/proxy_orchestrator.py`): `smoke_test_proxy` hardcoded `model: "sonnet"`, but
  passthrough proxies forward the client model unchanged (no tier aliasing). New `_resolve_smoke_test_model` reads the
  resolved Claude model from `GET /` tier mappings for `wire_shape: anthropic_passthrough`, defensively falling back to
  `sonnet`.
- **QA stale-container guard** (`skills/qa/scripts/start-container.sh`): the running-container reuse path `exit 0`'d
  before any image-revision check, so QA silently validated code older than the checkout (e.g. a proxy build predating
  the system-role fix). `FORGE_REV` is now computed before the reuse fast-path; a running container whose baked
  `org.opencontainers.image.revision` != `FORGE_REV` is refused (exit 3, points at `--reset`).
- **QA checklist + ignores**: `--yes --force` for non-interactive `session delete` (35 lines; `--force` overrides
  guards, `--yes` skips the prompt that `docker exec` EOFs on); removed the logout-skip-confirmation item; refreshed
  config-reset/policy-scoping/memory-retrack/disable sections + 1.0.21 count; new `.worktreeinclude` and `.envrc` ignore
  entries.

**Verification**: 70 unit+regression pass (new `test_bug_system_role_message_422.py`,
`test_bug_qa_stale_container_reuse.py`, plus `test_passthrough.py`/`test_proxy_orchestrator.py` additions); mypy clean
on the 4 changed proxy sources. Real-wire integration validation: `test_proxy_openrouter_e2e.py` (2 passed, translated
routing) + a host harness against real running proxies — passthrough malformed/non-object JSON -> 400/422, bad-model
stream -> real `404` (not 200-SSE), `smoke_test_proxy` resolves `claude-sonnet-4-6` and completes, and a system-role
message routes 200 through a translated proxy. Carried debt: the new passthrough error branches have unit +
manual-harness coverage but no committed integration test yet.

### Statusline Enhancement — Phase 5: Spend-cap proximity

**Goal**: Surface how close the session is to its configured spend cap, sourced from the proxy.

**Key changes**:

- `CostTracker.cap_summary()` (already present) wired into the proxy `GET /` snapshot under `metrics.costs.caps` via a
  new `_attach_cap_summary(metrics, tracker)` helper (`proxy/server.py`) — extracted so the wiring is unit-testable with
  a real `CostTracker` without standing up the full `root()` env, and keeps `ProxyMetrics` decoupled from `CostTracker`.
  The `caps` key is omitted entirely when no caps are configured (presence == caps active).
- New opt-in `spend_cap` segment: `format_spend_cap` renders the **binding** window (highest percent — the cap that
  blocks first) as `cap:<d|m> $X/$Y (Z%)`, threshold-colored (normal \<75%, yellow 75-89%, red >=90%).
  `_produce_spend_cap` reads `runtime.raw["metrics"]["costs"]["caps"]`; `None` in direct mode, on a registry-fallback
  proxy, or when caps are absent. `spend_cap` was the last reserved name — `SEGMENT_NAMES` now equals the producer set
  with zero reserved entries.
- Review fix: cap amounts use a new `_fmt_cap_money` (four decimals below a cent) instead of `_fmt_dollars`, which
  collapsed sub-cent smoke caps ($0.0005/$0.001) to the misleading `0c/0c`.

**Verification**: `_attach_cap_summary` CIT tests (real CostTracker; caps present/omitted); spend_cap format + producer
unit tests (binding window, thresholds, sub-cent precision, direct/no-caps hidden). `make test-unit` (5096 pass),
`make pre-commit` clean, full `test_metrics_integration.py` (15) green.

### Statusline Enhancement — Phase 4: Forge-unique opt-in segments

**Goal**: Surface Forge-specific posture (policy/supervisor/audit/routing) that nothing else in the bar shows.

**Key changes**:

- Four opt-in segments (off by default, absent from `DEFAULT_ORDER`): `supervisor`/`policy` read **effective** session
  state via a lazy `ctx.effective_intent` (`apply_overrides(intent, overrides)` on the raw manifest — no
  SessionState/dacite on the hot path); `audit`/`drift` read proxy `GET /` truth (`runtime.raw`). Names added to
  `SEGMENT_NAMES` + producers (equality invariant holds).
- `supervisor`/`policy` honor effective `policy.enabled` (a disabled policy makes the hook exit early): `SUP`/`pol:TDD`
  active, `SUP(susp)` suspended, `SUP(off)`/`pol:TDD(off)` disabled. A `%supervisor suspend` override flips the segment
  with no intent mutation.
- `audit` → `aud:<mode>` (+ `(lossy)` when inspecting/overriding a translated wire); `drift` mirrors the proxy's routing
  precedence — derives the route tier from stdin `model.id` (`explicit_tier_from_model`, 1:1 with the proxy's
  `_tier_from_model_name`) before falling back to `active_tier`, so an opus-pinned session on a sonnet-default proxy no
  longer false-positives.

**Review fixes (3 findings)**: (1) `policy.enabled` gating; (2) confirmed bundles revived only when intent has no policy
block at all — an override emptying `bundles` no longer resurrects stale `confirmed.policy.bundles`; (3) real-route
drift.

**Verification**: format-helper + producer unit tests, override-flips-supervisor through the full CLI, opt-in/off-by-
default wiring, three review-fix regression cases. `make pre-commit` clean (mypy + pyright); 5096 unit tests pass.

### Statusline Enhancement — Phase 3: Throttled cache-hit-rate (file-backed)

**Goal**: Add a `cache_hit` segment that surfaces cache effectiveness without re-scanning the transcript on every poll.

**Key changes**:

- New opt-in `cache_hit` segment (added to `SEGMENT_NAMES` + producer; equality invariant holds). Proxy mode reads the
  live `runtime.raw["metrics"]["cache_hit_rate"]` (free, no file). Direct mode uses `compute_cache_hit_rate`, a new
  deduped transcript primitive: groups by `requestId` (fallback `message.id`), keeps the max-`input_tokens` snapshot per
  request (streaming appends growing records — Claude Code #5904), and computes
  `sum(cache_read_input_tokens) / sum(input_tokens) * 100` — matching the proxy's `passthrough._normalize_usage` +
  `metrics.snapshot` definition exactly (reads over fresh input; cache creation is not a hit).
- `src/forge/cli/statusline/throttle.py`: caches the rate at
  `get_forge_home()/cache/statusline/<sha1(session_id|transcript_path)>.json`. Reuses while the transcript is unchanged
  (mtime+size) OR the entry is within `cache_hit_ttl`; recomputes otherwise. Atomic write (mkstemp + os.replace).
  Runtime-only: version mismatch / corrupt / any I/O error → recompute or skip, never raise. A `None` result is not
  cached. The path hashes the session id (never a raw stdin value).
- `cache_hit: off` hides the segment even when listed.

**Verification**: dedup + proxy-formula unit tests; throttle tests (within-TTL reuse via compute spy, unchanged-past-TTL
reuse, changed+past-TTL recompute, corrupt/version recompute, hashed key, None-not-cached); cache_hit e2e (proxy reads
metric + writes no file, direct writes throttle file, `off` hides). `make test-unit` (1558 pass), `make pre-commit`
clean, manual render `cache:75%`.

### Statusline Enhancement — Phase 2: Billing-aware cost + rate_limits shape fix

**Goal**: Make the cost segment honest for a mixed userbase (API key → real dollars; OAuth/subscription → quota), and
fix rate-limit rendering against the current payload shape.

**Key changes**:

- `format_rate_limits` now accepts BOTH the current object payload (`{five_hour, seven_day}`) and the legacy list, via
  `_extract_short_window` (prefers the 5h window). A bare dict without those keys is still rejected (back-compat). Added
  an opt-in reset countdown (`show_reset`, testable `now`) sanity-capped at ~8 days so a malformed `resets_at` can't
  render `616518h`.
- `RenderContext.billing_mode` resolves to `api` | `subscription` | `ambiguous` from `statusline.cost_mode` + raw
  `os.environ.get("ANTHROPIC_API_KEY")` (NOT `resolve_env_or_credential`, which would misclassify an OAuth session).
- `_produce_cost`: API → dollars (`get_session_metrics`); subscription/ambiguous → `format_billing_cost` (5h quota, or
  an `≈$` hedge when auto+no-key has a phantom dollar figure but no quota data); proxy unchanged (`~$`). Extracted
  shared `_fmt_dollars` / `_format_duration` helpers (no behavior change to the API path).
- `_produce_rate_limits` suppresses the standalone segment when billing is non-API AND `cost` is in the active layout
  (`ctx.active_segments`, set by `render_segments`), so the quota never shows twice.
- Documented `refreshInterval`/`padding` as a `forge claude preset edit` opt-in (`docs/end-user/config.md`); no
  auto-installed preset change.

**Verification**: Object-shape + reset-countdown + `format_billing_cost` unit tests; billing e2e through `status_line()`
(api/subscription/auto±key/suppression). Commands: `make test-unit` (1537 pass), `make pre-commit` clean,
`./scripts/test-integration.sh tests/integration/cli/test_status_line_integration.py` (10 pass), manual render across
all four billing modes.

### Statusline Enhancement — Phase 1: Segment registry + palette/glyphs

**Goal**: Make the status line config-driven and customizable without changing default output, and adopt a selectable
earthy palette.

**Key changes**:

- New `src/forge/cli/statusline/` siblings: `registry.py` (ordered `Segment` table, `resolve_order`, `render_segments`),
  `context.py` (lazy `RenderContext` — transcript scan / git / context parsing are `cached_property`, so disabled
  segments do zero work), `palette.py` (`Palette` + `Glyphs`, earthy "Sage & clay" instance).
- `status_line()` replaced its 106-line inline 5-category assembly with `render_segments` + the unchanged
  `render_categories()` / wrap-harden tail. Producers are thin adapters over existing `format_*`.
- Palette applied as an **output-level ANSI remap** (single-pass regex; `default` == empty remap == no-op), so earthy
  recolors the whole line without threading a `palette` arg through ~8 helpers. `glyphs: ascii|unicode` threads block
  chars (U+2588/U+2591) into the `get_context_display` progress bar only.
- **Breaking (research-preview clean break)**: removed the flat `show_rate_limits` config key. `rate_limits` is now an
  opt-in segment (not in `DEFAULT_ORDER`). New `_REMOVED_KEYS` map surfaces an actionable message on load (one-time
  warning), `set`, and `reset`, naming the replacement. **Reset path**: delete `show_rate_limits:` from
  `~/.forge/config.yaml` (auto-pruned on next `config set`) and, to keep rate limits, run
  `forge config set statusline.segments=path,model,rate_limits`.

**Verification**: Golden no-op guard freezes byte-identical default output across 4 fixtures on the API billing path
(the guard pins `ANTHROPIC_API_KEY`, so the snapshots are the `$` view); the sole no-key divergence — the `$`→`≈$` cost
hedge added in Phase 2 — is pinned by a companion golden-scope test. Lazy-compute tests (with firing controls);
earthy/unicode unit + e2e tests; `show_rate_limits` removal tests (load warn, set/reset reject); allowlist == producers
equality test + all-dropped→`DEFAULT_ORDER` fallback. Commands run: `make test-unit` (1512 pass), `make pre-commit`
clean (ruff/black/isort/mypy/pyright/mdformat),
`./scripts/test-integration.sh tests/integration/cli/test_status_line_integration.py` (10 pass, incl. the rate-limit
tests repointed to segment config), and a manual `forge status-line` render confirming earthy+unicode.

## 2026-06-02

### Phase 4: Review-pass hardening (4a / 4c / 4d)

**Goal**: Fix issues found reviewing the shipped Phase 4 slices before merge -- one concurrency race plus three
correctness/clarity gaps, each with a test.

**Key changes**:

- **4d cancellation race (spawn/register TOCTOU)**: `ClaudeHeadlessInvoker.run_parallel` could spawn a child between
  `Popen` returning and registering it in `children`; a `_cleanup` snapshot in that window left the child un-SIGTERMed,
  so `executor.shutdown(wait=True)` blocked on its `communicate(timeout)` (Ctrl+C hang + transient orphan). Fixed with a
  lock-guarded `cleanup_started` flag: a worker self-reaps a child registered after cleanup began, skips spawning once
  cancellation starts, and `shutdown(cancel_futures=True)` drops unstarted workers -- append and flag-read are atomic
  under `children_lock`, so each child is reaped exactly once.
- **4d cancelled workers no longer emit usage**: a cancelled job fell through to `_emit_worker` and was logged
  `status="error"`. Added a typed `HeadlessResult.cancelled` (keeps `error="cancelled"` for the review layer);
  `_emit_worker` skips cancelled -- one policy point.
- **4c direct-LLM `cached_tokens`**: `emit_direct_llm_usage` dropped `cached_tokens`; now copied from provider usage.
- **4a partial-origin marker**: pinned the both-or-neither `origin_run_id`/`origin_root_run_id` contract on
  `_memory_writer_env` with a comment + test, so the defensive fallback isn't mistaken for a parent/root bug.

**Verification**: `test_claude_invoker.py` + `test_emit.py` 24 passed (incl. new race + cancelled-emit + cached_tokens
tests) + `test_startup_queue.py` partial-marker test; mypy + pyright + `pre-commit` clean on changed files.

### Phase 4: Deferred integration validation (4a / 4c / 4d / 4f)

**Goal**: Run the CLAUDE.md-mandated Docker / real-`claude -p` integration deferred across the Phase 4 slices, now that
4a-4f have shipped, so every shipped slice has real-subprocess coverage (not just mocked unit tests).

**Key changes**: None -- validation-only run.

**Verification** (`./scripts/test-integration.sh <file> -v`):

- `test_policy_hooks.py` (4f, deterministic): 10/10 -- real `forge hook policy-check` (adapter->engine->responder, exit
  codes, manifest).
- `test_supervisor_e2e.py` (4a/4c/4f, deterministic harness): 4/4 (8.2s) -- `forge policy supervisor`
  aligned/divergent/infra-error + session-set wiring (covers 4a env stamping, 4c supervisor emission, the 4f
  `cli/policy.py:692` site).
- `test_real_claude_memory.py::test_real_handoff_review_only_smoke` (4a/4c, real Claude): PASSED -- real
  `forge memory-writer run` end-to-end (4a origin-identity marker plumbing + 4c emission).
- `test_real_claude_workers.py` (4d, real Claude): 2/2 (34.4s) -- real `claude -p --bare` fan-out via
  `ClaudeHeadlessInvoker.run_parallel` (the process-group spawn/cleanup/ordering the mocked unit tests can't reach).

**Pre-existing finding (NOT runtime-abstraction; surfaced by this run)**:
`test_real_claude_memory.py::test_real_shadow_curation_smoke` FAILS because it passes `--session` to
`forge memory track`, which PR #6 (`13f57db`, 2026-05-28, project-scoped memory passports) made invalid ("track ... does
not take a session"). Stale test from the #6 memory change -- `13f57db` is a pre-branch ancestor and this branch touches
neither `cli/memory.py` nor the test. Latent because `slow` real-Claude tests are rarely run. Needs a separate test-only
fix to the post-#6 shadow-curation invocation; tracked for whoever owns #6's surface.

## 2026-06-01

### Phase 4 (Slice 4f): Runtime-tagged ActionContext + named Claude hook adapter/responder

**Goal**: Make the policy hook's runtime boundary explicit -- so a Codex hook can normalize into the same
`ActionContext` and reuse the runtime-agnostic policy engine -- without changing any Claude behavior.

**Key changes**:

- `ActionContext` gains a **required** `runtime: str` (no default): every normalized action declares its origin runtime.
  `PolicyEngine.evaluate` still never branches on it -- it is attribution metadata, not control flow -- so the engine
  stays runtime-agnostic.
- Named the two Claude-specific halves behind runtime-neutral protocols (`src/forge/cli/hooks/protocols.py`,
  `HookAdapter`/`HookResponder`): `ClaudeHookAdapter.build_context` (Claude payload -> `ActionContext`, tags
  `runtime="claude_code"`; replaces the private `_build_action_context`, no compat shim) and `ClaudeHookResponder`
  (composed decision -> Claude wire: `format_deny`/`format_needs_review`/`allow_feedback` + `BLOCK_EXIT`/`ALLOW_EXIT`).
- `policy_check` (`cli/hooks/commands.py`) routes deny/needs_review/allow through the responder; the `[forge] Policy: …`
  summary + warning lines stay inline as a telemetry overlay, not part of the runtime wire contract. Output bytes and
  exit codes are unchanged -- the 77 existing hook-command snapshot tests pass untouched.
- Codex parity is NOT implied: its limits live in the 4e runtime registry (`pretool_policy="partial"`,
  `native_hooks="gated"`); a `CodexHookAdapter`/`CodexHookResponder` is the Phase 6 stub the protocols make room for.
- All 4 production constructors (hook + 3 on-demand checks) + ~45 test constructions pass `runtime`. `design.md` §4.1.4
  (runtime field + adapter/responder boundary) and §4.1.5 (responder owns the deny serialization) document the seam.

**Verification**: 340 policy + 77 hook-command + 23 new responder/adapter tests pass; `mypy` clean across policy +
cli/hooks (the precise `ActionContext | None` adapter return surfaced and fixed two latent `new_content` narrowing gaps
the old `Any` return had masked). Two pre-existing, unrelated regression failures (`forge info` patching-build text,
`run_claude_print` exit code) confirmed failing on a stashed clean tree -- not introduced here. Integration
(CLAUDE.md-mandated for hook changes): `tests/integration/docker/test_policy_hooks.py` -- the real wheel-installed
`forge hook policy-check` subprocess in an isolated container -- 10 passed (16.7s), confirming the
adapter->engine->responder dispatch (deny exit 2, allow exit 0 + manifest updates, fail-open) is byte-identical through
the real CLI boundary.

### Phase 4 (Slice 4e): Runtime registry capability matrix

**Goal**: Make "can this runtime do X?" a declarative lookup instead of hard-coded Claude Code assumptions, so Phase 5's
Codex invoker and auth/runtime preflight have a capability source to read.

**Key changes**:

- New `src/forge/core/runtime/` package: a frozen `RuntimeSpec` per runtime in a module-level `RUNTIMES` table (mirrors
  `core/auth/capabilities.py`'s `Credential`/`CREDENTIALS` pattern) + lookup helpers (`get_runtime` raises on unknown
  id; `list_runtimes`/`installed_runtimes`). Answers the card's seven questions:
  installed/interactive/headless/hooks/usage source/native resume/install scopes (+ curated-transfer in/out).
- **Installed vs version split**: `is_installed()` = PATH presence (reliable, fast); `detect()` = best-effort
  `--version` probe. Claude reuses `install/version.py:get_claude_runtime_version` via a **lazy** import (matching the
  `core->install` lazy-import precedent in `core/ops/gc.py`), so importing the registry never drags the installer.
- **Honest capability encoding**: partial/planned support is a tri-state `Literal`, not a `bool` -- Codex
  `pretool_policy="partial"` (the card: PreToolUse is not a full enforcement boundary), `interactive="beta"`, and
  `native_hooks="gated"` with machine-readable `hook_min_version`/`hook_feature_flag` (a preflight verifies the gate,
  not a note string); Gemini `native_hooks="none"`/`native_resume=False`. Codex/Gemini declare limits as values, never
  as parity-implying omissions.
- `forge runtime list [--json]` read surface (registered in `cli/main.py`). The table escapes free-text notes so a
  bracketed token like `[features] codex_hooks = true` survives Rich markup instead of being eaten as a style tag.
- `design.md` §5.5.5 documents the registry as the capability half of the runtime seam (the invoker is the lifecycle
  half). Nothing branches on the registry yet -- Phase 5 is its first consumer.

**Verification**: 16 new unit tests (`tests/src/core/runtime/test_registry.py` shape/fields/limits/`is_installed`/
`_probe_version`; `tests/src/cli/test_runtime.py` hermetic render + `--json` + the markup-escape regression) pass; mypy
clean on the 3 new source files; `forge runtime list` smoke-rendered the matrix against the real CLIs on this host
(claude 2.1.159 / codex 0.135.0 / gemini 0.43.0).

### Phase 4 (Slice 4d): HeadlessInvoker + review fan-out migration + per-worker usage events

**Goal**: Extract the review engine's parallel `claude -p` lifecycle behind a runtime-neutral `HeadlessInvoker` seam (so
Phase 5 can add a Codex runtime without touching callers), and emit the per-worker usage events deferred from 4c.

**Key changes**:

- New `src/forge/core/invoker/` package: `HeadlessRequest`/`HeadlessResult`/`Attribution` + the `HeadlessInvoker`
  Protocol (`run` single-shot, `run_parallel` fan-out), and `ClaudeHeadlessInvoker`. The seam is the **lifecycle, not
  the routing**: a request arrives already-routed (`argv`+`env`), so routing stays review-domain and the same
  `run_parallel` serves a future `CodexHeadlessInvoker`.
- `review/engine.py` `run_multi_review` shapes per-worker requests (`_prepare_worker`) and delegates to
  `ClaudeHeadlessInvoker().run_parallel`, mapping back via `_to_review_result`. The lifecycle moved **verbatim**
  (`Popen(start_new_session=True)`, `os.killpg` SIGTERM->SIGKILL under `children_lock`, `ThreadPoolExecutor(min(N,5))`,
  `result_map[idx]` ordering); original status conventions preserved.
- Per-worker usage events: `Attribution(command=...)` threaded from the 4 verbs (panel/analyze via `run_multi_review`,
  debate/consensus via `run_adversarial`/`run_consensus`); `run_parallel` emits one `emit_worker_usage` per worker
  (`attribution_granularity=worker`, `measurement_source=unattributed`, cost null -- the verb aggregate holds the
  estimated total; run/model/status/latency capture the tree leaf).
- The 4 single-shot callers keep `run_claude_session` (already the right abstraction with its guards; the invoker's
  `run()` is for protocol completeness + Phase 5). `design.md` §5.5.5 updated; checklist 4d boxes ticked.
- **Review fixes (folded in):** (1) cancellation cleanup — `run_parallel` manages the executor manually so `_cleanup()`
  SIGTERMs children **before** the blocking join; the `with ThreadPoolExecutor` `__exit__` would otherwise
  `shutdown(wait=True)` before cleanup, delaying SIGTERM up to `timeout_seconds` on Ctrl+C. (2) Per-worker events record
  the **actual routed** `model`/`provider`/`proxy_id` (`route.model_ref`/`route.provider`/`routing_result.proxy_id`),
  not the friendly catalog id with null provider/proxy. `design_appendix.md` §A.13 documents the per-worker emitter.

**Verification**: 62 existing review tests (`test_engine`/`test_adversarial`/`test_consensus`) pass with only a
patch-target retarget (`forge.review.engine.subprocess.Popen` -> `forge.core.invoker.claude.subprocess.Popen`), proving
the extraction is behavior-preserving; 15 invoker tests (`tests/src/core/invoker/test_claude_invoker.py`: ordering,
concurrency cap, timeout + cancellation killpg, run-id surfacing, single-shot parity, per-worker emission) + an engine
per-worker routed-metadata test. Full unit suite 4925 passed; mypy clean.

### Phase 4 (Slice 4c): Review fixes -- direct-path join, honest billing, latency

**Goal**: Close three correctness gaps in the 4c emitters found in review.

**Key changes**:

- Direct-path join now actually works. The tagger resolves its call's base_url synchronously (`resolve_client_base_url`
  -> new `resolve_provider_base_url`) and, when it is a registered Forge proxy, forwards `X-Request-ID` **and** records
  `source_refs.cost_request_id` (forwarded id == recorded id). Off-proxy: no header, null ref. Before, the id was
  minted, forwarded, then discarded -- so even a proxy target produced `source_refs=None`.
- Honest direct billing. `emit_direct_llm_usage` no longer hardcodes `has_api_key=True`/`api`; `billing_mode` defaults
  to `unknown` (the default tagger path routes via local LiteLLM with a dummy `not-needed` key, and proxy-lookup
  failures must not read as `api`).
- `latency_ms` now populated. `track_verb_cost` records wall-clock duration on every path (incl. no-proxy); the
  verb/session emitters copy `duration_ms`; the tagger times its own `complete()` call.

**Verification**: +4 unit tests (base_url resolver, end-to-end proxy join, billing/latency); full unit suite green (4910
passed); mypy clean. design.md §3.14 + appendix §A.13 updated.

### Phase 4 (Slice 4c): Instrument native + direct usage paths

**Goal**: Wire the usage-attribution ledger to the callsites where a run identity and a cost/usage signal already exist,
so `forge` verbs and the action tagger record who consumed what -- honestly, without faking figures Forge can't measure.

**Key changes**:

- `track_verb_cost` now yields a `VerbCostResult` holder (populated in place on exit) so callers read the estimated cost
  delta for attribution. A new `measured` flag separates a real snapshot delta from a no-proxy verb (null cost, not a
  fabricated $0). Backward-compatible: callers without `as cost` are unaffected; the verb-cost log is unchanged.
- New `core/usage` helpers: `infer_billing_mode` (conservative -- `api` only when direct + key, else `unknown`),
  `with_forge_request_id` + `target_is_forge_proxy` + `mint_request_id` (direct-path `X-Request-ID` correlation
  primitives), and `emit_verb_usage` / `emit_usage_for_session_result` / `emit_direct_llm_usage` (best-effort,
  depth-agnostic; no-op without a run identity). 4d reuses the emit helpers.
- Wired emitters: the four workflow verbs (`panel`/`analyze`/`debate`/`consensus`, one estimated verb-level event each,
  ambient run); memory writer, semantic supervisor, shadow curation (one event per `claude -p` run, attributed to the
  subprocess run, null `source_refs`); the action tagger, switched `ask()` -> `complete()` to capture
  `provider_usage_exact` provider tokens and forward `X-Request-ID` (behavior-preserving on a None-default client).
- Added `measurement_source=provider_usage_exact` (a direct call's exact in-band tokens fit none of the original four
  values); enum finalized with its first emitters -- nothing emitted before, so no migration.
- Deferred: review-engine per-worker events (-> 4d behind `HeadlessInvoker`); team supervisor/tagger + workflow stages
  (no cost wrapper / proxy-only); interactive launchers; native runtimes (Phase 5). `claude -p` per-request correlation
  stays null until 4g.

**Verification**: 20 new unit tests (billing/correlation/emit), tagger updated to `.complete()` + emits,
`test_workflow.py` verb-event emission, regression `test_bug_usage_claude_p_null_source_refs.py`; targeted suites green
(usage, tagger, cost_tracking, workflow, memory_writer, supervisor, shadow); mypy clean on all 11 wired files;
`make pre-commit` clean. Two commits: 4c-i foundation `1477d3b`, then 4c-ii wiring. design.md §3.14 + appendix §A.13
updated (emitters shipped).

### Phase 4 (Slice 4b): Usage-attribution ledger schema

**Goal**: Add the durable, versioned `~/.forge/usage/events/` attribution ledger -- the third data plane alongside cost
and audit, joined to them by a shared proxy `request_id` -- so Phase 4c can record which run/workflow/session invoked
which runtime/model and consumed what.

**Key changes**:

- New `src/forge/core/usage/` package (`ledger.py`): `UsageEvent` (`schema_version=1`; auto-stamped `event_id`/`ts`;
  required attribution core run/root/runtime/command/status; every other field defaulted), `SourceRefs`
  (`{cost_request_id, audit_request_id}`, nullable), and `BillingMode`/`MeasurementSource`/`AttributionGranularity`
  literals (provenance recorded, never inferred).
- `log_usage_event` (best-effort, never raises; `open_secure_append` 0600, dirs 0700; PID-sharded
  `usage/events/<month>_<pid>.jsonl`; module `_lock`); strict typed `read_usage_events` -- `dacite.Config(strict=True)`,
  so unknown fields, invalid literals, and wrong nested types are all corruption; a non-object line, a newer-schema
  record, or a malformed record is skipped with a one-time warning; raw-dict filters run before the typed build. Plus
  `prune_usage_events`. Modeled on `audit_logger.py` (versioned), NOT the unversioned `cost_logger.py`.
- **Refinement vs the decision's path**: PID-sharded `usage/events/<month>_<pid>.jsonl`, not a single `events.jsonl`, so
  cross-process review workers never contend on one file.
- Docs: `design.md` §3.2 (contract-files row) + §3.14 (three-plane model); `design_appendix.md` §A.13 (schema).

**Verification**: 16 unit tests (`tests/src/core/usage/test_ledger.py`: roundtrip, version stamp, 0600/0700 perms, null
and nested `source_refs`, newer-skip-warn-once, unknown-field / bad-literal / bad-nested corruption, non-object and
malformed line skip, run/command filters, ts-window, best-effort writer) plus a parametrized regression
(`tests/regression/test_bug_usage_ledger_non_dict_line.py`: a non-object JSONL line must not abort the read).
`pre-commit` clean (mypy + pyright). No callsites emit yet -- instrumentation is Slice 4c.

### Phase 4 (Slice 4a): Run-tree env contract

**Goal**: Give every Forge-spawned process a run-tree identity
(`FORGE_RUN_ID`/`FORGE_PARENT_RUN_ID`/`FORGE_ROOT_RUN_ID`) for usage attribution, orthogonal to the `FORGE_DEPTH`
recursion guard.

**Key changes**:

- `core/reactive/env.py`: `RunIdentity` + `mint_run_id`/`get_run_identity`/`new_root_run_identity`/
  `derive_child_run_identity`; `build_claude_env` gains `derive_run_identity=True` and stamps the triple right after the
  depth block (reads the spawner id before overwriting; recomputes parent so a stale inherited `FORGE_PARENT_RUN_ID`
  can't leak). `FORGE_DEPTH` and its three recursion guards are untouched.
- `SessionResult` and `ReviewResult` surface `run_id/parent_run_id/root_run_id` (read back from the built env) for Slice
  4c attribution; error/timeout returns carry it too.
- Interactive launches are roots: minting centralized in `invoke._build_environment` (`derive_run_identity=False` +
  fresh root + parent scrub) covers session start/resume/fork and bare `forge claude start`; the sidecar mints its own
  root in `container.py`. (Refinement vs plan: one choke point instead of per-builder, so resume/fork can't drift.)
- Memory-writer (queue-decoupled): `enqueue_handoff_marker` snapshots the session's
  `origin_run_id`/`origin_root_run_id`; `main._memory_writer_env` re-roots the detached spawn under that origin (fresh
  child run_id) and scrubs the drainer's run-tree **and** session identity
  (`FORGE_SESSION`/`FORK_NAME`/`PARENT_SESSION`, via the canonical `session_start` constants), so neither the run-tree
  nor the writer's `claude -p` hooks/status attribute to whichever CLI drained the queue (the writer takes its target
  session from `--session-name`).
- Docs: `design_appendix.md` §F.5 (run-tree identity vs recursion guard) + §C.1 (handoff marker origin fields).

**Verification**: targeted unit/regression tests pass, incl. new `tests/regression/test_run_tree_env_contract.py`
(depth/guard orthogonality, source-env-unmutated), run-id surfacing across env/session_runner/engine/container/
startup_queue, and `test_claude_invoke.py` interactive fresh-root carve-out (inherited run vars must not leak into a
root). `tests/src -m "not integration"` fully green (4866 passed). The only 2 failures under
`tests/src + tests/regression` are pre-existing and unrelated to run-tree: `test_bug_claude_print_helper_exit_code` (a
Docker-only conftest helper failing host-side at `tests/integration/docker/conftest.py:133`, mis-filed in `regression/`
without the `integration` marker) and `test_removal_patching_system::test_forge_info_no_traceback` (pre-OSS
manifest-guard assertion). `pre-commit` clean (mypy + pyright).

### Phase 3 (Stage C v1): Opt-in native-relocate for worktree forks

**Goal**: Ship `forge session fork --resume-mode native-relocate` as an opt-in, byte-faithful cross-CWD resume and make
the transfer fallback visible, while keeping transfer the default.

**Key changes**:

- `fork --resume-mode [transfer|native-relocate]` (`default=None`). For worktree/`--into` forks, native-relocate copies
  the parent JSONL into the child's encoded dir (reusing `relocate_transcript`) and launches `--resume --fork-session`
  from the worktree CWD; transfer stays the default and now prints a one-line tip pointing at native-relocate.
- Preflights before `fork_session()` (no orphans): reject sidecar (accounting for `--direct`/`--no-proxy` forcing host
  via `manager.py:1263-1266`), `--no-launch`, and a missing parent transcript; tips for `--resume-mode` on a same-dir
  fork and for `--strategy`/`--inline-plan` under native-relocate. A post-create relocate failure (e.g. `--into`
  conflict) rolls back the fork via `delete_session` (owns_worktree-aware, so an `--into` target is preserved).
- Provenance + cleanup: `Derivation.resume_mode="native-relocate"` + `relocated_parent_session_id`; `delete_session`
  unlinks the relocated copy in a branch gated only on the derivation (independent of the child UUID, so failed/partial
  launches still clean up), dir-scoped so the parent's original is never touched.
- Host mode only; `--rewrite-paths`, sidecar native-relocate, `resume --resume-mode native-relocate`, and the default
  flip are deferred (default-flip gates recorded in `card.md`). `docs/design.md` §3.9 documents the shipped opt-in.

**Verification**: 13 new unit tests (`test_session_commands.py::TestSessionFork` 10,
`test_fork_into.py::TestForkNativeRelocate` 3) pass; 39 existing fork tests green (no regression); pyright/mypy clean on
changed src; design.md under the 25k tiktoken size hook; `make pre-commit` clean.

### Phase 3 (spike): Native-relocate cross-CWD resume — PASS, wiring deferred

**Goal**: Settle the design.md §3.9 open question — can a Claude Code conversation resume across a CWD boundary if its
session JSONL is first copied into the destination CWD's encoded project dir? Deliver a contract test + go/no-go, not
the product surface.

**Key changes**:

- **Bug fix (surfaced by the spike)**: `encode_project_path` (`session/claude/paths.py`) now maps `_`→`-` alongside `/`
  and `.`. Claude Code 2.1.158 hyphenates underscores; Forge didn't, so `get_transcript_path` pointed at the wrong dir
  for any underscore-bearing path (silently breaking cleanup, status transcript reads, and relocation). Regression:
  `tests/regression/test_bug_encode_project_path_underscore.py`.
- **Relocate primitive**: new `session/claude/relocate.py` — `relocate_transcript()` does a content-untouched, atomic
  (temp + `os.replace`) copy into the dest CWD's encoded dir; owner-only perms; idempotent; refuses to clobber differing
  content; `rewrite_paths` seam reserved (`NotImplementedError`, off by default). 8 unit tests.
- **Reproduction script**: `scripts/experiments/native-resume/` (recreates the path dangling-referenced in code) —
  host-runnable, isolated `HOME`, control-vs-experiment, PASS/DISCOVERY-FAIL/SIGNATURE-FAIL/UNCATEGORIZED verdicts.
- **Contract test**: `tests/integration/docker/test_native_relocate_contract.py` + conftest `relocate_and_resume` — real
  Claude, signed-thinking + tool-use parent turn, in-container relocate via the real primitive, hook-free child resume
  (`FORGE_SESSION` unset) from a real git worktree; three-way verdict judged from Claude's project dir; host+container
  version gate; parent-immutability sha256. Found (and the harness documents) that `--dangerously-skip-permissions` is
  rejected under root, so the container runs without it (read-only tools still execute in `--print`).
- **Docs**: design.md §3.9 and the `session_fork.py` worktree-branch comment version-stamped; transfer stays the shipped
  default (native-relocate opt-in wiring is the deferred Stage C follow-up).

**Outcome**: **PASS on Claude Code 2.1.158.** Control (resume without relocating) still reproduces the 2026-04-02 "No
conversation found" discovery failure; the experiment (relocate, then resume) completes a signed-thinking tool-use
continuation with the relocated parent JSONL unmodified. Native-relocate is viable; opt-in
`--resume-mode native-relocate` wiring deferred (touch points recorded in the plan). Candidate for `impl_notes.md` after
review: the Claude project-dir encoding maps `/` `.` `_` → `-` (case/`-`/digits preserved).

**Verification**: host repro `[PASS]` (Claude 2.1.158);
`./scripts/test-integration.sh tests/integration/docker/test_native_relocate_contract.py` PASSED (23.6s); 8 relocate
unit + 3 encode-underscore regression + 880 session unit green; ruff/mypy/pyright + shellcheck clean; `make pre-commit`
clean.

### Phase 2: Optional Audit Proxy (Runtime Abstraction)

**Goal**: Make a Forge proxy an opt-in, user-controlled chokepoint that can observe and (optionally) control the wire
between Claude Code and the model provider, with redacted audit logs — without changing any existing proxy (all new
config defaults to inert).

**Key changes** (sliced OBSERVE-before-MUTATE; two orthogonal axes kept distinct: `wire_shape` and `intercept.mode`):

- **Config** (`config/schema.py`, `loader.py`): `wire_shape` (`openai_translated` | `anthropic_passthrough`) +
  `intercept` + `audit` on `ProxyInstanceConfig`/runtime `ProxyConfig`, strict unknown-key rejection, propagated to the
  running server; `override` requires `anthropic_passthrough` (validated at load).
- **Passthrough wire** (`proxy/passthrough.py`, server middleware): non-converting Anthropic forward path that preserves
  `thinking`/`redacted_thinking` byte-for-byte; intercepted in middleware before `MessagesRequest` validation; shipped
  `anthropic-passthrough` template.
- **Audit** (`proxy/audit_logger.py`, `utils` redaction): redact-before-persist JSONL records (`request`/`drift`/
  `mutation`), system/tool hashing, drift detection, retention pruning at startup; `forge proxy audit show|diff` +
  `%proxy audit`.
- **Override** (`proxy/intercept.py`): cache-aware `system_prompt_augment`, `system_prompt_guards` (warn/block/strip),
  reasoning-effort pin reusing `tier_overrides`; mutation-safety fingerprint tripwire (never rewrites historical
  messages; fails closed).
- **Sidecar** (`sidecar/container.py`, `docker/entrypoint.sh`, `Dockerfile.sidecar`, `scripts/test-integration.sh`):
  `FORGE_PROXY_ID` + narrow read-only-config / writable audit+costs mounts so records, costs, and caps persist on the
  host; sidecar-aware startup-validation skip; drift-state redirect; `--user` arbitrary-uid support (`HOME=/root` +
  `chmod 0777 /root`). Fixed two latent entrypoint bugs the E2E surfaced (bare `python` had no forge; `--log-level` is
  not a server flag) — the sidecar proxy could never start before.
- **Docs**: `design.md` §7.x + §3.4/§3.7/§4.0; `design_appendix.md` §A.11 (config) + §A.12 (audit log schema);
  `end-user/proxy.md` audit/intercept section + `audit_full_body` privacy warning.

**Verification**: focused unit suites (intercept, audit_logger, passthrough server-path, config schema/loader,
container, proxy_startup) + `tests/integration/sidecar/test_audit_plumbing.py` passing via the canonical runner under
forced `--user`; no-plaintext-secret regression; broad proxy/sidecar/config/session sweeps; ruff/mypy/pyright + full
`make pre-commit` clean. Deferred (debt): real-upstream `@pytest.mark.slow` passthrough signature-replay e2e (needs
`ANTHROPIC_API_KEY`); streamed full-body capture (request body + response metadata only today).

## 2026-05-31

### Phase 1: Schema-backed curated transfer + `forge transfer` CLI (Runtime Abstraction)

**Goal**: Make curated transfer a schema-backed, user-reviewable substrate and reposition `ai-curated` as the primary
cross-boundary transfer path, with a top-level `forge transfer` CLI to inspect and reshape it.

**Key changes**:

- **Transfer schema** (`src/forge/session/transfer.py`): `_build_ai_curated_output()` emits canonical sections 1-7
  (Lineage, Goal/Current Task, Decisions, Current State, Relevant Files, Open Questions, Runtime Hints); section 8 (User
  Notes) is the overlay merged at launch. `_build_frontmatter()` stamps `schema_version: 1`, reserves `target_runtime`
  for Phase 5, and marks `schema: "full"` only for a successful ai-curated body (`minimal|structured|full` →
  `compatibility-fallback`). `_validate_decision_citations()` drops citations outside the turn range the model saw, so
  `schema: full` never overstates evidence.
- **Three-file artifact model**: `generated.md` (regeneratable parent cache), `children/<child>.md` (frozen AI
  snapshot), `children/<child>.notes.md` (user overlay). `ensure_child` never overwrites an existing child; GC ties a
  notes file's liveness to its snapshot.
- **CLI** (`cli/transfer.py`, `core/ops/transfer.py`): new top-level `forge transfer show|regenerate|edit|diff`, pairing
  with `forge memory`. `regenerate` rewrites only the parent cache; `edit` targets the notes overlay; `show`/`diff` take
  `--child`.
- **Docs**: design.md §3.9 reframes curated transfer as the primary cross-boundary substrate (not a lossy fallback);
  appendix §M documents the frontmatter + 8-section contract + overlay; end-user/session.md updated.

**Verification**: 113 transfer tests pass (`test_transfer.py`, `test_transfer_cli.py`, `test_prev_sessions.py`,
regression `test_bug_transfer_notes_not_gc_orphaned.py`); shipped as commit `2b70c29`.

**Phase 1 closeout (2026-05-31, docs-only)**: `ctx` posture recorded in `design_appendix.md` §M.4 -- the transfer schema
is Forge-owned and canonical; `ctx` is prior art and inspiration only, never a dependency, and no interop is planned.
Both default-behavior decisions resolved as keep-current: `--review` stays opt-in (a plain `--fresh` resume never blocks
on `$EDITOR`) and `structured` stays the CLI default (`ai-curated` opt-in via `--strategy`, keeping the resume hot path
deterministic and LLM-free). Schema confirmed stable for Phase 5 (`target_runtime` reserved). All Phase 1 boxes ticked;
card stays in `doing/` for Phases 2-6. No code or tests changed.

## 2026-05-29

### fix: tombstone `forge handoff run` (memory_substrate follow-up)

**Goal**: Make the removed runner path fail with an actionable message, matching the report path.

**Key changes**: The memory_substrate closeout tombstoned `forge session handoff show` but left `forge handoff run` as a
generic Click "No such command 'handoff'" dead-end. Added a hidden top-level `handoff` tombstone group
(`cli/memory_writer.py`, registered in `main.py`) whose `run` command errors with "Use: forge memory-writer run",
mirroring `session_handoff.py`.

**Verification**: `forge handoff run` (bare and with old flags) exits non-zero naming `forge memory-writer run`, not
Click's "No such option"; regression `TestOldHandoffRunTombstone` in `test_memory_writer_cli.py` (2 tests).

### memory_substrate: resolve "handoff" naming → memory writer + transfer

**Goal**: Split the overloaded "handoff" term into two clear concepts — the **memory writer** (Stop-time project-doc
curation) and **transfer** (resume/fork context assembly) — across code, CLI, config, durable state, docs, and skills.

**Key changes**:

- **Session layer**: `git mv handoff_agent.py → memory_writer.py`, `handoff.py → transfer.py`; renamed
  `HandoffConfig→MemoryWriterConfig`, `HandoffResult→TransferResult`, `process_handoff→assemble_transfer_context`,
  `run_handoff_agent→run_memory_writer`, `review_dir→memory_report_dir`.
- **CLI**: `forge session handoff show → forge memory report show` (new `cli/memory_report.py`);
  `forge handoff run → forge memory-writer run`; old paths are actionable tombstones.
- **Durable state**: `--resume-mode handoff → transfer` with `confirmed.derivation.resume_mode` accept-and-tolerate
  (legacy `"handoff"`/`None` read as transfer); config key `handoff_timeout → memory_writer_timeout` (stale-key
  warn-and-ignore).
- **Docs/skills**: `docs/end-user/handoff.md → memory.md`; QA `16-handoff.md → 16-memory.md`; 3-layer memory taxonomy
  table added to design.md §5.6; design/appendix/diagrams/skills synced.
- **Internal naming sweep (closeout)**: drove residual `handoff` in `src/forge/` from 207 (Phase 0) to 39, all
  intentional KEEPs. Renamed `handoff_result→transfer_result` (manager.py, session_lifecycle.py); the GC
  transfer-context subsystem (`_detect_orphan_handoff_files`, `_build_handoff_context_reference_set`,
  `_clean_handoff_files` → `…transfer…`, incl. the **user-visible** `forge clean` category key
  `handoff_files→transfer_files`); the cost-tracking verb `handoff→memory-writer`; user-facing resume messages/help; and
  ~12 `core/reactive`/proxy docstrings ("handoff agent"→"memory writer"). Coupled tests updated (`test_gc.py` ×2,
  `test_session_resume_review.py`).

**Intentional KEEPs** (durable state / routing / fixtures): work-queue marker `kind="handoff"`,
`enqueue_handoff_marker()`, `marker_id="handoff-<id>"`, the `.forge/artifacts/<session>/handoff/` artifact path, the
`queued_handoff` Stop-hook field, the `forge session handoff` tombstone, the legacy-value migration messages, and the
generic-English passport "project-state" wording.

**Verification**: full unit+regression green (4902 passed); the 2 failures
(`test_session_resume_review::test_editor_nonzero_aborts_launch`,
`test_removal_patching_system::test_forge_info_no_traceback`) reproduce identically on `origin/main` (f8c07d9) —
pre-existing, unrelated. `test_handoff_integration.py` (10) green — renamed runtime + `forge memory report show`
end-to-end. `make pre-commit` clean. Shipped as PR #8; unrelated gemini-3.5-flash catalog work split to PR #9.

## 2026-05-28

### Add Claude Opus 4.8 (retain 4.6 + 4.7)

**Goal**: Add Opus 4.8 (released 2026-05-28) as the opt-in Anthropic alternative without shrinking the registry. The
catalog and pricing keep Opus 4.6 (default) and Opus 4.7 (prior opt-in) as distinct models; 4.8 takes over 4.7's opt-in
*role* in selections (review, templates, docs), not its place in the registry.

**Key changes**:

- Catalog + pricing: **added** `claude-opus-4-8` (entry, 5 aliases, `friendly_name`) alongside the retained
  `claude-opus-4-7` and `claude-opus-4-6` — three distinct registry models (`intelligence_score` 98 / 99 / 100).
  Researched 4.8 specs ($5/$25/$0.50, 1M context, 128K output, adaptive-only, fixed temperature, `xhigh`);
  `pricing.yaml` `updated_at` bumped. The `opus`/`claude-opus` defaults and proxy tier mappings stay on 4.6 — 4.8 is
  opt-in (`--model claude-opus-4-8`), taking over 4.7's role.
- Review workflow: `claude-opus-4.8` ModelSpec + `_CLAUDE_48_BOUNDED_REVIEW_PROMPT`; three Anthropic proxy templates'
  `model_alternatives.opus` repointed.
- Review guide `references/claude-4.7.md` → `claude-4.8.md`, rewritten against the live 4.8 docs (release date, from-4.7
  migration framing, dropped "new xhigh"; added mid-conversation system messages, fast mode, 1,024-token cache minimum,
  refusal `stop_details`; kept inherited constraints and 4.6 comparisons).
- Did NOT add a `max` effort tier (pre-existing cross-model Anthropic effort Forge omits; would fail `_EFFORT_RANK`
  validation). Left `glm-4.7-flash`, Sonnet/Haiku versions, and `### 4.7` QA section headings untouched.
- Tests moved in lockstep (catalog/pricing/review/proxy/session/config/supervisor); cosmetic test renames; negative
  tests now `claude-opus-4.8.1`; new `claude-opus-4-8` pricing test.

**Verification**: full unit suite green (4649 passed; the lone failure is a pre-existing COLUMNS-width-dependent test in
`test_session_resume_review.py`, reproduced identically on `origin/main`); integration tests pass; `make pre-commit`
clean; built-wheel clean-install smoke confirms catalog/pricing/guide load via `importlib.resources` and `opus` still
resolves to `claude-opus-4-6`.

**Additive correction (2026-05-29)**: the initial change renamed `claude-opus-4-7` → `claude-opus-4-8`, dropping 4.7
from the registry. Re-added `claude-opus-4-7` as a distinct catalog model (`intelligence_score` 99, `friendly_name`
`Claude Opus 4.7`) with its 5 aliases (pricing unchanged), so catalog/pricing stay additive; 4.8 keeps 4.7's opt-in role
in review/templates/docs. Verified: model-catalog unit suite green (128 tests); 4.6/4.7/4.8 resolve with
`intelligence_score` 98/99/100 and `opus` still defaulting to 4.6.

### Simplify memory strategies: 7 to 4, shadow mode orthogonal

**Goal**: Reduce strategy enum from 7 to 4 by removing redundant entries, make shadow mode orthogonal to strategy, and
rename `--as` to `--strategy`.

**Key changes**:

- Removed `debugging`, `patterns` strategies (topic scoping via passport `intent`/`captures` fields instead).
- Removed `suggested` strategy (shadow mode is now orthogonal -- `--propose` works with any strategy).
- Renamed `--as` to `--strategy`; `--as` is a hidden tombstone with rename guidance.
- Shadow path prefix changed from `suggested_*` to `shadow_*` in `derive_shadow_path()`.
- Shadow framing in `build_multi_doc_prompt()` now includes proposal-format instructions (checkboxes, rationale,
  self-prune) that were previously in the `suggested` strategy instruction.
- Stale passports with removed strategies rejected with actionable hints (`_REMOVED_STRATEGIES`).
- `_validate_designated_docs()` empty-shadows guard applies unconditionally; `suggested` coupling removed.
- `--propose` preserves existing passport strategy unless `--strategy` is explicitly passed.

**Verification**: full unit suite passes; `make pre-commit` clean.

## 2026-05-26

### Phase 1 / Slices 4-7: Simplify memory to passports + session activation

**Goal**: Reduce the memory system from three layers (passports, checkout activation, session participation) to two
primitives: passports select docs, session activation decides whether the memory writer runs. Research-preview clean
break.

**Key changes**:

- Removed `.forge/memory.yaml` (checkout-scoped activation), `forge memory extra add`, `forge memory untrack`,
  `DesignatedDoc.origin`, `MemoryIntent.designated_docs` (field removed from manifest schema), session-scoped doc lists,
  `--inherit-extras`/`--no-inherit-extras`, `--inherit-memory` tombstones, `--no-copy-memory-activation`,
  `ProjectMemoryConfig`, `memory_activation()` three-tier resolver, `copy_memory_activation()`.
- Added `forge memory disable`, `--memory on|off` on `fork`/`resume --fresh`/`start`.
- `forge memory enable`/`disable` are session-scoped only (resolve `$FORGE_SESSION` or `--session`).
- `forge memory list` is a sessionless passport scan (no writer filtering, no session needed).
- Stop hook and handoff runner check `effective.memory.auto_update.enabled` directly (incognito guard preserved).
- Handoff runner uses `scan_passported_docs()` as sole doc source (no doc fusion).
- `apply_memory_inheritance()` constructs a fresh `MemoryIntent(auto_update=...)` from parent; `--memory on` reuses
  parent config, `--memory off` writes explicit `HandoffConfig(enabled=False)`, `None` inherits.
- `strip_preview_memory_doc_lists()` sanitizer warns-and-strips stale `designated_docs` from old manifests per
  coding-standards section 5.
- Stale `.forge/memory.yaml` is now ignored; safe to delete.

**Verification**: 4645 unit tests pass; `make pre-commit` clean.

### Phase 1 / Slice 3: Fork activation copy + retire `--inherit-memory`

**Goal**: Make memory activation follow Forge-created worktrees by default and replace the multi-mode `--inherit-memory`
flag with a narrower extras-only inheritance model.

**Key changes**:

- `fork --worktree` copies `.forge/memory.yaml` from parent to child checkout by default (never overwrites existing;
  `--no-copy-memory-activation` opt-out; corrupt source warns and skips). `--into` forks skip the copy.
- Replaced `--inherit-memory all|none|shadowed` with `--inherit-extras` / `--no-inherit-extras` on both `fork` and
  `resume --fresh`. Default inherits `origin="extra"` entries only; project-discovered docs are not affected.
- Simplified `memory_inheritance.py`: removed `InheritMemoryMode` enum and multi-mode branching; extras-only filter.
- `--inherit-memory` is now a hidden tombstone with per-value replacement guidance.
- Docs: updated `design.md §5.6.4`, `docs/end-user/handoff.md` fork/resume memory sections.

**Verification**: `test_memory_inheritance.py` (25 tests) + `test_project_memory.py::TestCopyMemoryActivation` (5 tests)
pass; full `tests/src -m "not integration"` green (4718 passed).

### CLI command-shape cleanup: groups orient, leaves act

**Goal**: Make confusing bare CLI invocations follow one documented rule before PR: non-leaf command groups print help,
while leaf commands perform a sensible default action.

**Key changes**:

- Documented the command-shape invariant in `docs/developer/coding-standards.md` and `docs/design.md`: groups orient,
  leaves act, removed group-level shortcuts may remain only as non-executing tombstones.
- `forge config` now prints help; `forge config show` is the explicit command that displays and auto-creates
  `~/.forge/config.yaml`. Updated `docs/end-user/config.md` and design appendix references.
- Replaced the group-level `forge search -q/--query` action with `forge search query <terms>`. The old `-q` path now
  exits with a replacement tip instead of executing old behavior. Updated end-user docs, QA/walkthrough checklists, and
  tests/integration references.
- `forge proxy metrics` with multiple registered proxies now behaves like an acting leaf and shows all metrics
  (equivalent to `--all`) instead of erroring. `--json` follows the same implicit-all behavior.

**Verification**:
`uv run pytest tests/src/cli/test_config_cli.py tests/src/cli/test_proxy_commands.py tests/src/cli/test_search.py -q`
(146 passed); `make pre-commit`; smoke-checked `forge config`, `forge config -h`, `forge search -h`, and the
`forge search -q` tombstone.

## 2026-05-25

### Phase 1 / Slice 2: Sessionless `track` + participation-only `extra add`

**Goal**: Split the welded lifetimes in `forge memory track` so each verb owns one lifetime — `track` authors a
project-lifetime passport (sessionless), `extra add` records session-only participation (no passport), and `enable` owns
activation.

**Key changes**:

- `forge memory track` is now passport-only and sessionless: resolves `forge_root` from cwd, never writes
  `memory.designated_docs`, never auto-enables, ignores `$FORGE_SESSION`. It is a no-op (exit 0) on an
  already-passported doc with no flags, warns when the doc is outside the scan roots, and degrades (warn, still authors)
  on a corrupt `.forge/memory.yaml`. `--session`/`-s` is a hidden tombstone that errors and names `extra add`.
- New `forge memory extra add <path> --as <strategy>`: session-scoped participation with `origin="extra"`, echoes the
  resolved session, rejects `--as suggested` only when the target has no passport, and warns on writer-veto (case B) or
  redundant-under-root (case A).
- `DesignatedDoc.origin: Literal["extra"] | None` added, persisted, and inherited; `_check_legacy_docs` skips extras and
  names both new verbs; `list`/`status` expose `origin`; `untrack` warns when a passport remains under the roots.
- Shadow workflow no longer depends on the manifest: new `scan_shadow_passports()` and
  `check_shadow_path_collision_in_roots()` in `project_memory.py`; `collect_shadow_entries()` unions project-origin
  shadows (scope-correct roots) with session entries, de-duped by `(forge_root, shadow_path)`. Removed the now-dead
  manifest-based `check_shadow_path_collision`.
- Docs: `design.md` §4.0 table + new §5.6.7 verb taxonomy; `design_appendix.md §G.2`; board README; end-user
  `handoff.md`; QA and walkthrough skill checklists.

**Verification**: `tests/src/cli/test_memory.py` and
`tests/src/session/{test_handoff_agent,test_memory_inheritance,test_project_memory,test_shadow_curation}.py` pass; full
`tests/src -m "not integration"` green (4689 passed); `mypy` clean on touched modules.

### CLI tip consistency: shared recovery-output helpers

**Goal**: Make equivalent CLI failures tip identically — the reported bug was `forge session start <existing>` showing a
recovery tip while `forge session fork ... --name <existing>` showed none.

**Key changes**:

- New leaf module `src/forge/cli/output.py`: `print_tip`, `print_error`, `print_error_with_tip`, and
  `handle_session_error` (a type→tip dispatch holding only context-free recoveries — currently just
  `SessionExistsError`). Imports only `rich` + `forge.session.exceptions`; never imported by `core/proxy/review`.
- Renamed `_handle_error` → `handle_session_error` across `session.py` and its four importers (`session_lifecycle.py`,
  `session_fork.py`, `session_manage.py`, `session_handoff.py`); `session.py` re-exports `console` +
  `handle_session_error` from `output.py`.
- §1 fix: `session fork` onto an existing name now routes through `handle_session_error`, emitting a
  different-name/delete tip (no "resume" — meaningless for a fork-name collision). `start` keeps its richer
  resume/delete wording as a call-site tip.
- Added recovery tips to `session resume` (not-found → start), proxy `edit/set/validate` (→ create) and `delete/metrics`
  (→ list), and backend `start/delete` (→ create).
- **BREAKING**: `forge backend create <existing>` now prints red `Error:` + tip and exits 1 (was yellow + exit 0),
  matching the session/proxy "already exists" shape. Reset path: run the suggested `forge backend start` instead.
- Migrated the remaining Rich `console.print` `Tip:` sites in `src/forge/cli/**` onto the helpers and added an invariant
  test that allows `[dim]Tip:` only in `output.py`.
- Documented the convention in `CLAUDE.md` (UX Guidelines → Console Output Formatting): use the helpers for CLI Rich
  recovery output, "Run '<command>'" vs "Use --flag", single quotes not backticks.

**Verification**: 291 targeted CLI + regression tests pass (incl. `test_output.py`,
`test_bug_fork_session_exists_tip.py`); `make pre-commit` clean on touched files (mypy + pyright pass repo-wide).

**Out of scope**: Plain-text recovery hints inside `core/proxy/review` exception messages and `click.echo`/hook-JSON
tips remain strings by design (layering).

### Auto-start proxies from templates for `--proxy` and `--supervisor-proxy`

**Goal**: Stop `--supervisor-proxy <template>` (and `--proxy <template>`) from hard-failing with "not found in registry"
when the named template exists but no proxy is running yet; bring the proxy up instead.

**Key changes**:

- Added `ensure_proxy()` (`src/forge/proxy/proxy_orchestrator.py`): resolves a proxy by id/template and starts one from
  a matching config template when no *live* proxy is available (reuse/adopt/spawn via `start_proxy`). Liveness-aware — a
  template entry recorded `healthy` but unreachable (e.g. after a reboot) is marked `unhealthy` before a replacement is
  registered, so follow-up template lookups do not become ambiguous. Re-raises `AmbiguousProxyError` (multiple active —
  pick one) and `ProxyNotFoundError` (no proxy and no template).
- Renamed `preflight_supervisor_proxy` -> `ensure_supervisor_proxy`; it auto-starts via `ensure_proxy`, returns
  `(proxy_id, started)`, and raises actionable `ValueError`s (no-template hint to `forge proxy template list`,
  ambiguous, start-failure). Covers `--supervisor-proxy` on `session fork`, `session start`, and `policy supervise`.
- Wired the launch routers `_resolve_routing_from_cli` (session start/resume/fork `--proxy`) and `forge claude --proxy`
  onto `ensure_proxy`; all five `--proxy`/`--supervisor-proxy` paths print a dim "Started proxy X from template Y"
  notice when they spin one up.
- `forge policy supervise` now validates the target session *before* ensuring the proxy, so a bad target can't orphan a
  freshly started proxy.
- A registered-but-stopped (or stale-dead) proxy for a known template now auto-starts (was: "none are active" error).
  Workflow `--proxy via` is intentionally excluded (different routing layer + one-shot lifecycle).
- **Behavior break** (research preview): naming a template with no live proxy used to error; it now starts one. Unknown
  names (no proxy, no template) still fail, now with a `forge proxy template list` hint. Updated `docs/design.md`
  §3.6.3, `docs/end-user/proxy.md`, and `docs/end-user/session.md`.

**Verification**: regression `test_bug_supervisor_proxy_autostart.py` + `test_bug_stale_healthy_proxy_not_restarted.py`;
`TestEnsureProxy` (8 cases) in `test_proxy_orchestrator.py`; updated supervisor/claude/session CLI tests; 348 related
proxy/policy/session/regression tests pass; `ruff check` on touched Python files and `git diff --check` clean.

### Protect live sessions from deletion

**Goal**: Stop `forge session delete` from silently discarding a session's Forge state while it is still running in
Claude Code, and stop a session deleted mid-run from crashing the launcher with a traceback.

**Key changes**:

- `forge session delete <name>` now refuses to delete a session with a live launch (exit 1) unless `--force`; `--yes` no
  longer overrides this guard. `forge session delete --all` skips live sessions and deletes the rest (`--force` includes
  them). Liveness uses the self-healing active registry, so a crashed/exited launcher still deletes without `--force`.
- The post-launch backfill (`_infer_launch_confirmation`) tolerates a manifest deleted mid-run: an `exists()` preflight
  skips the locked write (so the lock layer cannot resurrect the session as a lock-only directory), and a
  `SessionFileNotFoundError` guard covers the narrow delete race. The launcher prints a "was deleted during this run"
  note instead of a traceback.
- **Behavior break** (research preview): deleting an active session previously warned and proceeded; it now blocks
  without `--force`. Updated `docs/end-user/session.md`.

**Verification**: `tests/regression/test_bug_delete_live_session.py` (preflight + race branch) and the expanded
`tests/src/cli/test_session_commands.py` delete matrix (single/`--all` x force/no-force x tracked/orphan);
`make pre-commit` clean.

## 2026-05-24

### Phase 1 / Slice 1: Project-Scoped Memory Activation

**Goal**: Activate the handoff agent once per checkout via `.forge/memory.yaml` instead of per-session
`forge memory enable`, through a single resolver consulted at both activation gates.

**Key changes**:

- New `src/forge/session/project_memory.py`: versioned `ProjectMemoryConfig` (strict `dacite` reader modeled on
  `SessionStore`, raises `ProjectMemoryConfigError`); the `memory_activation()` three-tier resolver (project baseline /
  whole-block legacy intent overlay only when `enabled is True` / sparse per-leaf overrides, the only tier that can
  disable); and `scan_passported_docs()` (root-contained via `_reject_unsafe_path`, which rejects absolute, escaping,
  and `..`-traversal roots and shadow paths; deterministic; shadow-materializing; capped at 50 after filtering).
- Both gates call the resolver: the Stop-hook enqueue site (`cli/hooks/commands.py`) and the detached runner
  (`cli/handoff.py`). The runner unions scanned passports with session `designated_docs` (session wins, de-duped by
  passport source + write path) while preserving the existing proxy-routing chain.
- `forge memory enable` is now dual-path: bare writes project `.forge/memory.yaml`; `--session X` keeps the sparse
  manifest override.
- Design docs: added `design.md §5.6.6` and `design_appendix.md §G.5`.

**Behavior change**: bare `forge memory enable` no longer targets the ambient `$FORGE_SESSION`; it enables the whole
checkout (prints a `Tip:` when `$FORGE_SESSION` is set). Use `--session <name>` for the per-session override. Additive,
no schema break; incognito sessions never activate.

**Verification**: `tests/src/session/test_project_memory.py` (38: config I/O + resolver + scanner, incl. unsafe-root and
unsafe-shadow-path rejection), `test_handoff.py` (+5 run_cmd; 2 legacy proxy tests still green),
`test_artifact_hooks.py::TestStopHook` (+3), `test_memory.py` (`TestMemoryEnableProject` +6; `TestMemoryEnable` pinned
to `--session`). Full `tests/src/session` + `tests/src/cli` unit suites: 2193 passed. mypy clean on touched files;
`make pre-commit` clean.

### Memory Enhancement Completion, Design Doc Sync, and Proposal Lifecycle

**Goal**: Close out the memory enhancement proposal (PR #1), update design docs to reflect shipped passport model,
establish the proposal lifecycle pattern, and prepare for runtime-abstraction.

**Key changes**:

- Archived final memory enhancement card and checklist snapshots to `docs/board/done/memory_enhancement/`.
- Updated `docs/design.md` section 5.6: replaced old `DesignatedDoc` model with passport-authoritative ownership, added
  sections for passport frontmatter (5.6.2), shadow curation (5.6.3), and memory inheritance (5.6.4). Added
  `forge memory shadows review` to command table.
- Updated `docs/design_appendix.md` section G and `docs/end-user/handoff.md`: replaced old manifest-based examples with
  passport frontmatter and `forge memory` setup guidance.
- Pruned `impl_notes.md`: replaced Phase 0 pre-migration system map (100+ lines) with compact shipped-architecture
  summary preserving durable decisions.
- Established card lifecycle in `docs/developer/documentation-guidelines.md`: propose -> todo -> doing -> done (with
  per-phase design-doc updates). Design docs are normative (track shipped code), not aspirational.
- Updated `docs/board/README.md`: board lanes, curation workflow, design-doc verification step in lifecycle.
- Installed runtime-abstraction checklist under `docs/board/todo/runtime_abstraction/checklist.md` with per-phase
  design-doc update rule.

**Verification**: archived card+checklist at `docs/board/done/memory_enhancement/`; design.md sections 5.6.2-5 and
`docs/end-user/handoff.md` reflect passport model; active checklist tracks runtime-abstraction phases 0-6.

## 2026-05-23

### Phase 5: Curated Shadow Review (Memory Enhancement)

**Goal**: Add LLM-powered curation of shadow proposals so users can synthesize accumulated suggestions against the
official doc, with source-cited output and persistent reports.

**Key changes**:

- Created `src/forge/session/shadow_curation.py` with `ShadowEntry` dataclass, `collect_shadow_entries()` (moved from
  CLI layer), `build_curation_prompt()`, `_doc_slug()` with hash suffix for collision resistance,
  `persist_curation_report()` with `curation-` prefix, `report_glob_pattern()`, and `run_shadow_curation()`
  orchestrator.
- Added `forge memory shadows review` command with `--curate`, `--show-latest`, `--for`, `--scope`, `--json` flags.
  Mutual exclusivity, session ownership, and scope constraints enforced. Bare `review --for` shows raw content with
  hint.
- Refactored `_collect_shadow_entries()` in `memory.py` to delegate to session-layer `collect_shadow_entries()`, fixing
  a layering inversion (CLI code was owning discovery logic). `shadows list` and `shadows show` now use `ShadowEntry`
  attribute access instead of dict keys.
- Routing resolved in CLI via `resolve_handoff_base_url()`, passes `base_url` + `direct` into core function. Cost
  tracked via `track_verb_cost("curation", ...)`.

**Verification**: 4,595 unit tests pass (17 new `test_shadow_curation.py` + 11 new `TestShadowsReview` in
`test_memory.py`). All existing shadow tests pass after refactor. mypy and ruff clean.

### Phase 2: Top-Level CLI (Memory Enhancement)

**Goal**: Replace `forge session memory` with a new top-level `forge memory` command group, wire passport infrastructure
from Phase 1 into CLI commands, add legacy config detection, and complete Phase 1 deferred tasks 3-4.

**Key changes**:

- Created `src/forge/cli/memory.py` with 5 commands: `enable`, `track`, `untrack`, `list`, `status`. Registered as
  top-level `forge memory` in `main.py` with `mem` alias.
- `track` synthesizes passports for docs without one (`--as` required), rewrites passports when flags override existing
  values (passport-authoritative design), rejects shadow-only passports (Phase 3), and auto-enables memory on first
  tracked doc. Uses leaf-key overrides (`memory.auto_update.enabled`, `memory.auto_update.mode`) to preserve existing
  auto-update fields like `min_turns`.
- `status` aggregates across sessions using `list_sessions()` with scope filtering. JSON output includes `forge_root`
  and `session` for disambiguation. Inaccessible manifests skipped gracefully.
- Replaced `session_memory.py` with hidden tombstone group: old commands error with replacement guidance. Registration
  in `session.py:_register_subgroups()` unchanged.
- Legacy detection via `_check_legacy_docs()`: per-doc counting of missing vs malformed passports using
  `resolve_passport_source(doc)`. Warning says "manifest-fallback behavior" (accurate for Phase 1 fallback).
- Updated `design.md` command table: removed old `forge session memory` entries, added `forge memory` section.
- Completed Phase 1 tasks 3 (passport-required-at-rest: no passport + no `--as` fails) and 4 (flag-vs-passport
  conflicts: `--as` rewrites passport, warnings printed, round-trip verified).

**Verification**: 4,471 unit tests pass (38 new `test_memory.py` + 5 tombstone tests replacing 13 old tests). All
pre-commit hooks clean (ruff, black, mypy, mdformat).

## 2026-05-22

### Phase 1: Passport Model (Memory Enhancement)

**Goal**: Build passport model infrastructure (shared strategy enum, YAML frontmatter parsing/serialization, validation,
handoff agent integration) so Phase 2 can wire it into the `forge memory` CLI.

**Key changes**:

- Created `src/forge/session/passport.py` with `MemoryStrategy` enum, `Passport`/`PassportUpdate`/`ResolvedDocSpec`
  dataclasses, frontmatter parsing (`extract_frontmatter`, `parse_passport`, `read_passport`), atomic serialization
  (`write_passport`), synthesis (`synthesize_passport`), writer validation (`validate_writer_spec`,
  `check_writer_access`), and flag-vs-passport conflict handling (`resolve_with_overrides`).
- Added `PassportError(field_path, reason, hint)` to `forge.session.exceptions`, subclassing `ForgeSessionError`.
- Refactored `handoff_agent.py`: replaced inline `DOC_STRATEGIES` with import from `passport.STRATEGY_INSTRUCTIONS`.
  `build_multi_doc_prompt()` now takes `list[ResolvedDocSpec]` (no file I/O). `run_handoff_agent()` reads passports,
  filters by writer authorization, resolves effective doc specs, and includes full passport contract (intent, captures,
  excludes, approval, compact_when) in the prompt.
- Updated `session_memory.py` to import `VALID_STRATEGY_NAMES` from `passport.py`.
- Tasks 3 (passport-required-at-rest) and 4 (flag-vs-passport conflicts) have infrastructure built but CLI enforcement
  deferred to Phase 2.

**Verification**: 4,441 unit tests pass. Focused passport/handoff/session-memory suite passes 191 tests. `make lint` and
`make type-check` clean. Passport-less docs continue working identically.

### Phase 0: Branch and Baseline (Memory Enhancement)

**Goal**: Map the existing `forge session memory` surface, stop-time update path, handoff report surface, old UX
references, and helper reuse decisions before any code changes.

**Key changes**:

- Mapped CLI surface (session_memory.py, 3 commands, 13 tests), data model (DesignatedDoc, MemoryIntent, HandoffConfig),
  and the read-effective/write-override persistence split.
- Mapped the full stop-time chain: stop hook, work queue, fire-and-forget CLI startup handler, CLI runner, handoff agent
  core. Documented that detached failures are not retried by the queue.
- Mapped the handoff report/show surface (session_handoff.py) separately from the update agent.
- Inventoried 15 entries (8 UPDATE, 2 REMOVE, 5 KEEP) across docs, tests, and skills for old `forge session memory` and
  old-model `designated_docs[]` references.
- Decided 8 helpers + 2 patterns reuse privately behind new `forge memory` CLI; VALID_STRATEGIES moves to shared
  location in Phase 1; old commands become a non-executing tombstone diagnostic path.
- Recorded all maps and decisions in `docs/board/impl_notes.md`.

**Verification**: All six Phase 0 checklist tasks checked with verification notes.

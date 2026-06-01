# Runtime Abstraction Checklist

Manual multi-session plan for executing [`card.md`](./card.md).

This card is in active execution under `doing/`. Move the whole `runtime_abstraction/` directory to `docs/board/done/`
after closeout.

## Maintenance

- Update this file during implementation sessions and once before ending a session.
- Keep tasks high-level, with concrete assertions that prove completion.
- Tick a task only when the assertion is satisfied and verification is recorded.
- Add short blocker notes inline under the relevant phase.
- Move completed-session details to `docs/board/change_log.md`; keep only active plan state here.
- Promote durable lessons to `docs/board/impl_notes.md` after human review.
- Update design docs per-phase as code ships (design docs are normative, not aspirational).
- Move the card directory to `docs/board/done/<slug>/` after the card is fully executed.
- Check size periodically while a card is active:

```bash
wc -l docs/board/doing/runtime_abstraction/checklist.md
./scripts/count-tokens.py --model <agent-model> docs/board/doing/runtime_abstraction/checklist.md
```

## Current Focus

**Phase 1 complete (2026-05-31).** Schema-backed curated transfer, the `children/<child>.notes.md` overlay, and the
top-level `forge transfer show|regenerate|edit|diff` CLI shipped in commit `2b70c29`; `docs/design.md` §3.9 and
`docs/design_appendix.md` §M reflect it. The `ctx` posture is recorded (prior art and inspiration only, never a
dependency -- §M.4), and both default-behavior decisions are resolved docs-only: keep `--review` opt-in, keep
`structured` the CLI default (`ai-curated` opt-in via `--strategy`). All Phase 1 boxes are ticked.

Next: Phase 2 (optional audit proxy) and Phase 3 (native-relocate spike) are independent and can ship in either order
before the Phase 4 runtime-abstraction core. The card stays in `doing/` until Phases 2-6 land.

**Deferred prerequisite (memory_substrate reconciliation) -- RESOLVED 2026-05-30:**

- [x] Reconcile this card's "curated handoff" vocabulary with the shipped **transfer** taxonomy, and retarget the
  proposed `forge session handoff regenerate|edit|diff` surface before implementing the schema.
  - Resolution: `card.md` now uses **curated transfer** throughout (the `ai-curated` transfer strategy, repositioned as
    the primary cross-runtime substrate), with a vocabulary note in the "Curated Transfer as Cross-Runtime Substrate"
    section tying it to `docs/design.md` §3.9 (transfer) and §5.6 (memory writer). The doc-updater stays the **memory
    writer**; resume/fork context stays **transfer**.
  - Namespace: the retargeted verbs live under a new **top-level `forge transfer` group**
    (`forge transfer show|regenerate|edit|diff`), chosen over `forge session transfer` on user-mental-model grounds so
    it pairs with `forge memory`. `forge session resume --fresh --review` stays the ergonomic entry point, not a second
    namespace. See the resolved namespace task in Phase 1 and the Open Decisions.
  - Verification: `rg "handoff" card.md` returns only intentional refs (the quoted historical term in the vocabulary
    note + `forge session handoff` tombstone mentions); `rg "forge session transfer" card.md` returns nothing.

## Phase 0 - Baseline Confirmation

- [x] Confirm PR #8 cost-control and routing foundation state.
  - Verification: Phase 0 foundations map to shipped code: subprocess routing in `src/forge/core/reactive/routing.py`
    and `src/forge/review/routing.py`; proxy request cost logs/caps in `src/forge/proxy/cost_logger.py`,
    `src/forge/proxy/server.py`, and `src/forge/config/schema.py`; session subprocess proxy inheritance in
    `tests/src/session/test_subprocess_proxy_inheritance.py`.
- [x] Record Phase 0 gaps before starting Phase 1 work.
  - Verification: foundation is confirmed, with future gaps carried forward below.

Phase 0 gaps carried forward:

- Team supervisor verb-cost snapshots remain future for `src/forge/policy/team/handlers.py`; track under Phase 4 usage
  ledger callsites.
- Review engine routing plans shipped, but review fan-out is still outside the invoker abstraction; track under Phase 4
  `HeadlessInvoker` and fan-out migration.
- Session and Claude launchers have subprocess-proxy environment wiring, but the durable runtime usage ledger remains
  future; track under Phase 4 usage ledger callsites.

## Phase 1 - Curated Transfer Reframe

- [x] Reposition `ai-curated` / curated transfer in `docs/design.md` as the primary cross-runtime and cross-topology
  transfer substrate, not merely a lossy fallback.
  - Assertion: design text distinguishes native resume (byte-faithful but opaque and CWD-locked) from curated transfer
    (runtime-neutral, user-editable) by user agency and runtime portability; `structured` remains the CLI default unless
    an explicit default change is approved.
  - Scope note (assertion refined 2026-05-31): the native-*relocate* leg of the agency reframe stays in `card.md` and
    lands in `design.md` only when Phase 3 ships native-relocate. Design docs describe shipped behavior
    (documentation-guidelines Rule 2), so an unshipped Phase 3 spike must not be written as current design; the original
    assertion's "native-relocate" clause was dropped for this reason.
  - Verification (2026-05-31): `docs/design.md` §3.9 ("Curated transfer is the primary cross-boundary substrate, not a
    lossy fallback") shipped in commit `2b70c29`; `structured` confirmed still the CLI default in both the prose and
    `transfer.py`.
- [x] Verify `forge session resume --fresh --review` behavior.
  - Note: this shipped before the runtime-abstraction checklist was activated; it is retained here as verified Phase 1
    foundation.
  - Assertion: transfer-mode resume opens the per-child user-notes overlay (`children/<child>.notes.md`) in `$EDITOR`;
    native mode rejects `--review` with an actionable error.
  - Verification: `src/forge/cli/session_lifecycle.py` implements the `resume --review` option, native-mode rejection,
    and `$EDITOR` launch for the user-notes overlay; `docs/design.md` command reference documents the CLI contract;
    `tests/src/cli/test_session_resume_review.py` covers the behavior.
- [x] Decide the resume-context command namespace before adding `regenerate|edit|diff`.
  - Decision (2026-05-30): **top-level `forge transfer` group** -- `forge transfer show|regenerate|edit|diff`. Chosen
    over the `forge session transfer` subgroup on user-mental-model grounds: users think "inspect/reshape the context
    that moves forward," not "a subresource of session," and it pairs with the top-level `forge memory` as the two
    halves of the former "handoff." This is a user-facing-namespace choice, not a scoping claim -- transfer is still
    session-derived and every verb takes a parent session argument.
  - Verified free/occupied (2026-05-30): `forge transfer` is unclaimed (no CLI command; `transfer` appears only as the
    `--resume-mode` value, a `forge clean` category key, and internal `transfer.py` symbols). `forge session handoff` is
    a removed-command tombstone (redirects to `forge memory report show`) and `forge session context` is a hidden
    deprecated alias for `forge session show` -- neither reusable. `forge transfer show` (assembled transfer artifact)
    is deliberately distinct from the deprecated `forge session context` (a running session's runtime context).
  - Single canonical namespace only: `forge session resume --fresh --review` remains a delegating entry point, not a
    competing surface.
- [x] Define the Forge-owned curated transfer schema contract in docs.
  - Assertion: schema records lineage, decisions with citations, current state, open questions, runtime hints, and user
    notes overlay.
  - Verification (2026-05-31): `docs/design_appendix.md` §M documents the contract -- §M.1 child-agnostic frontmatter
    (`schema_version: 1`, `schema`, `strategy`, `lineage`, `target_runtime`), §M.2 the 8 canonical sections (Lineage,
    Goal/Current Task, Decisions cited, Current State, Relevant Files, Open Questions, Runtime Hints, User Notes), §M.3
    the three-file layout + overlay. Shipped in `2b70c29`.
- [x] Implement the curated transfer schema in `src/forge/session/transfer.py`.
  - Assertion: generated transfer markdown has stable sections for the schema fields; existing
    `minimal|structured|full|ai-curated` strategies either emit that schema or document their compatibility fallback.
  - Verification (2026-05-31): `transfer.py` `_build_ai_curated_output()` emits canonical sections 1-7 (section 8 is the
    `.notes.md` overlay merged at show/launch); `_build_frontmatter()` stamps `schema: "full"` only for a successful
    ai-curated body and `schema: "compatibility-fallback"` for `minimal|structured|full`;
    `_validate_decision_citations()` drops fabricated citations so `schema: full` stays honest. Shipped in `2b70c29`.
- [x] Add tests for schema output and artifact durability.
  - Assertion: tests cover parent cache regeneration, per-child artifact preservation, and required schema sections for
    curated output.
  - Verification (2026-05-31): 113 passed -- `tests/src/session/test_transfer.py`
    (`test_ai_curated_renders_schema_sections`, `test_compatibility_fallback_frontmatter`,
    `test_generated_and_child_are_byte_identical`, citation grounding), `tests/src/cli/test_transfer_cli.py`
    (`test_regenerate_preserves_strategy`, `test_regenerate_does_not_touch_notes`,
    `test_show_json_includes_section_map`), `tests/src/session/test_prev_sessions.py` (notes round-trip, compose,
    `iter_children` excludes notes), and regression `tests/regression/test_bug_transfer_notes_not_gc_orphaned.py`.
- [x] Define the user notes overlay convention.
  - Assertion: docs/code state where user notes live, how they compose with generated content, and that regeneration
    never overwrites authoritative user notes.
  - Verification (2026-05-31): `children/<child>.notes.md` is the editable overlay (design.md §3.9, appendix §M.3);
    `prev_sessions.py` composes notes after the frozen snapshot at launch, `ensure_child` never overwrites an existing
    child, and `forge transfer regenerate` rewrites only `generated.md`. Covered by `test_prev_sessions.py`
    (`test_snapshot_notes_round_trip`, `test_compose_merges_user_notes`, `test_compose_skips_empty_notes`). Shipped in
    `2b70c29`.
- [x] Decide how `ctx` relates to Forge transfer.
  - Assertion: docs state whether `ctx` is only prior art, an import/export peer, or a future dependency.
  - Decision (2026-05-31): `ctx` is **prior art and inspiration only -- never a dependency**. The Forge-owned transfer
    schema is canonical and no `ctx` interop is planned (an optional import/export bridge could be added later on the
    existing schema, but is not committed work). Recorded in `docs/design_appendix.md` §M.4; the matching `card.md`
    prose and Open Question are aligned and marked resolved.
- [x] Confirm Phase 1 schema is stable enough for Phase 5 target-runtime tuning.
  - Assertion: Phase 5 can tune transfer presentation for Codex without changing transcript source artifacts or schema
    semantics.
  - Verification (2026-05-31): the schema reserves `target_runtime` (frontmatter + `TRANSFER_TARGET_RUNTIME`, appendix
    §M.1) and code owns the section skeleton, so Phase 5 retargets presentation without touching transcript artifacts or
    schema semantics. Closeout gates cleared -- the `ctx` posture is recorded (§M.4) and both default-behavior Open
    Decisions are resolved (keep `--review` opt-in, keep `structured` default). All Phase 1 boxes are now ticked; the
    card stays in `doing/` for Phases 2-6.

## Phase 2 - Optional Audit Proxy

Execution plan: `~/.claude/plans/yeah-let-s-move-on-proud-kernighan.md` (approved). Sliced OBSERVE-before-MUTATE; each
slice leaves the proxy working because new config defaults are inert. Two axes kept distinct everywhere: **wire shape**
(`openai_translated` | `anthropic_passthrough`) and **intercept mode** (`passthrough` | `inspect` | `override`).

### Slice 2a - Config schema + loader propagation + wire_shape (DONE 2026-05-31)

- [x] Add `InterceptConfig`/`InterceptOverrideConfig`/`AuditConfig` + `wire_shape` to `ProxyInstanceConfig` and runtime
  `ProxyConfig` (strict unknown-key rejection); propagate through `loader.load_proxy_instance_config_from_dict` +
  `_proxy_instance_to_forge_config` + `proxy_orchestrator`; report `wire_shape`/`intercept_mode` in `GET /`; add
  `forge proxy set` int-coercion for `audit.retention_days`/`max_total_mb`.
  - Assertion: defaults inert (`wire_shape="openai_translated"`, `intercept.mode="passthrough"`,
    `audit_full_body=False`); unknown sub-keys raise (`audit.full_body` typo); config reaches runtime `ProxyConfig`
    (propagation trap guarded).
  - Verification: `tests/src/config/test_schema.py::TestInterceptAuditConfig`,
    `tests/src/config/test_loader.py::test_proxy_instance_{config_round_trips,to_forge_config_propagates}_intercept_audit`;
    107 config tests pass; mypy/pyright/ruff clean.

### Slice 2b - Anthropic passthrough forward path + template (DONE 2026-05-31)

| Test               | Fixture                                               | Assertion                                                          | Test File                                                     |
| ------------------ | ----------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------- |
| Raw body preserved | passthrough proxy; unknown field + thinking blocks    | forwarded body byte-identical; unknown field + `signature` survive | `tests/regression/test_bug_passthrough_preserves_raw_body.py` |
| ASGI body re-read  | real app via `TestClient`                             | branch re-reads full raw body after `MessagesRequest` parse        | `tests/src/proxy/test_passthrough.py`                         |
| Template create    | `forge proxy create anthropic-passthrough --no-start` | `proxy.yaml` carries `wire_shape: anthropic_passthrough`           | manual CLI smoke (verified)                                   |

- [x] New `src/forge/proxy/passthrough.py` forwarder (httpx, raw SSE, no converters); early branch in
  `create_message`/`count_tokens` on `wire_shape`; `anthropic-passthrough.yaml` template (`provider: litellm` slot,
  `wire_shape` truth, `base_url: api.anthropic.com`); `ANTHROPIC_API_KEY` registered in `template_secrets.py`.
  - Verification: 10 passthrough/regression tests pass; full 1467-test proxy+config+core sweep green; mypy/pyright/ruff
    clean; CLI create smoke confirms `proxy.yaml` round-trip.
  - Deferred (checklist debt): real-upstream `@pytest.mark.slow` signature-replay e2e
    (`tests/integration/proxy/test_passthrough_e2e.py`) needs `ANTHROPIC_API_KEY` + Docker (release-validation tier).
    The in-process `TestClient` test covers the body-reparse risk now.

### Slice 2c - Audit logging + redaction + drift + `forge proxy audit show` + preflight (OBSERVE) (DONE 2026-05-31)

| Test                    | Fixture                                                            | Assertion                                                               | Test File                                                                                  |
| ----------------------- | ------------------------------------------------------------------ | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| No plaintext secret     | full-body record w/ planted secrets in headers+body+tools+response | none of the secrets appear in the JSONL; structure retained             | `tests/regression/test_bug_audit_header_redaction_no_leak.py`                              |
| Metadata-only default   | passthrough proxy in `inspect` mode, one request                   | audit record has hashes + counts, no body text, no secret header values | `tests/src/proxy/test_passthrough.py::test_passthrough_inspect_mode_writes_audit_metadata` |
| Drift fires on change   | two inspect requests, changed system prompt                        | second produces a `drift` record; baseline survives a simulated restart | `tests/src/proxy/test_audit_logger.py::TestDrift`                                          |
| `audit show` no secrets | audit records written for two proxies                              | `forge proxy audit show <id>` scopes by id, prints hashes not plaintext | `tests/src/cli/test_proxy_audit.py`                                                        |

- [x] `audit_logger.py` (`log_audit_record`/`read_audit_logs`/`prune_audit_logs`, `record_type` request/drift, hashing,
  `schema_version`, owner-only 0600/0700); `redact_headers` in `utils.py` (denylist + substring fallback) reusing
  `_redact_body_for_log`/`_redact_tools`; inspect-mode hook in both wire-shape paths (best-effort, guarded inert in
  `passthrough` mode); drift detection + per-proxy `audit_state.json`; `audit_full_body` opt-in (request body + headers
  redacted; streaming response = metadata only — full streamed-body capture deferred); retention pruning at startup;
  `GET /` `intercept` preflight (`can_inspect`/`thinking_blocks_preserved`); `forge proxy audit show` (`proxy_audit.py`)
  - `%proxy audit show`; `forge proxy set audit.audit_full_body=true` privacy warning; template flipped to
    `intercept.mode: inspect`.
  * Verification: 27 `test_audit_logger` + 4 `test_proxy_audit` + inspect server test + no-leak regression pass; broad
    697-test proxy+cli+config sweep green; mypy/pyright/ruff clean.

#### Slice 2c hardening - OBSERVE-half review fixes (DONE 2026-05-31)

Review of the OBSERVE half surfaced 10 issues (4 Blocker / 3 Medium / 3 Low); all verified against code and fixed.

| Test                              | Fixture                                                         | Assertion                                                           | Test File                                                                                                            |
| --------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Unknown block bypasses validation | passthrough proxy, nested `future_block_99` block via real ASGI | 200 (not 422); raw block forwarded; `X-Resolved-Model` set          | `tests/src/proxy/test_passthrough.py::test_passthrough_middleware_bypasses_validation_for_unknown_block`             |
| Translated proxy not intercepted  | `openai_translated` config via real ASGI                        | passthrough handler never reached                                   | `..::test_translated_proxy_not_intercepted_by_passthrough_middleware`                                                |
| Usage -> cost                     | non-streaming response w/ usage                                 | `_calc_and_log_cost` gets input/output/cached=100/50/10             | `..::test_passthrough_logs_cost_from_response_usage`                                                                 |
| Caps enforced                     | passthrough + cap exceeded, `on_cap_hit=reject`                 | 429 `spend_cap_exceeded`; forward not reached                       | `..::test_passthrough_enforces_spend_cap_reject`                                                                     |
| Streaming usage tap               | SSE `message_start`+`message_delta`, split chunk                | `on_complete` usage = in 200 / out 77 / cached 20                   | `..::test_forward_streaming_taps_usage`, `..::test_usage_accumulator_handles_split_chunks`                           |
| Full-body response + no leak      | inspect+`audit_full_body`, secret sys/user/resp/header          | record has redacted `response_body` + hashes/counts; zero plaintext | `..::test_passthrough_full_body_captures_redacted_response`                                                          |
| No-leak via server path           | TestClient passthrough, secret Authorization+body+response      | no plaintext in shard; wiring (not just writer) covered             | `tests/regression/test_bug_audit_header_redaction_no_leak.py::test_full_body_audit_through_server_path_no_plaintext` |
| Size retention                    | 3x 0.5 MiB shards, cap 1 MiB                                    | oldest pruned, newer kept                                           | `tests/src/proxy/test_audit_logger.py::TestPrune::test_prune_by_total_size_oldest_first`                             |
| Non-text system block             | system list w/ text + image block                               | image block excluded from hash                                      | `..::TestHashing::test_system_prompt_excludes_non_text_blocks`                                                       |

- [x] **B1** raw-validation bypass: passthrough intercepted in `log_requests_middleware` BEFORE FastAPI binds
  `MessagesRequest`, so unknown/future content blocks forward byte-for-byte. The middleware is the SOLE passthrough
  entry point — the old in-handler `wire_shape` branches in `create_message`/`count_tokens` were removed (they were dead
  for real requests once the middleware short-circuits `call_next`); handler-logic tests call
  `_handle_anthropic_passthrough` directly, middleware delegation is covered by two `TestClient` tests.
- [x] **B2** caps/cost: passthrough now runs the same spend-cap preflight + `_calc_and_log_cost` + `record_request`;
  usage captured from the non-streaming body and tapped from the streaming SSE (`_UsageAccumulator`).
- [x] **B3/M5** response-side audit: full-body record written response-side with redacted response + request
  hashes/counts; CLI label honest (`[req+resp]` vs `[req-body]`). **B4** no-leak now also covered through the server
  path.
- [x] **M6** event loop: request-side observation offloaded via `await asyncio.to_thread` (deterministic, off-loop).
  **M7** headers: `X-Resolved-Model/Tier`, `X-Cumulative-Cost`, `X-Spend-Warning`. **L8** parent `audit/` chmod 0700.
  **L10** system-prompt hash filters to text blocks.
  - Verification: 43 passthrough+audit_logger + broad 2147-test sweep green; mypy/pyright/ruff clean. (One pre-existing,
    unrelated failure on this branch: `test_removal_patching_system::...test_forge_info_no_traceback` — confirmed via
    stash; not touched by this work.)
  - Deferred (debt): translated-path full-body capture stays request-only (honest `[req-body]` label); passthrough
    streaming full-body carries response usage metadata, not the full streamed body. Docker proxy-runtime integration
    not yet run for 2a-2c (middleware change warrants it before merge).

### Slice 2d - Override mode + augment/guards + reasoning pin + mutation safety + `audit diff` (MUTATE) (DONE 2026-05-31)

| Test                                  | Fixture                                                                              | Assertion                                                                                         | Test File                                                                                           |
| ------------------------------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| History byte-identical under override | history with signed `thinking`+`redacted_thinking`; augment+guard+pin all on         | `messages` unchanged byte-for-byte; control surfaces (system/thinking) mutated                    | `tests/regression/test_bug_override_preserves_thinking_blocks.py`                                   |
| Augment is cache-aware                | system with a `cache_control` marker                                                 | augment inserted AFTER the last marker (prefix byte-identical); markerless flags invalidation     | `tests/regression/test_bug_augment_cache_aware_insertion.py`                                        |
| Override mutates + records (server)   | passthrough proxy, `mode=override`, augment + `tier_overrides.reasoning_effort=high` | forwarded body augmented + `thinking.budget_tokens=10000`; redacted mutation record, no plaintext | `tests/src/proxy/test_passthrough.py::test_passthrough_override_mutates_body_and_records`           |
| Guard block -> 403                    | `mode=override`, block guard matches system                                          | 403 `intercept_guard_blocked`; forward not reached; `blocked` mutation record                     | `..::test_passthrough_override_guard_block_returns_403`                                             |
| Non-override is inert                 | `mode=inspect` with augment configured                                               | body unmutated; no mutation record                                                                | `..::test_non_override_mode_does_not_apply_override`                                                |
| Pin floor consistent                  | each effort floor                                                                    | round-trips back to the same effort via `server._derive_reasoning_effort` (no table drift)        | `tests/src/proxy/test_intercept.py::TestReasoningPin::test_floor_consistent_with_server_thresholds` |
| `audit diff` view                     | drift + mutation records                                                             | renders both, tagged drift/mutation, hashes only                                                  | `tests/src/cli/test_proxy_audit.py`, `tests/src/cli/test_user_prompt_dispatcher.py`                 |

- [x] New `src/forge/proxy/intercept.py` (pure): `messages_fingerprint`, cache-aware `insert_augment_cache_aware`,
  `apply_guards` (warn/block/strip), `pin_reasoning` (effort floor -> Anthropic `thinking.budget_tokens`, clamped
  `>=1024`/`<max_tokens`), `apply_override` (build -> validate -> apply, mutation-safety `RuntimeError` tripwire).
  Reuses `audit_logger.hash_system_prompt`; reasoning pin reuses `tier_overrides.<tier>.reasoning_effort` (no new config
  key).
- [x] `override` branch wired into `_handle_anthropic_passthrough` AFTER the inspect record, BEFORE forward
  (mutate-after-observe); guard `block` short-circuits 403; mutation-safety violation fails closed (no forward).
  `audit_logger.write_mutation_record` (already-redacted payload). Non-override modes skip the branch entirely.
- [x] `forge proxy audit diff` leaf (`proxy_audit.py`) + `%proxy audit diff` (`direct_commands.py`): drift + mutation
  folded into one timeline, hashes/lengths/budgets only.
  - Verification: 126 focused (intercept+passthrough+audit CLI+dispatcher+regression) + broad 2184-test sweep green;
    mypy/pyright/ruff clean on changed src. One pre-existing unrelated failure (`test_forge_info_no_traceback`).
  - Deferred: override on the `openai_translated` wire shape (the lossy path) is out of scope — override targets the
    signature-safe passthrough path per the plan; translated proxies already apply tier_overrides via their own path.

#### Slice 2d hardening - review fixes (DONE 2026-05-31)

Review of 2d surfaced 14 issues (2 High / 4 Med / 5 Low / 3 nit); all verified against code and fixed.

- [x] **High**: (1) `intercept.mode=override` now REQUIRED to pair with `wire_shape=anthropic_passthrough` — rejected at
  `ProxyInstanceConfig.__post_init__` (was silently inert on translated, and GET / mislabelled it active). (2) guard
  config validated at config time — unknown keys rejected, `pattern` must be a non-empty str, regex compiled (a bad
  regex was silently disabling a security control).
- [x] **Medium**: (3) guards evaluate all `block` checks BEFORE any strip/augment, so a strip-before-block can't
  half-mutate a blocked body (+ regression). (4) passthrough reasoning pin resolves tier from the request model
  (`_tier_from_model_name`), not just `default_tier`, so an explicit opus request hits `tier_overrides.opus`. (5)
  mutation audit write offloaded via `asyncio.to_thread` (parity with inspect). (6) full-body records recompute hashes
  from the forwarded (post-override) body so the row is self-consistent.
- [x] **Low/nits**: (7) reasoning pin preserves unknown `thinking` sibling keys (forward-safe). (8) server-path
  fail-closed test (fingerprint mismatch -> raise, no forward). (9) force-enable floor semantics documented (consistent
  with translated `_max_effort`). (10) count_tokens override-skip commented. (11) guard matching per-block for all
  actions. (12) dropped unused `flatten_system_text`. (13) explicit `action == "warn"` branch. (14) renamed
  `intercept._short_hash` -> `_pattern_hash` (distinct from `proxy_audit._short_hash`).
  - Verification: 192 focused + broad 2194-test sweep green; mypy/pyright/ruff clean on 6 changed src; `make pre-commit`
    clean. New tests: config (override-requires-passthrough, 3 guard-validation), intercept (strip-then-block,
    siblings), server-path (model-tier pin, fail-closed, full-body consistency).

### Slice 2e - Sidecar audit plumbing (DONE 2026-06-01)

| Test                               | Fixture                                                        | Assertion                                                                       | Test File                                                      |
| ---------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| proxy_id adds env + both mounts    | `run_sidecar_session(proxy_id=...)`, host config dir present   | cmd has `FORGE_PROXY_ID`, `FORGE_HOME=/root/.forge`, config `:ro` + audit `:rw` | `tests/src/sidecar/test_container.py`                          |
| audit mount without config dir     | `proxy_id` set, no host config dir                             | ro config mount skipped; writable audit mount still present                     | `..::test_audit_mount_present_even_without_config_dir`         |
| template-only unchanged            | `proxy_id=None`                                                | no `FORGE_PROXY_ID`/`FORGE_HOME`/`/root/.forge` in cmd                          | `..::test_no_proxy_id_is_template_only`                        |
| drift state redirect in sidecar    | `FORGE_SIDECAR=1`                                              | `_audit_state_path` -> `audit/state/<id>.json` (not the read-only config dir)   | `tests/src/proxy/test_audit_logger.py::TestAuditStatePath`     |
| validation skipped in sidecar      | `FORGE_SIDECAR` set                                            | `server._sidecar_mode_active()` True -> host-registry check bypassed            | `tests/src/proxy/test_proxy_startup.py::TestSidecarModeActive` |
| sidecar overlay + host audit (E2E) | real image+entrypoint, `--proxy-id`, inspect passthrough proxy | in-container `GET /` `intercept_mode==inspect`; host audit shard has the record | `tests/integration/sidecar/test_audit_plumbing.py`             |

- [x] `FORGE_PROXY_ID` into `container.py` env + narrow read-only per-proxy config mount + writable host `audit/` mount;
  `docker/entrypoint.sh` passes `--proxy-id` when set; drift state writable in sidecar; preflight reports mode +
  host-visible audit. Docker E2E gate passes via the canonical runner.
  - **Plan correction (verified against code):** the plan's "no server CLI change needed" was wrong.
    `validate_proxy_startup` (`proxy_startup.py`) requires the proxy_id in the host registry AND registry port ==
    runtime port; in-container the registry isn't mounted and the port is fixed (8085), so `--proxy-id` would abort
    startup. Fix: `server._sidecar_mode_active()` skips that registry/port cross-check under `FORGE_SIDECAR` (the
    overlay is the in-container source of truth). Semantically correct — the check guards host-side registry coherence,
    absent in a one-proxy container.
  - **Drift-state redirect:** the per-proxy config dir is mounted read-only, so `audit_state.json` (written beside
    `proxy.yaml` on host) moves to the writable audit mount (`~/.forge/audit/state/<id>.json`) under `FORGE_SIDECAR`.
  - **Mounts:** `container.py` pins `FORGE_HOME=/root/.forge` and mounts host `~/.forge/proxies/<id>` (ro) +
    `~/.forge/audit` (rw) at that home; `get_forge_home()` is `/root/.forge` in-container (no USER in
    `Dockerfile.sidecar`).
- [x] **Two latent `entrypoint.sh` bugs found by the E2E and fixed** (the sidecar proxy could never start; never caught
  because `forge-sidecar:latest` was never in any test path): (1) bare `python -m forge.proxy.server` hit the system
  interpreter with no forge — now `/forge/.venv/bin/python` (the editable venv), PATH fallback for non-standard bases;
  (2) `--log-level warning` is not a server option (log level is env-driven, defaults to `off`) — removed. The E2E is
  the regression for both.
- [x] **Sidecar image wired into the canonical runner** (tooling gap: nothing built `forge-sidecar:latest`, and
  `Dockerfile.sidecar` pinned `FROM forge-claude-test:latest` while the runner tags by Claude version):
  `Dockerfile.sidecar` now takes `ARG BASE_IMAGE`; `scripts/test-integration.sh` builds `forge-sidecar:latest` from the
  freshly-built base after the base build; conftest failure message points at the runner.
  - Verification: **`./scripts/test-integration.sh tests/integration/sidecar/test_audit_plumbing.py` PASSES**
    (in-container `GET /` `intercept_mode==inspect`/`wire_shape==anthropic_passthrough`; host `forge proxy audit show`
    surfaces the record after the `--rm` container exits). Host gates green: 70 focused unit (`test_container` +
    `test_audit_logger` + `test_proxy_startup`), 516 proxy+sidecar+audit-CLI sweep, 177 session-command; ruff/mypy
    clean; fresh `uv run pyright` 0/0/0 on changed src; `bash -n` on entrypoint + runner OK.

#### Slice 2e hardening - review fixes (DONE 2026-06-01)

Review of 2e surfaced 9 issues (2 High / 1 Med / 4 Low / 2 nits/docs); all verified against code and fixed.

- [x] **High**: (1) **costs not host-persistent** — mounted `audit/` but not `costs/`, so cost history AND cumulative
  spend-cap accounting reset every `--rm` launch (caps bootstrap from cost logs). Added a writable `costs/` mount beside
  `audit/`. (2) **Linux `--user` vs `/root`** — real but pre-existing (the existing `/root/.claude` mounts + the
  entrypoint's direct `/root/.claude.json` write share it): under `--user uid:gid`, `/root` (0700) isn't
  traversable/writable. Fixed the inaccurate "runs as root" comment to record the limitation honestly; the UID-writable
  home rework is tracked as **follow-up** (touches the pre-existing `/root/.claude` flow, out of 2e scope).
- [x] **Medium**: (3) `--proxy-id` startup no longer hard-gates on `template_exists` — proxy.yaml is authoritative when
  a proxy id is supplied, so a proxy from a non-shipped user template starts in-container (`server.main`:
  `if proxy_id is None and not template_exists`).
- [x] **Low/nits**: (4) `run_sidecar_session` fails fast on the host when `proxy_id` has no `proxy.yaml` (was a late
  in-container health failure). (5) integration test carries a cross-reference comment to
  `run_sidecar_session`/`_ensure_audit_plumbing_mounts` (hand-rolled `docker run` can't drive `-it`+`exec claude`). (6)
  renamed `_audit_plumbing_mounts` -> `_ensure_audit_plumbing_mounts` and documented the host-dir `mkdir` side effect.
  (7) drift-state redirect gated on `FORGE_SIDECAR` **and** `FORGE_PROXY_ID` (template-only sidecars mount no audit/).
  (8) `_SIDECAR_FORGE_HOME` comment corrected re: Linux `--user`. (9) confirmed checklist 2f keeps the narrow-mount §7
  exception as a docs item.
  - Verification: **E2E re-run PASSES against a freshly-rebuilt base** (current source incl. #3/#7 baked); 71 focused
    unit + 799 proxy+sidecar+config+session sweep; ruff/mypy clean; fresh `uv run pyright` 0/0/0 on changed src;
    `pre-commit` clean.
  - **Follow-up (tracked):** Linux `--user` UID-writable home for the sidecar (fixes #2 fully; shared with the
    pre-existing `/root/.claude` mount + `/root/.claude.json` write). Out of 2e scope; macOS path verified.

### Slice 2f - Docs + always-on posture + closeout

- [ ] `docs/design.md` §7.x (intercept modes, sidecar-recommended/host-supported, narrow-mount §7 exception),
  `intercept_mode`/`wire_shape` in §3.7 `GET /`, `forge proxy audit` row in §4.0, §3.4 line; `docs/design_appendix.md`
  §A.11 (config schema) + §A.12 (audit log schema); `docs/end-user/proxy.md` audit/intercept section + `audit_full_body`
  privacy warning; `docs/board/change_log.md` Phase 2 entry; close out the deferred 2b e2e debt.

## Phase 3 - Native-Relocate Spike

- [ ] Spike cross-CWD Claude JSONL relocation.
  - Assertion: integration contract test proves Claude Code can resume relocated JSONL across CWD boundary without
    signature-validation failure, while explicitly acknowledging the prior Claude Code 2.1.90 negative result documented
    in `docs/design.md` §3.9.
- [ ] Tie the spike to the current no-op and transfer-only guards.
  - Assertion: checklist/test references cover the native-resume guard in `src/forge/session/manager.py` and the
    worktree-fork transfer branch in `src/forge/cli/session_fork.py`.
- [ ] Split native-relocate handling by code path.
  - Assertion: `fork --worktree`, `fork --into`, and `resume --fresh --resume-mode native-relocate` each have an
    explicit expected behavior before implementation.
- [ ] Gate path rewriting separately.
  - Assertion: absolute path rewriting is opt-in and disabled by default until tests prove it harmless.
- [ ] Preserve derivation and GC invariants for relocated artifacts.
  - Assertion: relocated JSONL, generated parent cache, and per-child transfer artifacts are traceable without orphaning
    or overwriting user-edited child files.
- [ ] Decide outcome of native-relocate.
  - Assertion: either introduce opt-in `--resume-mode native-relocate` or record why curated transfer remains the only
    cross-CWD path.

## Phase 4 - Runtime Abstraction Core

- [ ] Introduce `HeadlessInvoker` interface and `ClaudeHeadlessInvoker`.
  - Assertion: existing single headless callers of `run_claude_session()` keep user-visible behavior, timeout semantics,
    environment routing, and fail-open/fail-closed choices.
- [ ] Move review-engine fan-out behind invoker lifecycle management.
  - Assertion: `src/forge/review/engine.py` parallel `subprocess.Popen()` fan-out, process-group cleanup, timeout
    handling, cancellation, and deterministic result ordering are preserved and covered by tests.
- [ ] Add runtime registry capability matrix.
  - Assertion: registry answers installed, interactive, headless, hooks, usage, native resume, and scope capabilities.
- [ ] Generalize existing `ActionContext` / `PolicyDecision` for runtime adapters.
  - Assertion: current Claude hook adapter behavior is unchanged, runtime identity is represented explicitly, and Codex
    adapter limitations are represented as capabilities instead of implied parity.
- [ ] Define durable usage ledger schema.
  - Assertion: `~/.forge/usage/events.jsonl` event schema covers runtime, provider, model, proxy, billing mode, tokens,
    latency, status, and attribution ids.
- [ ] Instrument usage ledger callsites in staged order.
  - Assertion: workflow verbs (`src/forge/cli/workflow.py`), memory writer (`src/forge/session/memory_writer.py`),
    review engine (`src/forge/review/engine.py`), semantic supervisor (`src/forge/policy/semantic/supervisor.py`), team
    supervisor (`src/forge/policy/team/handlers.py`), Claude launcher (`src/forge/cli/claude.py`), and session launcher
    (`src/forge/cli/session.py`) each have an explicit done/deferred status.

## Phase 5 - Cross-Runtime Resume

- [ ] Add `CodexHeadlessInvoker`.
  - Assertion: uses `codex exec` JSONL output and captures usage events when available.
- [ ] Add runtime/auth preflight for native Codex execution.
  - Assertion: unsupported auth paths fail before launch with setup guidance.
- [ ] Add target-runtime-aware curator.
  - Assertion: consumes the stable Phase 1 transfer schema so output can be tuned for Codex without changing source
    transcript artifacts or schema semantics.
- [ ] Demonstrate Claude-to-Codex resume.
  - Assertion: a documented workflow can plan in Claude and implement in Codex using curated transfer.

## Phase 6 - Codex Frontend Beta

- [ ] Evaluate Codex as an interactive frontend runtime.
  - Assertion: decision is based on headless invocation, usage accounting, policy semantics, and curated transfer
    results from earlier phases.

## Open Decisions

Tracks Forge-local execution decisions for this checklist. For broader card questions, see
[`card.md` Open Questions](./card.md#open-questions).

- [x] Should `forge session resume --fresh --review` become default for curated transfer workflows? **Resolved
  2026-05-31: no -- keep `--review` opt-in.** A plain `--fresh` resume launches immediately; `--review` stays an
  explicit flag so non-interactive/scripted resume never blocks on `$EDITOR`. Curation is deliberate. Docs-only, no code
  change.
- [x] Which transfer-owned namespace should the resume-context commands use? **Resolved 2026-05-30: top-level
  `forge transfer ...`** (not `forge session transfer ...`), pairing with `forge memory`. Rationale and free/occupied
  verification are recorded in the Phase 1 namespace task above.
- [x] Should Phase 1 remain prose/schema-only, or should it change the default strategy after schema tests land?
  **Resolved 2026-05-31: prose/schema-only -- keep `structured` as the CLI default.** `ai-curated` stays opt-in via
  `--strategy ai-curated`, keeping the resume hot path deterministic, free, and LLM-free (matches design.md §3.9).
  Docs-only, no code change.
- [ ] Where do proxy cost logs, audit logs, and the future usage ledger converge?
- [ ] How should `FORGE_DEPTH` compose with future run-tree attribution ids?

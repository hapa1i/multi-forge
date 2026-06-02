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

**Phase 3 spike complete (2026-06-01) — native-relocate is VIABLE (PASS); opt-in wiring shipped (Stage C v1).** Both
gates agree on Claude Code 2.1.158: the control (resume without relocating) still reproduces the 2026-04-02 "No
conversation found" discovery failure, and the experiment (relocate the parent JSONL into the child CWD's encoded dir,
then `--resume --fork-session`) completes a signed-thinking tool-use continuation with the relocated parent unmodified.
Host repro (`scripts/experiments/native-resume/`) `[PASS]`; Docker contract test
(`tests/integration/docker/test_native_relocate_contract.py`) PASSED (23.6s). The spike also fixed a bug it surfaced:
`encode_project_path` now maps `_`→`-` (Claude 2.1.158 does, Forge didn't — broke transcript discovery for any
underscore path). `docs/design.md` §3.9 + the `session_fork.py` worktree-branch comment are version-stamped.

**Stage C v1 shipped (2026-06-01):** the opt-in `forge session fork --resume-mode native-relocate` (host mode only;
default stays transfer) relocates the parent JSONL and resumes byte-for-byte, with preflights (sidecar/`--direct`,
`--no-launch`, source-transcript), post-create rollback, and dir-scoped cleanup of the relocated copy. Deferred:
`--rewrite-paths`, sidecar native-relocate, `resume --resume-mode native-relocate`, and the (gated) default flip.

**Phase 2 complete (2026-06-01).** The optional always-on audit proxy shipped across commits `97abe5c` (OBSERVE),
`2663c06` (MUTATE), `d0eb708` (sidecar plumbing), and `5991896` (sidecar `--user` fix), plus the 2f docs slice:
`wire_shape`/`intercept`/`audit` config, the thinking-preserving `anthropic_passthrough` wire, redacted audit logs with
`forge proxy audit show|diff`, override-mode controls on the signature-safe path, and host-persistent sidecar audit.
`docs/design.md` §7.x + §3.4/§3.7/§4.0, `docs/design_appendix.md` §A.11/§A.12, and `docs/end-user/proxy.md` reflect it.
All Phase 2 slice boxes are ticked.

**Phase 1 complete (2026-05-31).** Schema-backed curated transfer, the `children/<child>.notes.md` overlay, and the
top-level `forge transfer show|regenerate|edit|diff` CLI shipped in commit `2b70c29`; `docs/design.md` §3.9 and
`docs/design_appendix.md` §M reflect it. All Phase 1 boxes are ticked.

Next: **Phase 4 (runtime-abstraction core)** -- **Slice 4a (run-tree env contract) shipped 2026-06-01**; next is Slice
4b (usage-ledger schema). The two cross-cutting Phase 4 decisions are resolved (data-plane: separate planes linked by
`request_id`; `FORGE_DEPTH`: additive run-tree env, integer guard unchanged) -- see Open Decisions for the de-risked
build sequence, recorded at the top of the Phase 4 section. Deferred Phase 3 follow-ups (`--rewrite-paths`,
sidecar/resume native-relocate, the gated default flip) are recorded as trackable boxes under Phase 3 and land when
prioritized. The card stays in `doing/` until Phases 3-6 land (board-contract: move to `done/` only when fully
executed).

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

| Test                               | Fixture                                                        | Assertion                                                                             | Test File                                                                   |
| ---------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| proxy_id adds env + mounts         | `run_sidecar_session(proxy_id=...)`, `proxy.yaml` present      | cmd has `FORGE_PROXY_ID`, `FORGE_HOME=/root/.forge`, config `:ro` + audit/costs `:rw` | `tests/src/sidecar/test_container.py::...test_proxy_id_adds_env_and_mounts` |
| missing proxy.yaml fails fast      | `proxy_id` set, no `proxy.yaml` on host                        | raises `FileNotFoundError` before `docker run` (no late in-container failure)         | `..::test_missing_proxy_yaml_fails_fast`                                    |
| template-only unchanged            | `proxy_id=None`                                                | no `FORGE_PROXY_ID`/`FORGE_HOME`/`/root/.forge` in cmd                                | `..::test_no_proxy_id_is_template_only`                                     |
| drift state redirect in sidecar    | `FORGE_SIDECAR=1`                                              | `_audit_state_path` -> `audit/state/<id>.json` (not the read-only config dir)         | `tests/src/proxy/test_audit_logger.py::TestAuditStatePath`                  |
| validation skipped in sidecar      | `FORGE_SIDECAR` set                                            | `server._sidecar_mode_active()` True -> host-registry check bypassed                  | `tests/src/proxy/test_proxy_startup.py::TestSidecarModeActive`              |
| sidecar overlay + host audit (E2E) | real image+entrypoint, `--proxy-id`, inspect passthrough proxy | in-container `GET /` `intercept_mode==inspect`; host audit shard has the record       | `tests/integration/sidecar/test_audit_plumbing.py`                          |

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
  `audit/`. (2) **Linux `--user` vs `/root`** — under `--user uid:gid` the process is a non-root uid with no passwd
  entry, so HOME collapsed to `/` and `/root` (0700) was un-traversable, breaking both forge (`~/.forge`) and claude
  (`~/.claude.json`). **Fixed:** `container.py` pins `HOME=/root` and `Dockerfile.sidecar` runs `chmod 0777 /root` so
  the mapped uid can reach the /root mounts (sandbox-justified; ephemeral single-session `--rm`). Reproduced + verified
  on macOS by forcing `--user` (container `/root` perms are real regardless of host OS).
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
  - Verification: **E2E PASSES under forced `--user` against a freshly-rebuilt base** (current source incl. #2/#3/#7
    baked; the test now always runs with `--user uid:gid` + `HOME=/root`, exercising the arbitrary-uid path on macOS);
    71 focused unit + 799 proxy+sidecar+config+session sweep; ruff/mypy clean; fresh `uv run pyright` 0/0/0 on changed
    src; `pre-commit` clean.

### Slice 2f - Docs + always-on posture + closeout (DONE 2026-06-01)

- [x] `docs/design.md` §7.x (intercept modes, sidecar-recommended/host-supported, narrow-mount §7 exception),
  `intercept_mode`/`wire_shape` in §3.7 `GET /`, `forge proxy audit` rows in §4.0, §3.4 line; `docs/design_appendix.md`
  §A.11 (config schema) + §A.12 (audit log schema); `docs/end-user/proxy.md` audit/intercept section + `audit_full_body`
  privacy warning; `docs/board/change_log.md` Phase 2 entry.
  - Design docs describe **shipped** behavior (documentation-guidelines Rule 2): §A.11/§A.12 anchors are linked from
    §7.x; the `chmod 0777 /root` + `HOME=/root` sandbox decision is recorded in §7.
  - **Doc-accuracy review fixes (6 issues, all verified against code):** full-body capture contract corrected (redacted
    request body every path; redacted **response** body only for non-streaming passthrough — streaming/translated
    deferred) in §7.x + §A.12 + `proxy.md`; §7 now records the `--user`/`HOME=/root`/`chmod 0777 /root` decision (the
    earlier "recorded in §7" claim was premature); "inert by default" reworded to note the `anthropic-passthrough`
    template opts into `inspect`; stale 2e mount table fixed (config `:ro` + audit/costs `:rw`; the silent-skip row
    replaced by the fail-fast test); `tool-surface` hyphen-wrap typo fixed.
  - Verification: `make pre-commit` clean (mdformat + link/anchor consistency); design.md/appendix/proxy.md/change_log
    render and cross-link.
  - **Carried forward as debt (not closed):** (a) deferred 2b real-upstream `@pytest.mark.slow` passthrough
    signature-replay e2e needs `ANTHROPIC_API_KEY` (release-validation tier); (b) streamed full-body capture stays
    request-body + response-metadata only; (c) optional cleanup — extract the `docker run` argv construction into a
    shared helper so `tests/integration/sidecar/test_audit_plumbing.py` and `run_sidecar_session` can't drift (cross
    -reference comment in place for now). (a)/(b) noted in the change_log Phase 2 entry.

**Phase 2 complete (2026-06-01).** The card **stays in `doing/`** — the `runtime_abstraction` card spans Phases 2-6.
Phase 3 shipped (native-relocate spike + fork Stage C v1); Phases 4-6 (runtime-abstraction core, cross-runtime resume,
Codex frontend) and the deferred Phase 3 follow-ups are not yet executed. Do **not** move the card to `done/` until
those land (board-contract: move only when the card is fully executed).

## Phase 3 - Native-Relocate Spike

**Spike outcome (2026-06-01): PASS on Claude Code 2.1.158 — native-relocate is viable.** The relocate primitive, host
reproduction, and Docker contract test shipped; the opt-in `--resume-mode native-relocate` CLI wiring (the per-code-path
split + derivation/GC provenance) is the deferred **Stage C** follow-up (touch points recorded in the execution plan).

- [x] Spike cross-CWD Claude JSONL relocation.
  - Assertion: integration contract test proves Claude Code can resume relocated JSONL across CWD boundary without
    signature-validation failure, while explicitly acknowledging the prior Claude Code 2.1.90 negative result documented
    in `docs/design.md` §3.9.
  - Verification (2026-06-01): `tests/integration/docker/test_native_relocate_contract.py` PASSED (23.6s) — signed
    parent thinking block exercised, child resume exit 0, ≥2 tool_use in the fork, relocated parent sha256 unchanged.
    Host repro `[PASS]`. The control still reproduces the "No conversation found" discovery failure (now confirmed on
    2.1.158 too); design.md §3.9 acknowledges it.
- [x] Tie the spike to the current no-op and transfer-only guards.
  - Assertion: checklist/test references cover the native-resume guard in `src/forge/session/manager.py` and the
    worktree-fork transfer branch in `src/forge/cli/session_fork.py`.
  - Verification: the `session_fork.py` worktree-branch comment (the transfer-only guard) is version-stamped with the
    spike result; the cross-`forge_root` native-resume no-op guard at `manager.py:700-703` is recorded as the Stage C
    wiring point (deferred, untouched here).
- [x] Gate path rewriting separately.
  - Assertion: absolute path rewriting is opt-in and disabled by default until tests prove it harmless.
  - Verification: `relocate_transcript(rewrite_paths=...)` is a reserved seam — `True` raises `NotImplementedError`
    (default off); content-untouched copy is the signature-safe minimum. Locked by
    `test_claude_relocate.py::TestRelocateTranscript::test_rewrite_paths_not_implemented`.
- [x] Decide outcome of native-relocate.
  - Assertion: either introduce opt-in `--resume-mode native-relocate` or record why curated transfer remains the only
    cross-CWD path.
  - Decision (2026-06-01): native-relocate is **viable** (PASS); the opt-in `--resume-mode native-relocate` wiring
    shipped as **Stage C v1** (fork, host mode only), and transfer remains the default for worktree forks. Deferred:
    `resume --resume-mode native-relocate`, sidecar, path rewriting, the default flip. Recorded in design.md §3.9.
- [x] Split native-relocate handling by code path. *(Stage C v1 — shipped for fork)*
  - Assertion: `fork --worktree` and `fork --into` resume natively via relocation;
    `resume --resume-mode native-relocate` has an explicit deferred status.
  - Verification (2026-06-01): `fork --resume-mode native-relocate` (a `click.Choice(["transfer", "native-relocate"])`
    on `forge session fork`, `default=None`) relocates the parent JSONL into the child's encoded dir and launches
    `--resume --fork-session` from the worktree CWD (`src/forge/cli/session_fork.py`). Host mode only (sidecar rejected,
    `--direct`-aware), `--no-launch` rejected, source-transcript preflighted before create, post-create relocate failure
    rolls back the fork (`delete_session`, owns_worktree-aware). `resume --resume-mode native-relocate` is **deferred**
    (the shared resume validator stays `{native, transfer}`). Covered by
    `tests/src/cli/test_session_commands.py::TestSessionFork` (10 cases: routing, notice, same-dir/strategy tips,
    sidecar/no-launch/source rejects, `--direct` allowed, conflict rollback).
- [x] Preserve derivation and GC invariants for relocated artifacts. *(Stage C v1 — shipped)*
  - Assertion: the relocated JSONL is traceable and cleaned up without orphaning or touching the parent's original.
  - Verification (2026-06-01): `Derivation.resume_mode="native-relocate"` + `relocated_parent_session_id` (the parent
    UUID) record the relocation (`models.py`, `manager.fork_session`); `delete_session` unlinks
    `get_transcript_path(child_root, parent_uuid)` in a branch gated only on the derivation (independent of the child
    UUID, so failed/partial launches still clean up) — dir-scoped to the child, never the parent's original. Covered by
    `test_fork_into.py::TestForkNativeRelocate` (derivation, same-dir fallback, cleanup-without-child-UUID).

#### Phase 3 hardening - review fixes (DONE 2026-06-01)

Review of the spike surfaced 10 issues (5 Medium / 5 Low); all verified against code and fixed. Both gates were re-run
green after the changes: host repro `[PASS]`, Docker contract test PASSED (23.0s).

- [x] **Medium**: (M1) the contract test's child root is now an **underscore-bearing path** (`/tmp/relocate_child_wt`),
  so real Claude exercises the `encode_project_path` `_`->`-` branch end-to-end — an encoder regression now surfaces as
  DISCOVERY-FAIL instead of passing silently on a clean `/workspace`-style path. (M2) host repro drops
  `--dangerously-skip-permissions` to match the contract test's root posture (Claude rejects the flag under root; the
  read-only `Read` tool runs without it). (M4) both gates digest the relocated parent JSONL before/after resume and
  assert it is unchanged (`--fork-session` must not mutate the relocated copy). (M5) both gates track whether a **signed
  thinking block** was actually present and emit `[INCONCLUSIVE]` (host) / `pytest.fail("INCONCLUSIVE: ...")` (Docker)
  rather than `[PASS]` when it was not — a clean resume with nothing to revalidate is not evidence for the
  signature-survival hypothesis.
- [x] **M3 real-Claude helper smoke (decision recorded)**: the conftest helper refactor (`run_claude_print` signature,
  `setup_real_claude`, `relocate_and_resume`) is exercised by **two passing real-Claude tests** — the new contract test
  and `tests/integration/docker/test_real_claude_hooks.py` (2 passed, 15.95s). The other three consumers
  (`test_real_claude_workers.py`, `test_real_claude_memory.py`, `test_real_claude_supervisor.py`) are **deferred to
  release-validation**: all call sites pass the changed args by keyword and the new params are keyword-only with
  unchanged defaults, so the change is backward-compatible by construction (statically verified).
- [x] **Low**: (L6) conftest detects the signed block by parsing JSONL **content blocks** (`type=="thinking"` with
  `signature`, or `type=="redacted_thinking"` with `data`), not a naive substring grep. (L7) the experiment README
  documents that `/`, `.`, and `_` all map to `-`. (L8) `relocate_transcript` writes via `tempfile.mkstemp` +
  `os.replace` (atomic, owner-only `0600`, unique temp name so concurrent same-UUID relocations can't collide; temp
  removed on any failure). (L9) discovery classification matches the **exact** `"no conversation found"` marker in both
  gates; a bare `"not found"` could mislabel an unrelated failure that should fall through to UNCATEGORIZED. (L10)
  `encode_project_path` carries a note that only `/`, `.`, `_` are characterized against real Claude — do not broaden
  the rule without a characterization test.
  - Verification: 30 host unit/regression tests pass (`test_claude_relocate` + `test_claude_paths` +
    `test_bug_encode_project_path_underscore`); `bash -n` + shellcheck clean on `reproduce.sh`; host repro `[PASS]` and
    `tests/integration/docker/test_native_relocate_contract.py` PASSED (23.0s) after the changes; `make pre-commit`
    clean.

### Phase 3 - Deferred follow-ups (parked; land when prioritized)

Recorded so they are not lost while Phase 4 proceeds. None block Phase 4. Verified still deferred against code at commit
`21688d6` (2026-06-01).

- [ ] `--rewrite-paths`: rewrite absolute paths inside relocated `tool_result` blocks (historical paths point at the
  parent checkout). Seam reserved; `relocate_transcript(rewrite_paths=True)` raises `NotImplementedError`
  (`session/claude/relocate.py:93`). **Gated**: needs a contract test proving the rewrite cannot invalidate a thinking
  signature (it touches signed historical content). **Blocks the default-flip below.**
- [ ] `resume --resume-mode native-relocate`: extend native-relocate from `fork` to `resume --fresh`. Validator
  currently accepts only `{native, transfer}` (`cli/session_lifecycle.py:346`); only `fork` has the choice. Lowest-risk
  item (relocate primitive + derivation/GC plumbing already exist); same stale-path caveat as `--rewrite-paths`.
- [ ] Sidecar native-relocate: currently rejected at preflight (`cli/session_fork.py:386`) because relocation writes to
  the host `~/.claude` store, which the sidecar does not mount. Needs a decision on mounting part of host `~/.claude`
  into the sidecar (UID/port-isolation tradeoffs per design.md §7). `--direct`/`--no-proxy` already escape to host mode.
- [ ] Gated default-flip: make native-relocate the default for cross-CWD forks. Two gates: (a) stale-path mitigation
  proven (`--rewrite-paths`), AND (b) a compaction/fallback story defined (relocated history is lost on `/compact`, same
  as native resume). Order: `--worktree` flips before `--into` (more collision surface on an existing `--into`
  worktree). Wiring point: the cross-`forge_root` native-resume no-op guard at `session/manager.py:700-703`.

## Phase 4 - Runtime Abstraction Core

**Cross-cutting decisions resolved (2026-06-01, see Open Decisions):** data-plane (three separate planes linked by
`request_id`) and `FORGE_DEPTH` vs run-tree (additive, orthogonal). **De-risked build sequence:** (1) run-tree env
contract in `build_claude_env` (additive, touches no durable schema); (2) define `usage/events.jsonl` schema with
nullable `source_refs`; (3) instrument native + direct `core.llm` paths first (linkage exact or moot); (4) proxied
per-request correlation fork last. The `HeadlessInvoker` refactor is the largest *implementation* risk but is
internal/refactorable -- it does not mint a durable contract, so it does not gate the schema work.

### Slice 4a - Run-tree env contract (DONE 2026-06-01)

- [x] Run-tree identity minted at the single env choke point, orthogonal to `FORGE_DEPTH`.

  - Assertion: every Forge-spawned process carries `(FORGE_RUN_ID, FORGE_PARENT_RUN_ID, FORGE_ROOT_RUN_ID)`; the
    interactive top is a fresh root; the queue-decoupled memory-writer roots under its originating session;
    `FORGE_DEPTH` and its three recursion guards (`supervisor.py`, `team/handlers.py`, `review/engine.py`) are
    unchanged.
  - Verification (2026-06-01): `RunIdentity` + `mint_run_id`/`get_run_identity`/`new_root_run_identity`/
    `derive_child_run_identity` in `core/reactive/env.py`; `build_claude_env(derive_run_identity=True)` stamps the
    triple right after the depth block (reads spawner id before overwrite; a stale `FORGE_PARENT_RUN_ID` is recomputed,
    not leaked). `SessionResult` (all 6 returns) and `ReviewResult` (5 post-env returns; 2 pre-env failures stay null)
    surface `run_id/parent_run_id/root_run_id`. Interactive root centralized in `invoke._build_environment`
    (`derive_run_identity=False` + fresh root + parent scrub) -- covers session start/resume/fork + bare
    `forge claude start`; sidecar mints its own root in `container.py`. Memory-writer: `enqueue_handoff_marker`
    snapshots `origin_run_id/origin_root_run_id`; `main._memory_writer_env` re-roots the detached spawn under the origin
    (parent=origin_run_id, root=origin_root_run_id, fresh run_id) and scrubs the drainer's id. Targeted unit/regression
    tests pass (incl. `tests/regression/test_run_tree_env_contract.py` orthogonality + source-env-unmutated, and
    `test_claude_invoke.py` interactive fresh-root carve-out -- inherited run vars must not leak into a root);
    `tests/src -m "not integration"` green (4866 passed); `pre-commit` clean (mypy + pyright). **Refinement vs plan:**
    interactive root minted once in `_build_environment` (the shared interactive choke point) rather than per-builder,
    so no caller (resume/fork) can drift.

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
- [x] Where do proxy cost logs, audit logs, and the future usage ledger converge? **Resolved 2026-06-01: they do not
  physically converge -- three separate planes linked by a shared `request_id`.** `costs/requests/*.jsonl` stays the
  cap-enforcement spend log + bootstrap source; `audit/requests/*.jsonl` stays the privacy-sensitive wire record with
  its own retention; the new `usage/events.jsonl` is the canonical attribution ledger ("which run/workflow/session
  invoked which runtime/provider/model via which route and consumed what"), referencing the other planes via
  **nullable** `source_refs` (`{cost_request_id, audit_request_id}`), not absorbing them. Join key verified to exist:
  the proxy generates one `request_id` per request (`server.py:1627`) and threads it into both the cost writer
  (`cost_logger.py:50`) and every audit writer (`audit_logger.py`). Denormalize `cost_micro_usd` into the event for
  greppability while keeping `source_refs` for provenance; native-runtime events (Codex/Gemini) carry units directly and
  leave `source_refs` null.
- [x] How should `FORGE_DEPTH` compose with future run-tree attribution ids? **Resolved 2026-06-01: run identity is
  authoritative; `FORGE_DEPTH` stays an additive integer guard, not reinterpreted.** New env
  `FORGE_RUN_ID`/`FORGE_PARENT_RUN_ID`/`FORGE_ROOT_RUN_ID` (root sets root to its own run_id; children inherit
  unchanged). `FORGE_DEPTH` keeps its `parent+1` computation at the single choke point (`env.py:130`); run tree and
  depth are **orthogonal** (no derivation to build), stamped together so they cannot drift. Do NOT reinterpret the
  integer -- three recursion guards depend on `>= 2` (`supervisor.py:393`, `team/handlers.py:180`,
  `review/engine.py:145`). Real Phase 4 task: audit that every spawn path (incl. review-engine fan-out, sidecar) stamps
  both at one site.
- [ ] Proxied per-request correlation: how does the attribution id reach the proxy cost/audit plane for `claude -p`
  subprocess traffic, where **Forge is not the HTTP client** (Claude is)? `source_refs.cost_request_id` is exact only on
  the direct `core.llm` path (set/read `X-Request-ID`). Options: **(a)** header propagation -- inject `FORGE_RUN_ID`
  into the subprocess env, have Claude forward it as a custom request header, proxy stamps it onto each record (needs a
  Claude-Code custom-header feasibility check); **(b)** out-of-band `(run_id, proxy_id, time_window)` correlation
  (inherits today's `estimated=True` snapshot concurrency fragility, `cost_tracking.py:7`). **Sequenced last (Phase 4
  step 4)** -- validate the ledger on native + direct paths first, then resolve this fork as its own slice.

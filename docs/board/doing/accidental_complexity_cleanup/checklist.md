# checklist -- accidental_complexity_cleanup

**Branch (Phase C)**: `cleanup/accidental-complexity-batch-c` (off `main` @ `1effdc7a`). Batches A + B shipped earlier
on `cleanup/accidental-complexity-batch-a-b`, merged via PR #65 (`584aa2a1`).

**Status**: **ACTIVE** (resumed 2026-07-04) -- Phase C, the finishing phase. Batches A + B are on `main`. Phase C ships
the one real bug (**Defect B**), the last trivial deletion (**#17**), and the **Gap A** audit. **#18-#20 are Earned
(keep, no deletion)** -- touched only if already in the file; #19 is reassessed only after Defect B (coupled pair 2).

**Current focus**: Defect B (auth-retry provider-trace gap + regression test) -> #17 (drop two dead `CredentialManager`
methods + their tests) -> Gap A (audit fail-open emitters; fix only if the CLI prose-only check is a real gap). All
anchors below re-verified on `main` @ `1effdc7a` -- line numbers are current, not the card's pre-merge base.

**History**: Batches A + B merged via PR #65 (`584aa2a1`) with two pre-merge follow-ups folded into the squash (a
`FORGE_DEBUG` fail-open regression test `test_forge_debug_invalid_warns_and_ignores` + a `loader.py` black-format fix);
an 8-dimension adversarial review plus an independent `make pre-commit` + full touched-suite run came back clean before
merge.

**Scope note**: all anchors re-verified on this branch's HEAD before editing (zero-caller `grep` across `src/` +
`tests/`). Decisions locked before implementation: **#9 = wire** (read `ActiveSessionStore` at list time; keeps the
`--json` shape, makes the field truthful); **#5 = delete** (verified the sole caller feeds a single
`scan_passported_docs` walk whose `(official_path, write_path)` keys are unique by construction, so the dedup is a no-op
-- the doubling source was removed in `6ca53620`).

---

## Phase A -- dead code + trivial fixes

Order does not matter functionally; #1 (bug fix) and the trivial deletions lead to build trust.

- [x] **#1** `cli/backend.py`: extract `_stop_instance(adapter, port)` (core stop, no output/exit) shared by `stop_cmd`
  and `delete_cmd`. Assertion: `delete_cmd` no longer calls `stop_cmd.callback`; both `# type: ignore[misc]` gone; a
  single-instance delete prints exactly one "Stopped" line (no double), and a stop failure surfaces via `delete_cmd`'s
  own `print_error` (no nested `sys.exit` from `stop_cmd`). **Superseded 2026-07-03** by `backend_runtime_cleanup`:
  `delete --port` was removed, `stop` now targets runtime ids, and the old regression was deleted in favor of
  clean-break coverage in `tests/src/cli/test_backend_commands.py`.
- [x] **#2** Delete `src/forge/policy/semantic/promotion.py` (18-line docstring-only module, 0 importers). Assertion:
  `grep -rn "semantic.promotion\|import promotion" src tests` returns nothing; suite imports clean.
- [x] **#3** `install/settings_merge.py`: delete `resolve_template_paths()` (0 callers, empty placeholder dict).
  Assertion: `grep -rn resolve_template_paths src tests` returns only the deletion.
- [x] **#4** `config/loader.py`: delete `load_yaml_strict()` (0 callers) and drop the dangling "use load_yaml_strict()"
  line from `load_yaml`'s docstring. Assertion: `grep -rn load_yaml_strict src tests` empty.
- [x] **#5** `session/memory_writer.py`: delete `_dedupe_specs` (def + the `:523` call) and the obsolete
  `TestDedupeSpecs` class + import in `tests/src/session/test_memory_writer.py`. Assertion:
  `grep -rn _dedupe_specs src tests` empty; memory-writer unit tests pass; `run_memory_writer` still returns the same
  `ready_specs` for a unique-path scan.
- [x] **#6** `runtime_config.py`: delete `_coerce_env_value` and simplify `_apply_env_overrides` to the single real
  override (`FORGE_DEBUG -> log_level` via `_coerce_debug_to_log_level`); drop the now-unused `field_map`. Assertion:
  `FORGE_DEBUG=1/true/off/debug` still coerces; a bogus `FORGE_DEBUG` still warns-and-ignores (fail-open per field).
- [x] **#7** `proxy/provider_trace_logger.py`: import `RequestMode`/`LocalUsageStatus` from the owner
  `core/telemetry/downstream.py` (delete the identical local `Literal` re-declarations); repoint
  `responses_passthrough.py:27` to import `RequestMode` from `downstream`. Assertion: the two `Literal` values are
  byte-identical to downstream's; `grep -rn "RequestMode = Literal" src` shows only `downstream.py`; proxy tests pass.
- [x] **#8** `core/llm/credentials.py`: reword the module (`:3`) and class (`:193`) docstrings -- drop the false
  "proactive refresh" (there is no background task) to "lazy, on-access refresh". Comment-only. Assertion: no
  "proactive" left; behavior unchanged.
- [x] **#9 (wire)** `core/ops/session.py` `list_sessions`: populate `ListSessionsItem.is_active` via
  `ActiveSessionStore.is_session_active(name, forge_root=entry.forge_root or entry.worktree_path)` (best-effort; a
  liveness-probe failure degrades to `False`, matching the existing best-effort manifest read). Assertion: a live
  session lists `is_active=True`; a non-live one `False`; `forge session list --json` emits the truthful value.
- [x] **#10** `session/passport.py`: drop the unread `inherit_on_fork` field (`:101`), its parse+validate (`:419-424`),
  its constructor arg (`:451`), and the strip-on-write (`:483`); **keep** `"inherit_on_fork"` in `_KNOWN_UPDATE_KEYS`
  (`:84`) so old passports still parse (accept-and-ignore). Update tests: replace the three field-touching tests with
  one that parses a passport whose YAML `update` block carries `inherit_on_fork: false` and asserts it round-trips
  without error and without the key; drop the `inherit_on_fork=True` kwarg from `test_memory_writer.py:1742`. Assertion:
  an old passport with `inherit_on_fork` parses cleanly; new passports never serialize it.
- [x] **#11** `core/invoker/`: hoist the byte-identical `_worker_reason_code` and the identical
  `record_upstream_operation(...)` block into `_lifecycle.py` (beside `_status`) as `_worker_reason_code` +
  `_record_worker_upstream(attribution, result, status)`; `claude.py`/`codex.py` keep only their differing
  `emit_worker_usage`/`emit_codex_usage` line and call the shared helper. Assertion: the `operation=None` suppression
  contract holds (no upstream row emitted); invoker tests pass for both runtimes.
- [x] **#12** `core/reactive/cost_tracking.py`: delete `resolve_subprocess_proxy_url()` (0 callers, not in `__init__`;
  no test references it). Assertion: `grep -rn resolve_subprocess_proxy_url src tests` empty.
- [x] **#21** Delete the two stale CLI-alias doc lines (`authentication.md:144` `--provider/-p`; `session.md:871`
  `--template`/`--base-url` deprecated-alias line) and **reword** (not delete) the reachable guard at
  `session_lifecycle.py:868` to name `--proxy`/proxy routing instead of the nonexistent `--template`/`--base-url`.
  Assertion: the removed alias bullets are gone (no "Alias for `--credential`" line in `authentication.md`; no
  "deprecated hidden alias" line in `session.md`). The historical `--provider` *migration* table at
  `authentication.md:302` legitimately stays. The guard still fires for `--no-proxy` + routing.

### Acceptance tests (risky / behavior-touching items)

| Test                           | Fixture                                               | Assertion                                            | Test File                                                                           |
| ------------------------------ | ----------------------------------------------------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `is_active` truthful           | one live active-session entry + one dormant session   | live item `is_active is True`, dormant `False`       | `tests/src/core/ops/test_session_ops.py`                                            |
| `--json` emits live flag       | `session list --json --scope all` with a live session | JSON row `is_active: true`                           | `tests/src/cli/test_session_commands.py` (`test_list_json_reports_active_liveness`) |
| backend delete clean break     | `backend delete litellm --port 4000`                  | exits 2; no runtime stop path remains                | `tests/src/cli/test_backend_commands.py` (`test_delete_port_option_is_clean_break`) |
| old passport accept-and-ignore | YAML `update.inherit_on_fork: false`                  | parses without error; round-trips without the key    | `tests/src/session/test_passport.py`                                                |
| env override still coerces     | `FORGE_DEBUG=1` / bogus value                         | `log_level=debug` / warn-and-ignore                  | `tests/src/test_runtime_config.py`                                                  |
| upstream suppression holds     | invoker result with `attribution.operation=None`      | no upstream row recorded (usage event still emitted) | `tests/src/core/invoker/test_*.py`                                                  |

### Deferred / decisions

- None deferred in Batch A. (#5 and #9 decisions recorded above.)

---

## Phase B -- medium effort (verify byte-identity / add characterization test first)

Grounded 2026-07-01 by a 4-way read-only mapper sweep on this branch's HEAD; anchors below re-verified and card claims
corrected inline. Order: **#13 -> #14 -> (#15 + #16 pair)**. #13/#14 are independent; #15 and #16 both edit the same
gemini/openai `auth_url` vestige in `config/loader.py`, so they land together (or #15 first) to avoid a self-conflict.

### Decisions (locked 2026-07-01)

- **#14 = full delete** (not privatize). Delete `search()` outright and migrate its **12** `TestSearch` methods
  (`test_engine.py:167-311`, corrected from 11) plus the oracle onto `search_from_index`. Feasible and cheap: the two
  functions differ only in plumbing (`search` takes docs directly; `search_from_index` takes a built index +
  `content_loader`), not scoring -- every behavior the tests assert (score sort, `limit`, empty query/docs, all 6
  snippet cases, metadata) is the same BM25 + `_best_snippet` logic, so a single in-memory adapter carries them (see #14
  task). Accepted cost: the two-implementation score-equivalence oracle (`test_scores_match_legacy_search`) is retired
  -- migrated tests become characterization tests of `search_from_index` itself.
- **#16 = fail-fast + reset message** (not migrate-in-place). Validation runs on **read**:
  `load_proxy_instance_config_from_dict` (`loader.py:395-440`) constructs `ProxyInstanceConfig`, whose `__post_init__`
  re-validates `provider` (`schema.py:764`) every load, so narrowing `valid_providers` rejects **any** persisted
  `~/.forge/proxies/*/proxy.yaml` with `provider: gemini|openai` regardless of origin. The create flow never wrote those
  (`preferred_provider` -> `provider`, `loader.py:419/542`), so only hand-edited/legacy files are affected; local scan
  clean (`grep -rlE "provider:\s*(gemini|openai)" ~/.forge/proxies/*/proxy.yaml`, none 2026-07-01). Reject on load with
  a clear `ValueError` naming litellm/openrouter + the recreate command (durable-state clean break,
  `coding_standards §5`).

### Tasks

- [x] **#13** Move the 4 debate/consensus eval templates (359 LOC, verified) out of `cli/workflow.py` into
  `forge.review.resources` and drop the drift guard. Anchors: `_DEBATE_EVALUATION_TEMPLATE` (`:959`),
  `_CODE_DEBATE_EVALUATION_TEMPLATE` (`:1054`), `_CONSENSUS_EVALUATION_TEMPLATE` (`:1515`),
  `_CODE_CONSENSUS_EVALUATION_TEMPLATE` (`:1588`); consumed by `_resolve_debate_prompt` (`:1177-1178`) /
  `_resolve_consensus_prompt` (`:1700-1701`); mechanism `_load_workflow_resource` (`:206`, already used by
  `panel`/`analyze`); package `src/forge/review/resources/` (wheel-bundled via `pyproject.toml:82`). Steps: (1) write
  the 4 templates as `forge/review/resources/*_evaluation.md`; (2) switch the two `_resolve_*` functions to
  `_load_workflow_resource`; (3) delete the 4 constants **and** the now-false "so the CLI doesn't depend on skill
  installation" comments (`:958`, `:1053`); (4) delete the 2 drift-guard classes
  `TestConsensusTemplateEquivalence`/`TestDebateTemplateEquivalence` (`test_skill_content.py:438,454`); (5) delete the 4
  `src/skills/{debate,consensus}/resources/*_evaluation.md` copies -- **verified unread** (both skills invoke
  `forge workflow debate/consensus`, `SKILL.md:63/64`; they do not read the eval files). **Keep
  `consensus/resources/synthesis.md`** -- the consensus skill reads it (`SKILL.md:80`). Assertion (direct, no live
  workflow): mirror the existing `TestLoadWorkflowResource` pattern (`test_run_resources.py:10-28`) -- add 4 unit tests
  calling `_load_workflow_resource("{debate,code_debate,consensus,code_consensus}_evaluation.md")` and asserting marker
  strings load from `forge.review.resources`; add direct `_resolve_debate_prompt`/`_resolve_consensus_prompt` unit tests
  (pure `(subject, prompt, code_mode) -> str | None`, no network/model/proxy) asserting the loaded template wraps input.
  `git grep _DEBATE_EVALUATION_TEMPLATE` empty; single source in `forge.review.resources` (drift now impossible, not
  merely unguarded).
- [x] **#14 (full delete, decided)** Delete the legacy in-memory `search()` (`search/engine.py:202-248`) outright.
  Steps: (1) add a test-local adapter `_search_docs(query, docs, limit=...)` to `test_engine.py` that builds a
  `BM25IndexData` via the existing `_build_index_data` (`:333-352`) + a dict-backed `content_loader`, then calls
  `search_from_index` -- this restores each test's doc-in/results-out ergonomics with a one-token call swap; (2) point
  all **12** `TestSearch` methods (`test_engine.py:167-311`) at `_search_docs`; (3) delete the
  `test_scores_match_legacy_search` oracle (`:510-551`) -- with `search()` gone there is no second implementation to
  cross-check, so the surviving tests characterize `search_from_index` directly; (4) delete `search()` and drop
  `"search"` from `__all__` (`search/__init__.py:33`) + the `from .engine import` (`:13`). **Leave
  `SearchDocument.tokens`** -- read at rebuild-index (`extractor.py:223`, `cli/search.py:343`). Assertion:
  `grep -n "def search(" src/forge/search/engine.py` empty (only `search_from_index` remains);
  `grep -rn "from forge.search import search\b" src tests` empty; the 12 migrated tests pass through `search_from_index`
  with identical scores/snippets (same BM25 + `_best_snippet` on an index built from the same docs).
- [x] **#15 (caution -- auth)** Delete `ConfigSecretsProvider` (`core/auth/secrets.py:115-168`) + the **write-only**
  `auth_url` plumbing. Verified: no production chain builds it (`CredentialManager.default = Chain(Env, File)`,
  `credentials.py:240-243`); only non-test ref is a docstring (`secrets.py:214`); `ProviderConfig.auth_url`
  (`schema.py:156`) is written (`loader.py:271-272` from `OPENAI_AUTH_URL`/`GEMINI_AUTH_URL`) but never read. Steps:
  delete the class + `__init__` export; delete the `auth_url` field; remove the `*_AUTH_URL` mappings + extraction
  (`loader.py:271-272,521-525,533`); fix the `ChainSecretsProvider` docstring (`:214`). Test fallout (verified
  2026-07-01, card's "~29 tests" and my earlier "12 at :150-207" both wrong -- actual is **10** `test_secrets.py`
  methods spanning `:178-288`): **delete** the 4 direct `TestConfigSecretsProvider` methods (`:178,186,194,201`);
  **revise** the 6 `TestChainSecretsProvider` methods that construct `ConfigSecretsProvider` in the chain
  (`:213,229,244,259,274,288`) -- the two config-specific ones (`test_chain_env_overrides_config:229`,
  `test_chain_falls_through_to_config:244`) lose their premise and should be deleted; the other 4 rewrite to an Env+File
  chain to keep coverage. Two more files carry the env names: **delete** `test_load_config_with_lease_applies_secrets`
  (`test_loader.py:777-804`) -- it asserts `config.proxy.gemini.auth_url` from `GEMINI_AUTH_URL`, which this item
  removes (this is the test #16 wrongly called `test_secret_auth_url`); and **fix**
  `test_bug_h6_secret_coercion.py:24-27` -- drop the 2 `GEMINI_AUTH_URL` + 2 `OPENAI_AUTH_URL` parametrize cases (or
  replace with a "no `*_AUTH_URL` mapping remains" negative assertion). `test_credentials_file.py:103,111` merely
  round-trips `GEMINI_AUTH_URL` as an arbitrary profile key -- **unaffected**, leave it. Assertion:
  `grep -rn "ConfigSecretsProvider\|OPENAI_AUTH_URL\|GEMINI_AUTH_URL" src tests` returns only the round-trip fixture in
  `test_credentials_file.py`; secrets tests green with Env+File coverage intact.
- [x] **#16 (caution -- config)** Narrow proxy providers to `{litellm, openrouter}` with fail-fast. Verified root cause
  is **config validation**, not runtime: `ProxyInstanceConfig.__post_init__` accepts
  `{litellm, openai, gemini, openrouter}` (`schema.py:764`) but `ModelProvider` is `{LITELLM, OPENROUTER, UNKNOWN}`
  (`client_factory.py:81`), so `provider: gemini` validates then silently routes to LiteLLM (`loader.py:555-562` ->
  `_detect_provider:144` -> model-name detection). Steps: narrow `valid_providers` + raise a clear `ValueError` naming
  the two (with a migration hint to `litellm-gemini`/`openrouter`); delete the dead gemini/openai branches
  (`loader.py:522-525,555-558`); drop `*_AUTH_URL` from `env_to_dict` (coordinated with #15). **Do NOT touch**
  `ProviderType`'s `openai` catalog literal (`core/provider_types.py:11`) -- separate concern. No `provider='gemini'`
  test to re-point: the only such test, `test_load_config_with_lease_applies_secrets` (`test_loader.py:777`), is deleted
  under #15 (it depends on the removed `auth_url` field, so a `litellm` swap would not save it). Grep the two files for
  a surviving `provider='gemini'` proxy construction before finishing. Per the **#16 decision** above (fail-fast + reset
  message). Assertion: `ProxyInstanceConfig(provider='gemini')` raises the supported-two message; `litellm`/`openrouter`
  pass; `forge proxy create litellm-gemini` still works.

### Acceptance tests (Batch B)

| Test                               | Fixture                                                    | Assertion                                                              | Test File                             |
| ---------------------------------- | ---------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------------------- |
| eval templates load from resources | `_load_workflow_resource("debate_evaluation.md")` (direct) | 4 loader tests + `_resolve_*_prompt` unit tests pass; no live workflow | `tests/src/cli/test_run_resources.py` |
| search() deleted, tests via index  | 12 `TestSearch` via `_search_docs` adapter                 | no `def search(`; scores/snippets pinned through `search_from_index`   | `tests/src/search/test_engine.py`     |
| `ConfigSecretsProvider` gone       | Env+File chain only                                        | `grep` clean; Env/File secrets tests pass                              | `tests/src/core/auth/test_secrets.py` |
| provider fail-fast                 | `ProxyInstanceConfig(provider='gemini')`                   | raises `ValueError` naming litellm/openrouter                          | `tests/src/config/test_schema.py`     |
| create still works                 | `forge proxy create litellm-gemini`                        | proxy created (`provider=litellm` from template)                       | `tests/src/config/test_loader.py`     |

## Phase C -- finishing phase (real wins + owed decisions)

Order: **Defect B -> #17 -> Gap A**. Defect B is the only behavior change; #17 is a trivial deletion; Gap A is an audit
that may or may not produce a fix. #18-#20 are **Earned** and stay unless the file is already open (see "Keep" below).

### Committed work

- [x] **Defect B (confirmed, High -- real bug, not a cleanup)** `proxy/server.py`: the auth-retry success branch
  (`client_factory.invalidate_and_retry` at `:1610`, records cost + metrics via the two `latency_ms=retry_duration_ms`
  blocks at `:1634`/`:1648`) never calls `record_provider_trace` -- the only two call sites are the non-retry success
  paths (`:1394`, `:1478`). A 401 -> credential-refresh -> 200-on-retry therefore produces cost/metrics with **no**
  provider-trace record, the exact "what happened to this request?" gap the plane was built to close (origin: a
  supervised fork through OpenRouter). Fix: add one `record_provider_trace(...)` on the retry branch (the
  backend-capability gate lives inside the helper, so an unconditional call is safe). **Assertion**: a 401->refresh->200
  retry emits exactly one downstream provider-trace record carrying the retry's `request_id` + `latency_ms`; a
  non-provider-trace-capable backend still emits none. Regression:
  `tests/regression/test_bug_auth_retry_provider_trace.py`. **Verified 2026-07-04**: shipped as two commits -- a
  no-behavior `refactor(proxy)` routing all provider-trace sites through one shared `_trace_ctx` dict
  (`record_provider_trace(**_trace_ctx, ...)`; dropping the spread fails loudly on the missing required `request_id`, so
  a new path cannot silently omit the run-tree context -- the bug class Defect B was), then a `fix(proxy)` adding the
  retry-branch call via that spread. DRY (not a minimal add) kept `server.py` under the personal 2,500-line guardrail
  (2,494) while removing real duplication; the durable module-extraction is logged as a follow-up (see Deferred). The
  regression drives `create_message` through the retry branch with the **real** helper (no spy) under an isolated
  `FORGE_HOME`, then asserts on the observable outcome by reading the downstream plane back via
  `read_provider_traces(request_id=...)`: the capable case (`openrouter`, premise-guarded
  `capabilities.provider_trace is True`) reads exactly one record carrying `request_id`/`request_mode`/`latency_ms`; the
  non-capable case (`anthropic-passthrough`, premise-guarded `... is False`) reads `[]` (the read-side field filter
  drops the retry's cost-only record). Fail-first proof: with the fix reverted the capable test fails at the read-back
  (`got 0`, `assert 0 == 1`) while the non-capable test stays green; reapplying the fix -> 2 passed. The read-back (vs a
  call spy) is what makes the "exactly one readable record" and "gate holds" claims real -- it would catch a no-op
  helper, wrong backend, failed `downstream_event_id` merge, or gate regression.

- [x] **#17** Delete `CredentialManager.get_cache_status` (`core/llm/credentials.py:433`) and `.clear_cache` (`:456`) --
  no `src/` caller (the `proxy/client_factory.py:497,528` pair is a **different** class; leave it). Remove their direct
  tests in `tests/src/core/llm/test_credentials.py:180-206` (removed code -> delete test, testing_guidelines).
  **Assertion**: `grep -rn "get_cache_status\|clear_cache" src/forge/core/llm` returns nothing; the credentials suite is
  green with the two methods and their tests gone. **Verified 2026-07-04**: both methods deleted; `test_cache_status` +
  `test_clear_cache` removed; `test_invalidate_clears_cache` **rewritten** to read `cm._cache` directly (it borrowed the
  now-deleted `get_cache_status` but tests the kept `invalidate` -- refines the card's blunt "delete :180-206"). grep
  clean; `time`/`Any` imports still used (3/8); ruff clean; `test_credentials.py` 25 passed.

- [x] **Gap A (audit -> fix only if real)** `cli/policy.py::supervisor_evaluate` sets `passed` from prose-prefix
  matching only (`_INFRA_FAILURE_PREFIXES = ("Supervisor error:", "Supervisor skipped")` `:764`, applied `:920`), while
  the engine treats the **structural** `decision.fail_open` flag as authoritative (`engine.py:302,321`). Audit every
  `_supervisor_fail_open_decision` call site (`policy/semantic/supervisor.py:763,782,816,829,848,876,889`): does each
  emit a warning starting with one of the two prefixes? **If any sets `fail_open=True` with a non-matching/absent
  warning**, `forge policy supervisor evaluate` reports `passed=true`/exit-0 on a fail-open -- fix by having the CLI
  honor `decision.fail_open` (reuse the engine predicate `_warning_mentions_fail_open` / the flag) instead of prose
  only. **Assertion**: either (a) record the enumerated audit showing every fail-open warning carries a matching prefix
  and mark "not a gap", or (b) add a regression asserting `supervisor evaluate` exits 1 on a `fail_open=True` decision
  whose warning lacks the prefix. **Verified 2026-07-04 -- REAL gap**: 4 fail-open warnings miss the two prefixes
  (`Supervisor lane unavailable:` :816; `Codex supervisor lane needs an approved plan:` :829;
  `str(_SupervisorRoutingError)`, e.g. `Supervisor proxy '...' not found` :848/:562;
  `Supervisor verdict could not be parsed` :889). `invoke_supervisor` returns the raw decision, so `fail_open` is
  intact. Fix (`cli/policy.py:925`): `infra_failure` now also honors `decision.fail_open` (prose match kept as a
  fallback). Regressions `test_fail_open_without_infra_prefix_exits_2/_json` fail pre-fix (exit 0) and pass post-fix
  (exit **2**, not 1 -- infra_failure is exit 2; the earlier "exits 1" wording was wrong). Full
  `test_policy_supervisor.py` 79 passed.

### Keep -- Earned, no deletion (act only if already editing the file)

- [ ] **#18** `cli/claude.py:99-139` hand-rolls a 3rd copy of the proxy `GET /` identity gate. Earned (deliberate seam).
  Optional: extract an `assert_proxy_healthy` primitive -- **not** required to close the card.
- [x] **#19** `proxy/server.py` repeats per-outcome cost/metrics/provider-trace accounting ~5x. Earned (money/telemetry
  caution zone). **Reassessed after Defect B landed** (coupled pair 2): took the *thin* consolidation for the
  provider-trace **context** only -- one shared `_trace_ctx` dict spread (`**_trace_ctx`) at all three trace call sites,
  which is what let Defect B add its retry call without repeating 8 kwargs (and blocks the next silent-omission). The
  broader per-outcome cost/metrics blocks stay Earned/as-is (money path, genuine per-outcome divergence).
- [ ] **#20** `cli/workflow.py:1391,1723` `_parse_worker_specs`/`_parse_consensus_worker_specs` are near-identical.
  Earned; consolidating would surface the `code_mode` asymmetry (Minor C). Low value -- default: leave as-is.

### Resolved decisions (2026-07-04) -- now committed

- [x] **WorkflowPolicy: DEMOTE** (confirmed) -- make the current unshipped state explicit; do **not** graduate here, do
  **not** delete the pipeline. Sub-tasks:

  - Relabel the `docs/end-user/policy.md` workflow section **experimental / manifest-only**; state plainly there is no
    CLI enable/list surface -- the only activation is manually setting `policy.bundles: ["workflow"]` +
    `policy.bundle_config.workflow`.
  - Narrow/remove `get_all_bundles()` (verify its caller set first) so `workflow` is not advertised as a normal
    discoverable bundle when its only caller is tests; leave `BUNDLES` discovery + `policy enable --bundle`
    (`tdd`/`coding_standards`) untouched.
  - **Keep** the pipeline, registry path, and `build_divergence_config()` intact (no deletion).
  - File a follow-on `proposed/graduate_workflow_policy_cli/` card for the real `--workflow <preset>` UX + wiring
    `build_divergence_config` (product/docs/tests -- deliberately out of this cleanup card).
  - **Assertion**: `policy.md` names it experimental/manifest-only; `get_all_bundles` no longer advertises `workflow` to
    any non-test path; `policy list` / `policy enable --bundle` unchanged; the pipeline + `build_divergence_config`
    still import and run; the follow-on card exists in `proposed/`.
  - **Verified 2026-07-04**: `get_all_bundles()` had exactly one caller -- its own test. The CLI `list_bundles`/`enable`
    iterate `BUNDLES` directly and never included `workflow`, so deleting the function (clean-break) + its
    `test_workflow_in_all_bundles` removes the only place `workflow` was advertised as discoverable. Relabeled the
    `policy.md` header experimental/manifest-only and hardened the note ("no CLI surface... not in
    `forge policy list`"). Pipeline, `get_bundle_policies`, `get_bundle_for_policy`, `build_divergence_config`
    untouched; `proposed/graduate_workflow_policy_cli/card.md` filed. 578 policy tests + mypy green. **Review
    follow-up**: the `registry.py` module docstring still listed `workflow` as a flat "Available bundle"; reworded to
    split CLI-discoverable `BUNDLES` (tdd/coding_standards) from the dynamic manifest-only `workflow` path.

- [x] **Micro-cleanup (a) -- marker-schema doc drift** (confirmed in scope): reconcile `design_appendix §B` (says schema
  **v2**) with the code's emitted + strictly-accepted `schema_version` (`core/workqueue`). Verify which side is right,
  fix the drifted one. **Assertion**: doc and code agree (grep the emitted `schema_version` + the strict-read guard; one
  authoritative value). **Verified 2026-07-04**: code is authoritative -- `MARKER_SCHEMA_VERSION = 1`, `queue.py` emits
  1 and strictly rejects `!= 1`. The **doc** drifted; fixed `design_appendix §B.1` header `(v2) -> (v1)` + example
  `schema_version: 2 -> 1`. The unrelated downstream `schema_version=2` references (a different schema) stay.

- [x] **Micro-cleanup (b) -- Reporter/Confidence literal dedup** (confirmed in scope, #7-style): import
  `Reporter`/`Confidence` from their owner instead of re-declaring them in `core/telemetry/downstream.py`.
  **Assertion**: the literals are defined once (owner only); `grep` shows no duplicate
  `Reporter = Literal`/`Confidence = Literal`; telemetry tests pass. **Verified 2026-07-04 -- direction reversed from
  the card's assumption**: `vocabulary.py` could not be the sole owner (the card's guess) because `core/usage/__init__`
  eagerly imports `emit -> downstream`, so `downstream` importing `usage.vocabulary` cycles; de-coupling `__init__` was
  out (~12 `from core.usage import emit_*` consumers). Instead defined both **once** in a new neutral leaf
  `core/telemetry/vocabulary.py` (imports only `typing`, sits below `downstream`); `downstream` and `usage/vocabulary`
  import + re-export it (all consumer import sites unchanged; `__all__` marks the re-exports). Import smoke test shows
  no cycle and one shared object; 830 telemetry/usage/proxy tests + mypy/pyright/ruff green.

### Deferred (Phase C)

- [ ] **`server.py` at the 2,500-line guardrail** (surfaced by Defect B): the file sits at **2,494** after the
  provider-trace DRY -- durable headroom needs a real extraction, not more line-golf. Extract cohesive module-level
  helpers (e.g. reasoning/verbosity/hyperparameter mapping, `_request_log_config`) into a sibling module; the
  `create_message` hot path stays put. Own card/commit, deliberately out of this cleanup's scope. **Trigger**: next time
  `server.py` growth is blocked, or as a standalone `proposed/` card.

### Acceptance tests (Phase C)

| Test                            | Fixture                                                                        | Assertion                                                                             | Test File                                                |
| ------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| auth-retry emits provider-trace | 401 -> credential refresh -> 200 on retry, provider-trace-capable backend      | exactly one downstream provider-trace record with the retry `request_id`/`latency_ms` | `tests/regression/test_bug_auth_retry_provider_trace.py` |
| retry trace gated by capability | same retry, non-capable backend                                                | no provider-trace record emitted (helper gate holds)                                  | `tests/regression/test_bug_auth_retry_provider_trace.py` |
| #17 methods gone                | --                                                                             | `grep` clean in `core/llm`; credentials suite green                                   | `tests/src/core/llm/test_credentials.py`                 |
| Gap A (real; fixed)             | `fail_open=True` decision, warning without an `_INFRA_FAILURE_PREFIXES` prefix | `supervisor evaluate` exits 2 (not 0)                                                 | `tests/src/cli/test_policy_supervisor.py`                |
| WorkflowPolicy demoted          | --                                                                             | `get_all_bundles` gone; `policy list`/`enable` unchanged; pipeline still imports      | `tests/src/policy/workflow/test_registry_integration.py` |
| marker schema doc = code        | --                                                                             | `design_appendix §B.1` says v1, matching `MARKER_SCHEMA_VERSION`                      | (doc-only)                                               |
| Reporter/Confidence single-src  | import from `downstream` and `usage.vocabulary`                                | no duplicate `Literal` decl; both resolve to the one leaf object; no import cycle     | `tests/src/core/telemetry/`, `tests/src/core/usage/`     |

### Phase C closeout

- [x] `make pre-commit` clean (ruff, black, isort, mypy, pyright, mdformat, gitleaks) across all touched files.
- [x] Focused suites green: proxy provider-trace/server, `test_credentials.py`, policy supervisor, policy/workflow,
  telemetry + usage (830 + 578 + 25 + ... all green across the touched packages).
- [x] **Integration run** (Defect B touches the proxy request path): user ran the **full integration suite green**
  (2026-07-04), covering the proxy provider-trace E2E path.
- [x] `change_log.md` entry (feature-completion size) covering Defect B + #17 + Gap A + WorkflowPolicy DEMOTE + the two
  micro-cleanups.
- [x] Promoted two durable lessons to `impl_notes.md` (2026-07-04, human-approved): every proxy success path -- incl.
  auth-retry -- must emit provider-trace (the `_trace_ctx`-spread guard); and shared cost/usage vocabulary Literals live
  in the `core/telemetry/vocabulary.py` leaf, never in `core/usage`, because `usage/__init__ -> emit -> downstream`
  cycles.
- [x] Docs synced: WorkflowPolicy decision landed in `policy.md` (experimental/manifest-only); marker-schema doc drift
  fixed in `design_appendix §B.1`.
- [ ] Card moved `doing/ -> done/` after merge to `main`.

---

## Closeout (Batch A)

- [x] `make pre-commit` clean (ruff, black, isort, mypy, pyright, mdformat, gitleaks).
- [x] Unit suite green (`7222 passed`). Docker/real-Claude integration tier **not run**: the #5/#9/#21 changes are
  dead-code/no-op removals + a list-time read that do not alter the `claude -p`/hook/Docker dispatch path.
- [x] `change_log.md` entry (feature-completion size) summarizing Batch A.
- [x] Design/end-user docs synced: `authentication.md` + `session.md` (#21 removals); verified no design doc references
  the deleted symbols (`grep` clean across `docs/design*.md`, `cli_reference.md`).
- [x] Batches A + B merged to `main` via PR #65 (`584aa2a1`). Card moved `doing/ -> paused/` (not `done/`): Batch C
  (#17-#20) + Defect B + Gap A remain open. Resume from the Phase C stub.

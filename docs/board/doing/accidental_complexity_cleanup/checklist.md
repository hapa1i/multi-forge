# checklist -- accidental_complexity_cleanup

**Branch**: `cleanup/accidental-complexity-batch-a`

**Current focus**: Batches A + B **implemented + verified**. Batch B (#13-#16) shipped in 4 commits; targeted unit
suites green per item, #15/#16 integration-verified (auth credential resolution 4 passed, proxy commands 27 passed), and
a 4-way adversarial review came back clean save one stale comment (fixed). Card stays in `doing/` while Batch C remains
(stub below).

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
  own `print_error` (no nested `sys.exit` from `stop_cmd`).
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

| Test                             | Fixture                                               | Assertion                                            | Test File                                                                           |
| -------------------------------- | ----------------------------------------------------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `is_active` truthful             | one live active-session entry + one dormant session   | live item `is_active is True`, dormant `False`       | `tests/src/core/ops/test_session_ops.py`                                            |
| `--json` emits live flag         | `session list --json --scope all` with a live session | JSON row `is_active: true`                           | `tests/src/cli/test_session_commands.py` (`test_list_json_reports_active_liveness`) |
| backend delete: single "Stopped" | one running instance, `backend delete --port -y`      | exactly one "Stopped" line; no nested exit           | `tests/regression/test_bug_backend_delete_double_stop.py`                           |
| old passport accept-and-ignore   | YAML `update.inherit_on_fork: false`                  | parses without error; round-trips without the key    | `tests/src/session/test_passport.py`                                                |
| env override still coerces       | `FORGE_DEBUG=1` / bogus value                         | `log_level=debug` / warn-and-ignore                  | `tests/src/test_runtime_config.py`                                                  |
| upstream suppression holds       | invoker result with `attribution.operation=None`      | no upstream row recorded (usage event still emitted) | `tests/src/core/invoker/test_*.py`                                                  |

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

## Phase C -- optional / low-value -- STUB

Items #17-#20 per `card.md` (mostly Earned; #17 drops two dead methods). Plus surfaced defects: **Defect B** (auth-retry
provider-trace gap -- needs a regression test) and **Gap A** (policy fail-open prose-only check -- needs the fail-open
emitter audit before deciding if it is a real gap).

---

## Closeout (Batch A)

- [x] `make pre-commit` clean (ruff, black, isort, mypy, pyright, mdformat, gitleaks).
- [x] Unit suite green (`7222 passed`). Docker/real-Claude integration tier **not run**: the #5/#9/#21 changes are
  dead-code/no-op removals + a list-time read that do not alter the `claude -p`/hook/Docker dispatch path.
- [x] `change_log.md` entry (feature-completion size) summarizing Batch A.
- [x] Design/end-user docs synced: `authentication.md` + `session.md` (#21 removals); verified no design doc references
  the deleted symbols (`grep` clean across `docs/design*.md`, `cli_reference.md`).
- [ ] Card moved `doing/ -> done/` only after merge to `main` (per board contract); this card stays in `doing/` while
  Batches B/C remain open.

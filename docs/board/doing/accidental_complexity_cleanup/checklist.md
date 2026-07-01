# checklist -- accidental_complexity_cleanup

**Branch**: `cleanup/accidental-complexity-batch-a`

**Current focus**: Batch A **implemented + verified** (full unit suite `7222 passed`; ruff + mypy clean). Awaiting
`make pre-commit` + merge. Batches B/C are stubs below -- populate when picked up.

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
  Assertion: `grep -rn "\-\-provider\|deprecated hidden alias" docs/end-user` clean; the guard still fires for
  `--no-proxy` + routing.

### Acceptance tests (risky / behavior-touching items)

| Test                             | Fixture                                             | Assertion                                                | Test File                            |
| -------------------------------- | --------------------------------------------------- | -------------------------------------------------------- | ------------------------------------ |
| `is_active` truthful             | one live active-session entry + one dormant session | live item `is_active is True`, dormant `False`           | `tests/src/core/ops/test_session.py` |
| `--json` emits live flag         | `forge session list --json` with a live session     | JSON row `is_active: true`                               | existing `session_manage` CLI test   |
| backend delete: single "Stopped" | one running instance, `backend delete --port -y`    | exactly one "Stopped" line; no nested exit on stop error | `tests/src/cli/test_backend*.py`     |
| old passport accept-and-ignore   | YAML `update.inherit_on_fork: false`                | parses without error; round-trips without the key        | `tests/src/session/test_passport.py` |
| env override still coerces       | `FORGE_DEBUG=1` / bogus value                       | `log_level=debug` / warn-and-ignore                      | `tests/src/test_runtime_config.py`   |
| upstream suppression holds       | invoker result with `attribution.operation=None`    | no upstream row recorded (usage event still emitted)     | `tests/src/core/invoker/test_*.py`   |

### Deferred / decisions

- None deferred in Batch A. (#5 and #9 decisions recorded above.)

---

## Phase B -- medium effort (add characterization test first) -- STUB

Items #13-#16 per `card.md`. Populate assertions when picked up. #15+#16 are a coupled pair (same gemini/openai
`auth_url` vestige); #16 gated on team confirmation no hand-written `provider: gemini/openai` proxy.yaml exists.

## Phase C -- optional / low-value -- STUB

Items #17-#20 per `card.md` (mostly Earned; #17 drops two dead methods). Plus surfaced defects: **Defect B** (auth-retry
provider-trace gap -- needs a regression test) and **Gap A** (policy fail-open prose-only check -- needs the fail-open
emitter audit before deciding if it is a real gap).

---

## Closeout (Batch A)

- [ ] `make pre-commit` clean (ruff, black, isort, mypy, pyright, mdformat, gitleaks).
- [ ] Unit suite green; targeted integration for memory-writer/session paths where touched (#5, #9, #21).
- [ ] `change_log.md` entry (feature-completion size) summarizing Batch A.
- [ ] Design/end-user docs synced: `docs/end-user/authentication.md` + `session.md` (#21 removals); confirm no design
  doc references the deleted symbols.
- [ ] Card moved `doing/ -> done/` only after merge to `main` (per board contract); this card stays in `doing/` while
  Batches B/C remain open.

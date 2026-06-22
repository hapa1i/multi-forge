# Checklist: OpenRouter `user` injection — unified global toggle

Execution plan for `feat/openrouter-user-direct-callers`. Card: [card.md](card.md).

## Current focus

**Done (2026-06-20).** All five phases shipped: the unified global toggle, the proxied-gate repoint, the sidecar
config.yaml mount, and direct-caller injection (plan-check, curation), with docs, changelog, and impl_notes synced. 432
unit tests green across all touched files; the sidecar integration run passed in Docker (config.yaml mount, in-container
toggle read); mypy, pyright, and `make pre-commit` clean. Card moved to `done/`.

## Decision (load-bearing)

**One toggle governs both paths**, living in `~/.forge/config.yaml` as `provider_trace.inject_provider_user`. Chosen on
the principle *product experience drives architecture*: a single user-facing switch beats two per-scope homes, even
though it requires changing the sidecar mount boundary.

- **Rejected**: separate homes (proxied stays per-proxy `proxy.yaml`, direct gets `config.yaml`). Additive and
  sidecar-safe, but exposes two switches for one conceptual feature.
- **Accepted costs** (all verified against the code before deciding):
  1. Proxied gate (`_inject_provider_user_enabled`, `proxy/server.py`) repoints from `config.proxy.provider_trace` to
     `get_runtime_config().provider_trace` — same pattern as the proxy already using
     `get_runtime_config().auth_ignore_env`.
  2. Sidecar must mount `~/.forge/config.yaml` (ro) or proxied injection silently breaks in-container (the incident
     path: supervised forks can run in sidecar). Narrow, read-only, single file — same shape as the existing
     `proxies/<id>/` mount.
  3. `proxy.yaml`'s `provider_trace.inject_provider_user` is deprecated → warn-and-degrade (user-owned config is a
     system boundary; do not reject). Retention keys (`retention_days`, `max_total_mb`) stay proxy-owned in
     `proxy.yaml`.
  4. Per-proxy granularity is lost (acceptable for an observability-only grouping id; probe 4 confirmed it is
     stickiness-neutral).

## Phases

### Phase 1 — Global toggle in runtime config ✅

- [x] Added nested `RuntimeProviderTraceConfig(inject_provider_user: bool = False)` + `RuntimeConfig.provider_trace`
  (`src/forge/runtime_config.py`), mirroring `StatusLineConfig`.
  `get_runtime_config().provider_trace.inject_provider_user` defaults `False`, `True` when set. Default config content
  documents it.
- [x] Loader is **fail-open**: `_coerce_bool` accepts quoted `"true"`/`"false"` (no silent degrade); a non-bool subtree
  warns and resets only `provider_trace`; unknown sub-keys dropped (forward compat). set/edit keep the strict raise.
- [x] `forge config set provider_trace.inject_provider_user=true` round-trips — generalized `_set_nested_key` to a
  section registry (`_nested_sections`) instead of hardcoding `statusline`. Invalid value / unknown subkey rejected at
  the CLI. (Also removed a dead `key` param from `_coerce_value` surfaced while editing.)
- [x] Tests: `tests/src/test_runtime_config.py` (`TestProviderTraceConfig{Defaults,Load}`) +
  `tests/src/cli/test_config_cli.py` (`TestConfigSetProviderTrace`). **130 passed; mypy + pyright clean.**

### Phase 2 — Repoint proxied gate + deprecate the proxy.yaml key ✅

- [x] `_inject_provider_user_enabled()` (`proxy/server.py`) now reads
  `get_runtime_config().provider_trace.inject_provider_user` (the only reader of the flag, grep-confirmed). The
  `_provider_user_value` capability gate (`backend_id` declares `provider_user_grouping`) is unchanged.
- [x] `ProviderTraceConfig` (`config/schema.py`) is retention-only; `_coerce_provider_trace_config` pops **both**
  `inject_provider_user` and legacy `inject_openrouter_user` with a one-time relocation warning naming
  `~/.forge/config.yaml` + the `forge config set` command. Updated the `runtime_config.py` module docstring (the proxy
  may read specific non-routing fields; the old "never" claim was false).
- [x] Tests: gate-reads-runtime-config (`test_routing_invariants.py`), schema retention + relocated-key-accepted
  (`test_schema.py`), regression renamed `test_bug_provider_trace_inject_alias.py` →
  `test_bug_proxy_yaml_inject_key_relocated.py` (rewritten for warn-and-degrade), loader-drop regression assertions
  swapped to retention. `test_server_forge_headers.py` needed no change (param-driven `_provider_user_value`). **234
  focused + 782 proxy/config green; mypy+pyright clean.**

### Phase 3 — Sidecar carries config.yaml ✅

- [x] `_ensure_audit_plumbing_mounts` (`sidecar/container.py`) appends `(config.yaml, .../config.yaml, ro)` **only when
  the host file exists** (Docker bind source must pre-exist; absent ⇒ toggle defaults off ⇒ mount is the correct no-op).
  Container path `/root/.forge/config.yaml` is exactly where the in-container `get_runtime_config()` reads.
- [x] Function docstring records config.yaml as a deliberate narrow ro mount (design §7 update lands in Phase 5 doc
  sync).
- [x] Tests: `tests/src/sidecar/test_container.py` (present → mounted ro; absent → omitted). **38 sidecar tests green;
  pyright clean.** Integration run (sidecar/proxy runtime touch) deferred to closeout per testing_guidelines.

### Phase 4 — Direct-caller injection (the card feature) ✅

- [x] `with_openrouter_user(hyperparams, user_id)` in `core/usage/correlation.py` — deep-copy, **no-clobber**
  (`setdefault` preserves an explicit caller `extra["openai"]["user"]`), preserves sibling `openai` extras (composes
  with `with_forge_request_id`'s `extra_headers`). Exported from `core/usage/__init__.py`.
- [x] `resolve_direct_provider_user(role) -> str | None` (same module): reads the **unified** flag; `None` if off; reads
  `FORGE_SESSION` + `FORGE_ROOT_RUN_ID` **with `FORGE_RUN_ID` fallback for root** (parity with `reactive/env.py:467`);
  `None` when no identity; else `derive_provider_session_id(session, root, role)`. Broad-except → `None`: never raises.
- [x] Wired into `run_plan_check` (`policy/semantic/plan_check.py`): added `_effective_provider` (explicit-wins, detect
  as fallback) and gate `== "openrouter"`; chained the additive wrappers (effort → request-id → user), dropping the
  `merge_hyperparams` indirection. Role = `"plan-check"`.
- [x] Wired into curation (`session/transfer.py` `_call_llm_for_curation`): provider is always
  `AI_CURATION_PROVIDER == "openrouter"`, so applied on any non-None `uid`. Role = `"transfer-curate"`.
- [x] Tagger stays out — the existing `tagger.py:57-58` comment already documents "local LiteLLM … not a
  provider-user-grouping-capable source"; no code change needed.
- [x] Tests (21 new): `test_correlation.py` (`TestWithOpenrouterUser` ×4 + `TestResolveDirectProviderUser` ×7, incl.
  `test_matches_proxied_derivation` for cross-plane id equality and `test_never_raises_degrades_to_none` for fail-open);
  `test_plan_check.py` (`TestRunPlanCheckProviderUser` ×5: openrouter+flag, flag-off, non-openrouter, no-leak,
  derivation match); `test_transfer.py` (`TestCurationProviderUser` ×4: flag-on, flag-off, run-fallback, no-leak). **432
  passed across all touched files; mypy + pyright clean on changed source + tests.**

### Phase 5 — Docs, changelog, closeout

- [x] design.md §3.14 + appendix §A.14: toggle is now a **global** `config.yaml` setting governing both proxied and
  direct OpenRouter routes; `proxy.yaml` key deprecated → retention-only; sidecar mounts config.yaml; both planes derive
  the id from the same `derive_provider_session_id`.
- [x] end-user `config.md` (new global toggle + `forge config set` example, beside `upstream_event_volume`) and
  `proxy.md` (rewrote the per-proxy section → global + migration note). `cli_reference.md` confirmed clean (no new
  command surface; grep found no `inject_*` references).
- [x] `change_log.md`: feature + **breaking-change** entry (proxy.yaml `provider_trace.inject_provider_user` →
  `~/.forge/config.yaml`) with the `forge config set` migration path.
- [x] Promoted durable lessons to `impl_notes.md` (ownership test for both-plane config; sidecar must mount any host
  config the in-container proxy reads; write-vs-load boundary asymmetry; cross-plane id equality). Human review via PR.
- [x] **Sidecar integration run recorded**: extended `tests/integration/sidecar/test_audit_plumbing.py` to mount
  `config.yaml` (mirroring `_ensure_audit_plumbing_mounts`) and assert the in-container `get_runtime_config()` reads the
  toggle. **Passed in Docker (1 passed in 5.12s).**
- [x] `make pre-commit` clean (ruff, black, isort, mypy, pyright, mdformat, gitleaks all pass).
- [x] Move card `doing/ → done/` (this commit).

## Acceptance tests (fixture-grounded)

| Test                            | Fixture                                                      | Assertion                                                                        | Test File                                                                            |
| ------------------------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Global flag default off         | fresh `~/.forge/config.yaml` absent                          | `get_runtime_config().provider_trace.inject_provider_user is False`              | `tests/src/test_runtime_config.py`                                                   |
| Global flag on                  | config.yaml sets `provider_trace.inject_provider_user: true` | accessor returns `True`                                                          | `tests/src/test_runtime_config.py`                                                   |
| Proxied gate reads runtime flag | runtime flag on, capable backend                             | `_provider_user_value(...)` returns a non-None id                                | `tests/src/proxy/test_server_forge_headers.py`                                       |
| proxy.yaml key deprecated       | proxy.yaml has `provider_trace.inject_provider_user: true`   | loads, warns once, value ignored                                                 | `tests/regression/test_bug_proxy_yaml_inject_key_relocated.py`                       |
| Sidecar mounts config.yaml      | host config.yaml exists                                      | mount list has `(…/config.yaml, ro)`                                             | `tests/src/sidecar/test_container.py`                                                |
| Direct plan-check injects       | flag on, route openrouter, `FORGE_SESSION` set               | `hp.extra["openai"]["user"] == derive_provider_session_id(...)`                  | `tests/src/policy/semantic/test_plan_check.py`                                       |
| No-clobber                      | `hp` already has `extra["openai"]["user"]`                   | `with_openrouter_user` returns it unchanged                                      | `tests/src/core/usage/test_correlation.py`                                           |
| Cross-plane id match            | flag on, session+root set                                    | direct id `== derive_provider_session_id(session, root, role)` (== proxied path) | `tests/src/core/usage/test_correlation.py`                                           |
| No name leak                    | `FORGE_SESSION="super-secret-session-name"`                  | injected value is `forge_sess_<hash>`; the raw name never appears                | `tests/src/policy/semantic/test_plan_check.py`, `tests/src/session/test_transfer.py` |
| Fail-open                       | config read raises in resolver                               | resolver returns `None` (no injection); never raises into the caller             | `tests/src/core/usage/test_correlation.py`                                           |

## Review fixes (post Phase 1–3)

- [x] **Edit-path fail-open hole** (review note): `forge config edit` validated by constructing `RuntimeConfig`, which
  runs the loader's forward-compat coercion and silently DROPS unknown nested subkeys — so a typo like
  `provider_trace.inject_provider_usre: true` passed validation, persisted, and left the toggle off. Added explicit
  write-surface unknown-subkey validation to `edit_cmd` (reuses `_nested_sections()`, covers `provider_trace` AND
  `statusline`), restoring parity with `set` (fail-closed). Loader stays fail-open by design. Regressions:
  `test_edit_rejects_unknown_provider_trace_subkey` + `test_edit_accepts_valid_provider_trace` (45 CLI tests green).
- [x] **Stale active-card status** (review note): the moved `card.md` still said `Status: Todo` with the flag-home
  question framed as open — confusing for the next `gather-context` session. Set `Status: Doing` and marked the
  open-question RESOLVED (one toggle governs both), pointing to the checklist Decision.

## Notes / open items

- **Flag shape revisitable**: nested `provider_trace.inject_provider_user` chosen for conceptual grouping + symmetry. If
  `forge config set` nested-key support is awkward, reconsider a flat `inject_provider_user` (UX-driven).
- **Role labels**: `plan-check` / `transfer-curate` (match the usage-ledger `command` names). Base groups by session;
  role is a sub-group suffix.
- **Integration tier required** before closeout (sidecar + proxy runtime change) per testing-guidelines.

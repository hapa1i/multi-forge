# Checklist: OpenRouter `user` injection — unified global toggle

Execution plan for `feat/openrouter-user-direct-callers`. Card: [card.md](card.md).

## Current focus

Phase 4 — direct-caller injection (the card feature): `with_openrouter_user` helper + wire into
plan-check and transfer curation. (Phases 1–3 done — the unified-toggle infrastructure: runtime
toggle, proxied gate repoint, sidecar mount. 1054+ tests green across the touched areas;
mypy+pyright clean. Sidecar integration run deferred to closeout per testing-guidelines.)

## Decision (load-bearing)

**One toggle governs both paths**, living in `~/.forge/config.yaml` as
`provider_trace.inject_provider_user`. Chosen on the principle *product experience drives architecture*: a single
user-facing switch beats two per-scope homes, even though it requires changing the sidecar mount boundary.

- **Rejected**: separate homes (proxied stays per-proxy `proxy.yaml`, direct gets `config.yaml`). Additive and
  sidecar-safe, but exposes two switches for one conceptual feature.
- **Accepted costs** (all verified against the code before deciding):
  1. Proxied gate (`_inject_provider_user_enabled`, `proxy/server.py`) repoints from `config.proxy.provider_trace` to
     `get_runtime_config().provider_trace` — same pattern as the proxy already using `get_runtime_config().auth_ignore_env`.
  2. Sidecar must mount `~/.forge/config.yaml` (ro) or proxied injection silently breaks in-container (the incident path:
     supervised forks can run in sidecar). Narrow, read-only, single file — same shape as the existing `proxies/<id>/` mount.
  3. `proxy.yaml`'s `provider_trace.inject_provider_user` is deprecated → warn-and-degrade (user-owned config is a system
     boundary; do not reject). Retention keys (`retention_days`, `max_total_mb`) stay proxy-owned in `proxy.yaml`.
  4. Per-proxy granularity is lost (acceptable for an observability-only grouping id; probe 4 confirmed it is
     stickiness-neutral).

## Phases

### Phase 1 — Global toggle in runtime config ✅

- [x] Added nested `RuntimeProviderTraceConfig(inject_provider_user: bool = False)` + `RuntimeConfig.provider_trace`
      (`src/forge/runtime_config.py`), mirroring `StatusLineConfig`. `get_runtime_config().provider_trace.inject_provider_user`
      defaults `False`, `True` when set. Default config content documents it.
- [x] Loader is **fail-open**: `_coerce_bool` accepts quoted `"true"`/`"false"` (no silent degrade); a non-bool subtree
      warns and resets only `provider_trace`; unknown sub-keys dropped (forward compat). set/edit keep the strict raise.
- [x] `forge config set provider_trace.inject_provider_user=true` round-trips — generalized `_set_nested_key` to a
      section registry (`_nested_sections`) instead of hardcoding `statusline`. Invalid value / unknown subkey rejected
      at the CLI. (Also removed a dead `key` param from `_coerce_value` surfaced while editing.)
- [x] Tests: `tests/src/test_runtime_config.py` (`TestProviderTraceConfig{Defaults,Load}`) +
      `tests/src/cli/test_config_cli.py` (`TestConfigSetProviderTrace`). **130 passed; mypy + pyright clean.**

### Phase 2 — Repoint proxied gate + deprecate the proxy.yaml key ✅

- [x] `_inject_provider_user_enabled()` (`proxy/server.py`) now reads
      `get_runtime_config().provider_trace.inject_provider_user` (the only reader of the flag, grep-confirmed). The
      `_provider_user_value` capability gate (`backend_id` declares `provider_user_grouping`) is unchanged.
- [x] `ProviderTraceConfig` (`config/schema.py`) is retention-only; `_coerce_provider_trace_config` pops **both**
      `inject_provider_user` and legacy `inject_openrouter_user` with a one-time relocation warning naming
      `~/.forge/config.yaml` + the `forge config set` command. Updated the `runtime_config.py` module docstring (the
      proxy may read specific non-routing fields; the old "never" claim was false).
- [x] Tests: gate-reads-runtime-config (`test_routing_invariants.py`), schema retention + relocated-key-accepted
      (`test_schema.py`), regression renamed `test_bug_provider_trace_inject_alias.py` →
      `test_bug_proxy_yaml_inject_key_relocated.py` (rewritten for warn-and-degrade), loader-drop regression assertions
      swapped to retention. `test_server_forge_headers.py` needed no change (param-driven `_provider_user_value`).
      **234 focused + 782 proxy/config green; mypy+pyright clean.**

### Phase 3 — Sidecar carries config.yaml ✅

- [x] `_ensure_audit_plumbing_mounts` (`sidecar/container.py`) appends `(config.yaml, .../config.yaml, ro)` **only when
      the host file exists** (Docker bind source must pre-exist; absent ⇒ toggle defaults off ⇒ mount is the correct
      no-op). Container path `/root/.forge/config.yaml` is exactly where the in-container `get_runtime_config()` reads.
- [x] Function docstring records config.yaml as a deliberate narrow ro mount (design §7 update lands in Phase 5 doc sync).
- [x] Tests: `tests/src/sidecar/test_container.py` (present → mounted ro; absent → omitted). **38 sidecar tests green;
      pyright clean.** Integration run (sidecar/proxy runtime touch) deferred to closeout per testing-guidelines.

### Phase 4 — Direct-caller injection (the card feature)

- [ ] `with_openrouter_user(hyperparams, user_id)` in `core/usage/correlation.py` — deep-copy, **no-clobber** (preserve an
      explicit caller `extra["openai"]["user"]`), sets `extra["openai"]["user"] = user_id`. Mirrors
      `with_forge_request_id`'s shape. Export from `core/usage/__init__.py`.
- [ ] `resolve_direct_provider_user(role) -> str | None` (same module): reads the **unified** flag
      (`get_runtime_config().provider_trace.inject_provider_user`); returns `None` if off; reads `FORGE_SESSION` +
      `FORGE_ROOT_RUN_ID`; returns `None` when neither is set (nothing to group by); else
      `derive_provider_session_id(session, root, role)`. Defensive (broad-except → `None`): never raises into a caller.
- [ ] Wire into `run_plan_check` (`policy/semantic/plan_check.py`): after `hp` is built, gate on the **resolved route
      provider == "openrouter"**, apply `hp = with_openrouter_user(hp, uid)` when `uid` is non-None. Role = `"plan-check"`.
- [ ] Wire into curation (`session/transfer.py`): provider is always `AI_CURATION_PROVIDER == "openrouter"`, so apply
      unconditionally on a non-None `uid`. Role = `"transfer-curate"`.
- [ ] Tagger stays out (routes via local LiteLLM; cannot reach OpenRouter) — confirm the existing explanatory comment is
      present; no code change.
- [ ] Tests: `tests/src/core/usage/test_correlation.py` (no-clobber, deep-copy, sets user; resolver flag-off/no-env/derives);
      `tests/src/policy/semantic/test_plan_check.py` (injects on openrouter+flag; skips when provider≠openrouter or flag off;
      **no-path-leak**: injected value matches `forge_sess_…`/`forge_run_…`, never the raw session name or a path; fail-open:
      a forced derive error leaves the check working); `tests/src/session/test_transfer*.py` (curation injects).

### Phase 5 — Docs, changelog, closeout

- [ ] design.md §3.14 + appendix §A.14: the toggle is now a **global** `config.yaml` setting governing both proxied and
      direct OpenRouter routes; `proxy.yaml` key deprecated; sidecar mounts config.yaml; retention stays proxy-owned.
- [ ] end-user `config.md` (new global toggle + `forge config set` example) and `proxy.md` (migration note: the per-proxy
      key moved). Confirm `cli_reference.md` needs no change (no new command surface).
- [ ] `change_log.md`: feature + **breaking-change** entry (proxy.yaml `provider_trace.inject_provider_user` →
      `~/.forge/config.yaml`), with the migration path.
- [ ] Promote durable lessons to `impl_notes.md` after review (the mount-boundary rationale; unified-toggle ownership split;
      the warn-and-degrade migration pattern for a relocated user-config key).
- [ ] `make pre-commit` clean; focused unit suites green; the Phase 3 sidecar integration run recorded.
- [ ] Move card `doing/ → done/`.

## Acceptance tests (fixture-grounded)

| Test | Fixture | Assertion | Test File |
| ---- | ------- | --------- | --------- |
| Global flag default off | fresh `~/.forge/config.yaml` absent | `get_runtime_config().provider_trace.inject_provider_user is False` | `tests/src/test_runtime_config.py` |
| Global flag on | config.yaml sets `provider_trace.inject_provider_user: true` | accessor returns `True` | `tests/src/test_runtime_config.py` |
| Proxied gate reads runtime flag | runtime flag on, capable backend | `_provider_user_value(...)` returns a non-None id | `tests/src/proxy/test_server_forge_headers.py` |
| proxy.yaml key deprecated | proxy.yaml has `provider_trace.inject_provider_user: true` | loads, warns once, value ignored | `tests/regression/test_bug_proxy_yaml_inject_key_deprecated.py` |
| Sidecar mounts config.yaml | host config.yaml exists | mount list has `(…/config.yaml, ro)` | `tests/src/sidecar/test_container.py` |
| Direct plan-check injects | flag on, route openrouter, `FORGE_SESSION` set | `hp.extra["openai"]["user"] == derive_provider_session_id(...)` | `tests/src/policy/semantic/test_plan_check.py` |
| No-clobber | `hp` already has `extra["openai"]["user"]` | `with_openrouter_user` returns it unchanged | `tests/src/core/usage/test_correlation.py` |
| No path/name leak | `FORGE_SESSION="secret/path"` | injected value is `forge_sess_<hash>`, contains no `/` and not the raw name | `tests/src/policy/semantic/test_plan_check.py` |
| Fail-open | forced derive error | plan-check still returns its verdict; no injection | `tests/src/policy/semantic/test_plan_check.py` |

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

# Status-line Enhancement Checklist

Execution plan for [`card.md`](./card.md). Full design: `~/.claude/plans/giggly-swimming-wren.md`.

This card is in active execution under `doing/`. Move the whole `statusline-enhancement/` directory to
`docs/board/done/` after closeout.

## Maintenance

- Update this file during implementation sessions and once before ending a session.
- Tick a task only when its assertion is satisfied and verification is recorded.
- Add short blocker notes inline under the relevant phase.
- Move completed-session details to `docs/board/change_log.md`; keep only active plan state here.
- Update design docs per phase as code ships (`docs/design_appendix.md §A.8`).

## Current Focus

**Phase 3 (throttled cache-hit-rate) complete.** New `cache_hit` opt-in segment: proxy mode reads the live
`metrics.cache_hit_rate` (free); direct mode computes it from the transcript with `requestId` dedup (matching the
proxy's `cache_read/input*100` formula) and throttles the result on disk (`statusline/throttle.py`) so a busy session
recomputes at most once per `cache_hit_ttl`. All cache I/O is fail-open. Verified: `make test-unit` (1558 pass),
`make pre-commit` clean, manual render (`cache:75%` with dedup + throttle file written). Next: Phase 4 Forge-unique
pure-read segments.

## Phase 0 — Nested `statusline:` config foundation

- [x] `src/forge/cli/statusline/names.py` with `SEGMENT_NAMES` + `DEFAULT_ORDER` (no heavy imports; `DEFAULT_ORDER`
  excludes `rate_limits` to match today's default-hidden behavior).
- [x] `StatusLineConfig` + `_coerce_statusline_config` + `RuntimeConfig.statusline` field; coercion in
  `RuntimeConfig.__post_init__`; strict enum validation in `StatusLineConfig.__post_init__`.
- [x] Loader subtree fail-open: `_dict_to_runtime_config` catches a bad `statusline` → warn + default, preserving other
  keys.
- [x] `forge config set statusline.<key>` dotted handling (`_set_nested_key`); `segments` comma→list; unknown
  enum/segment/subkey rejected (fail-closed). `show` dict-ifies the nested dataclass; `%config` expands it.
- [x] `get_default_config_content()` documents the `statusline:` section.
- [x] (Done in Phase 1) remove `show_rate_limits` — atomic with the `rate_limits` segment.
- [x] Board card + checklist created.

| Test              | Fixture                                              | Assertion                                    | Test File                                                                                       |
| ----------------- | ---------------------------------------------------- | -------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| nested defaults   | `RuntimeConfig()`                                    | `.statusline.cost_mode == "auto"`            | `tests/src/test_runtime_config.py::TestStatusLineConfigDefaults`                                |
| enum fail-closed  | `RuntimeConfig(statusline={cost_mode:wat})`          | raises `ValueError`                          | `...::TestStatusLineConfigCoercion::test_bad_enum_in_dict_raises`                               |
| subtree fail-open | bad statusline + valid `status_timeout` on disk      | `status_timeout` preserved, statusline reset | `...::TestStatusLineConfigLoad::test_bad_statusline_subtree_fails_open`                         |
| dotted set        | `forge config set statusline.cost_mode=subscription` | persists nested                              | `tests/src/cli/test_config_cli.py::TestConfigSetStatusline::test_set_cost_mode_persists_nested` |
| unknown segment   | `set statusline.segments=path,bogus`                 | exit 1, names valid segments                 | `...::test_set_unknown_segment_rejected`                                                        |

## Phase 1 — Segment-registry refactor + palette/glyphs

- [x] Golden no-op guard test FIRST: snapshot `status_line()` stdout for 4 fixtures (direct minimal, direct+thinking
  metrics, session breadcrumb/loop/sidecar, proxy+template+tier). Landed against current code.
- [x] `statusline/registry.py` (`Segment`, `SEGMENTS`, `resolve_order`, `render_segments`) + `statusline/context.py`
  (lazy `RenderContext` via `cached_property` for transcript/git/context).
- [x] Replaced inline assembly (`status_line.py`) with registry; `render_categories()` + wrap/harden tail unchanged.
  Producers are thin adapters over existing `format_*` (`render_categories(where, [], [], stream, [])`).
- [x] `Palette` (default == constants) + `earthy` ("Sage & clay") via output-level ANSI remap (`statusline/palette.py`);
  `glyphs: ascii|unicode` threaded into `get_context_display` progress bar. Default path is a literal no-op.
- [x] Removed `show_rate_limits` (clean break: field + gate + tests; `_REMOVED_KEYS` gives actionable load/set/reset
  guidance) and reintroduced `rate_limits` as an opt-in segment (excluded from `DEFAULT_ORDER`).
- [x] Tests: registry names ⊆ `names.SEGMENT_NAMES`; `DEFAULT_ORDER` all implemented; `segments=[path,model]` triggers
  no transcript/git work (with controls proving the spies fire when accessed).

| Test         | Fixture                 | Assertion                                     | Test File                                   |
| ------------ | ----------------------- | --------------------------------------------- | ------------------------------------------- |
| golden no-op | 4 stdin fixtures        | post-refactor stdout == pre-refactor snapshot | `tests/src/cli/test_statusline_registry.py` |
| lazy compute | `segments=[path,model]` | transcript scan + git spies not called        | `...test_statusline_registry.py`            |
| earthy remap | `palette=earthy`        | path/tier recolored; RESET/SEP untouched      | `tests/src/cli/test_statusline_palette.py`  |
| unicode bar  | `glyphs=unicode`        | progress bar uses block chars, ascii gone     | `...test_statusline_palette.py`             |
| removed key  | `set show_rate_limits`  | exit 1, names `statusline.segments`           | `tests/src/cli/test_config_cli.py`          |

## Phase 2 — Billing-aware cost + rate_limits shape fix

- [x] `format_rate_limits` supports BOTH object (`five_hour`/`seven_day`) and list shapes via `_extract_short_window`;
  optional reset countdown (`show_reset`, testable `now`, sanity-capped at ~8 days for malformed timestamps).
- [x] Resolved `billing_mode` in `RenderContext` (`api`/`subscription`/`ambiguous`) from `cost_mode` + raw
  `os.environ.get("ANTHROPIC_API_KEY")` (NOT resolve_env_or_credential — would misclassify OAuth as API).
- [x] `_produce_cost`: `subscription`/`ambiguous`→`format_billing_cost` (quota, or `≈$` hedge when no quota data),
  `api`→`$`, proxy unchanged (`~$`). `_produce_rate_limits` suppresses itself when billing is non-API AND `cost` is in
  the active layout (via `ctx.active_segments`, set by `render_segments`).
- [x] Documented `refreshInterval`/`padding` as a `forge claude preset edit` opt-in (`docs/end-user/config.md`); no
  auto-installed preset change.

| Test           | Fixture                         | Assertion                             | Test File                                  |
| -------------- | ------------------------------- | ------------------------------------- | ------------------------------------------ |
| object shape   | `{five_hour:{used_percentage}}` | renders `RL:N%` (prefers 5h)          | `tests/src/cli/test_status_line.py`        |
| bad dict       | `{unexpected: dict}`            | None (back-compat, not guessed)       | `...test_status_line.py`                   |
| subscription   | `cost_mode=subscription` + RL   | quota shown, no `$`                   | `tests/src/cli/test_statusline_billing.py` |
| auto heuristic | `auto` ± `ANTHROPIC_API_KEY`    | key→`$`, no-key+RL→quota, no-key→`≈$` | `...test_statusline_billing.py`            |
| suppression    | subscription + cost+rate_limits | quota appears once (`RL:` count == 1) | `...test_statusline_billing.py`            |

## Phase 3 — Throttled cache-hit-rate (file-backed)

- [x] `_produce_cache_hit`: proxy mode reads `runtime.raw["metrics"]["cache_hit_rate"]` (free, no file); direct mode
  `compute_cache_hit_rate` dedups by `requestId` (fallback `message.id`, max-input snapshot per request) and matches the
  proxy formula `sum(cache_read_input_tokens)/sum(input_tokens)*100`. `cache_hit=off` hides the segment. Added
  `cache_hit` to `SEGMENT_NAMES` + producer (equality invariant holds).
- [x] `statusline/throttle.py`: cache at `get_forge_home()/cache/statusline/<sha1(session_id|transcript_path)>.json`;
  reuse when transcript unchanged OR within `cache_hit_ttl`; atomic write (mkstemp+os.replace); runtime-only (version
  mismatch/corrupt → recompute); all I/O fail-open; `None` result not cached.

| Test            | Fixture                                  | Assertion                                   | Test File                                   |
| --------------- | ---------------------------------------- | ------------------------------------------- | ------------------------------------------- |
| requestId dedup | two growing entries, same `requestId`    | counted once (max snapshot), 50% not 50/300 | `tests/src/cli/test_status_line.py`         |
| proxy formula   | input 200, cache_read 150 across 2 reqs  | 75.0                                        | `...test_status_line.py`                    |
| within TTL      | re-render 5s later, transcript changed   | reuse stale, compute spy not called         | `tests/src/cli/test_statusline_throttle.py` |
| unchanged       | re-render past TTL, transcript identical | reuse, no recompute                         | `...test_statusline_throttle.py`            |
| corrupt/version | bad JSON or version 999 cache file       | recompute                                   | `...test_statusline_throttle.py`            |
| proxy no-file   | proxy `metrics.cache_hit_rate`           | `cache:64%`, no throttle file written       | `...test_statusline_throttle.py`            |

## Phase 4 — Forge-unique pure-read segments (opt-in)

- [ ] `produce_supervisor`/`policy` read EFFECTIVE state via `apply_overrides(intent, overrides)` on the raw manifest
  dict (not raw intent). `produce_audit` (intercept fields from GET /). `produce_drift` (compact-name of
  `tier_mappings[active_tier]` vs stdin `model.id`).

## Phase 5 — Spend-cap proximity (proxy change; ship last)

- [ ] 5a: add `CostTracker.cap_summary()` to the `GET /` snapshot (`proxy/server.py` ~`:1609`) under
  `metrics.costs.caps`. Proxy endpoint test.
- [ ] 5b: `produce_spend_cap` → `$X/$Y (Z%)` with threshold colors; `None` when absent or registry-fallback proxy.

## Closeout

- [ ] Update `docs/design_appendix.md §A.8` (status line gets `session_id` via stdin; new `statusline:` section,
  `cost_mode`, segments, `show_rate_limits` removal). Update `docs/end-user/` config/status guidance.
- [ ] `docs/board/change_log.md` entry (incl. `show_rate_limits` clean-break reset note).
- [ ] Promote durable lessons to `impl_notes.md` after human review.
- [ ] `make pre-commit` clean; relevant integration tests run. Move card `doing/ → done/`.

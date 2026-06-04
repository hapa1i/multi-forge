# Status-line Enhancement

Status: in execution (`doing/`), branch `statusline-enhancement`.

## Summary

Make `forge status-line` (`src/forge/cli/status_line.py`) honest about cost across a mixed userbase, user-customizable,
and richer with Forge-unique signals. Four concrete goals:

1. **Billing-aware cost.** Some users run Claude Code on an API key (per-token billing — dollars are real); others on
   OAuth/subscription (dollars are a phantom; quota burn is the real signal). The cost segment must adapt to how Claude
   Code is actually authenticated.
2. **User-customizable fields.** A nested `statusline:` section in `forge config` lets users choose which segments
   display and in what order.
3. **Richer signals.** Surface Forge-unique state (supervisor, policy/TDD, audit posture, spend caps) and a throttled
   cache-hit-rate.
4. **Preferred palette.** Adopt a selectable earthy palette + ASCII/unicode glyph toggle.

## Motivation: status line as a boundary surface

The status line is the always-visible window onto what the runtime, proxy, and session are actually doing. A dollar
figure that is meaningless on a subscription, or a token count that is silently inflated, erodes trust in everything
else it shows. This card makes each displayed signal sourced and honest, and gives the user agency over what the bar
surfaces.

## Verified findings (drive the design)

1. **In-memory caches are dead across renders.** `_transcript_cache` (`status_line.py:359`) and `_numstat_cache`
   (`:967`) are module-level dicts, but each render is a fresh process — they never persist. Any "compute occasionally"
   feature MUST be **file-backed**, keyed by `session_id`. (Verified: the command logs to `status-line.<PID>.log`, a new
   PID per tick.)
2. **`scan_transcript` double-counts tokens** (`:449-455`): sums `message.usage` with no `requestId` dedup → 2–4×
   inflation (Claude Code #5904). Masked today (stdin `context_window.*` preferred) but unusable as the cache-hit basis;
   needs a deduped primitive.
3. **`rate_limits` parsed against the wrong shape** (`:891` expects a *list*; current Claude Code payload is an *object*
   `{five_hour:{used_percentage,resets_at}, seven_day:{...}}`). With today's payload rate limits never render. Gated off
   by default (`show_rate_limits=False`), which is why the drift went unnoticed.
4. **Forge can't positively detect subscription/OAuth.** `infer_billing_mode` (`billing.py:28`) only returns
   `"api"`/`"unknown"` (subprocess attribution). The status line needs its own main-session signal: raw
   `os.environ.get("ANTHROPIC_API_KEY")` (NOT `resolve_env_or_credential`, which falls back to the Forge credential file
   and would misclassify an OAuth session as API).

**Two simplifications found:** proxy mode already exposes `metrics.cache_hit_rate` + token totals at `GET /`
(`metrics.py:157-197`) — transcript scanning is direct-mode only; and nearly all Forge-unique signals are already in the
manifest (`models.py:134-220`) — pure reads.

## Architecture (see plan)

- **Keep `status_line.py` as the module; add siblings** under `src/forge/cli/statusline/` (`names.py`, `registry.py`,
  `context.py`, `throttle.py`) — avoids a package rename that breaks the ~1750-line test suite's internal imports.
- **Segment registry**: ordered tuple of `Segment(name, producer, bucket)`; `DEFAULT_ORDER` (in `names.py`) reproduces
  today's exact output. `path`/`branch` are `where`-bucket (concatenated); the rest are separator-joined `stream`. The
  renderer feeds the same `render_categories()` + wrap/harden tail unchanged.
- **Lazy `RenderContext`** (`cached_property`): expensive derivations (transcript scan, git, cache-hit) run only if an
  enabled segment accesses them.
- **`Palette`** dataclass; default == current module constants. `format_*` gain optional `palette`/`glyphs` kwargs
  (additive — existing tests keep passing).
- **Nested config**: `StatusLineConfig` coerced in `RuntimeConfig.__post_init__` (mirrors `_coerce_cost_config`) — the
  only convergence point because `from __future__ import annotations` defeats `dict_to_dataclass`, and
  `forge config set`/`edit` build `RuntimeConfig(**dict)` directly. Strict enums (fail-closed for set/edit); loader
  catches statusline errors → subtree fail-open. Segment names owned by renderer + set/edit, not the dataclass.

## Scope / phasing

Phase 0 config foundation → 1 registry refactor → 2 billing-aware cost + rate_limits fix → 3 throttled cache-hit → 4
Forge-unique segments → 5 spend-cap proximity (proxy change). Each phase is independently shippable and test-backed.
Detailed plan: `~/.claude/plans/giggly-swimming-wren.md`.

## Risks / open questions

- **`show_rate_limits` clean break**: removed and folded into segment presence + `cost_mode` (research-preview clean
  break; changelog + reset note). Done in Phase 1 (atomic with the `rate_limits` segment), not Phase 0.
- **Python-process startup cost**: lazy context + no new subprocess/network beyond the existing `detect_proxy()` GET /.
  Keep new imports lazy.
- **`refreshInterval` in preset** would trip the installer conflict path (`installer.py:626`) — documented as a
  `forge claude preset edit` opt-in instead of an auto-installed change.
- **`drift` segment**: compare normalized `model.id` (not `display_name`) to avoid false positives.

## Out of scope

- `forge usage cache-stats` cross-session aggregator command (separate card; reuses Phase 3's deduped primitive).
- `effort.level` / `pr.*` segments (registry has slots; follow-on).

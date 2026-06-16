# Supervisor Status-Line Health -- Execution Checklist

Execution plan for [`card.md`](card.md). Branch: `supervisor_statusline_health`.

Surface frontier-supervisor **fail-open** on the always-visible status bar. Carry a structured, additive `failure_kind`
from each fail-open site through to a cheap in-memory health reader, and render a `SUP!N <kind>` suffix that preserves
existing posture. Scope v1 to the **frontier** supervisor; tier-1 cascade plan-check is excluded by construction (it
escalates to the frontier instead of allowing).

## Current focus

Phase 1, task 1: add the `FailureKind` Literal alias + optional `failure_kind` field to `PolicyDecision`
(`policy/types.py`) **and** the matching key in the hand-written `serialize_decision` (`policy/store.py:37`), then prove
it survives a strict `SessionStore` round-trip while legacy decisions without it still read. This is the additive-schema
foundation everything depends on, and the one place the hand-written serializer can silently drop the field.

## Verified ground truth (read before implementing)

These were confirmed against the current code; they shape the whole plan:

- **Additive is safe with no schema bump.** `PolicyConfirmed.decisions` is typed `list[dict[str, Any]]`
  (`session/models.py:288`), so dacite `strict=True` (`session/store.py:191`) never validates inner decision keys.
  `SCHEMA_VERSION` stays `1` (`session/models.py:21`); precedent: `supervisor_launch_controls`,
  `supervisor_shadow_sampling` added optional fields with no bump.
- **The serializer is hand-written and drops unlisted fields.** `serialize_decision` (`policy/store.py:22-38`) emits an
  explicit dict and already omits `PolicyDecision.intent`. Adding the dataclass field alone persists **nothing** -- the
  key must be added at `store.py:37`.
- **Decisions are stored composite-nested.** `serialize_composite_decision` (`store.py:53-73`) nests
  `decisions: [serialize_decision(d)]`, so a supervisor `failure_kind` lives at
  `confirmed.policy.decisions[i].decisions[j]` where `policy_id == "semantic.supervisor"`.
- **Two clean structured write-seams; no error-text parsing for the deterministic kinds.** `SessionResult.timed_out`
  (`core/reactive/session_runner.py:48`) gives `timeout`; the `parsed` flag in `run_supervisor_check`
  (`policy/semantic/supervisor.py:519`) gives `parse`. The parse tag must be stamped there, **not** in
  `verdict_to_decision`, which also serves genuine divergences (`invoke_supervisor` at `:535` drops `parsed`).
- **Render is golden-immune by construction.** `supervisor` is opt-in and excluded from `names.DEFAULT_ORDER`
  (`cli/statusline/names.py:34-37`); the suffix only appears when failures exist, so healthy `SUP` stays byte-identical.
  `RED`/`YELLOW`/`METRICS_COLOR` constants exist (`status_line.py:31-42`); a literal ASCII `"!"` is already the in-line
  alert char (`status_line.py:688,711`).

## Resolved design decisions (the card's open questions)

| Question                                        | Decision                                                                                                                     | Why                                                                                                                                                                                                |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Recency window: consecutive vs windowed count   | **Consecutive-failure count** (newest-first streak until the first non-fail-open supervisor decision -- any allow/warn/deny) | Motivating case was consecutive timeouts; `usage_summary`'s cumulative count over the 100-entry ring would read as a misleading session-long number on the always-visible bar.                     |
| Clear immediately vs short window after success | **Clear immediately** -- a newer clean supervisor allow resets `recent_failures` to 0                                        | Falls out of the consecutive-streak model for free; a time-decay window needs state the decision log does not carry. `last_seen_at` is still recorded for the detail view.                         |
| Should repeated fail-open escalate policy       | **Out of scope for v1** -- `failure_kind`/`SupervisorHealth` are telemetry only                                              | `design_workflows.md` §1.2 mandates fail-open for policy evaluations; escalation is an enforcement behavior change, a separate card.                                                               |
| Unicode vs ASCII glyph for the marker           | **Literal ASCII `!`** (`SUP!3 timeout`)                                                                                      | No unicode warning glyph exists; `Glyphs` carries only progress-bar fill chars and threads only into `get_context_display`. ASCII survives the normalize-text strip hook and is golden-irrelevant. |
| All warnings vs only fail-open infra failures   | **Only fail-open** (the four kinds: timeout/auth/parse/error)                                                                | A genuine low-confidence divergence (`parsed=True`, no `failure_kind`) is the supervisor *working* -- it must not inflate the marker.                                                              |
| RED vs YELLOW threshold                         | **RED at `>=3` consecutive fail-opens, YELLOW at 1-2**                                                                       | Mirrors the tiered `format_spend_cap` (`status_line.py:1280`). Confirm the exact threshold during Phase 4.                                                                                         |

## Invariants (must / must-not)

- **Additive schema, no version bump.** `failure_kind` is optional/defaulted on `PolicyDecision` and an extra key in
  `serialize_decision`. Old decisions without it MUST read under dacite `strict=True`.
- **The serializer is the real seam.** Adding the field to the dataclass persists nothing; the explicit key at
  `store.py:37` is mandatory and must be asserted in a test.
- **Do not change enforcement.** `failure_kind` is metadata only -- it MUST NOT change the `decision` value, fail-open
  behavior, cache behavior (only clean allows are cached), or any warning string.
- **Frontier-only scope.** `failure_kind` is set only on `semantic.supervisor` fail-open sub-decisions. Tier-1
  `semantic.plan_check` MUST NOT carry a supervisor `failure_kind` or increment supervisor counters/health.
- **Parse tag seam.** `failure_kind="parse"` is stamped at `supervisor.py:519` (where `parsed` exists), NOT in
  `verdict_to_decision`.
- **Render fail-open + always exit 0.** The `supervisor_health` reader and `format_supervisor` MUST NOT raise on
  malformed manifest input; degrade to no suffix. `status_line()` MUST always exit 0.
- **Posture-independent health suffix.** The `!N <kind>` suffix attaches to whatever posture token renders -- `SUP`,
  `SUP(susp)`, or `SUP(off)` -- because suspended/disabled write no new decisions, so showing the prior fail-open
  history is the honest signal the card asks for (`SUP(susp)!2 timeout`, `SUP(off)!4 error`).
- **Do not thread palette/glyph through `format_*`.** Use inline `YELLOW`/`RED` module constants and a literal ASCII
  `!`; palette recoloring stays at the output level (`apply_palette`).
- **Allowlist == producers.** Do NOT add a new segment name -- the suffix lives inside the existing `supervisor`
  segment. `SEGMENT_NAMES` MUST stay equal to `{seg.name for seg in SEGMENTS}`.
- **Golden default bar unchanged.** `supervisor` stays out of `DEFAULT_ORDER`; `format_supervisor(health=None)` MUST be
  byte-identical to today.
- **Zero I/O when inactive.** `supervisor_health` is a `cached_property` reading the already-loaded manifest dict only,
  accessed solely by `_produce_supervisor`.
- **Atomic internal interface change.** The `format_supervisor` signature + `_produce_supervisor` call change in one
  commit, no compatibility shim (internal clean break).

## Phases

### Phase 1: Additive `failure_kind` on `PolicyDecision` + safe persistence

**Goal**: Add an optional, defaulted `failure_kind` and persist it through the hand-written serializer without a schema
bump, proving old and new decisions both read under strict dacite.

- [ ] `PolicyDecision` gains `failure_kind: FailureKind | None = None` (last, defaulted) plus a module-level
  `FailureKind = Literal["timeout", "auth", "parse", "error"]`; existing constructors stay valid. *Verify*: extend
  `tests/src/policy/test_types.py` to assert `PolicyDecision(decision="allow", policy_id="t").failure_kind is None`.
  *Files*: `src/forge/policy/types.py`.
- [ ] `serialize_decision` emits `"failure_kind": decision.failure_kind`; a `timeout` decision serializes with
  `["failure_kind"] == "timeout"` and a default decision serializes with `["failure_kind"] is None` (proving the
  hand-written serializer no longer drops it the way it drops `intent`). *Verify*: new direct `serialize_decision` unit
  test (`tests/src/policy/semantic/test_supervisor.py` or `test_types.py`). *Files*: `src/forge/policy/store.py`.
- [ ] A manifest written with a `semantic.supervisor` sub-decision carrying `failure_kind="timeout"` survives
  `SessionStore.write -> read()` under `strict=True`; a legacy entry with no `failure_kind` key still reads and
  `.get()`s as `None`. *Verify*: extend the `_decision` helper + `_write_manifest` round-trip in
  `tests/src/core/ops/test_usage_summary.py`. *Files*: `tests/src/core/ops/test_usage_summary.py`.

**Design-doc updates**: `design_appendix.md` (the `confirmed.policy.decisions` schema reference) -- note `failure_kind`
is an optional additive field, no `SCHEMA_VERSION` bump, set only on supervisor fail-open sub-decisions.

### Phase 2: Tag `failure_kind` at each supervisor fail-open site (no enforcement change)

**Goal**: Set the correct `failure_kind` at every frontier fail-open return in `run_supervisor_check` without altering
decision/cache/enforcement, and confirm tier-1 plan-check never carries it.

- [ ] Subprocess fail-open branch (`supervisor.py:506-517`) sets `failure_kind="timeout"` when `result.timed_out`, else
  `"error"` -- derived from `SessionResult.timed_out`, NOT by string-matching `result.error`. `decision` stays `allow`,
  warning text byte-unchanged. *Verify*: extend `test_supervisor.py::test_timeout_allows_with_warning` (timed-out mock
  -> `failure_kind == "timeout"`) + sibling non-timeout failure -> `"error"`; the cache test still passes. *Files*:
  `src/forge/policy/semantic/supervisor.py`.
- [ ] Proxy-routing fail-open (`supervisor.py:461-469`) sets `failure_kind="auth"`, `decision` stays `warn`. Subprocess
  errors whose `result.error` is a missing-proxy/credential message classify as `"auth"`; if that string check proves
  brittle, fall back to `"error"` (see Blockers). *Verify*: new `test_supervisor.py` test mocking
  `resolve_subprocess_routing` to raise -> `warn` + `failure_kind == "auth"`. *Files*:
  `src/forge/policy/semantic/supervisor.py`.
- [ ] Parse fail-open is tagged `failure_kind="parse"` only at `supervisor.py:519-521` where `parsed is False` -- NOT in
  `verdict_to_decision`. A genuine low-confidence divergence (`parsed=True`) leaves `failure_kind=None`, distinguishing
  it from a parse failure despite an identical decision shape. *Verify*: `test_supervisor.py` -- empty/unparseable
  stdout (`run_ok=True, parsed=False`) -> `"parse"`; parsed divergent verdict -> `None`. Cross-grounded by
  `test_verdict.py::test_parse_empty_response`. *Files*: `src/forge/policy/semantic/supervisor.py`.
- [ ] Remaining allow fail-opens set `failure_kind="error"`: FORGE_DEPTH skip (`407-415`), no-`resume_id` (`417-424`),
  resume-target resolution (`426-435`). `decision` stays `allow`, warning strings byte-unchanged. (No `skipped` kind in
  v1; taxonomy is timeout/auth/parse/error.) *Verify*: extend `test_supervisor.py::test_skips_supervisor_at_max_depth`
  and `test_missing_confirmed_uuid_fails_open` to assert `failure_kind == "error"` with `decision` + warnings preserved.
  *Files*: `src/forge/policy/semantic/supervisor.py`.
- [ ] Tier-1 plan-check failures never carry a supervisor `failure_kind` and never increment supervisor counters: a
  `plan_check` `needs_review` entry has `policy_id == "semantic.plan_check"` and increments `plan_check_needs_review`.
  *Verify*: `test_plan_check.py::test_never_denies_or_warns` + `test_checker_failure_escalates` (tier-1 emits only
  allow/needs_review on its own policy_id); `test_usage_summary.py` counter separation. *Files*: assertions only (no
  source change) in `tests/src/policy/semantic/test_plan_check.py`.

**Design-doc updates**: `design_workflows.md` §1.2 -- note `failure_kind` is metadata-only on fail-open decisions, does
not change fail-open/enforcement/cache, and is frontier-only (tier-1 excluded).

### Phase 3: `SupervisorHealth` reader over `confirmed.policy.decisions`

**Goal**: A `SupervisorHealth(recent_failures, last_kind, last_seen_at)` helper that scans the decision log newest-first
for the consecutive run of supervisor fail-opens, with a legacy warning-string fallback, never raising on malformed
input.

- [ ] `SupervisorHealth` computes a **consecutive**-failure count: scan `confirmed.policy.decisions` newest-first over
  `semantic.supervisor` sub-decisions, counting contiguous fail-opens (a sub-decision is a fail-open iff the shared
  classifier of Phase 3 task 2 returns a kind). The streak breaks at the first **non-fail-open** supervisor decision --
  any `allow`/`warn`/`deny` with `failure_kind is None` -- because a parsed verdict (even a divergent `warn`/`deny`)
  proves the frontier supervisor ran. `last_kind` = newest failure's kind, `last_seen_at` = its `evaluated_at`; a
  non-fail-open newer than the last failure yields `recent_failures == 0`. *Verify*:
  `tests/src/cli/test_statusline_forge_segments.py` -- 3 consecutive supervisor timeouts -> `recent_failures == 3`,
  `last_kind == "timeout"`; append a newest clean `allow` -> `0`; **and** a newest parsed `warn` and a newest parsed
  `deny` (both `failure_kind is None`) each break the streak to `0`. *Files*: `src/forge/cli/statusline/context.py`.
- [ ] **Shared** classifier `classify_supervisor_failure(sub_decision: dict) -> FailureKind | None` lives in
  `policy/semantic/supervisor.py` (beside the warning strings it matches) and is the single fail-open-detection API for
  BOTH the status line and `forge activity` (Phase 5). It returns the explicit `failure_kind` when present; else a
  legacy fallback over the warning text (`Timed out after` -> `timeout`, `could not be parsed` -> `parse`,
  otherwise-`failing open` -> `error`); else `None` (not a fail-open). Human strings are the fallback only, never the
  primary API. One shared API keeps the bar's marker and the activity breakdown consistent for pre-`failure_kind`
  decisions (the card's "`forge activity` explains the marker" promise). *Verify*:
  `tests/src/policy/semantic/test_supervisor.py` -- `"Supervisor error: Timed out after 45s, failing open"` (no
  `failure_kind`) -> `"timeout"`; `"Supervisor verdict could not be parsed ..."` -> `"parse"`; a divergence `warn`
  without `failing open` -> `None` (strings verbatim from `supervisor.py:515` and `verdict.py:77`). *Files*:
  `src/forge/policy/semantic/supervisor.py`, `src/forge/cli/statusline/context.py`.
- [ ] The reader is fail-open: non-dict/missing `confirmed.policy.decisions`, non-list `decisions`, or a malformed
  sub-decision entry returns an empty `SupervisorHealth` (`recent_failures == 0`, `last_kind is None`) and never raises
  -- mirroring `effective_intent`'s `return {}` degrade (`context.py:124-141`). *Verify*:
  `test_statusline_forge_segments.py` feeding manifest variants (missing `confirmed`, `decisions == "garbage"`, a list
  with a non-dict element) -> empty health, no exception. *Files*: `src/forge/cli/statusline/context.py`.
- [ ] `supervisor_health` is exposed as a `@cached_property` on `RenderContext` doing **zero I/O** (reads the
  already-loaded manifest dict only); computed at most once and only when the supervisor segment is active. *Verify*:
  extend/mirror `test_statusline_registry.py::TestLazyContext` -- with supervisor not in the active set,
  `supervisor_health` is never accessed; cached reuse asserted by accessing twice. *Files*:
  `src/forge/cli/statusline/context.py`.

**Design-doc updates**: document `SupervisorHealth` (fields, consecutive semantics, legacy fallback) in `design.md`
status-line section or `design_appendix` as a status-line-private reader.

### Phase 4: Render the `SUP!N <kind>` suffix (posture-preserving, golden-safe)

**Goal**: Append the health suffix to `format_supervisor`'s output as a colored ASCII suffix after the posture token,
default-off, without threading palette/glyph args and without touching golden bars.

- [ ] `format_supervisor` gains an optional `health` param (default `None`) that, when present with
  `recent_failures > 0`, appends `!N <kind>` to the **rendered posture token regardless of posture** -- `SUP!3 timeout`,
  `SUP(susp)!2 timeout`, `SUP(off)!4 error` (the card examples). Off/suspended history stays visible: those states write
  no new decisions, so the suffix honestly shows the watcher was failing before it was turned off. Uses a literal ASCII
  `!` and `YELLOW`/`RED` constants (YELLOW for 1-2, RED for `>=3`, mirroring `format_spend_cap` at
  `status_line.py:1280`). With `health=None`, output is byte-identical to today. *Verify*:
  `test_statusline_forge_segments.py::TestFormatHelpers::test_supervisor_active_vs_suspended` still passes; new tests
  assert the suffix appears on all three postures (`SUP`, `SUP(susp)`, `SUP(off)`) when health is present, and
  `health=None` equals the current posture-only output. *Files*: `src/forge/cli/status_line.py`.
- [ ] `_produce_supervisor` passes `health=ctx.supervisor_health` into `format_supervisor` atomically with the signature
  change (single producer seam, no shim); all posture branches (off/susp/active) preserved and the health suffix
  appended to whichever posture renders. *Verify*: new `_produce_supervisor` test -- `policy.enabled` + manifest with 3
  supervisor timeouts -> segment contains `SUP` and `!3 timeout`; `policy.enabled=False` -> `SUP(off)` AND the `!3`
  suffix; `suspended=True` -> `SUP(susp)` AND the suffix. *Files*: `src/forge/cli/statusline/registry.py`.
- [ ] Default status bar is byte-identical: golden snapshots unchanged (supervisor absent from `DEFAULT_ORDER`), and
  `SEGMENT_NAMES == {seg.name for seg in SEGMENTS}` (no new segment -- the suffix lives inside the existing supervisor
  segment). *Verify*: `test_statusline_registry.py::TestGoldenNoOpGuard` + `test_allowlist_equals_producers` pass
  unchanged; add an explicit assertion that `supervisor` is not in `DEFAULT_ORDER`. *Files*:
  `tests/src/cli/test_statusline_registry.py`.
- [ ] Render fail-open holds: a raising `supervisor_health` or `format_supervisor` does not crash the line --
  `status_line()` exits 0 and the segment degrades to absent. *Verify*: `test_statusline_registry.py` -- inject a
  `supervisor_health` that raises, assert exit 0 + segment omitted (the `render_segments` try/except is the net, not the
  primary handling). *Files*: `tests/src/cli/test_statusline_registry.py`.

**Design-doc updates**: update the status-line segment reference (`design.md` or the end-user statusline guide) to
describe the `SUP!N <kind>` suffix, posture preservation, ASCII `!`, and yellow/red tiers.

### Phase 5: `forge activity` + `session.md` detail surfacing

**Goal**: Make `forge activity <session>` explain the marker with a per-kind fail-open breakdown from the same decision
log, and add a short `session.md` note linking the bar to the detail view.

- [ ] `PolicyActivity` gains a per-kind supervisor fail-open counter populated via the **shared**
  `classify_supervisor_failure` (Phase 3 task 2) inside the existing supervisor sub-decision loop
  (`usage_summary.py:508-516`), no new I/O. Using the shared classifier (not a bare `sub.get("failure_kind")`) means
  legacy decisions the status line counts via fallback are ALSO counted here -- so `forge activity` explains a marker
  the bar shows. *Verify*: `test_usage_summary.py::TestPolicyPlane` -- per-kind counter increments for
  timeout/error/parse/ auth via explicit `failure_kind`, AND a legacy decision (no key,
  `Timed out after ... failing open` warning) increments the timeout counter. *Files*:
  `src/forge/core/ops/usage_summary.py`.
- [ ] `forge activity` Supervisor render appends a `failing open: N timeout, N error...` line from the new counter, and
  the `--json` shape includes the per-kind breakdown. *Verify*: extend
  `test_activity.py::test_human_render_shows_supervisor` (failing-open line) and the JSON-counter test. *Files*:
  `src/forge/cli/activity.py`.
- [ ] `docs/end-user/session.md` adds a short note after the supervisor activity example explaining `SUP!N` means recent
  frontier checks are failing open (actions may proceed without frontier review), pointing to
  `forge activity <session>`. *Verify*: doc review; grep `session.md` mentions `SUP!` and `forge activity` near the
  supervisor example. *Files*: `docs/end-user/session.md`.

**Design-doc updates**: ensure `cli_reference.md` / `session.md` reflect the new `forge activity` failing-open line.

### Phase 6: Closeout

**Goal**: Verify end-to-end on the supervisor path, sync design docs, record closeout.

- [ ] Regression test guards silent-loss of fail-open evidence: a supervisor timeout writes `failure_kind="timeout"` and
  it survives the strict manifest round-trip (the "structured timeout recorded" acceptance; corruption/silent-loss class
  per the regression mandate). *Verify*: new `tests/regression/test_bug_supervisor_failure_kind_persisted.py`. *Files*:
  `tests/regression/test_bug_supervisor_failure_kind_persisted.py`.
- [ ] Supervisor-path integration verification passes: the resume-harness E2E still reports infra error and fail-open is
  unchanged; `failure_kind` does not alter decision/enforcement on the real `claude -p` path. *Verify*:
  `./scripts/test-integration.sh tests/integration/docker/test_supervisor_e2e.py -v` --
  `test_resume_harness_reports_infra_error` + an escalation case still pass; `final_decision`/warning unchanged.
  *Files*: `tests/integration/docker/test_supervisor_e2e.py` (assertions may need extending).
- [ ] `make pre-commit` clean; `change_log.md` has a feature-completion entry (goal/key changes/verification); durable
  lessons staged for `impl_notes.md` after human review; card moved `doing/ -> done/`. *Verify*: `make pre-commit` exits
  0; `change_log.md` updated newest-first; `git mv` the card directory. *Files*: `docs/board/change_log.md`,
  `docs/board/impl_notes.md`.

**Design-doc updates**: final pass -- `design.md` / `design_appendix.md` / `design_workflows.md` reflect `failure_kind`,
`SupervisorHealth`, and the suffix as shipped; `cli_reference.md` reflects the `forge activity` change.

## Acceptance test table

| Test                                 | Fixture                                                                                | Assertion                                                                                      | Test File                                                        |
| ------------------------------------ | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| Structured timeout recorded          | mocked `SessionResult(timed_out=True)` through `run_supervisor_check`                  | fail-open `allow` carries `failure_kind == "timeout"` and persists to the decision log         | `tests/src/policy/semantic/test_supervisor.py`                   |
| Structured parse recorded            | `run_ok=True, parsed=False` (empty/unparseable stdout)                                 | `warn` carries `failure_kind == "parse"`; parse-fallback warning string unchanged              | `tests/src/policy/semantic/test_supervisor.py`                   |
| Healthy path unchanged               | `parsed=True` aligned verdict                                                          | `failure_kind is None`; `SupervisorHealth.recent_failures == 0`                                | `tests/src/policy/semantic/test_supervisor.py`                   |
| Timeout visible with kind + count    | `policy.enabled` + manifest with 3 supervisor timeouts                                 | rendered supervisor segment contains `SUP` and `!3 timeout`                                    | `tests/src/cli/test_statusline_forge_segments.py`                |
| Consecutive failures counted         | 3 contiguous supervisor fail-opens, no clean allow between                             | `recent_failures == 3`, `last_kind == "timeout"`                                               | `tests/src/cli/test_statusline_forge_segments.py`                |
| Tier-1 plan-check excluded           | `plan_check` `needs_review` entry (`semantic.plan_check`)                              | increments `plan_check_needs_review`, never supervisor counters/health                         | `tests/src/policy/semantic/test_plan_check.py`                   |
| Success clears the warning           | 3 failures then a newest clean allow                                                   | `recent_failures == 0` after the clean allow breaks the streak                                 | `tests/src/cli/test_statusline_forge_segments.py`                |
| Disabled posture preserved + suffix  | `policy.enabled=False` / `suspended=True` with health present                          | `SUP(off)`/`SUP(susp)` posture renders WITH the health suffix (e.g. `SUP(off)!4 error`)        | `tests/src/cli/test_statusline_forge_segments.py`                |
| Legacy warning fallback              | sub-decision with no `failure_kind`, warning `Timed out after 45s, failing open`       | `last_kind == "timeout"` via string fallback                                                   | `tests/src/cli/test_statusline_forge_segments.py`                |
| Status-line fail-open                | `decisions == "garbage"` / non-dict sub-decision / missing `confirmed`                 | reader returns empty health without raising; `status_line()` exits 0, segment absent           | `tests/src/cli/test_statusline_registry.py`                      |
| Additive schema survives strict read | manifest with `failure_kind` + a legacy entry without it                               | both round-trip through `SessionStore.read()` under `strict=True`; missing key reads as `None` | `tests/src/core/ops/test_usage_summary.py`                       |
| Persisted round-trip regression      | timed-out `SupervisorRun` persisted via the store path                                 | read-back sub-decision `failure_kind == "timeout"`                                             | `tests/regression/test_bug_supervisor_failure_kind_persisted.py` |
| Parsed verdict breaks streak         | newest `semantic.supervisor` is a parsed `warn`/`deny` (`failure_kind is None`)        | `recent_failures == 0` (a parsed verdict proves the frontier ran)                              | `tests/src/cli/test_statusline_forge_segments.py`                |
| Legacy decision counted in activity  | a pre-`failure_kind` supervisor fail-open (warning `Timed out after ... failing open`) | `forge activity` increments the timeout counter via the shared classifier (matches the bar)    | `tests/src/core/ops/test_usage_summary.py`                       |

## Blockers / deferred (v1 scope boundaries)

- **`auth` classification is fuzzy.** `timeout` is deterministic (`result.timed_out`); the proxy-routing branch
  (`supervisor.py:461-469`) is a clean `auth` source, but distinguishing missing-proxy/credential from generic error in
  the subprocess branch (`506-517`) requires inspecting `result.error` content. If that proves brittle, fall back to
  `"error"` for that sub-case (Phase 2 task 2 names the fallback).
- **Usage ledger as a secondary source is deferred.** v1 sources health solely from `confirmed.policy.decisions`. The
  decision log catches proxy-not-found and parse fail-opens the ledger misses (`supervisor.py:463` emits no ledger
  event; parse is a success-status ledger row). Do not wire the ledger in v1.
- **Unknown-verdict silent degrade** (`verdict.py:91-96`) coerces to aligned with no persisted warning, so it is
  invisible to both the log and the marker. Accepted as an undetectable degrade in v1.
- **`MAX_DECISION_LOG = 100` eviction** can drop old failures (accepted recency risk). Fine for a consecutive-recent
  marker; explicitly not an audit trail. `forge activity`'s existing "at capacity" footnote already warns.
- **RED-vs-YELLOW threshold** proposed at `>=3` (RED) / 1-2 (YELLOW); confirm the exact number during Phase 4.

## Provenance

Plan derived from an Understand/Design workflow (4 parallel subsystem readers + synthesis), then every load-bearing fact
(serializer, `timed_out`/`parsed` seams, dict-typed `decisions`, golden exclusion, ASCII `!`, tiered colors, counter
separation) was independently re-verified against the current code and cited test files.
